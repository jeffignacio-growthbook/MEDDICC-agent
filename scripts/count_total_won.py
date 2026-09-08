#!/usr/bin/env python3
"""
Count total won deals using different methods.
"""
import sys
from pathlib import Path
from dotenv import load_dotenv

env_path = Path(__file__).parent.parent / ".env"
load_dotenv(env_path)

sys.path.insert(0, str(Path(__file__).parent.parent / "api"))
from db import get_supabase
from supabase_client import select_all
from field_semantics import is_won

def count_won():
    sb = get_supabase()

    print("=" * 80)
    print("COUNTING TOTAL WON DEALS")
    print("=" * 80)
    print()

    # Method 1: select_all with deal_status filter
    print("Method 1: select_all with deal_status='won'")
    deals_method1 = select_all(
        sb,
        "deals",
        columns="deal_id,deal_status,stage",
        filters=[("eq", "deal_status", "won")]
    )
    print(f"  Count: {len(deals_method1)}")
    print()

    # Method 2: Direct table query + is_won filter
    print("Method 2: Direct query + is_won(stage) filter")
    all_deals = sb.table("deals").select("deal_id,stage,deal_status").execute()
    won_by_stage = [d for d in all_deals.data if is_won(d.get("stage"))]
    print(f"  Total deals: {len(all_deals.data)}")
    print(f"  Won by is_won(stage): {len(won_by_stage)}")
    print()

    # Method 3: Direct query + deal_status filter
    print("Method 3: Direct query + deal_status='won' filter")
    won_by_status = [d for d in all_deals.data if d.get("deal_status") == "won"]
    print(f"  Won by deal_status: {len(won_by_status)}")
    print()

    print("=" * 80)
    print("CONCLUSION")
    print("=" * 80)
    print()
    if len(deals_method1) == len(won_by_stage) == len(won_by_status):
        print(f"✅ All methods agree: {len(deals_method1)} won deals")
    else:
        print("⚠️  Methods disagree:")
        print(f"  select_all: {len(deals_method1)}")
        print(f"  is_won(stage): {len(won_by_stage)}")
        print(f"  deal_status: {len(won_by_status)}")

if __name__ == "__main__":
    count_won()
