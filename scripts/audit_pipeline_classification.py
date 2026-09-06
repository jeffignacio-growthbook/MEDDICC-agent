#!/usr/bin/env python3
"""
Audit pipeline classification logic against live data.

Reconciles actual bucket math:
- Total active deals
- is_incremental_pipeline() = True
- is_renewal_base() = True
- BOTH = True (overlap)
- NEITHER = True (uncategorized gap)

Validates: total = incremental + renewal - overlap + neither
"""
import sys
import os
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent / "api"))
from db import get_supabase
from field_semantics import is_incremental_pipeline, is_renewal_base

def audit_classification():
    """Audit all active deals and categorize by classification helpers."""
    sb = get_supabase()

    # Fetch all active deals with ARR breakdown
    response = sb.table("deals").select(
        "deal_id,company_name,deal_value,pipeline_id,expansion_arr,new_arr,renewal_revenue,stage"
    ).eq("deal_status", "active").execute()

    all_active = response.data
    total_count = len(all_active)
    total_value = sum(d.get("deal_value") or 0 for d in all_active)

    # Classify each deal
    incremental_only = []
    renewal_only = []
    both = []
    neither = []

    for deal in all_active:
        is_incr = is_incremental_pipeline(deal)
        is_ren = is_renewal_base(deal)

        if is_incr and is_ren:
            both.append(deal)
        elif is_incr and not is_ren:
            incremental_only.append(deal)
        elif is_ren and not is_incr:
            renewal_only.append(deal)
        else:
            neither.append(deal)

    # Calculate totals
    incr_count = len(incremental_only) + len(both)
    incr_value = sum(d.get("deal_value") or 0 for d in incremental_only) + sum(d.get("deal_value") or 0 for d in both)

    ren_count = len(renewal_only) + len(both)
    ren_value = sum(d.get("deal_value") or 0 for d in renewal_only) + sum(d.get("deal_value") or 0 for d in both)

    # Print results
    print("=" * 80)
    print("PIPELINE CLASSIFICATION AUDIT")
    print("=" * 80)
    print()
    print(f"Total active deals: {total_count}")
    print(f"Total deal_value: ${total_value:,.0f}")
    print()
    print("CLASSIFICATION BUCKETS:")
    print()
    print(f"Incremental ONLY: {len(incremental_only)} deals / ${sum(d.get('deal_value') or 0 for d in incremental_only):,.0f}")
    print(f"Renewal ONLY: {len(renewal_only)} deals / ${sum(d.get('deal_value') or 0 for d in renewal_only):,.0f}")
    print(f"BOTH (overlap): {len(both)} deals / ${sum(d.get('deal_value') or 0 for d in both):,.0f}")
    print(f"NEITHER (uncategorized): {len(neither)} deals / ${sum(d.get('deal_value') or 0 for d in neither):,.0f}")
    print()
    print("TOTALS (with overlap):")
    print(f"is_incremental_pipeline() = True: {incr_count} deals / ${incr_value:,.0f}")
    print(f"is_renewal_base() = True: {ren_count} deals / ${ren_value:,.0f}")
    print()

    # Reconciliation check
    reconciled_count = len(incremental_only) + len(renewal_only) + len(both) + len(neither)
    reconciled_value = (
        sum(d.get("deal_value") or 0 for d in incremental_only) +
        sum(d.get("deal_value") or 0 for d in renewal_only) +
        sum(d.get("deal_value") or 0 for d in both) +
        sum(d.get("deal_value") or 0 for d in neither)
    )

    print("RECONCILIATION:")
    print(f"Sum of buckets: {reconciled_count} deals / ${reconciled_value:,.0f}")
    print(f"Matches total: {'✅ YES' if reconciled_count == total_count and reconciled_value == total_value else '❌ NO'}")
    print()

    # Check for BOTH deals (should these exist?)
    if both:
        print("=" * 80)
        print(f"WARNING: {len(both)} deals classified as BOTH incremental AND renewal")
        print("=" * 80)
        print()
        print("These deals have BOTH renewal_revenue AND (expansion_arr OR new_arr):")
        print()
        for deal in both[:10]:  # Show first 10
            print(f"  {deal.get('company_name')} (stage: {deal.get('stage')})")
            print(f"    pipeline_id: {deal.get('pipeline_id')}")
            print(f"    expansion_arr: {deal.get('expansion_arr')}")
            print(f"    new_arr: {deal.get('new_arr')}")
            print(f"    renewal_revenue: {deal.get('renewal_revenue')}")
            print(f"    deal_value: {deal.get('deal_value')}")
            print()
        if len(both) > 10:
            print(f"  ... and {len(both) - 10} more")
            print()

    # Check for NEITHER deals (classification gap)
    if neither:
        print("=" * 80)
        print(f"WARNING: {len(neither)} deals classified as NEITHER (uncategorized)")
        print("=" * 80)
        print()
        print("These deals don't match incremental OR renewal criteria:")
        print()
        for deal in neither[:10]:
            print(f"  {deal.get('company_name')} (stage: {deal.get('stage')})")
            print(f"    pipeline_id: {deal.get('pipeline_id')}")
            print(f"    expansion_arr: {deal.get('expansion_arr')}")
            print(f"    new_arr: {deal.get('new_arr')}")
            print(f"    renewal_revenue: {deal.get('renewal_revenue')}")
            print(f"    deal_value: {deal.get('deal_value')}")
            print()
        if len(neither) > 10:
            print(f"  ... and {len(neither) - 10} more")
            print()

    # Find the 11 renewal-stage deals from Slack response
    renewal_stages = ["Upcoming Renewal", "Renewal Engaged"]
    renewal_staged_deals = [d for d in all_active if d.get("stage") in ["1297321618", "1297321619"]]

    print("=" * 80)
    print(f"RENEWAL-STAGED DEALS (stages: Upcoming Renewal, Renewal Engaged)")
    print("=" * 80)
    print(f"Total found: {len(renewal_staged_deals)} deals")
    print()

    upcoming_renewal = [d for d in renewal_staged_deals if d.get("stage") == "1297321618"]
    renewal_engaged = [d for d in renewal_staged_deals if d.get("stage") == "1297321619"]

    print(f"Upcoming Renewal (1297321618): {len(upcoming_renewal)} deals")
    print(f"Renewal Engaged (1297321619): {len(renewal_engaged)} deals")
    print()

    # Classify these specific deals
    for stage_name, stage_id, deals in [
        ("Upcoming Renewal", "1297321618", upcoming_renewal),
        ("Renewal Engaged", "1297321619", renewal_engaged)
    ]:
        if deals:
            print(f"\n{stage_name} deals classification:")
            for deal in deals:
                is_incr = is_incremental_pipeline(deal)
                is_ren = is_renewal_base(deal)
                classification = []
                if is_incr:
                    classification.append("INCREMENTAL")
                if is_ren:
                    classification.append("RENEWAL")
                if not classification:
                    classification.append("NEITHER")

                print(f"  {deal.get('company_name')}: {' + '.join(classification)}")
                print(f"    expansion_arr: {deal.get('expansion_arr')}, new_arr: {deal.get('new_arr')}, renewal_revenue: {deal.get('renewal_revenue')}")
                print(f"    deal_value: {deal.get('deal_value')}, pipeline_id: {deal.get('pipeline_id')}")

if __name__ == "__main__":
    audit_classification()
