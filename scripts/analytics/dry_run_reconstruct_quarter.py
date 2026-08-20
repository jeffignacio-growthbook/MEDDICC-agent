"""
Phase 3 dry run — reconstruct one quarter to MEMORY, write nothing.

Reconstructs every weekly snapshot for a quarter using the corrected
population and reports whether the result is trustworthy enough to write.
Writes to no table; the reconstructed rows go to a file artifact so a bad run
can be diffed rather than only re-run.

CORRECTED POPULATION (this is the Phase 2a fix, implemented not just
diagnosed). The prior attempt drove the population from
property_history.keys() and dropped any deal whose stage history did not
reach back to D — the ~291-cap, 16-27% coverage. Here the population is
driven from the deals table via the shared inclusion rule: every deal
created on or before D that is not terminal at D is IN, and a deal with no
stage history at D is a null-stage 'pre_history' row, not a drop.

So coverage no longer means "how many deals did we keep" — the cap is gone
and by construction we keep the whole open population. It means "how much of
that population has stage history reaching back to D": 'exact' is usable for
conversion analysis, 'pre_history' is in the snapshot as open but its stage
is unknown. Older quarters legitimately carry more pre_history, and that is
what min_scoped_snapshot_coverage_pct gates.

WHAT THIS DRY RUN DOES AND DOES NOT ESTABLISH:
  - Per-week scoped coverage against min_scoped_snapshot_coverage_pct.
  - Confidence distribution under the redefined labels.
  - One-week cross-validation against Method 1's written rows. This tests
    RECONSTRUCTION FIDELITY — does replaying history reproduce a known-good
    same-day capture — NOT rule correctness. Both methods call the same
    is_deal_open_at_date, so a shared-rule bug moves both arms together and
    reads as agreement. The rule's evidence is the deal-level point-in-time
    comparison (15 recovered past-due-open deals; one genuine disagreement,
    Creative CX, constant across four dates), not a green cross-validation.

Usage:
    python scripts/analytics/dry_run_reconstruct_quarter.py \
        --quarter "FY2027 Q2" --cross-validate-date 2026-08-19
    ... --deals-json deals.json   # offline, deals from a file not Supabase
"""
import argparse
import json
import os
import sys
from collections import Counter, defaultdict
from datetime import date, datetime, timedelta
from pathlib import Path

REPO_ROOT = Path(__file__).parent.parent.parent
sys.path.insert(0, str(REPO_ROOT / 'scripts'))
sys.path.insert(0, str(REPO_ROOT / 'scripts' / 'analytics'))
sys.path.insert(0, str(REPO_ROOT / 'api'))

import yaml
from point_in_time import (is_deal_in_analytics_scope, load_scope_config,
                           reconstruct_open_rows)
from utils import get_fiscal_quarter, get_value_properties, compute_deal_value
# Single source of truth for the per-property cache shape — importing rather
# than re-declaring, so a new tracked property cannot exist in the fetcher and
# silently read as no_history here.
from hubspot_history import HISTORY_KEYS


def parse_date(raw):
    if raw in (None, '', 'null'):
        return None
    s = str(raw).strip()
    if s.lstrip('-').isdigit():
        try:
            return datetime.utcfromtimestamp(int(s) / 1000).date()
        except (ValueError, OSError, OverflowError):
            return None
    try:
        return datetime.fromisoformat(s.replace('Z', '+00:00')).date()
    except ValueError:
        return None


def quarter_weeks(quarter_label, config):
    """The weekly Monday snapshot dates whose fiscal quarter is quarter_label.

    Derived by labelling candidate Mondays with get_fiscal_quarter rather than
    hardcoding the fiscal layout, so the fiscal calendar cannot be got wrong
    here.
    """
    # Scan a 2-year window of Mondays; keep those in the target quarter.
    start = date(2025, 1, 6)  # a Monday
    weeks = []
    for i in range(0, 130):
        d = start + timedelta(weeks=i)
        _, _, label = get_fiscal_quarter(d, config)
        if label == quarter_label:
            weeks.append(d)
    return weeks


def load_cache(cache_path):
    cache = json.loads(Path(cache_path).read_text())
    stage_history = cache['deals']
    field_history = {prop: {d: {'history': rec.get(key) or []}
                            for d, rec in cache['deals'].items()}
                     for prop, key in HISTORY_KEYS.items()}
    return stage_history, field_history


