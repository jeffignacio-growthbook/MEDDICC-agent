#!/usr/bin/env python3
"""
Reconcile audit logic vs dollar-split logic to explain the 126-deal discrepancy.

Prior audit: 444 = 298 (incremental only) + 99 (renewal only) + 8 (both) + 39 (neither)
New script: 444 = 172 (incremental only) + 100 (renewal only) + 8 (both) + 164 (neither)

Difference: 126 deals moved from "incremental only" to "neither"
"""
import sys
import os
from pathlib import Path
from dotenv import load_dotenv

env_path = Path(__file__).parent.parent / ".env"
load_dotenv(env_path)

sys.path.insert(0, str(Path(__file__).parent.parent / "api"))
from db import get_supabase
from field_semantics import is_incremental_pipeline, is_renewal_base

def reconcile():
    sb = get_supabase()

    response = sb.table("deals").select(
        "deal_id,company_name,deal_value,pipeline_id,expansion_arr,new_arr,renewal_revenue,stage"
    ).eq("deal_status", "active").execute()

    all_active = response.data
    print(f"Total active deals: {len(all_active)}")
    print()

    # AUDIT LOGIC (using is_incremental_pipeline helper)
    audit_incremental_only = []
    audit_renewal_only = []
    audit_both = []
    audit_neither = []

    for deal in all_active:
        is_incr = is_incremental_pipeline(deal)
        is_ren = is_renewal_base(deal)

        if is_incr and is_ren:
            audit_both.append(deal)
        elif is_incr and not is_ren:
            audit_incremental_only.append(deal)
        elif is_ren and not is_incr:
            audit_renewal_only.append(deal)
        else:
            audit_neither.append(deal)

    print("=" * 80)
    print("AUDIT LOGIC (using is_incremental_pipeline)")
    print("=" * 80)
    print(f"Incremental ONLY: {len(audit_incremental_only)} deals")
    print(f"Renewal ONLY: {len(audit_renewal_only)} deals")
    print(f"BOTH: {len(audit_both)} deals")
    print(f"NEITHER: {len(audit_neither)} deals")
    print(f"Total: {len(audit_incremental_only) + len(audit_renewal_only) + len(audit_both) + len(audit_neither)}")
    print()

    # DOLLAR-SPLIT LOGIC (using incremental_value > 0)
    dollar_incremental_only = []
    dollar_renewal_only = []
    dollar_both = []
    dollar_neither = []

    for deal in all_active:
        expansion_arr = deal.get("expansion_arr") or 0
        new_arr = deal.get("new_arr") or 0
        renewal_revenue = deal.get("renewal_revenue") or 0

        incremental_value = expansion_arr + new_arr

        has_incremental = incremental_value > 0
        has_renewal = renewal_revenue > 0

        if has_incremental and has_renewal:
            dollar_both.append(deal)
        elif has_incremental and not has_renewal:
            dollar_incremental_only.append(deal)
        elif has_renewal and not has_incremental:
            dollar_renewal_only.append(deal)
        else:
            dollar_neither.append(deal)

    print("=" * 80)
    print("DOLLAR-SPLIT LOGIC (using incremental_value > 0)")
    print("=" * 80)
    print(f"Incremental ONLY: {len(dollar_incremental_only)} deals")
    print(f"Renewal ONLY: {len(dollar_renewal_only)} deals")
    print(f"BOTH: {len(dollar_both)} deals")
    print(f"NEITHER: {len(dollar_neither)} deals")
    print(f"Total: {len(dollar_incremental_only) + len(dollar_renewal_only) + len(dollar_both) + len(dollar_neither)}")
    print()

    # FIND THE DIFFERENCE
    # Deals that are "incremental" by audit but "neither" by dollar-split
    audit_incremental_ids = {d["deal_id"] for d in audit_incremental_only + audit_both}
    dollar_neither_ids = {d["deal_id"] for d in dollar_neither}

    moved_to_neither = audit_incremental_ids & dollar_neither_ids

    print("=" * 80)
    print("DISCREPANCY ANALYSIS")
    print("=" * 80)
    print(f"Deals counted as incremental by AUDIT: {len(audit_incremental_ids)}")
    print(f"Deals counted as neither by DOLLAR-SPLIT: {len(dollar_neither_ids)}")
    print(f"Deals that moved from incremental → neither: {len(moved_to_neither)}")
    print()

    # Show examples of the moved deals
    moved_deals = [d for d in all_active if d["deal_id"] in moved_to_neither]

    print(f"Examples of {len(moved_deals)} deals that moved to 'neither':")
    print()
    for deal in moved_deals[:10]:
        print(f"  {deal.get('company_name')}")
        print(f"    pipeline_id: {deal.get('pipeline_id')}")
        print(f"    expansion_arr: {deal.get('expansion_arr')}")
        print(f"    new_arr: {deal.get('new_arr')}")
        print(f"    renewal_revenue: {deal.get('renewal_revenue')}")
        print(f"    deal_value: {deal.get('deal_value')}")
        print(f"    is_incremental_pipeline(): {is_incremental_pipeline(deal)}")
        print()

    if len(moved_deals) > 10:
        print(f"  ... and {len(moved_deals) - 10} more")
        print()

    # CRITICAL FINDING
    print("=" * 80)
    print("ROOT CAUSE")
    print("=" * 80)
    print()
    print("The audit's is_incremental_pipeline() returns True for:")
    print("  1. ANY deal in new business pipeline (regardless of ARR values)")
    print("  2. Deals in renewal pipeline with expansion_arr > 0 OR new_arr > 0")
    print()
    print("The dollar-split logic only counts deals where:")
    print("  - expansion_arr + new_arr > 0")
    print()
    print(f"Result: {len(moved_to_neither)} deals in new business pipeline have NO ARR recorded.")
    print("These are data quality gaps - they're in the pipeline but have $0 value.")
    print()

    # CORRECT APPROACH
    print("=" * 80)
    print("CORRECT IMPLEMENTATION")
    print("=" * 80)
    print()
    print("For q011 'pipeline', we should:")
    print("  1. Use is_incremental_pipeline() to determine which deals count (DEAL COUNT)")
    print("  2. For each deal, calculate incremental_value = expansion_arr + new_arr")
    print("  3. Sum incremental_value (not deal_value) for DOLLAR TOTAL")
    print("  4. Flag deals with incremental_value = 0 as data quality gaps")
    print()

    # Calculate correct numbers
    audit_incremental_deals = audit_incremental_only + audit_both
    total_incremental_arr = sum(
        (d.get("expansion_arr") or 0) + (d.get("new_arr") or 0)
        for d in audit_incremental_deals
    )

    zero_arr_deals = [
        d for d in audit_incremental_deals
        if ((d.get("expansion_arr") or 0) + (d.get("new_arr") or 0)) == 0
    ]

    print("CORRECT VERIFIED VALUE:")
    print(f"  Deal count: {len(audit_incremental_deals)} (using is_incremental_pipeline)")
    print(f"  Total incremental ARR: ${total_incremental_arr:,.0f} (sum of expansion_arr + new_arr)")
    print(f"  Data quality gap: {len(zero_arr_deals)} deals in pipeline with $0 incremental ARR")
    print()

if __name__ == "__main__":
    reconcile()
