#!/usr/bin/env python3
"""
Compute cycle time with multiple rolling window options for Q016.
Correct methodology per QUESTIONS_FOR_JEFF_FINAL.md:
- Won deals only (not lost)
- Full timestamp parsing (not date-only)
- Filter: days >= 0 (not > 0)
"""
import sys
from pathlib import Path
from dotenv import load_dotenv
from datetime import datetime, timezone, timedelta
import statistics

env_path = Path(__file__).parent.parent / ".env"
load_dotenv(env_path)

sys.path.insert(0, str(Path(__file__).parent.parent / "api"))
from db import get_supabase
from field_semantics import is_won

def compute_rolling_windows():
    sb = get_supabase()

    print("=" * 80)
    print("Q016 ROLLING WINDOW CYCLE TIME COMPUTATION")
    print("=" * 80)
    print()

    # Fetch all deals
    all_deals = sb.table("deals").select(
        "deal_id,company_name,create_date,close_date,stage,deal_status"
    ).execute()

    print(f"Total deals in database: {len(all_deals.data)}")

    # Filter to won deals only
    won_deals = [d for d in all_deals.data if is_won(d.get("stage"))]
    print(f"Won deals: {len(won_deals)}")
    print()

    # Parse dates and compute cycle times for ALL won deals (all-time)
    deals_with_cycle_time = []
    bad_data_count = 0

    for deal in won_deals:
        create_date = deal.get("create_date")
        close_date = deal.get("close_date")

        if create_date and close_date:
            try:
                # Parse with full timestamp (not date-only)
                created = datetime.fromisoformat(create_date.replace("Z", "+00:00"))
                closed = datetime.fromisoformat(close_date.replace("Z", "+00:00"))

                # Ensure both are timezone-aware (add UTC if naive)
                if created.tzinfo is None:
                    created = created.replace(tzinfo=timezone.utc)
                if closed.tzinfo is None:
                    closed = closed.replace(tzinfo=timezone.utc)

                cycle_days = (closed - created).days

                # Filter: days >= 0 (not > 0)
                if cycle_days < 0:
                    bad_data_count += 1
                elif cycle_days >= 0:
                    deals_with_cycle_time.append({
                        "deal_id": deal.get("deal_id"),
                        "company_name": deal.get("company_name"),
                        "create_date": created,
                        "close_date": closed,
                        "cycle_days": cycle_days
                    })
            except Exception as e:
                bad_data_count += 1
                print(f"  ⚠️  Parse error for {deal.get('company_name')}: {e}")

    print(f"Valid won deals with cycle time data: {len(deals_with_cycle_time)}")
    print(f"Bad data (parse errors or negative cycle): {bad_data_count}")
    print()

    # Get current timestamp for rolling window calculations
    now = datetime.now(timezone.utc)

    # Define rolling windows
    windows = {
        "all_time": None,
        "12_month": 365,
        "6_month": 182  # 6 months * 30.4 days ≈ 182 days
    }

    results = {}

    print("=" * 80)
    print("RESULTS BY WINDOW")
    print("=" * 80)
    print()

    for window_name, window_days in windows.items():
        if window_days is None:
            # All-time: use all deals
            window_deals = deals_with_cycle_time
        else:
            # Rolling window: filter by close_date
            cutoff_date = now - timedelta(days=window_days)
            # Ensure cutoff_date is timezone-aware for comparison
            window_deals = [
                d for d in deals_with_cycle_time
                if d["close_date"] >= cutoff_date
            ]

        cycle_times = [d["cycle_days"] for d in window_deals]
        cycle_times.sort()

        if len(cycle_times) == 0:
            results[window_name] = {
                "sample_size": 0,
                "median": None,
                "p25": None,
                "p75": None,
                "min": None,
                "max": None
            }
            print(f"**{window_name.upper().replace('_', ' ')}**")
            print(f"  Sample size: 0 deals (no data)")
            print()
            continue

        median = statistics.median(cycle_times)
        p25 = cycle_times[len(cycle_times) // 4]
        p75 = cycle_times[3 * len(cycle_times) // 4]
        min_val = min(cycle_times)
        max_val = max(cycle_times)

        results[window_name] = {
            "sample_size": len(cycle_times),
            "median": median,
            "p25": p25,
            "p75": p75,
            "min": min_val,
            "max": max_val
        }

        print(f"**{window_name.upper().replace('_', ' ')}**")
        print(f"  Sample size: {len(cycle_times)} won deals")
        print(f"  Median: {median} days")
        print(f"  Distribution:")
        print(f"    Min: {min_val} days")
        print(f"    25th percentile: {p25} days")
        print(f"    Median: {median} days")
        print(f"    75th percentile: {p75} days")
        print(f"    Max: {max_val} days")
        print()

    # Summary comparison table
    print("=" * 80)
    print("COMPARISON TABLE")
    print("=" * 80)
    print()
    print(f"{'Window':<15} {'Sample':<10} {'Median':<10} {'Min':<8} {'P25':<8} {'P75':<8} {'Max':<8}")
    print("-" * 80)

    for window_name in ["all_time", "12_month", "6_month"]:
        r = results[window_name]
        if r["median"] is None:
            print(f"{window_name.replace('_', ' '):<15} {'0':<10} {'N/A':<10} {'N/A':<8} {'N/A':<8} {'N/A':<8} {'N/A':<8}")
        else:
            print(f"{window_name.replace('_', ' '):<15} {r['sample_size']:<10} {r['median']:<10} {r['min']:<8} {r['p25']:<8} {r['p75']:<8} {r['max']:<8}")

    print()
    print("=" * 80)
    print("RECOMMENDATION FOR JEFF")
    print("=" * 80)
    print()

    print("These are the ACTUAL computed values from your data:")
    print()
    print(f"1. **All-time window**: {results['all_time']['median']} days ({results['all_time']['sample_size']} deals)")
    print(f"   - Pros: Largest sample, most stable")
    print(f"   - Cons: Blends historical deals with potentially different conditions")
    print()
    print(f"2. **Rolling 12-month**: {results['12_month']['median']} days ({results['12_month']['sample_size']} deals)")
    print(f"   - Pros: Balance of recency and sample size")
    print(f"   - Cons: Still includes deals from a year ago")
    print()
    print(f"3. **Rolling 6-month**: {results['6_month']['median']} days ({results['6_month']['sample_size']} deals)")
    print(f"   - Pros: Reflects most current conditions")
    print(f"   - Cons: Smaller sample, more volatile")
    print()

    # Sample size assessment
    if results['6_month']['sample_size'] < 20:
        print("⚠️  **Note:** 6-month sample size is below 20 deals - may be too volatile for reliable metric")

    if results['12_month']['sample_size'] < 20:
        print("⚠️  **Note:** 12-month sample size is below 20 deals - may want to consider all-time")

    print()
    print("**Question for Jeff:** Which window should the canonical cycle_time metric use?")
    print()

    return results

if __name__ == "__main__":
    compute_rolling_windows()
