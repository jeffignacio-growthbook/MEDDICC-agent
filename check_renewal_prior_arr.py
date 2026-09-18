#!/usr/bin/env python3
"""Check if renewal deals have prior_arr populated."""
from dotenv import load_dotenv
load_dotenv()

import os
from supabase import create_client
from collections import Counter

supabase_url = os.getenv("SUPABASE_URL")
supabase_key = os.getenv("SUPABASE_SERVICE_KEY")

supabase = create_client(supabase_url, supabase_key)

# Query renewal deals with prior_arr
response = supabase.table("deals") \
    .select("deal_id,company_name,arr_usd,renewal_revenue,prior_arr,new_arr,expansion_arr") \
    .eq("pipeline_id", "866608541") \
    .execute()

deals = response.data

print(f"Renewal pipeline deals: {len(deals)}")
print("=" * 70)

# Check prior_arr population
with_prior = [d for d in deals if d.get('prior_arr') is not None and d.get('prior_arr') != 0]
without_prior = [d for d in deals if d.get('prior_arr') is None or d.get('prior_arr') == 0]

print(f"\nPRIOR_ARR availability:")
print(f"  With prior_arr (non-zero): {len(with_prior):3}")
print(f"  Without prior_arr (null/0): {len(without_prior):3}")
print(f"  Coverage: {(len(with_prior)/len(deals)*100):.1f}%")

# Check other ARR components
with_renewal = [d for d in deals if d.get('renewal_revenue') is not None and d.get('renewal_revenue') != 0]
with_new = [d for d in deals if d.get('new_arr') is not None and d.get('new_arr') != 0]
with_expansion = [d for d in deals if d.get('expansion_arr') is not None and d.get('expansion_arr') != 0]

print(f"\nARR component population:")
print(f"  renewal_revenue (non-zero): {len(with_renewal):3} ({len(with_renewal)/len(deals)*100:.1f}%)")
print(f"  new_arr (non-zero):         {len(with_new):3} ({len(with_new)/len(deals)*100:.1f}%)")
print(f"  expansion_arr (non-zero):   {len(with_expansion):3} ({len(with_expansion)/len(deals)*100:.1f}%)")

# Show sample with prior_arr
print(f"\nSample renewal deals WITH prior_arr (first 10):")
for i, deal in enumerate(with_prior[:10]):
    name = deal['company_name'] or 'N/A'
    arr = deal.get('arr_usd', 0) or 0
    renewal = deal.get('renewal_revenue', 0) or 0
    prior = deal.get('prior_arr', 0) or 0
    expansion = deal.get('expansion_arr', 0) or 0

    # Calculate expansion/contraction
    if prior > 0:
        change = renewal - prior
        change_pct = (change / prior) * 100
        change_type = "expansion" if change > 0 else "contraction" if change < 0 else "flat"
        print(f"  [{i+1}] {name[:25]:25} | prior=${prior:>8,.0f} renewal=${renewal:>8,.0f} | {change_type:12} {change_pct:+6.1f}%")

print(f"\nSample renewal deals WITHOUT prior_arr (first 5):")
for i, deal in enumerate(without_prior[:5]):
    name = deal['company_name'] or 'N/A'
    arr = deal.get('arr_usd', 0) or 0
    renewal = deal.get('renewal_revenue', 0) or 0
    print(f"  [{i+1}] {name[:25]:25} | arr=${arr:>8,.0f} renewal=${renewal:>8,.0f} | prior=NULL")

print("\n" + "=" * 70)
print("ASSESSMENT:")
if len(with_prior) >= len(deals) * 0.8:
    print("  ✓ prior_arr available for 80%+ of renewal deals")
    print("  → Can compute NRR (expansion/contraction against prior baseline)")
elif len(with_prior) > 0:
    print(f"  ⚠ prior_arr available for only {len(with_prior)/len(deals)*100:.0f}% of renewal deals")
    print("  → Can compute GRR (renewals - churn) for all deals")
    print(f"  → Can compute NRR for {len(with_prior)} deals only")
else:
    print("  ✗ prior_arr not populated for any renewal deals")
    print("  → Can compute GRR (renewals - churn) only")
    print("  → Cannot compute NRR (no baseline for expansion/contraction)")
