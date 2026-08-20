"""
Investigate → back up → purge → verify → write, for the historical backfill.

The Phase 4 collision pre-check found ~20,240 pre-existing snapshot_source=
'backfilled' rows across the four target quarters, with counts inverted
against a coherent reconstruction (FY2026 Q3 at 8,897 ≈ 684/week against an
open population that never exceeds ~415). That is legacy output from the
defective attempts, and an upsert over it would interleave corrected rows
with orphaned legacy rows at dates the new writer does not emit. So it is
purged and rewritten, not overwritten.

DESTRUCTIVE. Guarded:
  1. Investigate — dates/quarter, non-Mondays, out-of-range, duplicate
     (deal_id, snapshot_date) pairs, quarter-label correctness, a sample.
  2. Back up EVERY matching row to a durable file (data/backups, in-repo),
     then re-read it and confirm the count matches before any delete.
  3. Purge — scoped to snapshot_source='backfilled' AND the four target
     quarters, per-quarter, nothing else.
  4. Verify — prospective and backfill_current_quarter counts unchanged
     across the purge; report remaining rows by (fiscal_quarter, source).
  5. Write — the corrected reconstruction (collision check now clean).

Runs only when --confirm-purge is passed, so a bare invocation cannot delete.

Usage (CI, after the fetch step builds the cache):
    python scripts/analytics/purge_and_rewrite_backfill.py --confirm-purge
"""
import argparse
import json
import sys
from collections import Counter
from datetime import datetime
from pathlib import Path

REPO_ROOT = Path(__file__).parent.parent.parent
sys.path.insert(0, str(REPO_ROOT / 'scripts'))
sys.path.insert(0, str(REPO_ROOT / 'scripts' / 'analytics'))
sys.path.insert(0, str(REPO_ROOT / 'api'))

from supabase_client import select_all
from utils import get_fiscal_quarter
from backfill_snapshots import SnapshotBackfiller, DEFAULT_QUARTERS

BACKFILLED = 'backfilled'
PROTECTED_SOURCES = ('prospective', 'backfill_current_quarter')


def count_by_source(client, quarters=None):
    filters = [('in_', 'fiscal_quarter', quarters)] if quarters else None
    rows = select_all(client, 'deals_snapshot',
                      columns='fiscal_quarter,snapshot_source', filters=filters)
    c = Counter((r.get('fiscal_quarter'), r.get('snapshot_source')) for r in rows)
    return {k: v for k, v in sorted(c.items(), key=lambda x: (str(x[0][0]), str(x[0][1])))}


def investigate(client, config, quarters):
    rows = select_all(
        client, 'deals_snapshot',
        columns='deal_id,snapshot_date,fiscal_quarter,stage_id,deal_value,'
                'backfill_confidence,has_property_history,snapshot_source',
        filters=[('in_', 'fiscal_quarter', quarters),
                 ('eq', 'snapshot_source', BACKFILLED)])
    print(f"\nInvestigating {len(rows)} 'backfilled' rows across {quarters}\n")

    by_q = {}
    for r in rows:
        by_q.setdefault(r['fiscal_quarter'], []).append(r)

    for q in sorted(by_q):
        qr = by_q[q]
        dates = sorted({r['snapshot_date'] for r in qr})
        non_monday = [d for d in dates
                      if datetime.fromisoformat(d).weekday() != 0]
        mislabeled = 0
        for r in qr:
            d = datetime.fromisoformat(r['snapshot_date']).date()
            _, _, lbl = get_fiscal_quarter(d, config)
            if lbl != r['fiscal_quarter']:
                mislabeled += 1
        pair_counts = Counter((r['deal_id'], r['snapshot_date']) for r in qr)
        dups = {k: n for k, n in pair_counts.items() if n > 1}
        print(f"  {q}: {len(qr)} rows, {len(dates)} distinct dates "
              f"({dates[0]}..{dates[-1]})")
        print(f"      distinct dates {'> 13 — MULTIPLE RUNS or wrong grid' if len(dates) > 13 else '= expected 13'}")
        print(f"      non-Monday dates: {len(non_monday)}"
              + (f"  e.g. {non_monday[:3]}" if non_monday else ""))
        print(f"      rows whose snapshot_date is NOT in claimed quarter: {mislabeled}")
        print(f"      duplicate (deal_id, snapshot_date) pairs: {len(dups)}"
              + (f"  (max multiplicity {max(pair_counts.values())})" if dups else ""))

    print("\n  Sample of 10 rows (stage / value / confidence):")
    for r in rows[:10]:
        print(f"    {r['deal_id']:<14} {r['snapshot_date']}  q={r['fiscal_quarter']:<11} "
              f"stage={str(r['stage_id']):<16} value={str(r['deal_value']):<12} "
              f"conf={r.get('backfill_confidence')}  has_hist={r.get('has_property_history')}")
    return len(rows)


