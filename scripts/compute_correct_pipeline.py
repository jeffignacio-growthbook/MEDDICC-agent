#!/usr/bin/env python3
"""
Compute correct INCREMENTAL ARR pipeline value for q011 verified value update.

Per business definition: Pipeline = expansion_arr + new_arr (excludes renewal base).
This script queries Supabase to get the correct numbers.
"""
import sys
import os
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent / "api"))
from db import get_supabase
from field_semantics import is_incremental_pipeline

def compute_incremental_pipeline():
    """Query all active deals and filter to incremental ARR pipeline."""
    sb = get_supabase()

    # Fetch all active deals with ARR breakdown
    response = sb.table("deals").select(
        "deal_id,company_name,deal_value,pipeline_id,expansion_arr,new_arr,renewal_revenue,stage"
    ).eq("deal_status", "active").execute()

    all_active = response.data

    # Filter to incremental pipeline
    incremental_deals = [d for d in all_active if is_incremental_pipeline(d)]

    # Calculate totals
    total_deals = len(incremental_deals)
    total_pipeline = sum(d.get("deal_value") or 0 for d in incremental_deals)

    # Renewal deals for comparison
    renewal_pipeline_id = "866608541"
    renewal_deals = [d for d in all_active if d.get("pipeline_id") == renewal_pipeline_id]
    renewal_count = len(renewal_deals)
    renewal_value = sum(d.get("deal_value") or 0 for d in renewal_deals)

    print("=" * 80)
    print("INCREMENTAL ARR PIPELINE (Correct Definition)")
    print("=" * 80)
    print()
    print(f"Total active deals: {len(all_active)}")
    print(f"Incremental pipeline deals: {total_deals}")
    print(f"Total incremental pipeline: ${total_pipeline:,.0f}")
    print()
    print(f"Renewal pipeline deals (excluded): {renewal_count}")
    print(f"Renewal pipeline value (excluded): ${renewal_value:,.0f}")
    print()
    print(f"Difference: {len(all_active) - total_deals} deals, ${(sum(d.get('deal_value') or 0 for d in all_active) - total_pipeline):,.0f}")
    print()
    print("=" * 80)
    print("VERIFIED VALUE FOR q011")
    print("=" * 80)
    print()
    print(f"total_arr: {int(total_pipeline)}")
    print(f"deal_count: {total_deals}")
    print(f'note: "Incremental ARR pipeline (expansion + new business). Excludes {renewal_count} renewal deals (${renewal_value:,.0f}) which are reported separately."')
    print()

if __name__ == "__main__":
    compute_incremental_pipeline()
