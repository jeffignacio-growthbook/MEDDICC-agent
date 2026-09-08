#!/usr/bin/env python3
"""
Investigate why select_all returns 154 deals when there are only 121 won deals.
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

def investigate():
    sb = get_supabase()

    print("=" * 80)
    print("INVESTIGATING EXTRA DEALS")
    print("=" * 80)
    print()

    # Get cutoff date
    now = datetime.now(timezone.utc)
    cutoff = now - timedelta(days=12 * 30)
    since_date = cutoff.strftime("%Y-%m-%d")

    print(f"12-month cutoff: {since_date}")
    print()

    # What select_all returns
    print("Query 1: select_all with filters")
    filters = [("eq", "deal_status", "won"), ("gte", "close_date", since_date)]
    deals_from_select_all = select_all(
        sb,
        "deals",
        columns="deal_id,deal_status,stage,close_date,company_name",
        filters=filters,
    )
    print(f"  Returns: {len(deals_from_select_all)} deals")
    print()

    # Check deal_status values
    status_counts = {}
    for deal in deals_from_select_all:
        status = deal.get("deal_status")
        status_counts[status] = status_counts.get(status, 0) + 1

    print("  Deal status breakdown:")
    for status, count in sorted(status_counts.items()):
        print(f"    {status}: {count}")
    print()

    # How many are actually won by is_won(stage)?
    won_by_stage = [d for d in deals_from_select_all if is_won(d.get("stage"))]
    print(f"  Won by is_won(stage): {len(won_by_stage)}")
    print()

    # Show some examples of deals that aren't won by stage
    not_won_by_stage = [d for d in deals_from_select_all if not is_won(d.get("stage"))]
    if not_won_by_stage:
        print(f"  {len(not_won_by_stage)} deals have deal_status='won' but NOT is_won(stage)=True:")
        for deal in not_won_by_stage[:5]:
            print(f"    - {deal['company_name']}: status={deal['deal_status']}, stage={deal['stage']}")
        print()

if __name__ == "__main__":
    investigate()
