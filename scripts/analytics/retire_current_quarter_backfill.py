"""
Retire the backfill_current_quarter stopgap for the current fiscal quarter.

Why
---
backfill_current_quarter.py was a stopgap written before Method 1 (the live
weekly cron) existed, to fill the current quarter's already-elapsed weeks. It
stamps each deal's CURRENT stage onto every week instead of reconstructing
stage point-in-time, so within-quarter stage movement is unobservable and
exits read as structurally zero (verified empirically: 0/696 transitions in
FY2027 Q3's copied-stage rows vs 184/4,274 in a point-in-time backfilled
quarter). Those rows are what query_pipeline_movement reads (three Monday rows
beat two consecutive-day prospective rows in the grid guard), so the movement
view is wrong for the current quarter.

Fix: reconstruct the current quarter's ELAPSED weeks point-in-time with the
same Method 2 machinery, purge the backfill_current_quarter rows, and let
Method 1 (prospective) own everything from its first live write forward. After
this every deals_snapshot row is point-in-time from one of two correct
sources: 'backfilled' (reconstructed) or 'prospective' (Method 1 live).

Scope of the write
------------------
Only Mondays that (a) have elapsed and (b) predate Method 1's first live
'prospective' write for this quarter — so we never reconstruct a not-yet-
elapsed week nor a week Method 1 already owns. The Method 1 start is read from
the data (min prospective snapshot_date in the quarter), not hardcoded.

Guards (same discipline as Method 2's purge-and-rewrite)
--------------------------------------------------------
  1. Schema gate — validate_writable() inserts+rolls back representative rows
     BEFORE any delete (the incident fix).
  2. Backup — every backfill_current_quarter row to a durable in-repo file,
     re-read and count-matched before any delete.
  3. Purge — scoped to snapshot_source='backfill_current_quarter' AND this
     quarter only.
  4. Protected-source verify — 'prospective' counts unchanged across the purge.
  5. Targeted collision check — no 'backfilled' rows exist on the target dates
     (prospective lives on other dates, so the write is purely additive there).
  6. Coverage gate per week — reported; failing weeks flagged.
  7. Numbers first — a bare run (no --confirm) reports the dry-run and stops.

Usage (CI, after the fetch step builds the cache):
    # dry-run (numbers only, no write):
    python scripts/analytics/retire_current_quarter_backfill.py
    # execute (guarded write):
    python scripts/analytics/retire_current_quarter_backfill.py --confirm
"""
import argparse
import json
import sys
from collections import Counter
from datetime import datetime, date, timedelta
from pathlib import Path

REPO_ROOT = Path(__file__).parent.parent.parent
sys.path.insert(0, str(REPO_ROOT / 'scripts'))
sys.path.insert(0, str(REPO_ROOT / 'scripts' / 'analytics'))
sys.path.insert(0, str(REPO_ROOT / 'api'))

from supabase_client import select_all
from utils import get_fiscal_quarter
from backfill_snapshots import SnapshotBackfiller, _scoped_coverage

STOPGAP = 'backfill_current_quarter'
RECONSTRUCTED = 'backfilled'
LIVE = 'prospective'


def current_quarter_label(config):
    _, _, label = get_fiscal_quarter(date.today(), config)
    return label


def method1_start(client, quarter):
    """Earliest live 'prospective' snapshot_date in the quarter, or None."""
    rows = select_all(client, 'deals_snapshot', columns='snapshot_date',
                      filters=[('eq', 'fiscal_quarter', quarter),
                               ('eq', 'snapshot_source', LIVE)])
    dates = sorted(r['snapshot_date'] for r in rows)
    return dates[0] if dates else None


