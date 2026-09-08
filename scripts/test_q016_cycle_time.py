#!/usr/bin/env python3
"""
Test q016: Cycle time calculation
"""
import sys
from pathlib import Path
from dotenv import load_dotenv
from datetime import datetime, timezone

env_path = Path(__file__).parent.parent / ".env"
load_dotenv(env_path)

sys.path.insert(0, str(Path(__file__).parent.parent / "api"))
from db import get_supabase

def test_q016():
    sb = get_supabase()

    print("=" * 80)
    print("Q016: Sales Cycle Time")
    print("=" * 80)
    print()

    # Get won deals with both create_date and close_date
    deals = sb.table("deals").select(
        "deal_id,company_name,create_date,close_date,stage"
    ).eq("deal_status", "won").execute()

    print(f"Total won deals: {len(deals.data)}")
    print()

    # Calculate cycle times
    cycle_times = []
    for deal in deals.data:
        create_date = deal.get("create_date")
        close_date = deal.get("close_date")

        if create_date and close_date:
            try:
                created = datetime.fromisoformat(create_date.replace("Z", "+00:00"))
                closed = datetime.fromisoformat(close_date.replace("Z", "+00:00"))
                cycle_days = (closed - created).days

                # Filter out negative/zero values
                if cycle_days > 0:
                    cycle_times.append(cycle_days)
            except:
                pass

    cycle_times.sort()
    median_cycle_time = cycle_times[len(cycle_times) // 2] if cycle_times else 0

    print(f"Deals with valid cycle time: {len(cycle_times)}")
    print(f"Median cycle time: {median_cycle_time} days")
    print()

    if cycle_times:
        print(f"Distribution:")
        print(f"  Min: {min(cycle_times)} days")
        print(f"  25th percentile: {cycle_times[len(cycle_times) // 4]} days")
        print(f"  Median: {median_cycle_time} days")
        print(f"  75th percentile: {cycle_times[3 * len(cycle_times) // 4]} days")
        print(f"  Max: {max(cycle_times)} days")
        print()

    print("VERIFIED VALUE for q016:")
    print(f"  median_cycle_days: {median_cycle_time}")
    print(f"  won_count: {len(cycle_times)}")
    print()

    return {
        "median_cycle_days": median_cycle_time,
        "won_count": len(cycle_times)
    }

if __name__ == "__main__":
    test_q016()
