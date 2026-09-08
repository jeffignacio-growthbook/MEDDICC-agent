#!/usr/bin/env python3
"""
Verify q016 cycle time using CORRECT methodology per commit 587f24a:
- Use ALL closed deals (won + lost), not just won
- Calculate: (close_date - create_date) in days
- Report MEDIAN
"""
import sys
from pathlib import Path
from dotenv import load_dotenv
from datetime import datetime, timezone

env_path = Path(__file__).parent.parent / ".env"
load_dotenv(env_path)

sys.path.insert(0, str(Path(__file__).parent.parent / "api"))
from db import get_supabase
from field_semantics import is_won, is_lost

def verify_q016_correct():
    sb = get_supabase()

    print("=" * 80)
    print("Q016 CYCLE TIME - CORRECT METHODOLOGY VERIFICATION")
    print("=" * 80)
    print()

    # Get ALL deals (not just won)
    all_deals = sb.table("deals").select(
        "deal_id,company_name,create_date,close_date,stage,deal_status"
    ).execute()

    print(f"Total deals in database: {len(all_deals.data)}")
    print()

    # Filter to closed deals (won OR lost)
    closed_deals = []
    won_deals = []
    lost_deals = []

    for deal in all_deals.data:
        stage = deal.get("stage")
        if is_won(stage):
            won_deals.append(deal)
            closed_deals.append(deal)
        elif is_lost(stage):
            lost_deals.append(deal)
            closed_deals.append(deal)

    print(f"Won deals: {len(won_deals)}")
    print(f"Lost deals: {len(lost_deals)}")
    print(f"TOTAL CLOSED deals (won + lost): {len(closed_deals)}")
    print()

    # Calculate cycle times for ALL closed deals
    all_closed_cycle_times = []
    won_only_cycle_times = []

    bad_data_count = 0

    for deal in closed_deals:
        create_date = deal.get("create_date")
        close_date = deal.get("close_date")
        stage = deal.get("stage")

        if create_date and close_date:
            try:
                created = datetime.fromisoformat(create_date.replace("Z", "+00:00"))
                closed = datetime.fromisoformat(close_date.replace("Z", "+00:00"))
                cycle_days = (closed - created).days

                # Filter out negative/zero/suspicious values
                if cycle_days <= 0:
                    bad_data_count += 1
                    print(f"  ⚠️  Bad data: {deal.get('company_name')} - cycle_days={cycle_days}")
                elif cycle_days > 0:
                    all_closed_cycle_times.append(cycle_days)

                    if is_won(stage):
                        won_only_cycle_times.append(cycle_days)
            except:
                pass

    print()
    print(f"Bad data (cycle_days <= 0): {bad_data_count} deals")
    print()

    # Calculate medians
    all_closed_cycle_times.sort()
    won_only_cycle_times.sort()

    median_all_closed = all_closed_cycle_times[len(all_closed_cycle_times) // 2] if all_closed_cycle_times else 0
    median_won_only = won_only_cycle_times[len(won_only_cycle_times) // 2] if won_only_cycle_times else 0

    print("=" * 80)
    print("RESULTS")
    print("=" * 80)
    print()

    print(f"METHOD 1 (CORRECT per commit 587f24a):")
    print(f"  Population: ALL closed deals (won + lost)")
    print(f"  Valid deals: {len(all_closed_cycle_times)}")
    print(f"  MEDIAN: {median_all_closed} days")
    print()

    print(f"METHOD 2 (WRONG - what I calculated earlier):")
    print(f"  Population: Won deals only")
    print(f"  Valid deals: {len(won_only_cycle_times)}")
    print(f"  MEDIAN: {median_won_only} days")
    print()

    print(f"Expected from YAML: 159 days")
    print()

    if median_all_closed == 159:
        print("✅ CORRECT METHOD matches YAML (159 days)")
    elif abs(median_all_closed - 159) <= 10:
        print(f"⚠️  CLOSE: {median_all_closed} days vs 159 (within 10 days - likely data drift)")
    else:
        print(f"❌ DISCREPANCY: {median_all_closed} days vs 159 expected")
        print(f"   Difference: {median_all_closed - 159} days")

    print()

    # Distribution for all closed
    if all_closed_cycle_times:
        print("Distribution (ALL closed deals):")
        print(f"  Min: {min(all_closed_cycle_times)} days")
        print(f"  25th percentile: {all_closed_cycle_times[len(all_closed_cycle_times) // 4]} days")
        print(f"  Median: {median_all_closed} days")
        print(f"  75th percentile: {all_closed_cycle_times[3 * len(all_closed_cycle_times) // 4]} days")
        print(f"  Max: {max(all_closed_cycle_times)} days")
        print()

    return {
        "median_all_closed": median_all_closed,
        "median_won_only": median_won_only,
        "yaml_expected": 159
    }

if __name__ == "__main__":
    verify_q016_correct()
