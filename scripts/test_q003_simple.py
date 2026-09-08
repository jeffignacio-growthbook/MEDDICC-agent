#!/usr/bin/env python3
"""
Simple test for q003: Count deals with no ARR, verify synthesis shows actual count.
"""
import sys
from pathlib import Path
from dotenv import load_dotenv

env_path = Path(__file__).parent.parent / ".env"
load_dotenv(env_path)

sys.path.insert(0, str(Path(__file__).parent.parent / "api"))
from db import get_supabase

def test_q003_count():
    sb = get_supabase()

    print("=" * 80)
    print("Q003: Which deals have no ARR recorded?")
    print("=" * 80)
    print()

    # Get all active deals
    deals = sb.table("deals").select(
        "deal_id,company_name,expansion_arr,new_arr,renewal_revenue"
    ).eq("deal_status", "active").execute()

    total_active = len(deals.data)
    print(f"Total active deals: {total_active}")
    print()

    # Count deals with NO ARR at all (no incremental, no renewal)
    no_arr_at_all = []
    for deal in deals.data:
        expansion_arr = deal.get("expansion_arr") or 0
        new_arr = deal.get("new_arr") or 0
        renewal_revenue = deal.get("renewal_revenue") or 0

        if expansion_arr == 0 and new_arr == 0 and renewal_revenue == 0:
            no_arr_at_all.append(deal)

    # Count deals with no INCREMENTAL ARR (but might have renewal)
    no_incremental = []
    for deal in deals.data:
        expansion_arr = deal.get("expansion_arr") or 0
        new_arr = deal.get("new_arr") or 0

        if expansion_arr == 0 and new_arr == 0:
            no_incremental.append(deal)

    print(f"Deals with NO ARR at all (no expansion, new, or renewal): {len(no_arr_at_all)}")
    print(f"Deals with NO INCREMENTAL ARR (no expansion/new, might have renewal): {len(no_incremental)}")
    print()

    # Breakdown by interpretation
    print("Most likely interpretation of 'no ARR recorded':")
    print(f"  → No incremental ARR: {len(no_incremental)} deals")
    print(f"  → Of those, also no renewal ARR: {len(no_arr_at_all)} deals")
    print()

    print("VERIFIED VALUE for q003:")
    print(f"  count: {len(no_incremental)}")
    print(f"  total_deals: {total_active}")
    print(f"  pct: {len(no_incremental) / total_active * 100:.1f}%")
    print()

    return {
        "no_arr_at_all": len(no_arr_at_all),
        "no_incremental": len(no_incremental),
        "total_active": total_active
    }

if __name__ == "__main__":
    test_q003_count()
