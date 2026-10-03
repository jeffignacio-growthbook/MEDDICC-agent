#!/usr/bin/env python3
"""
One-off audit: compare the OLD actual_incremental_closed_won() filter
(pipeline_id-based renewal exclusion + is_won(current stage) outcome)
against the proposed NEW filter (is_incremental_pipeline() dollar-based
exclusion + deal_status=="won" outcome — matching query_path_to_target's
inline computation and assess_loss_concentration.won_incremental_arr) —
over REAL data, for:
  1. The current fiscal quarter (the new current-quarter QTD use this
     filter change is being made for).
  2. Every prior-year window query_coverage_proxy_target_by_week()
     actually uses (the existing use of this function, computing the
     proxy-target curve's historical base).

Also reports query_rep_attainment's own won-ARR total for the current
quarter as a fourth, independently-computed reference point (it has yet
a different renewal-exclusion rule: deal_status=="won" + pipeline_id-based
exclusion — a hybrid of the OLD and NEW definitions below).

Report only. No primitive is changed here. Safe to delete once this
one-time comparison is read.
"""
import sys
from pathlib import Path
from datetime import date

REPO_ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(REPO_ROOT / "scripts"))
sys.path.insert(0, str(REPO_ROOT / "scripts" / "analytics"))
sys.path.insert(0, str(REPO_ROOT / "api"))
sys.path.insert(0, str(REPO_ROOT))


def _old_definition(sb, q_start_iso, q_end_iso):
    """pipeline_id-based renewal exclusion + is_won(current stage)."""
    from field_semantics import _RENEWAL_PIPELINE_ID, is_won
    from supabase_client import select_all
    from api.incremental_arr import incremental_arr
    deals = select_all(sb, 'deals',
        columns='deal_id,stage,close_date,pipeline_id,new_arr,expansion_arr,deal_status')
    total, n = 0.0, 0
    for d in deals:
        stage, close_date, pipeline_id = d.get('stage'), d.get('close_date'), d.get('pipeline_id')
        if not stage or not close_date:
            continue
        if str(pipeline_id) == _RENEWAL_PIPELINE_ID:
            continue
        try:
            if not is_won(str(stage)):
                continue
        except Exception:
            continue
        if not (q_start_iso <= str(close_date)[:10] <= q_end_iso):
            continue
        total += incremental_arr(d)
        n += 1
    return total, n


def _new_definition(sb, q_start_iso, q_end_iso):
    """is_incremental_pipeline() dollar-based exclusion + deal_status=='won'."""
    from field_semantics import is_incremental_pipeline
    from supabase_client import select_all
    from api.incremental_arr import incremental_arr
    deals = select_all(sb, 'deals',
        columns='deal_id,close_date,pipeline_id,new_arr,expansion_arr,deal_status',
        filters=[('eq', 'deal_status', 'won'),
                 ('gte', 'close_date', q_start_iso),
                 ('lte', 'close_date', q_end_iso)])
    total, n = 0.0, 0
    for d in deals:
        if is_incremental_pipeline(d):
            total += incremental_arr(d)
            n += 1
    return total, n


def _rep_attainment_definition(sb, q_start_iso, q_end_iso):
    """query_rep_attainment's own rule: deal_status=='won' + pipeline_id-
    based exclusion (a hybrid of old and new, reported for reference)."""
    from field_semantics import _RENEWAL_PIPELINE_ID
    from supabase_client import select_all
    from api.incremental_arr import incremental_arr
    deals = select_all(sb, 'deals',
        columns='owner_email,new_arr,expansion_arr,pipeline_id,deal_status,close_date',
        filters=[('eq', 'deal_status', 'won'),
                 ('gte', 'close_date', q_start_iso),
                 ('lte', 'close_date', q_end_iso)])
    total, n = 0.0, 0
    for d in deals:
        if str(d.get('pipeline_id') or '') == _RENEWAL_PIPELINE_ID:
            continue
        total += incremental_arr(d)
        n += 1
    return total, n


def _reopened_deal_diagnostic(sb, q_start_iso, q_end_iso):
    """Deals where the outcome source (deal_status) and the materialized
    `stage` column disagree on whether the deal is won, within the given
    close_date window. Two directions, independently real:
      (a) stage says won, deal_status says not won — e.g. reopened after
          being marked Closed Won, stage not yet re-synced (or lagging).
      (b) deal_status says won, stage says not won (a stage-lag/correction
          scenario in the other direction).
    Needed to size how much the 2026-10-03 filter generalization (reading
    deal_status instead of stage) actually moves real numbers, beyond the
    synthetic fixture in tests/test_coverage_qtd_reconciliation.py.
    Report only — no write, no primitive touched."""
    from field_semantics import is_won
    from supabase_client import select_all
    from api.incremental_arr import incremental_arr
    deals = select_all(sb, 'deals',
        columns='deal_id,stage,deal_status,close_date,new_arr,expansion_arr',
        filters=[('gte', 'close_date', q_start_iso),
                 ('lte', 'close_date', q_end_iso)])
    stage_won_status_not = []
    status_won_stage_not = []
    for d in deals:
        stage = d.get('stage')
        status = (d.get('deal_status') or '').lower()
        try:
            stage_says_won = bool(stage) and is_won(str(stage))
        except Exception:
            stage_says_won = False
        status_says_won = status == 'won'
        if stage_says_won and not status_says_won:
            stage_won_status_not.append(d)
        elif status_says_won and not stage_says_won:
            status_won_stage_not.append(d)
    return stage_won_status_not, status_won_stage_not