def backup(client, quarters, path):
    rows = select_all(client, 'deals_snapshot', columns='*',
                      filters=[('in_', 'fiscal_quarter', quarters),
                               ('eq', 'snapshot_source', BACKFILLED)])
    # Nothing to preserve (e.g. a re-run after the quarters were already
    # purged): do NOT write an empty file over a prior good backup.
    if not rows:
        print("\nNothing to back up — target quarters already hold 0 "
              "'backfilled' rows. Existing backup left untouched.")
        return 0
    # Never overwrite an existing backup; a re-run must not clobber the
    # rollback from an earlier run. Write to the first free numbered sibling.
    path = Path(path)
    if path.exists():
        stem, suffix = path.stem, path.suffix
        n = 1
        while (path.parent / f"{stem}_{n}{suffix}").exists():
            n += 1
        path = path.parent / f"{stem}_{n}{suffix}"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(rows, indent=1, default=str))
    # Verify durability: re-read from disk and confirm the count matches.
    reread = json.loads(path.read_text())
    print(f"\nBacked up {len(rows)} rows -> {path}")
    print(f"  re-read {len(reread)} rows from disk: "
          f"{'MATCH' if len(reread) == len(rows) else 'MISMATCH — ABORT'}")
    if len(reread) != len(rows):
        raise SystemExit("Backup verification failed — not deleting anything.")
    return len(rows)


