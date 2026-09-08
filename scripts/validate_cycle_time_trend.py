#!/usr/bin/env python3
"""
Validate the "40-day lengthening" claim with non-overlapping quarter buckets.

Overlapping windows (6mo ⊂ 12mo ⊂ all-time) are NOT three independent
observations - they're the same recent deals counted with shrinking denominators.

Real trend test: bucket by QUARTER of close_date and check if median cycle
time is monotonically increasing quarter-over-quarter.
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
    """
    GrowthBook fiscal year: May 1 - Apr 30
    Q1 = May-Jul, Q2 = Aug-Oct, Q3 = Nov-Jan, Q4 = Feb-Apr
    """
    month = dt.month
    year = dt.year

    if month >= 5:  # May-Dec
        fy_year = year + 1  # FY starts in May, so May 2025 is FY2026
        if month <= 7:
            quarter = 1
        elif month <= 10:
            quarter = 2
        else:  # Nov-Dec
            quarter = 3
    else:  # Jan-Apr
        fy_year = year
        if month <= 1:
            quarter = 3
        else:  # Feb-Apr
            quarter = 4

    return f"FY{fy_year} Q{quarter}"

def validate_trend():
    sb = get_supabase()

    print("=" * 80)
    print("CYCLE TIME TREND VALIDATION: NON-OVERLAPPING QUARTERS")
    print("=" * 80)
    print()

    # Fetch all won deals
    all_deals = sb.table("deals").select(
        "deal_id,company_name,create_date,close_date,stage,deal_value"
    ).execute()

    won_deals = [d for d in all_deals.data if is_won(d.get("stage"))]
    print(f"Total won deals: {len(won_deals)}")
    print()

    # Parse and bucket by quarter
    deals_by_quarter = defaultdict(list)

    for deal in won_deals:
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
                    "deal_id": deal.get("deal_id"),
                    "company_name": deal.get("company_name"),
                    "cycle_days": cycle_days,
                    "deal_value": deal.get("deal_value"),
                    "close_date": close_date
                })
        except (ValueError, AttributeError):
            continue

    # Sort quarters chronologically
    sorted_quarters = sorted(deals_by_quarter.keys())

    print("QUARTERLY CYCLE TIME ANALYSIS (NON-OVERLAPPING)")
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

    # Check for monotonic increase
    if len(quarterly_medians) < 2:
        print("⚠️  Insufficient quarters for trend analysis")
        return

    # Look at most recent 6 quarters
    recent_quarters = quarterly_medians[-6:]

    print("Most Recent 6 Quarters:")
    for quarter, q_median, sample in recent_quarters:
        print(f"  {quarter}: {q_median:.0f} days ({sample} deals)")
    print()

    # Check if trending up
    is_increasing = all(
        recent_quarters[i][1] <= recent_quarters[i+1][1]
        for i in range(len(recent_quarters)-1)
    )

    if is_increasing:
        print("✅ MONOTONIC INCREASE: Each quarter's median >= previous quarter")
        print("   → This confirms a genuine lengthening trend")
    else:
        print("⚠️  NOT MONOTONIC: Quarters show variation, not steady increase")
        print("   → The 'lengthening trend' may be recency bias or outliers")

    print()

    # Calculate average across recent quarters vs older quarters
    if len(quarterly_medians) >= 8:
        older_medians = [m for q, m, s in quarterly_medians[:-4]]
        recent_medians = [m for q, m, s in quarterly_medians[-4:]]

        avg_older = sum(older_medians) / len(older_medians)
        avg_recent = sum(recent_medians) / len(recent_medians)

        print(f"Average of older quarters (all except last 4): {avg_older:.1f} days")
        print(f"Average of recent 4 quarters: {avg_recent:.1f} days")
        print(f"Difference: {avg_recent - avg_older:.1f} days")
        print()

    # Find outliers in most recent quarters
    print("=" * 80)
    print("OUTLIER ANALYSIS: Longest Cycles in Last 4 Quarters")
    print("=" * 80)
    print()

    # Get all deals from last 4 quarters
    recent_quarter_names = [q for q, m, s in quarterly_medians[-4:]]
    recent_deals = []
    for quarter in recent_quarter_names:
        recent_deals.extend(deals_by_quarter[quarter])

    # Sort by cycle time descending
    recent_deals.sort(key=lambda d: d["cycle_days"], reverse=True)

    print(f"Top 5 longest cycles in recent quarters:")
    for i, deal in enumerate(recent_deals[:5], 1):
        deal_value = deal.get("deal_value")
        value_str = f"${deal_value:,.0f}" if deal_value else "N/A"
        print(f"  {i}. {deal['company_name']}: {deal['cycle_days']} days (value: {value_str})")

    print()

    # Calculate median without these outliers
    recent_cycle_times = [d["cycle_days"] for d in recent_deals]
    recent_median_with_outliers = median(recent_cycle_times)

    # Remove top 5 outliers
    recent_cycle_times_no_outliers = [d["cycle_days"] for d in recent_deals[5:]]
    if recent_cycle_times_no_outliers:
        recent_median_no_outliers = median(recent_cycle_times_no_outliers)

        print(f"Median WITH top 5 outliers: {recent_median_with_outliers:.1f} days")
        print(f"Median WITHOUT top 5 outliers: {recent_median_no_outliers:.1f} days")
        print(f"Impact of outliers: {recent_median_with_outliers - recent_median_no_outliers:.1f} days")

    print()
    print("=" * 80)
    print("CONCLUSION")
    print("=" * 80)
    print()

    if is_increasing:
        print("✅ GENUINE TREND CONFIRMED")
        print("   Cycle time is increasing quarter-over-quarter (non-overlapping buckets)")
        print("   → The '40-day lengthening' claim is supported by the data")
        print("   → Rolling window metric correctly captures this trend")
    else:
        print("⚠️  TREND NOT CONFIRMED")
        print("   Quarter-over-quarter medians show variation, not steady increase")
        print("   → The rolling window comparison may reflect recency bias")
        print("   → Check outlier impact: are a few large deals skewing recent medians?")

if __name__ == "__main__":
    validate_trend()
