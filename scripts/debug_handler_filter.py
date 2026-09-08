#!/usr/bin/env python3
"""
Debug why handler shows 151 deals when there are only 121 won deals.
"""
import sys
from pathlib import Path
from dotenv import load_dotenv
from datetime import datetime, timedelta, timezone

env_path = Path(__file__).parent.parent / ".env"
load_dotenv(env_path)

sys.path.insert(0, str(Path(__file__).parent.parent / "api"))
from db import get_supabase
from supabase_client import select_all
from field_semantics import is_won

def debug_filter():
    sb = get_supabase()

    print("=" * 80)
    print("DEBUGGING HANDLER FILTER")
    print("=" * 80)
    print()

    # Test the exact filter the handler uses
    now = datetime.now(timezone.utc)
    cutoff = now - timedelta(days=12 * 30)  # 12 months
    since_date = cutoff.strftime("%Y-%m-%d")

    print(f"Rolling 12-month cutoff: {since_date}")
    print()

    # Test 1: What select_all returns with handler filters
    print("Test 1: Handler's select_all call")
    filters = [("eq", "deal_status", "won")]
    filters.append(("gte", "close_date", since_date))

    deals = select_all(
        sb,
        "deals",
        columns="deal_id,create_date,close_date,deal_status,stage",
        filters=filters,
    )

    print(f"  Deals returned by select_all: {len(deals)}")
    print()

    # Count how many actually pass the cycle time logic
    cycle_times = []
    for deal in deals:
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

            days = (close_date - create_date).days

            if days >= 0:
                cycle_times.append(days)
        except (ValueError, AttributeError):
            continue

    print(f"  Deals with valid cycle time: {len(cycle_times)}")
    print()

    # Test 2: Compare to standalone script approach
    print("Test 2: Standalone script approach (is_won filter)")
    all_deals = sb.table("deals").select(
        "deal_id,company_name,create_date,close_date,stage,deal_status"
    ).execute()

    won_deals = [d for d in all_deals.data if is_won(d.get("stage"))]
    print(f"  Total won deals by is_won(stage): {len(won_deals)}")

    # Filter to 12-month window
    won_12mo = []
    for deal in won_deals:
        close_date_str = deal.get("close_date")
        if not close_date_str:
            continue

        try:
            close_date = datetime.fromisoformat(close_date_str.replace("Z", "+00:00"))
            if close_date.tzinfo is None:
                close_date = close_date.replace(tzinfo=timezone.utc)

            if close_date >= cutoff:
                won_12mo.append(deal)
        except (ValueError, AttributeError):
            continue

    print(f"  Won deals in 12-month window: {len(won_12mo)}")
    print()

    print("=" * 80)
    print("CONCLUSION")
    print("=" * 80)
    print()
    print(f"Handler finds: {len(cycle_times)} deals")
    print(f"Standalone finds: {len(won_12mo)} deals")
    print(f"Difference: {abs(len(cycle_times) - len(won_12mo))}")

if __name__ == "__main__":
    debug_filter()
