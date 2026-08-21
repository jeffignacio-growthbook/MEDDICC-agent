#!/usr/bin/env python3
"""
Reconstruct deals_snapshot.forecast_category point-in-time — unlock commit
calibration and category churn.

The historical backfill (Method 2) wrote stage_id, deal_value and close_date
point-in-time but never forecast_category, so query_commit_calibration and
query_category_churn return null. The category history IS already in the
property-history cache (hubspot_history maps hs_manual_forecast_category ->
forecast_category_history); this consumes it through the SAME backward-looking
rule used for every other field (point_in_time.get_field_at_date) — no second
implementation of the logic.

This is an UPDATE of existing rows (the rows exist; the column is null), NOT a
re-backfill. Two modes:

  --dry-run  (default) reconstruct to memory and REPORT: rows resolved vs null
             (and why null), category distribution, and the go/no-go number —
             distinct deals tagged COMMIT at a mid-quarter week. No writes.

  --execute  schema/writable probe, back up affected rows to a durable in-repo
             file (re-read + count-matched), then UPDATE ONLY forecast_category
             and the category_confidence token in data_quality_notes — never
             stage_id, deal_value, close_date or any other column. Batched,
             resumable, idempotent, stable ordering. prospective rows (Method
             1's, already categorized by the live writer) are never touched;
             counted before and after.

Rules (unchanged from the substrate work):
  * value = most recent history entry with timestamp <= snapshot_date; never
    the nearest in either direction, never a forward-fill.
  * no entry at or before the date => NULL (pre_history / no_history / cleared),
    never a default category.
  * gates unchanged; a quarter below min_evidence_count returns null downstream.
"""
import os
import re
import sys
import json
import argparse
from pathlib import Path
from datetime import datetime
from collections import defaultdict, Counter

REPO_ROOT = Path(__file__).parent.parent.parent
sys.path.insert(0, str(REPO_ROOT / 'scripts'))
sys.path.insert(0, str(REPO_ROOT / 'scripts' / 'analytics'))

from supabase import create_client
from supabase_client import select_all
from point_in_time import get_field_at_date

CACHE_FILE = 'property_history_cache.json'
CATEGORY_HISTORY_KEY = 'forecast_category_history'   # hubspot_history HISTORY_KEYS
BACKUP_FILE = 'forecast_category_backup.json'
UPDATE_COLUMNS = ('forecast_category', 'data_quality_notes')  # nothing else


def _load_field_history(cache_path: str) -> dict:
    """Shape the cache's category history for get_field_at_date, exactly as
    backfill_snapshots builds field_history for the other fields."""
    with open(cache_path) as f:
        cache = json.load(f)
    deals = cache['deals']
    return {deal_id: {'history': rec.get(CATEGORY_HISTORY_KEY) or []}
            for deal_id, rec in deals.items()}


def _reconstruct(field_history, deal_id, snapshot_date_str):
    """(category_or_None, confidence) via the shared backward-looking rule."""
    d = datetime.strptime(snapshot_date_str[:10], '%Y-%m-%d')
    raw, conf = get_field_at_date(field_history, deal_id, d)
    if raw in (None, '', 'null'):
        return None, conf
    return str(raw), conf


def _upsert_category_note(existing_note: str, cat_conf: str) -> str:
    """Return data_quality_notes with category_confidence=<conf> set, preserving
    any existing value_confidence / close_date_confidence tokens. Idempotent —
    replaces an existing category_confidence token rather than appending a
    second one."""
    note = existing_note or ''
    token = f"category_confidence={cat_conf}"
    if 'category_confidence=' in note:
        return re.sub(r"category_confidence=[^;]*", token, note)
    if note.strip():
        return f"{note.rstrip().rstrip(';')}; {token}"
    return token


def _update_payload(category, note):
    """The exact column set an UPDATE may touch — forecast_category and the
    confidence note, nothing else. Factored so a test can assert the invariant."""
    return {'forecast_category': category, 'data_quality_notes': note}


PROBE_DEAL_ID = '__category_write_probe__'


