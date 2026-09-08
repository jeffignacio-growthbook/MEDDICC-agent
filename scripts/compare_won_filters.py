#!/usr/bin/env python3
"""
Compare is_won(stage) vs deal_status filtering to understand discrepancy.
"""
import sys
from pathlib import Path
from dotenv import load_dotenv

env_path = Path(__file__).parent.parent / ".env"
load_dotenv(env_path)

sys.path.insert(0, str(Path(__file__).parent.parent / "api"))
from db import get_supabase
from field_semantics import is_won

def compare_filters():
    sb = get_supabase()

    print("=" * 80)
    print("COMPARING WON DEAL FILTERS")
    print("=" * 80)
    print()

    # Fetch all deals
    deals = sb.table("deals").select("deal_id,stage,deal_status,company_name").execute()

    won_by_stage = [d for d in deals.data if is_won(d.get("stage"))]
    won_by_status = [d for d in deals.data if d.get("deal_status") == "won"]

    print(f"Total deals in database: {len(deals.data)}")
    print(f"Won by is_won(stage): {len(won_by_stage)}")
    print(f"Won by deal_status=='won': {len(won_by_status)}")
    print(f"Difference: {abs(len(won_by_stage) - len(won_by_status))}")
    print()

    # Find deals in one set but not the other
    stage_ids = {d["deal_id"] for d in won_by_stage}
    status_ids = {d["deal_id"] for d in won_by_status}

    in_stage_not_status = stage_ids - status_ids
    in_status_not_stage = status_ids - stage_ids

    if in_stage_not_status:
        print(f"Deals won by stage but NOT by status: {len(in_stage_not_status)}")
        for deal_id in list(in_stage_not_status)[:5]:
            deal = next(d for d in won_by_stage if d["deal_id"] == deal_id)
            print(f"  - {deal['company_name']}: stage={deal['stage']}, status={deal['deal_status']}")
        print()

    if in_status_not_stage:
        print(f"Deals won by status but NOT by stage: {len(in_status_not_stage)}")
        for deal_id in list(in_status_not_stage)[:5]:
            deal = next(d for d in won_by_status if d["deal_id"] == deal_id)
            print(f"  - {deal['company_name']}: stage={deal['stage']}, status={deal['deal_status']}")
        print()

    print("=" * 80)
    print("CONCLUSION")
    print("=" * 80)
    print()

    if len(won_by_stage) == len(won_by_status) and len(in_stage_not_status) == 0:
        print("✅ Both filters produce identical results - use either one")
    else:
        print("⚠️  Filters produce different results - need to choose canonical definition")
        print()
        print("Recommendation: Use is_won(stage) as it's the canonical field_semantics definition")

if __name__ == "__main__":
    compare_filters()