def load_deals(deals_json):
    if deals_json:
        rows = json.loads(Path(deals_json).read_text())
    else:
        from supabase import create_client
        from supabase_client import select_all
        sb = create_client(os.environ['SUPABASE_URL'],
                           os.environ['SUPABASE_SERVICE_KEY'])
        rows = select_all(sb, 'deals',
                          columns='deal_id,create_date,pipeline_id,'
                                  'company_name,stage')
    deals = {}
    for r in rows:
        cd = parse_date(r.get('create_date'))
        if cd is None:
            continue
        deals[str(r['deal_id'])] = {
            'create': cd,
            'pipeline': str(r.get('pipeline_id') or 'default'),
            'name': r.get('company_name') or '',
            'current_stage': r.get('stage'),
        }
    return deals


def method1_rows(cross_val_date):
    """Method 1's written prospective deal-ids for one date (for fidelity)."""
    from supabase import create_client
    from supabase_client import select_all
    sb = create_client(os.environ['SUPABASE_URL'],
                       os.environ['SUPABASE_SERVICE_KEY'])
    rows = select_all(sb, 'deals_snapshot', columns='deal_id,stage_id',
                      filters=[('eq', 'snapshot_date', cross_val_date),
                               ('eq', 'snapshot_source', 'prospective')])
    return {str(r['deal_id']): r.get('stage_id') for r in rows}


