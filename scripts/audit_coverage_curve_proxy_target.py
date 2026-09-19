#!/usr/bin/env python3
"""
Audit-only script: rebuild the coverage curve on Jeff's corrected basis.

Two distinct concepts, kept separate throughout (per Jeff's explicit
instruction — never blended):

1. HISTORICAL CALIBRATION BASIS (the 4 complete quarters: FY2026 Q3,
   FY2026 Q4, FY2027 Q1, FY2027 Q2): none of them ever had a real
   target (confirmed live: zero rep_targets rows for any of the four,
   in any label format). Proxy target = 2x the SAME quarter's actual
   closed-won incremental ARR from the PRIOR YEAR. This REPLACES the
   earlier pipeline/actual-outcome-for-the-SAME-quarter ratio — that
   was a different question (retrospective: how did pipeline compare
   to what that same quarter ultimately closed) than this one
   (prospective proxy: how did pipeline compare to a stand-in target
   set from the prior year, which is what a coverage-ratio target
   curve is actually supposed to calibrate against).

2. CURRENT QUARTER (FY2027 Q3): uses the REAL stated quota — NOT this
   proxy. That is out of scope for this script; noted for the
   eventual primitive's own documentation, not computed here.

IMPORTANT GENERALIZATION CHECK (not just taking the request literally):
Jeff's instruction named FY2026 Q1 as "one more quarter of history"
needed, framed around FY2027 Q1's proxy specifically. The same 2x-
prior-year-same-quarter logic applies to ALL FOUR complete quarters,
requiring FOUR prior-year quarters, not one:
  FY2026 Q3 -> needs FY2025 Q3
  FY2026 Q4 -> needs FY2025 Q4
  FY2027 Q1 -> needs FY2026 Q1  (the one explicitly named)
  FY2027 Q2 -> needs FY2026 Q2
All four are checked here, not just the one named, so no quarter
silently ends up without a valid proxy.

Reuses actual_incremental_closed_won() and qualified_pipeline_at_week()
from audit_coverage_curve.py UNMODIFIED — same is_won()/close_date/
non-renewal query, just pointed at different (prior-year) windows.
Prior-year windows are derived via get_fiscal_quarter() (the canonical
date->quarter function), not deals_snapshot lookups — deals_snapshot
has no data that far back for most of these prior-year quarters, but
the `deals` table's terminal outcome data doesn't need it; the window
math is what get_fiscal_quarter() already does correctly.

READ-ONLY throughout. No writes.
"""
import sys
import statistics
from pathlib import Path
from datetime import date as date_cls
from dateutil.relativedelta import relativedelta

REPO_ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(REPO_ROOT / "scripts"))
sys.path.insert(0, str(REPO_ROOT / "scripts" / "analytics"))
sys.path.insert(0, str(REPO_ROOT / "api"))

from db import get_supabase
from forecast_analyses import _get_complete_quarters, _quarter_window_iso
from utils import get_fiscal_quarter, get_pipeline_config
from audit_coverage_curve import actual_incremental_closed_won, qualified_pipeline_at_week


def prior_year_window(q_start_iso: str):
    """(prior_start_iso, prior_end_iso, prior_label) for the SAME quarter
    one fiscal year earlier, via get_fiscal_quarter() — not naive date
    subtraction, so this respects the actual fiscal calendar."""
    q_start = date_cls.fromisoformat(q_start_iso)
    shifted = q_start - relativedelta(years=1)
    prior_start, prior_end, prior_label = get_fiscal_quarter(shifted)
    return prior_start.isoformat(), prior_end.isoformat(), prior_label


