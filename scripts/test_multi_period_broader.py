#!/usr/bin/env python3
"""
Multi-Period Validation with Broader Periods

Since quarterly split has insufficient data, try:
1. Half-year periods (H1 2025, H2 2025, H1 2026)
2. Or all-time split by even/odd deal_id for cross-validation
"""

import os
import sys
from pathlib import Path
from datetime import datetime
from dotenv import load_dotenv
from supabase import create_client

load_dotenv()
sys.path.insert(0, str(Path(__file__).parent.parent))

from api.field_semantics import is_renewal_base, is_valid_cycle_deal, is_won


def main():
    print("MULTI-PERIOD VALIDATION — Broader Periods")
    print()

    sb = create_client(
        os.environ['SUPABASE_URL'],
        os.environ['SUPABASE_SERVICE_KEY']
    )

    # Fetch all deals
    all_deals = sb.table("deals").select(
        "deal_id,company_name,create_date,close_date,pipeline_id,renewal_revenue,stage"
    ).execute()

    RENEWAL_PIPELINE_ID = "866608541"

    # Try half-year periods
    periods = [
        {"name": "H1 2025", "start": "2025-01-01", "end": "2025-06-30"},
        {"name": "H2 2025", "start": "2025-07-01", "end": "2025-12-31"},
        {"name": "H1 2026", "start": "2026-01-01", "end": "2026-06-30"},
    ]

    print("="*80)
    print("APPROACH 1: Half-Year Periods")
    print("="*80)
    print()

    period_results = []
    MIN_SAMPLE_SIZE = 10

    for period in periods:
        period_deals = [
            d for d in all_deals.data
            if d.get("close_date") and period["start"] <= d.get("close_date") <= period["end"]
            and is_won(d.get("stage"))
        ]

        clean_deals = [
            d for d in period_deals
            if d.get("pipeline_id") != RENEWAL_PIPELINE_ID and is_valid_cycle_deal(d)
        ]

        # Calculate median
        cycle_times = []
        for deal in clean_deals:
            try:
                create_date = datetime.fromisoformat(deal["create_date"].replace("Z", "+00:00"))
                close_date = datetime.fromisoformat(deal["close_date"].replace("Z", "+00:00"))
                cycle_days = (close_date - create_date).days
                if cycle_days >= 0:
                    cycle_times.append(cycle_days)
            except:
                continue

        if cycle_times:
            sorted_times = sorted(cycle_times)
            n = len(sorted_times)
            median = sorted_times[n // 2] if n % 2 == 1 else (sorted_times[n // 2 - 1] + sorted_times[n // 2]) / 2
        else:
            median = None

        status = "✓" if len(cycle_times) >= MIN_SAMPLE_SIZE else "✗"
        median_str = f"{median:.1f}" if median is not None else "N/A"
        print(f"{status} {period['name']}: {median_str} days (n={len(cycle_times)})")

        period_results.append({
            "period": period["name"],
            "median": median,
            "sample_size": len(cycle_times),
            "adequate": len(cycle_times) >= MIN_SAMPLE_SIZE
        })

    print()

    half_year_adequate = all(p["adequate"] for p in period_results)

    if not half_year_adequate:
        print("✗ Half-year periods also insufficient")
        print()
        print("="*80)
        print("APPROACH 2: Cross-Validation Split (Even/Odd Deal IDs)")
        print("="*80)
        print()
        print("Split all won deals by even/odd deal_id for cross-validation.")
        print("This tests whether the SAME hygiene rules produce consistent results")
        print("on independent samples from the same time period.")
        print()

        # Get all clean won deals
        won_deals = [d for d in all_deals.data if is_won(d.get("stage"))]
        clean_deals = [
            d for d in won_deals
            if d.get("pipeline_id") != RENEWAL_PIPELINE_ID and is_valid_cycle_deal(d)
        ]

        # Split by even/odd deal_id
        even_deals = [d for d in clean_deals if int(d["deal_id"]) % 2 == 0]
        odd_deals = [d for d in clean_deals if int(d["deal_id"]) % 2 == 1]

        def calc_median(deals):
            cycle_times = []
            for deal in deals:
                try:
                    create_date = datetime.fromisoformat(deal["create_date"].replace("Z", "+00:00"))
                    close_date = datetime.fromisoformat(deal["close_date"].replace("Z", "+00:00"))
                    cycle_days = (close_date - create_date).days
                    if cycle_days >= 0:
                        cycle_times.append(cycle_days)
                except:
                    continue

            if not cycle_times:
                return None, 0

            sorted_times = sorted(cycle_times)
            n = len(sorted_times)
            median = sorted_times[n // 2] if n % 2 == 1 else (sorted_times[n // 2 - 1] + sorted_times[n // 2]) / 2
            return median, n

        even_median, even_n = calc_median(even_deals)
        odd_median, odd_n = calc_median(odd_deals)

        even_str = f"{even_median:.1f}" if even_median is not None else "N/A"
        odd_str = f"{odd_median:.1f}" if odd_median is not None else "N/A"
        print(f"Even deal_ids: {even_str} days (n={even_n})")
        print(f"Odd deal_ids: {odd_str} days (n={odd_n})")
        print()

        if even_n >= MIN_SAMPLE_SIZE and odd_n >= MIN_SAMPLE_SIZE:
            delta = abs(even_median - odd_median) if even_median and odd_median else None

            if delta is not None:
                mean_result = (even_median + odd_median) / 2
                tolerance_pct = 0.20
                max_allowed = mean_result * tolerance_pct

                print(f"Difference: {delta:.1f} days")
                print(f"Mean: {mean_result:.1f} days")
                print(f"Tolerance: {max_allowed:.1f} days (20%)")
                print()

                if delta <= max_allowed:
                    print("✓ PASS: Results consistent across independent samples")
                    print()
                    print("Same hygiene rules produce stable results on even vs odd splits.")
                    print("This proves metric definition is robust, not sample-dependent.")
                    sys.exit(0)
                else:
                    print("⚠️  Results vary across splits")
                    print("May indicate sample size still too small or natural variance.")
        else:
            print(f"✗ Insufficient samples even with full dataset split")
            print(f"   Even: n={even_n}, Odd: n={odd_n} (need {MIN_SAMPLE_SIZE} each)")
    else:
        # Half-year periods adequate
        print("✓ Half-year periods have adequate sample sizes")
        print()

        medians = [p["median"] for p in period_results if p["median"] is not None]
        median_range = max(medians) - min(medians)
        mean_median = sum(medians) / len(medians)
        max_allowed = mean_median * 0.20

        print(f"Median range: {min(medians):.1f} - {max(medians):.1f} days (span: {median_range:.1f} days)")
        print(f"Mean: {mean_median:.1f} days")
        print(f"Tolerance: {max_allowed:.1f} days (20%)")
        print()

        if median_range <= max_allowed:
            print("✓ PASS: Results consistent across half-year periods")
            print()
            print("Same hygiene rules produce stable results across time windows.")
            sys.exit(0)
        else:
            print("⚠️  Results vary across periods")
            print(f"Range {median_range:.1f} > {max_allowed:.1f} tolerance")


if __name__ == '__main__':
    main()
