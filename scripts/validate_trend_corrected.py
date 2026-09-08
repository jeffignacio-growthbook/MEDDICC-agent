#!/usr/bin/env python3
"""
Re-run quarter-bucket trend analysis on CORRECTED population (renewals excluded).

Previous trend analysis (CONTAMINATED) showed non-monotonic quarters:
  FY2026 Q2: 311 days
  FY2026 Q3: 116 days
  FY2026 Q4: 179 days
  FY2027 Q1: 148 days

Now checking if there's any real trend in non-renewal deals.
"""
import sys
from pathlib import Path
from dotenv import load_dotenv
from datetime import datetime, timezone
from statistics import median
from collections import defaultdict

env_path = Path(__file__).parent.parent / ".env"
load_dotenv(env_path)

sys.path.insert(0, str(Path(__file__).parent.parent / "api"))
from db import get_supabase
from field_semantics import is_won

def get_fiscal_quarter(dt):
    """GrowthBook fiscal year: May 1 - Apr 30"""
    month = dt.month
    year = dt.year

    if month >= 5:  # May-Dec
        fy_year = year + 1
        if month <= 7:
            quarter = 1
        elif month <= 10:
            quarter = 2
        else:
            quarter = 3
    else:  # Jan-Apr
        fy_year = year
        if month <= 1:
            quarter = 3
        else:
            quarter = 4

    return f"FY{fy_year} Q{quarter}"

def validate_corrected():
    sb = get_supabase()

    print("=" * 80)
    print("TREND VALIDATION - CORRECTED (NON-RENEWAL ONLY)")
    print("=" * 80)
    print()

    # Fetch all deals
    all_deals = sb.table("deals").select(
        "deal_id,company_name,create_date,close_date,stage,pipeline_id"
    ).execute()

    # Filter: won AND not renewal pipeline
    RENEWAL_PIPELINE_ID = "866608541"
    won_non_renewal = [
        d for d in all_deals.data
        if is_won(d.get("stage")) and d.get("pipeline_id") != RENEWAL_PIPELINE_ID
    ]

    print(f"Non-renewal won deals: {len(won_non_renewal)}")
    print()

    # Bucket by quarter
    deals_by_quarter = defaultdict(list)

    for deal in won_non_renewal:
        close_date_str = deal.get("close_date")
        create_date_str = deal.get("create_date")

        if not close_date_str or not create_date_str:
            continue

        try:
            close_date = datetime.fromisoformat(close_date_str.replace("Z", "+00:00"))
            create_date = datetime.fromisoformat(create_date_str.replace("Z", "+00:00"))

            if close_date.tzinfo is None:
                close_date = close_date.replace(tzinfo=timezone.utc)
            if create_date.tzinfo is None:
                create_date = create_date.replace(tzinfo=timezone.utc)

            cycle_days = (close_date - create_date).days

            if cycle_days >= 0:
                quarter = get_fiscal_quarter(close_date)
                deals_by_quarter[quarter].append({
                    "company_name": deal.get("company_name"),
                    "cycle_days": cycle_days
                })
        except (ValueError, AttributeError):
            continue

    # Sort quarters
    sorted_quarters = sorted(deals_by_quarter.keys())

    print("QUARTERLY ANALYSIS (NON-OVERLAPPING, NON-RENEWAL)")
    print("-" * 80)
    print(f"{'Quarter':<15} {'Sample':<10} {'Median':<10} {'Min':<8} {'P25':<8} {'P75':<8} {'Max':<8}")
    print("-" * 80)

    quarterly_medians = []

    for quarter in sorted_quarters:
        deals = deals_by_quarter[quarter]
        cycle_times = [d["cycle_days"] for d in deals]
        cycle_times.sort()

        if len(cycle_times) == 0:
            continue

        q_median = median(cycle_times)
        q_min = min(cycle_times)
        q_max = max(cycle_times)
        q_p25 = cycle_times[len(cycle_times) // 4] if len(cycle_times) >= 4 else cycle_times[0]
        q_p75 = cycle_times[3 * len(cycle_times) // 4] if len(cycle_times) >= 4 else cycle_times[-1]

        quarterly_medians.append((quarter, q_median, len(cycle_times)))

        print(f"{quarter:<15} {len(cycle_times):<10} {q_median:<10.0f} {q_min:<8} {q_p25:<8} {q_p75:<8} {q_max:<8}")

    print()
    print("=" * 80)
    print("TREND ANALYSIS")
    print("=" * 80)
    print()

    if len(quarterly_medians) < 4:
        print("⚠️  Very few quarters with data - trend analysis unreliable")
        print()

    # Recent quarters
    recent_quarters = quarterly_medians[-6:] if len(quarterly_medians) >= 6 else quarterly_medians

    print("Most Recent Quarters:")
    for quarter, q_median, sample in recent_quarters:
        print(f"  {quarter}: {q_median:.0f} days ({sample} deals)")
    print()

    # Check for monotonic increase
    if len(recent_quarters) >= 2:
        is_increasing = all(
            recent_quarters[i][1] <= recent_quarters[i+1][1]
            for i in range(len(recent_quarters)-1)
        )

        if is_increasing:
            print("✅ MONOTONIC INCREASE")
        else:
            print("⚠️  NOT MONOTONIC - shows variation")

    print()
    print("=" * 80)
    print("CONCLUSION")
    print("=" * 80)
    print()

    print("CORRECTED population (non-renewal only):")
    print(f"  Total deals analyzed: {sum(len(deals_by_quarter[q]) for q in sorted_quarters)}")
    print(f"  Quarters with data: {len(sorted_quarters)}")
    print()

    if len(recent_quarters) >= 3:
        medians = [m for q, m, s in recent_quarters]
        avg_median = sum(medians) / len(medians)
        print(f"Average median across recent quarters: {avg_median:.0f} days")
        print()

    print("With renewals excluded, the cycle time metric now correctly measures")
    print("new business and expansion deals only. Very small sample sizes (12-22 deals)")
    print("suggest all-time window may be more stable than rolling windows.")

if __name__ == "__main__":
    validate_corrected()
