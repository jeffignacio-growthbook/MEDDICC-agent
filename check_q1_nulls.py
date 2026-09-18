#!/usr/bin/env python3
"""Check Q1 null renewal_revenue deals for incremental_arr."""
from dotenv import load_dotenv
load_dotenv()

import os
from supabase import create_client
from datetime import datetime

supabase_url = os.getenv("SUPABASE_URL")
supabase_key = os.getenv("SUPABASE_SERVICE_KEY")
supabase = create_client(supabase_url, supabase_key)

# Get all FY2027 Q1 renewal pipeline deals
# Q1 FY2027 = Feb 2026 - Apr 2026
response = supabase.table("deals") \
    .select("deal_id,company_name,stage,close_date,renewal_revenue,new_arr,expansion_arr") \
    .eq("pipeline_id", "866608541") \
    .gte("close_date", "2026-02-01") \
    .lt("close_date", "2026-05-01") \
    .execute()

deals = response.data

print(f"FY2027 Q1 renewal deals: {len(deals)}")
print("=" * 70)

# Find deals with null renewal_revenue
null_renewal = [d for d in deals if d.get('renewal_revenue') is None or d.get('renewal_revenue') == 0]
with_renewal = [d for d in deals if d.get('renewal_revenue') is not None and d.get('renewal_revenue') != 0]

print(f"With renewal_revenue: {len(with_renewal)}")
print(f"Null renewal_revenue: {len(null_renewal)}")
print()

if null_renewal:
    print(f"Deals with NULL renewal_revenue:")
    print("-" * 70)
    for deal in null_renewal:
        deal_id = deal['deal_id']
        name = deal.get('company_name', 'N/A')
        stage = deal.get('stage', 'N/A')
        renewal = deal.get('renewal_revenue', 0) or 0
        new_arr = deal.get('new_arr', 0) or 0
        expansion = deal.get('expansion_arr', 0) or 0
        incremental = new_arr + expansion

        print(f"\nDeal ID: {deal_id}")
        print(f"  Company: {name}")
        print(f"  Stage: {stage}")
        print(f"  Close Date: {deal.get('close_date', 'N/A')}")
        print(f"  renewal_revenue: {renewal}")
        print(f"  new_arr: {new_arr}")
        print(f"  expansion_arr: {expansion}")
        print(f"  TOTAL incremental_arr: {incremental}")

        if incremental != 0:
            print(f"  ⚠️  HAS INCREMENTAL ARR BUT NULL RENEWAL REVENUE")
            print(f"      This expansion would be counted in NRR numerator")
            print(f"      but excluded from denominator (inflates ratio)")

# Calculate what NRR should be with and without the null-deal expansion
print("\n" + "=" * 70)
print("NRR CALCULATION CHECK:")
print("=" * 70)

# Denominator: sum of renewal_revenue from non-null deals only
total_renewal_revenue = sum(d.get('renewal_revenue', 0) for d in with_renewal)

# Current (buggy) numerator: includes incremental from ALL not-lost deals
from api.field_semantics import is_won, is_lost

not_lost_all = [d for d in deals if not is_lost(d.get('stage', ''))]
buggy_numerator = sum(
    (d.get('renewal_revenue', 0) or 0) + (d.get('new_arr', 0) or 0) + (d.get('expansion_arr', 0) or 0)
    for d in not_lost_all
)

# Correct numerator: includes incremental ONLY from deals with renewal_revenue
not_lost_with_renewal = [d for d in with_renewal if not is_lost(d.get('stage', ''))]
correct_numerator = sum(
    d.get('renewal_revenue', 0) + (d.get('new_arr', 0) or 0) + (d.get('expansion_arr', 0) or 0)
    for d in not_lost_with_renewal
)

buggy_nrr = (buggy_numerator / total_renewal_revenue) if total_renewal_revenue > 0 else 0
correct_nrr = (correct_numerator / total_renewal_revenue) if total_renewal_revenue > 0 else 0

print(f"\nDenominator (renewal_revenue from non-null deals): ${total_renewal_revenue:,.2f}")
print(f"\nBuggy numerator (includes incremental from nulls): ${buggy_numerator:,.2f}")
print(f"Buggy NRR: {buggy_nrr:.1%}")
print(f"\nCorrect numerator (excludes null deals entirely): ${correct_numerator:,.2f}")
print(f"Correct NRR: {correct_nrr:.1%}")
print(f"\nDifference: {(buggy_nrr - correct_nrr)*100:.1f} percentage points")
print(f"\nHubSpot Reference: 107%")
print(f"Handler Current: {buggy_nrr:.1%}")
print(f"Handler Fixed: {correct_nrr:.1%}")
