#!/usr/bin/env python3
"""
Compute correct INCREMENTAL ARR pipeline value with dollar-level split.

Per Jeff's confirmed definition (Sep 6, 2026):
- Pipeline = sum of (expansion_arr + new_arr) per deal
- For BOTH-category deals: only expansion_arr portion counts toward pipeline
- Renewal_revenue excluded (reported separately)
"""
import sys
import os
from pathlib import Path
from dotenv import load_dotenv

# Load env vars from .env
env_path = Path(__file__).parent.parent / ".env"
load_dotenv(env_path)

sys.path.insert(0, str(Path(__file__).parent.parent / "api"))
from db import get_supabase

def compute_incremental_pipeline_dollar_split():
    """Query all active deals and compute incremental ARR with dollar-level split."""
    sb = get_supabase()

    # Fetch all active deals with ARR breakdown
    response = sb.table("deals").select(
        "deal_id,company_name,deal_value,pipeline_id,expansion_arr,new_arr,renewal_revenue,stage"
    ).eq("deal_status", "active").execute()

    all_active = response.data

    # Dollar-level split logic
    incremental_deals = []
    renewal_only_deals = []
    both_deals = []
    neither_deals = []

    total_incremental_arr = 0
    total_renewal_arr = 0

    for deal in all_active:
        expansion_arr = deal.get("expansion_arr") or 0
        new_arr = deal.get("new_arr") or 0
        renewal_revenue = deal.get("renewal_revenue") or 0

        # Calculate incremental value (dollar-level)
        incremental_value = expansion_arr + new_arr

        # Classify
        has_incremental = incremental_value > 0
        has_renewal = renewal_revenue > 0

        if has_incremental and has_renewal:
            both_deals.append({
                **deal,
                "_incremental_value": incremental_value,
                "_renewal_value": renewal_revenue
            })
            total_incremental_arr += incremental_value
            total_renewal_arr += renewal_revenue
        elif has_incremental and not has_renewal:
            incremental_deals.append({
                **deal,
                "_incremental_value": incremental_value
            })
            total_incremental_arr += incremental_value
        elif has_renewal and not has_incremental:
            renewal_only_deals.append({
                **deal,
                "_renewal_value": renewal_revenue
            })
            total_renewal_arr += renewal_revenue
        else:
            # NEITHER category
            neither_deals.append(deal)

    # Calculate totals
    total_incremental_deals = len(incremental_deals) + len(both_deals)
    total_renewal_deals = len(renewal_only_deals) + len(both_deals)

    print("=" * 80)
    print("INCREMENTAL ARR PIPELINE (Dollar-Level Split)")
    print("=" * 80)
    print()
    print(f"Total active deals: {len(all_active)}")
    print()
    print("CLASSIFICATION BREAKDOWN:")
    print(f"  Incremental ONLY: {len(incremental_deals)} deals")
    print(f"  Renewal ONLY: {len(renewal_only_deals)} deals")
    print(f"  BOTH (split at dollar level): {len(both_deals)} deals")
    print(f"  NEITHER (uncategorized): {len(neither_deals)} deals")
    print()
    print("DOLLAR-LEVEL TOTALS:")
    print(f"  Total incremental ARR: ${total_incremental_arr:,.0f} ({total_incremental_deals} deals)")
    print(f"  Total renewal ARR: ${total_renewal_arr:,.0f} ({total_renewal_deals} deals)")
    print()
    print(f"Uncategorized (NEITHER) deals: {len(neither_deals)} deals, ${sum(d.get('deal_value') or 0 for d in neither_deals):,.0f} deal_value")
    print()

    # Show BOTH deals breakdown
    if both_deals:
        print("=" * 80)
        print(f"BOTH-CATEGORY DEALS (Dollar-Level Split)")
        print("=" * 80)
        print(f"Total: {len(both_deals)} deals")
        print()
        for deal in both_deals:
            print(f"  {deal.get('company_name')}")
            print(f"    expansion_arr: ${deal.get('expansion_arr'):,.0f} → incremental pipeline")
            print(f"    new_arr: ${deal.get('new_arr') or 0:,.0f} → incremental pipeline")
            print(f"    renewal_revenue: ${deal.get('renewal_revenue'):,.0f} → renewal ARR")
            print(f"    deal_value: ${deal.get('deal_value'):,.0f} (total)")
            print(f"    _incremental_value: ${deal.get('_incremental_value'):,.0f}")
            print()

    # Show NEITHER deals examples
    if neither_deals:
        print("=" * 80)
        print(f"NEITHER-CATEGORY DEALS (Data Quality Gap)")
        print("=" * 80)
        print(f"Total: {len(neither_deals)} deals")
        print()
        for deal in neither_deals[:10]:
            print(f"  {deal.get('company_name')}")
            print(f"    expansion_arr: {deal.get('expansion_arr')}")
            print(f"    new_arr: {deal.get('new_arr')}")
            print(f"    renewal_revenue: {deal.get('renewal_revenue')}")
            print(f"    deal_value: {deal.get('deal_value')}")
            print()
        if len(neither_deals) > 10:
            print(f"  ... and {len(neither_deals) - 10} more")
            print()

    print("=" * 80)
    print("Q011 VERIFIED VALUE (For canonical_questions.yaml)")
    print("=" * 80)
    print()
    print(f"total_arr: {int(total_incremental_arr)}")
    print(f"deal_count: {total_incremental_deals}")
    print(f'note: "Incremental ARR pipeline as of {all_active[0].get("close_date") if all_active else "unknown"}. Dollar-level split: sum of expansion_arr + new_arr per deal. Excludes {len(renewal_only_deals)} renewal-only deals (${total_renewal_arr:,.0f}) which are reported separately. {len(both_deals)} deals contribute to BOTH pipeline and renewal ARR."')
    print()

if __name__ == "__main__":
    compute_incremental_pipeline_dollar_split()