def purge(client, quarters):
    deleted = {}
    for q in quarters:
        before = len(select_all(client, 'deals_snapshot', columns='deal_id',
                     filters=[('eq', 'fiscal_quarter', q),
                              ('eq', 'snapshot_source', BACKFILLED)]))
        client.table('deals_snapshot').delete()\
            .eq('snapshot_source', BACKFILLED).eq('fiscal_quarter', q).execute()
        after = len(select_all(client, 'deals_snapshot', columns='deal_id',
                    filters=[('eq', 'fiscal_quarter', q),
                             ('eq', 'snapshot_source', BACKFILLED)]))
        deleted[q] = before - after
        print(f"  purged {q}: {before} -> {after}  (deleted {before - after})")
    return deleted


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--cache-file', default='property_history_cache.json')
    ap.add_argument('--quarters', default=','.join(DEFAULT_QUARTERS))
    ap.add_argument('--confirm-purge', action='store_true',
                    help='Required. Without it, investigate only, no delete/write.')
    ap.add_argument('--backup-path',
                    default='data/backups/deals_snapshot_backfilled_prepurge.json')
    args = ap.parse_args()
    quarters = [q.strip() for q in args.quarters.split(',') if q.strip()]

    print("=" * 92)
    print("PURGE-AND-REWRITE HISTORICAL BACKFILL"
          + ("" if args.confirm_purge else "  (INVESTIGATE ONLY — no --confirm-purge)"))
    print("=" * 92)

    b = SnapshotBackfiller(property_history_cache=args.cache_file)

    # SCHEMA GATE — a real insert-and-rollback of representative rows, before
    # any delete. This is the fix for the incident where the purge ran and the
    # write then failed on the backfill_confidence CHECK, leaving the quarters
    # empty: a column-existence probe passed but the values did not satisfy the
    # constraint. Now a missing column OR a constraint violation aborts BEFORE
    # a single row is deleted, so a purge never happens without a provable
    # ability to write the replacements.
    ok, err = b.validate_writable()
    if not ok:
        print(f"\n✗ ABORT: a representative row does not write to deals_snapshot:\n"
              f"    {err}")
        print("  Fix the schema (column or constraint) before purging anything.")
        raise SystemExit(3)
    print("\nSchema gate: representative rows (exact/pre_history/no_history) "
          "insert and roll back cleanly")

    # Baseline across ALL quarters, so protected sources can be checked after.
    print("\nBaseline — all deals_snapshot rows by (fiscal_quarter, source):")
    baseline = count_by_source(b.client)
    for (fq, src), n in baseline.items():
        print(f"    {str(fq):<12} {str(src):<26} {n:>7}")
    protected_before = {k: v for k, v in baseline.items()
                        if k[1] in PROTECTED_SOURCES}

    investigate(b.client, b.config, quarters)

    if not args.confirm_purge:
        print("\nInvestigate-only: pass --confirm-purge to back up, purge and write.")
        return 0

    backup(b.client, quarters, args.backup_path)

    print("\nPurging 'backfilled' rows in target quarters:")
    purge(b.client, quarters)

    # Verify protected sources survived intact.
    after = count_by_source(b.client)
    protected_after = {k: v for k, v in after.items()
                       if k[1] in PROTECTED_SOURCES}
    print("\nProtected sources (prospective, backfill_current_quarter) "
          "before vs after purge:")
    ok = protected_before == protected_after
    for k in sorted(set(protected_before) | set(protected_after)):
        print(f"    {str(k[0]):<12} {str(k[1]):<26} "
              f"{protected_before.get(k, 0):>7} -> {protected_after.get(k, 0):>7}")
    if not ok:
        raise SystemExit("✗ Protected-source counts changed — STOP. The purge "
                         "touched rows it must not have.")
    print("  ✓ protected sources unchanged")

    print("\nRemaining rows by (fiscal_quarter, source) — clean baseline for the write:")
    for (fq, src), n in after.items():
        print(f"    {str(fq):<12} {str(src):<26} {n:>7}")

    # WRITE — collision check inside backfill_quarters is now clean.
    print("\n" + "=" * 92)
    print("WRITING corrected reconstruction")
    print("=" * 92)
    collisions = b.collision_check(quarters)
    if collisions:
        print("✗ collision check still non-empty after purge — STOP:")
        for c in collisions:
            print(f"    {c['fiscal_quarter']} {c['snapshot_source']} {c['count']}")
        raise SystemExit(2)

    before_total = b.snapshot_row_count()
    result = b.backfill_quarters(quarters, report_only=False)
    after_total = b.snapshot_row_count()

    final = count_by_source(b.client)
    print(f"\ndeals_snapshot total rows: {before_total} -> {after_total} "
          f"(+{after_total - before_total})")
    print("\nFinal rows by (fiscal_quarter, source):")
    for (fq, src), n in final.items():
        print(f"    {str(fq):<12} {str(src):<26} {n:>7}")
    # NO_HISTORY population: deals that reconstruct with no stage history at
    # all become permanent null-stage rows in the substrate. Identify them so
    # they are understood before surfacing as anomalies. Probed at the newest
    # target week, which captures every such deal created by then.
    from datetime import date as _date
    probe_weeks = b.quarter_weeks(quarters[-1])
    if probe_weeks:
        nh = b.identify_no_history_deals(probe_weeks[-1])
        print(f"\nNO_HISTORY deals at {probe_weeks[-1]} (permanent null-stage "
              f"rows): {len(nh)}")
        print(f"  {'deal_id':<14} {'company':<26} {'current_stage':<16} "
              f"{'created':<12} hist_entries")
        for d in nh:
            print(f"  {d['deal_id']:<14} {str(d['company_name'])[:26]:<26} "
                  f"{str(d['current_stage']):<16} {d['create_date']:<12} "
                  f"{d['dealstage_history_entries']}")
        print("  hist_entries=0 means HubSpot has no dealstage history for the "
              "deal at all —")
        print("  typically an import or an API-created deal that never "
              "transitioned stage.")

    if result['unclassifiable']:
        print(f"\n✗ {len(set(result['unclassifiable']))} unclassifiable-stage deals")
        return 1
    print("\n✓ Purge-and-rewrite complete.")
    return 0


if __name__ == '__main__':
    sys.exit(main())