def main():
    sb = get_supabase()
    pipeline_config = get_pipeline_config()
    qualified_stage_order = pipeline_config.get("qualified_stage_order", 1)

    complete_quarters = _get_complete_quarters(sb)
    print(f"Complete (closed) quarters being calibrated: {complete_quarters}\n")

    print("=" * 100)
    print("STEP 1: prior-year same-quarter actual closed-won incremental ARR "
          "(the proxy-target basis)")
    print("=" * 100)

    proxy_targets = {}
    quarter_windows = {}
    for quarter in complete_quarters:
        q_start_iso, q_end_iso = _quarter_window_iso(sb, quarter)
        quarter_windows[quarter] = (q_start_iso, q_end_iso)
        prior_start_iso, prior_end_iso, prior_label = prior_year_window(q_start_iso)

        prior_actual, prior_n = actual_incremental_closed_won(sb, prior_start_iso, prior_end_iso)
        proxy_target = 2 * prior_actual
        proxy_targets[quarter] = proxy_target

        print(f"{quarter} (window {q_start_iso}..{q_end_iso}):")
        print(f"  Prior-year same quarter: {prior_label} ({prior_start_iso}..{prior_end_iso})")
        print(f"  Prior-year actual closed-won incremental ARR: ${prior_actual:,.0f} "
              f"({prior_n} deals)")
        if prior_actual <= 0 or prior_n == 0:
            print(f"  >>> WARNING: no usable prior-year actual — proxy target "
                  f"would be ${proxy_target:,.0f}, NOT a valid basis for this quarter.")
        else:
            print(f"  Proxy target (2x prior-year actual): ${proxy_target:,.0f}")
        print()

    valid_quarters = [q for q in complete_quarters if proxy_targets.get(q, 0) > 0]
    invalid_quarters = [q for q in complete_quarters if q not in valid_quarters]
    print(f"Quarters with a VALID (non-zero) proxy target: {valid_quarters}")
    if invalid_quarters:
        print(f"Quarters EXCLUDED (no usable prior-year actual, cannot compute a "
              f"valid proxy): {invalid_quarters}")

    print("\n" + "=" * 100)
    print("STEP 2: pooled week-by-week curve, PIPELINE / PROXY TARGET "
          "(2x prior-year actual)")
    print("This REPLACES the earlier pipeline/same-quarter-actual-outcome curve — "
          "different denominator, different question.")
    print("=" * 100)
    print(f"{'week':>4s}  " + "  ".join(f"{q:>16s}" for q in valid_quarters) +
          f"  {'pooled_mean':>12s}  {'pooled_median':>13s}")
    print("=" * 100)

    pooled_by_week = {}
    for week in range(1, 14):
        row_ratios = []
        cells = []
        for quarter in valid_quarters:
            q_start_iso, q_end_iso = quarter_windows[quarter]
            pipeline_val, n_deals = qualified_pipeline_at_week(
                sb, quarter, week, qualified_stage_order, q_start_iso, q_end_iso)
            proxy_target = proxy_targets[quarter]
            ratio = pipeline_val / proxy_target
            row_ratios.append(ratio)
            cells.append(f"{ratio:>6.2f}x(n={n_deals:>3d})")

        mean_r = statistics.mean(row_ratios) if row_ratios else None
        median_r = statistics.median(row_ratios) if row_ratios else None
        pooled_by_week[week] = {"mean": mean_r, "median": median_r,
                                 "n_quarters": len(row_ratios)}

        mean_str = f"{mean_r:.2f}x" if mean_r is not None else "null"
        median_str = f"{median_r:.2f}x" if median_r is not None else "null"
        print(f"{week:>4d}  " + "  ".join(f"{c:>16s}" for c in cells) +
              f"  {mean_str:>12s}  {median_str:>13s}")

    print("\n" + "=" * 100)
    print("SHAPE CHECK (proxy-target basis): week 1 vs week 13")
    print("=" * 100)
    week1 = pooled_by_week.get(1, {}).get("median")
    week13 = pooled_by_week.get(13, {}).get("median")
    if week1 is not None and week13 is not None:
        print(f"Week 1 pooled median: {week1:.2f}x")
        print(f"Week 13 pooled median: {week13:.2f}x")
        print(f"Observed change: {week13 - week1:+.2f}x over the quarter "
              f"(negative = decay toward 1x, as hypothesized)")
    else:
        print("Insufficient data to compare week 1 vs week 13 directly.")

    print(f"\nNumber of quarters actually pooled: {len(valid_quarters)} "
          f"(out of {len(complete_quarters)} complete quarters)")

    print("\nDONE")


if __name__ == "__main__":
    main()