def reconstruct_week(D, deals, stage_history, field_history, config,
                     value_props, excl_pipelines, stage_cfg):
    """Coverage tally for one date. Population + value reconstruction come from
    the shared point_in_time.reconstruct_open_rows — this function only scopes
    and counts, so it cannot diverge from the writer on who is in the snapshot."""
    open_rows, raised = reconstruct_open_rows(
        deals, stage_history, field_history, D, config, value_props,
        compute_deal_value)
    rows, tally = [], Counter()
    for r in open_rows:
        stage = r['stage_id']
        s_conf = r['stage_confidence']
        pipeline = r['pipeline']
        # Denominator scoped by PIPELINE (known from the deals table whatever
        # the stage shows); numerator also needs a known, qualified stage.
        # Certainty excludes, ignorance counts against us: a KNOWN excluded
        # stage leaves the denominator; an UNKNOWN stage in a non-excluded
        # pipeline stays in and, being unusable, depresses coverage.
        pipeline_in_scope = pipeline not in excl_pipelines
        usable = is_deal_in_analytics_scope(stage, pipeline,
                                            excl_pipelines, stage_cfg)
        in_denom = pipeline_in_scope and (usable or stage is None)
        rows.append({**r, 'snapshot_date': D.isoformat(),
                     'in_denom': in_denom, 'usable': usable})
        tally['open'] += 1
        tally[f'stage_{s_conf}'] += 1
        tally[f"value_{r['value_confidence']}"] += 1
        if in_denom:
            tally['scopable_open'] += 1
            tally[f'scopable_stage_{s_conf}'] += 1
            if usable:
                tally['usable'] += 1
    return rows, tally, raised


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--quarter', default='FY2027 Q2')
    ap.add_argument('--cache-file', default='property_history_cache.json')
    ap.add_argument('--deals-json', default=None)
    ap.add_argument('--cross-validate-date', default='2026-08-19')
    ap.add_argument('--out', default='dry_run_reconstruction.json')
    args = ap.parse_args()

    config = yaml.safe_load((REPO_ROOT / 'config/client.yaml').read_text())
    gate = config['forecast_analysis'].get('min_scoped_snapshot_coverage_pct', 80)
    value_props = get_value_properties(config)
    excl_pipelines, stage_cfg = load_scope_config(config)
    stage_history, field_history = load_cache(args.cache_file)
    deals = load_deals(args.deals_json)

    # A value property with no history column would silently read no_history
    # for every deal — the exact invisibility that hid renewal_revenue.
    missing = [p for p in value_props if p not in HISTORY_KEYS]
    if missing:
        print(f"✗ value properties {missing} are not tracked in the cache.")
        return 2

    weeks = quarter_weeks(args.quarter, config)
    print("=" * 92)
    print(f"PHASE 3 DRY RUN — {args.quarter}  (reconstruct to memory, write nothing)")
    print("=" * 92)
    print(f"\nDeals with create_date: {len(deals)}   cache: {len(stage_history)}")
    print(f"Weeks in {args.quarter}: {len(weeks)}"
          + (f"  {weeks[0]}..{weeks[-1]}" if weeks else "  (none)"))
    print(f"Scoped-coverage gate (min_scoped_snapshot_coverage_pct): {gate}%")
    if not weeks:
        print("✗ No weeks resolved for this quarter label.")
        return 2

    all_rows, summary, any_raised = [], [], []
    print(f"\n{'week':<12} {'open':>6} {'denom':>7} {'usable':>7} {'pre_hist':>9} "
          f"{'no_hist':>8} {'usable%':>8} {'gate':>6}")
    print("-" * 92)
    for D in weeks:
        rows, tally, raised = reconstruct_week(
            D, deals, stage_history, field_history, config, value_props,
            excl_pipelines, stage_cfg)
        all_rows.extend(rows)
        any_raised.extend(raised)
        denom = tally['scopable_open']          # open, non-excluded pipeline
        usable_n = tally['usable']                # known + qualified stage
        pre = tally['scopable_stage_pre_history']
        no = tally['scopable_stage_no_history']
        pct = (usable_n / denom * 100) if denom else 0.0
        verdict = 'PASS' if pct >= gate else 'FAIL'
        summary.append((D, tally['open'], denom, usable_n, pre, no, pct, verdict))
        print(f"{D.isoformat():<12} {tally['open']:>6} {denom:>7} {usable_n:>7} "
              f"{pre:>9} {no:>8} {pct:>7.1f}% {verdict:>6}")

    Path(args.out).write_text(json.dumps(all_rows, indent=1, default=str))
    passed = [s for s in summary if s[7] == 'PASS']

    # ---- Confidence distribution (stage + value) across the quarter --------
    stage_dist, value_dist = Counter(), Counter()
    for r in all_rows:
        stage_dist[r['stage_confidence']] += 1
        value_dist[r['value_confidence']] += 1
    tot = len(all_rows) or 1
    print(f"\nConfidence distribution across {len(all_rows)} reconstructed "
          f"deal-weeks (redefined labels):")
    print("  stage:  " + "  ".join(f"{k}={v} ({v/tot*100:.0f}%)"
                                    for k, v in stage_dist.most_common()))
    print("  value:  " + "  ".join(f"{k}={v} ({v/tot*100:.0f}%)"
                                    for k, v in value_dist.most_common()))
    print("  Old definition produced 0% 'exact' by requiring a same-day change;"
          " 'exact' now means history covers the date.")

    if any_raised:
        print(f"\n✗ {len(any_raised)} deal-week(s) raised on an unclassifiable "
              f"stage — resolve before Phase 4.")

    # ---- One-week cross-validation (fidelity, not rule validation) ---------
    print("\n" + "=" * 92)
    print(f"CROSS-VALIDATION — {args.cross_validate_date} vs Method 1 (fidelity)")
    print("=" * 92)
    print("Tests whether replayed history reproduces Method 1's same-day capture.")
    print("NOT rule validation: both call is_deal_open_at_date, so a shared-rule")
    print("bug moves both arms together. The rule's evidence is the deal-level")
    print("point-in-time comparison, not this agreement.")
    if args.deals_json:
        print("\n(offline: --deals-json given, skipping Method 1 comparison)")
    else:
        cvd = date.fromisoformat(args.cross_validate_date)
        rows, _, _ = reconstruct_week(cvd, deals, stage_history, field_history,
                                      config, value_props, excl_pipelines,
                                      stage_cfg)
        recon = {r['deal_id'] for r in rows}
        m1 = method1_rows(args.cross_validate_date)
        m1_ids = set(m1)
        both = recon & m1_ids
        stage_agree = sum(1 for i in both
                          if next(r for r in rows if r['deal_id'] == i)['stage_id']
                          == m1[i])
        print(f"\n  reconstructed open: {len(recon)}   Method 1 wrote: {len(m1_ids)}")
        print(f"  in both: {len(both)}   stage agrees: {stage_agree}/{len(both)}")
        print(f"  reconstruct-only: {len(recon - m1_ids)}   "
              f"Method1-only: {len(m1_ids - recon)}")
        print("  (Method 1 writes unscoped and today's stage==stage@D for a")
        print("   same-day capture, so disagreement here is fidelity signal.)")

    # ---- Verdict -----------------------------------------------------------
    print("\n" + "=" * 92)
    print("VERDICT")
    print("=" * 92)
    print(f"  weeks passing {gate}% scoped coverage: {len(passed)}/{len(summary)}")
    for D, *_rest, usable, verdict in summary:
        if verdict == 'FAIL':
            print(f"    {D.isoformat()}  {usable:.1f}%  FAIL — history does not "
                  f"reach back far enough; not a bug, a limit of this quarter")
    print("\n  DOLLAR-BASIS CAVEAT: forecast_analyses still coalesces null "
          "deal_value to 0")
    print("  (config/null_value_coalescing_ledger.yaml). No dollar-basis "
          "conversion number")
    print("  may be reported or acted on until that ledger is worked off. "
          "basis: count is")
    print("  unaffected and is the current default.")
    print(f"\n  Reconstruction written to {args.out} (memory/file only; "
          f"no table touched).")
    return 0


if __name__ == '__main__':
    sys.exit(main())