def _writable_probe(sb):
    """Insert-and-rollback probe: prove forecast_category + data_quality_notes
    actually accept a write before touching real rows. A missing column, type
    error or constraint surfaces HERE, at zero cost. The probe row uses a
    sentinel deal_id and is always deleted, even on failure. Returns (ok, err)."""
    probe = {
        'deal_id': PROBE_DEAL_ID, 'snapshot_date': '1970-01-01',
        'pipeline_id': 'default', 'stage_id': None, 'stage_order': None,
        'deal_value': None, 'close_date': None, 'owner_email': None,
        'deal_status': 'active', 'snapshot_source': 'backfilled',
        'fiscal_quarter': 'PROBE', 'week_of_quarter': 1,
        'forecast_category': 'COMMIT',
        'data_quality_notes': 'category_confidence=exact',
    }
    ok, err = True, None
    try:
        sb.table('deals_snapshot').upsert(
            probe, on_conflict='deal_id,snapshot_date').execute()
        # read it back and confirm the two columns took the values
        r = sb.table('deals_snapshot').select(
            'forecast_category,data_quality_notes').eq(
            'deal_id', PROBE_DEAL_ID).execute()
        got = (r.data or [{}])[0]
        if got.get('forecast_category') != 'COMMIT':
            ok, err = False, f"probe read-back mismatch: {got}"
    except Exception as e:
        ok, err = False, str(e)
    finally:
        try:
            sb.table('deals_snapshot').delete().eq(
                'deal_id', PROBE_DEAL_ID).execute()
        except Exception:
            pass
    return ok, err


def _count_by_source(sb, source):
    rows = select_all(sb, 'deals_snapshot', columns='deal_id',
                      filters=[('eq', 'snapshot_source', source)])
    return len(rows)


def execute(sb, field_history):
    """Phase 3 write. Populate forecast_category (raw point-in-time value) for
    RESOLVED backfilled rows, plus its confidence note. Touches ONLY the two
    category columns via per-row .update() (never an upsert of the whole row,
    never an insert). prospective rows (Method 1's) are excluded by the load
    filter and counted before/after as a guard. Backup of the before-state is
    written and re-read/count-matched before any write. Idempotent: a row
    already carrying the reconstructed value is skipped, so a re-run is a no-op
    and a partial run resumes cleanly. Gates unchanged — this only fills a
    wrongly-null column; it does not decide whether any analysis clears them."""
    print("=" * 72)
    print("FORECAST_CATEGORY RECONSTRUCTION — EXECUTE (writing)")
    print("=" * 72)

    ok, err = _writable_probe(sb)
    if not ok:
        raise SystemExit(f"ABORT: schema/writable probe failed: {err}")
    print("✓ schema/writable probe passed (forecast_category + data_quality_notes)")

    prospective_before = _count_by_source(sb, 'prospective')
    print(f"prospective rows before: {prospective_before} (must be unchanged)")

    rows = load_backfilled_rows(sb)
    rows.sort(key=lambda r: (str(r['deal_id']), str(r['snapshot_date'])))  # stable

    to_write, skip_done, anomalies = [], 0, []
    dist = Counter()
    for r in rows:
        cat, conf = _reconstruct(field_history, r['deal_id'], r['snapshot_date'])
        if cat is None:
            continue  # leave genuinely-null rows null (pre_history / no_history)
        cur = r.get('forecast_category')
        if cur == cat:
            skip_done += 1  # already written — idempotent no-op
            continue
        if cur is not None:
            # a non-null value that disagrees with the reconstruction is NOT
            # ours to overwrite — record and skip rather than clobber.
            anomalies.append((r['deal_id'], r['snapshot_date'], cur, cat))
            continue
        note = _upsert_category_note(r.get('data_quality_notes'), conf)
        to_write.append({'deal_id': r['deal_id'],
                         'snapshot_date': r['snapshot_date'],
                         'category': cat, 'note': note,
                         'note_before': r.get('data_quality_notes')})
        dist[cat] += 1

    print(f"resolved rows to write: {len(to_write)}  "
          f"already-correct (skipped): {skip_done}  anomalies: {len(anomalies)}")
    if anomalies:
        print("  ⚠️ non-null forecast_category disagreeing with reconstruction "
              "(left untouched):")
        for a in anomalies[:10]:
            print(f"      {a}")

    # Backup the before-state, re-read and count-match BEFORE any write.
    backup = [{'deal_id': w['deal_id'], 'snapshot_date': w['snapshot_date'],
               'forecast_category_before': None,  # backfilled column is null pre-write
               'data_quality_notes_before': w['note_before']}
              for w in to_write]
    with open(BACKUP_FILE, 'w') as f:
        json.dump({'rows': backup, 'count': len(backup)}, f)
    with open(BACKUP_FILE) as f:
        reread = json.load(f)
    assert reread['count'] == len(to_write) == len(reread['rows']), \
        "backup count mismatch — refusing to write"
    print(f"✓ backup written and count-matched: {BACKUP_FILE} "
          f"({len(backup)} rows)")

    if not to_write:
        print("nothing to write (idempotent no-op).")
    else:
        written = 0
        for w in to_write:
            sb.table('deals_snapshot').update(
                _update_payload(w['category'], w['note'])).eq(
                'deal_id', w['deal_id']).eq(
                'snapshot_date', w['snapshot_date']).execute()
            written += 1
            if written % 500 == 0:
                print(f"  written {written}/{len(to_write)}")
        print(f"✓ wrote {written} rows (forecast_category + note only)")

    prospective_after = _count_by_source(sb, 'prospective')
    print(f"prospective rows after: {prospective_after}")
    assert prospective_after == prospective_before, \
        f"prospective rows changed {prospective_before}->{prospective_after}!"
    print("✓ prospective rows untouched")

    print("\ncategory distribution WRITTEN this run:")
    for k, v in sorted(dist.items(), key=lambda kv: -kv[1]):
        print(f"   {k}: {v}")
    return 0