def _print_reopened_deal_diagnostic(label, q_start_iso, q_end_iso, a, b):
    from api.incremental_arr import incremental_arr
    a_total = sum(incremental_arr(d) for d in a)
    b_total = sum(incremental_arr(d) for d in b)
    print(f"{label} [{q_start_iso}..{q_end_iso}] reopened/stage-lag diagnostic:")
    print(f"  (a) stage=won, deal_status!=won: {len(a)} deals, ${a_total:,.0f} — "
          f"{[d['deal_id'] for d in a] if a else '(none)'}")
    print(f"  (b) deal_status=won, stage!=won: {len(b)} deals, ${b_total:,.0f} — "
          f"{[d['deal_id'] for d in b] if b else '(none)'}")


def main():
    from db import get_supabase
    from utils import get_fiscal_quarter
    from forecast_analyses import _get_complete_quarters, _quarter_window_iso, _prior_year_window

    sb = get_supabase()

    print("=" * 70)
    print("CURRENT QUARTER (the new use this filter change is being made for)")
    print("=" * 70)
    q_start, q_end, label = get_fiscal_quarter(date.today())
    q_start_iso, q_end_iso = q_start.isoformat(), q_end.isoformat()
    old_total, old_n = _old_definition(sb, q_start_iso, q_end_iso)
    new_total, new_n = _new_definition(sb, q_start_iso, q_end_iso)
    ra_total, ra_n = _rep_attainment_definition(sb, q_start_iso, q_end_iso)
    print(f"{label} [{q_start_iso}..{q_end_iso}]")
    print(f"  OLD (pipeline_id excl + is_won(stage)): ${old_total:,.0f} (n={old_n})")
    print(f"  NEW (is_incremental_pipeline + deal_status==won): ${new_total:,.0f} (n={new_n})")
    print(f"  DIFF (new - old): ${new_total - old_total:,.0f}")
    print(f"  query_rep_attainment's own rule (4th definition): ${ra_total:,.0f} (n={ra_n})")
    print(f"  DIFF (rep_attainment - new): ${ra_total - new_total:,.0f}")
    a, b = _reopened_deal_diagnostic(sb, q_start_iso, q_end_iso)
    _print_reopened_deal_diagnostic(label, q_start_iso, q_end_iso, a, b)

    print()
    print("=" * 70)
    print("PRIOR-YEAR WINDOWS (query_coverage_proxy_target_by_week's existing use)")
    print("=" * 70)
    complete_quarters = _get_complete_quarters(sb)
    if not complete_quarters:
        print("No complete quarters found — nothing to compare.")
        return 0

    total_abs_diff = 0.0
    for quarter in complete_quarters:
        q_start_iso, q_end_iso = _quarter_window_iso(sb, quarter)
        if not q_start_iso:
            print(f"{quarter}: no snapshot date found, skipping")
            continue
        prior_start_iso, prior_end_iso, prior_label = _prior_year_window(q_start_iso)
        old_total, old_n = _old_definition(sb, prior_start_iso, prior_end_iso)
        new_total, new_n = _new_definition(sb, prior_start_iso, prior_end_iso)
        diff = new_total - old_total
        total_abs_diff += abs(diff)
        print(f"{quarter}'s prior-year base ({prior_label}) [{prior_start_iso}..{prior_end_iso}]")
        print(f"  OLD: ${old_total:,.0f} (n={old_n})   NEW: ${new_total:,.0f} (n={new_n})   "
              f"DIFF: ${diff:,.0f}")
        if diff != 0:
            print(f"  -> This changes query_coverage_proxy_target_by_week's proxy_targets['{quarter}']"
                  f"['value'] (2x this base) by ${2 * diff:,.0f}")
        a, b = _reopened_deal_diagnostic(sb, prior_start_iso, prior_end_iso)
        _print_reopened_deal_diagnostic(prior_label, prior_start_iso, prior_end_iso, a, b)

    print()
    print(f"Sum of |diff| across all prior-year windows: ${total_abs_diff:,.0f}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