def counts_by_source(client, quarter):
    rows = select_all(client, 'deals_snapshot',
                      columns='snapshot_source,snapshot_date',
                      filters=[('eq', 'fiscal_quarter', quarter)])
    by_src = Counter(r.get('snapshot_source') for r in rows)
    dates_by_src = {}
    for r in rows:
        dates_by_src.setdefault(r.get('snapshot_source'), set()).add(r['snapshot_date'])
    return by_src, {k: sorted(v) for k, v in dates_by_src.items()}


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--cache-file', default='property_history_cache.json')
    ap.add_argument('--quarter', default=None,
                    help="Fiscal quarter label (default: current, e.g. 'FY2027 Q3')")
    ap.add_argument('--confirm', action='store_true',
                    help='Required to write. Without it: dry-run numbers only.')
    ap.add_argument('--backup-path',
                    default='data/backups/deals_snapshot_current_quarter_stopgap_prepurge.json')
    args = ap.parse_args()

    b = SnapshotBackfiller(property_history_cache=args.cache_file)
    quarter = args.quarter or current_quarter_label(b.config)
    gate = b.config['forecast_analysis'].get('min_scoped_snapshot_coverage_pct', 80)

    print("=" * 92)
    print(f"RETIRE backfill_current_quarter — {quarter}"
          + ("  (DRY-RUN, no write)" if not args.confirm else "  (EXECUTING)"))
    print("=" * 92)

    # ── current state ──
    by_src, dates_by_src = counts_by_source(b.client, quarter)
    print(f"\nCurrent {quarter} rows by source:")
    for src in sorted(by_src):
        print(f"    {str(src):<26} {by_src[src]:>6}  dates={dates_by_src.get(src)}")

    stopgap_n = by_src.get(STOPGAP, 0)
    if stopgap_n == 0:
        print(f"\nNothing to retire — {quarter} has no '{STOPGAP}' rows.")
        return 0

    # ── bound the reconstruction: elapsed Mondays strictly before Method 1 ──
    m1 = method1_start(b.client, quarter)
    today = date.today()
    if m1:
        through = datetime.fromisoformat(m1).date() - timedelta(days=1)
        print(f"\nMethod 1 first live write in {quarter}: {m1} "
              f"→ reconstruct Mondays on/before {through}")
    else:
        through = today
        print(f"\nNo live 'prospective' rows yet in {quarter} → reconstruct "
              f"elapsed Mondays on/before {through}")
    b.through_date = through

    weeks = b.quarter_weeks(quarter)
    print(f"Elapsed weeks to reconstruct ({len(weeks)}): "
          f"{[w.isoformat() for w in weeks]}")
    if not weeks:
        print("No elapsed weeks resolved — nothing to do.")
        return 0

    # ── dry-run reconstruction numbers per week ──
    print(f"\n{'week (Monday)':<14} {'rows':>6} {'exact':>7} {'pre_h':>6} "
          f"{'no_h':>6} {'usable%':>8} {'gate':>6}   stopgap_rows_same_date")
    print("-" * 92)
    total_rows = 0
    min_pct = 999.0
    all_pass = True
    for D in weeks:
        rows, unclassifiable, tally = b.build_rows_for_date(D)
        if unclassifiable:
            print(f"  ✗ {D}: {len(set(unclassifiable))} unclassifiable-stage "
                  f"deals — resolve in field_semantics before writing.")
            all_pass = False
        usable, denom = _scoped_coverage(rows, b.config)
        pct = (usable / denom * 100) if denom else 0.0
        min_pct = min(min_pct, pct)
        verdict = 'PASS' if pct >= gate else 'FAIL'
        all_pass = all_pass and verdict == 'PASS'
        stopgap_same = sum(1 for d in dates_by_src.get(STOPGAP, [])
                           if d == D.isoformat())
        total_rows += tally['rows']
        print(f"  {D.isoformat():<12} {tally['rows']:>6} "
              f"{tally.get('stage_exact', 0):>7} {tally.get('stage_pre_history', 0):>6} "
              f"{tally.get('stage_no_history', 0):>6} {pct:>7.1f}% {verdict:>6}   "
              f"{('yes' if stopgap_same else 'no')}")
    print("-" * 92)
    print(f"  reconstructed rows total: {total_rows} | min week coverage: "
          f"{min_pct:.1f}% (gate {gate}%) | {'ALL PASS' if all_pass else 'SOME FAIL'}")
    print(f"  stopgap rows to be purged: {stopgap_n}")

    if not args.confirm:
        print("\nDRY-RUN only. Re-run with --confirm to back up, purge the "
              f"'{STOPGAP}' rows, and write the reconstruction.")
        return 0

    if not all_pass:
        print("\n✗ ABORT: a week fails the coverage gate or has unclassifiable "
              "stages. Not writing. (Never lower the gate to pass.)")
        return 2

    # ── 1. schema gate (before any delete) ──
    ok, err = b.validate_writable(sample_date=weeks[-1])
    if not ok:
        print(f"\n✗ ABORT (schema gate): {err}")
        return 3
    print("\nSchema gate: representative rows insert and roll back cleanly.")

    # ── 2. backup the stopgap rows ──
    stopgap_rows = select_all(b.client, 'deals_snapshot', columns='*',
                              filters=[('eq', 'fiscal_quarter', quarter),
                                       ('eq', 'snapshot_source', STOPGAP)])
    bpath = Path(args.backup_path)
    if bpath.exists():
        n = 1
        while (bpath.parent / f"{bpath.stem}_{n}{bpath.suffix}").exists():
            n += 1
        bpath = bpath.parent / f"{bpath.stem}_{n}{bpath.suffix}"
    bpath.parent.mkdir(parents=True, exist_ok=True)
    bpath.write_text(json.dumps(stopgap_rows, indent=1, default=str))
    reread = json.loads(bpath.read_text())
    print(f"\nBacked up {len(stopgap_rows)} '{STOPGAP}' rows -> {bpath} "
          f"({'MATCH' if len(reread) == len(stopgap_rows) else 'MISMATCH — ABORT'})")
    if len(reread) != len(stopgap_rows):
        raise SystemExit("Backup verification failed — not deleting anything.")

    # ── protected-source baseline (prospective) ──
    prospective_before = by_src.get(LIVE, 0)

    # ── 3. purge the stopgap rows for this quarter ──
    before = len(select_all(b.client, 'deals_snapshot', columns='deal_id',
                 filters=[('eq', 'fiscal_quarter', quarter),
                          ('eq', 'snapshot_source', STOPGAP)]))
    b.client.table('deals_snapshot').delete()\
        .eq('snapshot_source', STOPGAP).eq('fiscal_quarter', quarter).execute()
    after = len(select_all(b.client, 'deals_snapshot', columns='deal_id',
                filters=[('eq', 'fiscal_quarter', quarter),
                         ('eq', 'snapshot_source', STOPGAP)]))
    print(f"\nPurged '{STOPGAP}' in {quarter}: {before} -> {after} "
          f"(deleted {before - after})")

    # ── 4. verify protected source (prospective) unchanged ──
    by_src2, _ = counts_by_source(b.client, quarter)
    prospective_after = by_src2.get(LIVE, 0)
    print(f"Protected source '{LIVE}': {prospective_before} -> {prospective_after}")
    if prospective_after != prospective_before:
        raise SystemExit("✗ Protected-source count changed — STOP.")

    # ── 5. targeted collision check on the target dates ──
    target_dates = {w.isoformat() for w in weeks}
    clash = select_all(b.client, 'deals_snapshot', columns='snapshot_date,snapshot_source',
                       filters=[('eq', 'fiscal_quarter', quarter),
                                ('eq', 'snapshot_source', RECONSTRUCTED)])
    clash_dates = {r['snapshot_date'] for r in clash} & target_dates
    if clash_dates:
        raise SystemExit(f"✗ existing '{RECONSTRUCTED}' rows on target dates "
                         f"{sorted(clash_dates)} — STOP.")
    print(f"Collision check: no existing '{RECONSTRUCTED}' rows on "
          f"{sorted(target_dates)} — write is additive.")

    # ── 6. write the reconstruction (bounded weeks) ──
    before_total = b.snapshot_row_count()
    result = b.backfill_quarters([quarter], report_only=False,
                                 checkpoint_path='retire_cq_checkpoint.json')
    after_total = b.snapshot_row_count()

    by_src3, dates3 = counts_by_source(b.client, quarter)
    print(f"\ndeals_snapshot total rows: {before_total} -> {after_total} "
          f"(+{after_total - before_total})")
    print(f"\nFinal {quarter} rows by source:")
    for src in sorted(by_src3):
        print(f"    {str(src):<26} {by_src3[src]:>6}  dates={dates3.get(src)}")

    if result['unclassifiable']:
        print(f"\n✗ {len(set(result['unclassifiable']))} unclassifiable-stage deals")
        return 1
    print(f"\n✓ Retired '{STOPGAP}' for {quarter}. Every row is now point-in-time "
          f"('{RECONSTRUCTED}' reconstructed or '{LIVE}' live).")
    return 0


if __name__ == '__main__':
    sys.exit(main())