def load_backfilled_rows(sb):
    """Existing backfilled snapshot rows we may update. prospective rows are
    Method 1's and excluded here (protected)."""
    return select_all(
        sb, 'deals_snapshot',
        columns='deal_id,snapshot_date,fiscal_quarter,week_of_quarter,'
                'snapshot_source,forecast_category,data_quality_notes',
        filters=[('eq', 'snapshot_source', 'backfilled')])


def report(sb, field_history):
    # "Commit-like" = the top forecast tier(s). HubSpot's raw enum carries
    # MOST_LIKELY between COMMIT and BEST_CASE, which the prompt's category list
    # did not mention — so probe both a strict COMMIT definition and a
    # COMMIT+MOST_LIKELY one, and report the vocabulary actually seen.
    COMMIT_ONLY = {'COMMIT'}
    COMMIT_LIKE = {'COMMIT', 'MOST_LIKELY'}

    rows = load_backfilled_rows(sb)
    by_q = defaultdict(lambda: {
        'total': 0, 'resolved': 0, 'null_no_history': 0,
        'null_pre_history': 0, 'null_cleared': 0, 'dist': Counter(),
        # distinct deals per week under each definition
        'commit_by_week': defaultdict(set), 'commitlike_by_week': defaultdict(set)})

    for r in rows:
        q = r.get('fiscal_quarter') or 'UNKNOWN'
        cat, conf = _reconstruct(field_history, r['deal_id'], r['snapshot_date'])
        b = by_q[q]
        b['total'] += 1
        if cat is not None:
            b['resolved'] += 1
            b['dist'][cat] += 1
            wk = r.get('week_of_quarter')
            if cat in COMMIT_ONLY:
                b['commit_by_week'][wk].add(r['deal_id'])
            if cat in COMMIT_LIKE:
                b['commitlike_by_week'][wk].add(r['deal_id'])
        else:
            b['dist']['NULL'] += 1
            b[f'null_{conf}'] = b.get(f'null_{conf}', 0) + 1

    me = _min_evidence()
    print("=" * 72)
    print("FORECAST_CATEGORY RECONSTRUCTION — DRY RUN (no writes)")
    print("=" * 72)
    print(f"backfilled rows considered: {len(rows)}")
    print(f"min_evidence_count (config): {me}")
    print("NOTE: HubSpot's raw enum includes MOST_LIKELY (a tier the prompt's "
          "list omitted). COMMIT-only and COMMIT+MOST_LIKELY are both reported; "
          "the client's 'Commit' definition decides which the answer uses.")

    def _peak(week_sets):
        # (peak_week, peak_distinct_count) across weeks 1-13
        best_wk, best_n = None, 0
        for wk in range(1, 14):
            n = len(week_sets.get(wk, ()))
            if n > best_n:
                best_wk, best_n = wk, n
        return best_wk, best_n

    go_nogo = {}
    for q in sorted(by_q):
        b = by_q[q]
        resolved_pct = (b['resolved'] / b['total'] * 100) if b['total'] else 0
        print(f"\n── {q} ──  rows={b['total']}  resolved={b['resolved']} "
              f"({resolved_pct:.0f}%)  null={b['total'] - b['resolved']}")
        print(f"   null reasons: no_history={b.get('null_no_history', 0)}  "
              f"pre_history={b.get('null_pre_history', 0)}  "
              f"cleared={b.get('null_cleared', 0)}")
        dist = "  ".join(f"{k}={v}" for k, v in sorted(
            b['dist'].items(), key=lambda kv: -kv[1]))
        print(f"   distribution: {dist}")
        # distinct COMMIT deals per week — the anchor may be any week, so show all
        wk_line = " ".join(
            f"w{wk}:{len(b['commit_by_week'].get(wk, ()))}" for wk in range(1, 14))
        print(f"   COMMIT distinct/week: {wk_line}")
        cpw, cpn = _peak(b['commit_by_week'])
        lpw, lpn = _peak(b['commitlike_by_week'])
        go_nogo[q] = {'commit_peak_wk': cpw, 'commit_peak_n': cpn,
                      'like_peak_wk': lpw, 'like_peak_n': lpn}
        print(f"   >>> peak COMMIT: {cpn} (week {cpw})   "
              f"peak COMMIT+MOST_LIKELY: {lpn} (week {lpw})")

    print("\n" + "=" * 72)
    print("GO / NO-GO — peak distinct top-tier deals in a single week")
    print("(commit calibration anchors on the empirically-measured week, not a "
          f"fixed midpoint; a quarter must reach min_evidence_count={me} in the "
          "anchor week to yield a rate. Gate unchanged.)")
    print("=" * 72)
    for q in sorted(go_nogo):
        g = go_nogo[q]
        cv = "GO" if g['commit_peak_n'] >= me else "below gate -> null"
        lv = "GO" if g['like_peak_n'] >= me else "below gate -> null"
        print(f"   {q}:  COMMIT peak {g['commit_peak_n']:>4d} (w{g['commit_peak_wk']}) "
              f"{cv:<20s} | COMMIT+MOST_LIKELY peak {g['like_peak_n']:>4d} "
              f"(w{g['like_peak_wk']}) {lv}")


def _min_evidence():
    import yaml
    cfg = yaml.safe_load((REPO_ROOT / 'config' / 'client.yaml').read_text())
    return cfg.get('proposal_engine', {}).get('min_evidence_count', 30)


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument('--dry-run', action='store_true', default=True)
    ap.add_argument('--execute', action='store_true',
                    help='(Phase 3) write the reconstruction')
    ap.add_argument('--cache-file', default=CACHE_FILE)
    args = ap.parse_args()

    sb = create_client(os.environ['SUPABASE_URL'],
                       os.environ['SUPABASE_SERVICE_KEY'])
    field_history = _load_field_history(args.cache_file)
    print(f"Loaded category history for {len(field_history)} deals "
          f"from {args.cache_file}")

    if args.execute:
        return execute(sb, field_history)
    report(sb, field_history)
    return 0


if __name__ == '__main__':
    sys.exit(main())
