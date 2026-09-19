#!/usr/bin/env python3
"""
Audit-only script: does real historical data support a 3x-early ->
~1x-late decay curve for pipeline coverage, or a different shape?
(NORTH_STAR.md CRO Priority #2, per Jeff's domain-spec point 4.)

Method mirrors the already-built commit win-rate-by-week calibration
(forecast_analyses.py): pool across the same 4 complete quarters,
compute a per-week figure, report real sample sizes, never assume a
shape.

For each complete quarter and each week 1-13:
  ratio(week) = qualified, incremental-scoped pipeline $ AT that week
                / actual closed-won incremental ARR for the WHOLE quarter
Pooled (median + mean) across the 4 quarters at each week gives the
empirical "how much pipeline existed, relative to what eventually
closed" curve.

IMPORTANT CAVEAT, confirmed via migration 064 before writing this:
deals_snapshot.new_arr/expansion_arr are NOT backfilled — NULL for
every snapshot row taken before 2026-09-11, which is ALL rows in the
4 complete historical quarters (all already closed before that date).
The precise incremental-ARR (new+expansion, excluding pure renewal)
scoping used elsewhere this session (is_incremental_pipeline()) is
therefore NOT computable historically at the dollar-component level.
This script instead uses deal_value with the renewal PIPELINE excluded
(pipeline_id != _RENEWAL_PIPELINE_ID) as the best available historical
proxy — pipeline_id IS present on every historical row. This is an
approximation, not the exact is_incremental_pipeline() definition:
it will not catch a rare expansion deal living inside the renewal
pipeline (undercounts slightly) and will not exclude a stray
renewal_revenue value on a non-renewal-pipeline deal if one exists
(overcounts slightly). Flagged explicitly rather than silently treated
as exact.

Qualified threshold: config/client.yaml's top-level
pipeline.qualified_stage_order (confirmed = 1), compared against
deals_snapshot's own stage_order column (present on every row since
the base schema, migration 005) — no separate lookup needed.

READ-ONLY throughout. No writes.
"""
import sys
import statistics
from pathlib import Path

REPO_ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(REPO_ROOT / "scripts"))
sys.path.insert(0, str(REPO_ROOT / "scripts" / "analytics"))
sys.path.insert(0, str(REPO_ROOT / "api"))

from supabase_client import select_all
from db import get_supabase
from forecast_analyses import _get_complete_quarters, _quarter_window_iso
from field_semantics import _RENEWAL_PIPELINE_ID, is_won
from utils import get_pipeline_config


def actual_incremental_closed_won(sb, q_start_iso, q_end_iso):
    """Actual closed-won incremental ARR (new_arr+expansion_arr) for the
    quarter, current deals table, renewal pipeline excluded — same
    terminal-outcome-read pattern _in_quarter_won_by_pipeline() uses
    elsewhere in forecast_analyses.py, adapted to sum ARR not count."""
    deals = select_all(sb, "deals",
        columns="deal_id,stage,close_date,pipeline_id,new_arr,expansion_arr")
    total = 0.0
    n = 0
    for d in deals:
        stage, close_date, pipeline_id = d.get("stage"), d.get("close_date"), d.get("pipeline_id")
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
        total += (d.get("new_arr") or 0) + (d.get("expansion_arr") or 0)
        n += 1
    return total, n


def qualified_pipeline_at_week(sb, quarter, week, qualified_stage_order):
    """deal_value-based proxy (see module docstring caveat), renewal
    pipeline excluded, qualified stage threshold applied, from the
    point-in-time snapshot."""
    rows = select_all(sb, "deals_snapshot",
        columns="deal_id,deal_value,pipeline_id,stage_order",
        filters=[("eq", "fiscal_quarter", quarter),
                 ("eq", "week_of_quarter", week)])
    total = 0.0
    n = 0
    for r in rows:
        if str(r.get("pipeline_id")) == _RENEWAL_PIPELINE_ID:
            continue
        stage_order = r.get("stage_order")
        if stage_order is None or stage_order < qualified_stage_order:
            continue
        total += r.get("deal_value") or 0
        n += 1
    return total, n


def main():
    sb = get_supabase()
    pipeline_config = get_pipeline_config()
    qualified_stage_order = pipeline_config.get("qualified_stage_order", 1)
    print(f"qualified_stage_order (config/client.yaml, top-level): {qualified_stage_order}")
    print(f"Renewal pipeline excluded: {_RENEWAL_PIPELINE_ID}")

    complete_quarters = _get_complete_quarters(sb)
    print(f"Complete (closed) quarters: {complete_quarters}\n")

    quarter_actuals = {}
    for quarter in complete_quarters:
        q_start_iso, q_end_iso = _quarter_window_iso(sb, quarter)
        actual, n_won = actual_incremental_closed_won(sb, q_start_iso, q_end_iso)
        quarter_actuals[quarter] = actual
        print(f"{quarter}: actual closed-won incremental ARR = ${actual:,.0f} "
              f"({n_won} deals, window {q_start_iso}..{q_end_iso})")

    print("\n" + "=" * 100)
    print(f"{'week':>4s}  " + "  ".join(f"{q:>16s}" for q in complete_quarters) +
          f"  {'pooled_mean':>12s}  {'pooled_median':>13s}")
    print("=" * 100)

    pooled_by_week = {}
    for week in range(1, 14):
        row_ratios = []
        cells = []
        for quarter in complete_quarters:
            pipeline_val, n_deals = qualified_pipeline_at_week(sb, quarter, week, qualified_stage_order)
            actual = quarter_actuals[quarter]
            if actual and actual > 0:
                ratio = pipeline_val / actual
                row_ratios.append(ratio)
                cells.append(f"{ratio:>6.2f}x(n={n_deals:>3d})")
            else:
                cells.append(f"{'no_actual':>16s}")

        if row_ratios:
            mean_r = statistics.mean(row_ratios)
            median_r = statistics.median(row_ratios)
            pooled_by_week[week] = {"mean": mean_r, "median": median_r, "n_quarters": len(row_ratios)}
        else:
            mean_r = median_r = None
            pooled_by_week[week] = {"mean": None, "median": None, "n_quarters": 0}

        mean_str = f"{mean_r:.2f}x" if mean_r is not None else "null"
        median_str = f"{median_r:.2f}x" if median_r is not None else "null"
        print(f"{week:>4d}  " + "  ".join(f"{c:>16s}" for c in cells) +
              f"  {mean_str:>12s}  {median_str:>13s}")

    print("\n" + "=" * 100)
    print("SHAPE CHECK: does the pooled ratio decay from ~3x toward ~1x across the quarter?")
    print("=" * 100)
    week1 = pooled_by_week.get(1, {}).get("median")
    week13 = pooled_by_week.get(13, {}).get("median")
    if week1 is not None and week13 is not None:
        print(f"Week 1 pooled median: {week1:.2f}x")
        print(f"Week 13 pooled median: {week13:.2f}x")
        print(f"Observed delta: {week1 - week13:+.2f}x over the quarter")
    else:
        print("Insufficient data to compare week 1 vs week 13 directly.")

    print("\nDONE")


if __name__ == "__main__":
    main()
