#!/usr/bin/env python3
"""Check Q1 incremental_arr breakdown."""
from dotenv import load_dotenv
load_dotenv()

import os
from supabase import create_client
from api.field_semantics import is_won, is_lost

supabase_url = os.getenv("SUPABASE_URL")
supabase_key = os.getenv("SUPABASE_SERVICE_KEY")
supabase = create_client(supabase_url, supabase_key)

# Get all FY2027 Q1 renewal pipeline deals with all relevant fields
response = supabase.table("deals") \
    .select("deal_id,company_name,stage,close_date,renewal_revenue,new_arr,expansion_arr,deal_value") \
    .eq("pipeline_id", "866608541") \
    .gte("close_date", "2026-02-01") \
    .lt("close_date", "2026-05-01") \
    .execute()

deals = response.data

# Filter to deals with renewal_revenue (non-null)
with_renewal = [d for d in deals if d.get('renewal_revenue') is not None and d.get('renewal_revenue') != 0]

print(f"FY2027 Q1 renewal deals with renewal_revenue: {len(with_renewal)}")
print("=" * 70)

# Compute totals
total_renewal_revenue = sum(d.get('renewal_revenue', 0) for d in with_renewal)
total_new_arr = sum(d.get('new_arr', 0) or 0 for d in with_renewal)
total_expansion = sum(d.get('expansion_arr', 0) or 0 for d in with_renewal)
total_incremental = total_new_arr + total_expansion

print(f"\nTotals across {len(with_renewal)} deals:")
print(f"  renewal_revenue: ${total_renewal_revenue:>12,.2f}")
print(f"  new_arr:         ${total_new_arr:>12,.2f}")
print(f"  expansion_arr:   ${total_expansion:>12,.2f}")
print(f"  TOTAL incr:      ${total_incremental:>12,.2f}")

# Find deals with incremental_arr
with_incremental = [d for d in with_renewal if (d.get('new_arr', 0) or 0) + (d.get('expansion_arr', 0) or 0) > 0]

print(f"\n{len(with_incremental)} deals have non-zero incremental_arr:")
print("-" * 70)
for deal in with_incremental:
    name = deal.get('company_name', 'N/A')
    renewal = deal.get('renewal_revenue', 0)
    new = deal.get('new_arr', 0) or 0
    expansion = deal.get('expansion_arr', 0) or 0
    incremental = new + expansion
    stage = deal.get('stage', '')

    status = "WON" if is_won(stage) else "LOST" if is_lost(stage) else "OPEN"

    print(f"{name[:30]:30} | renewal=${renewal:>8,.0f} | new=${new:>8,.0f} | exp=${expansion:>8,.0f} | total=${incremental:>8,.0f} | {status}")

# Compute NRR for closed-only and assume-open-wins
print("\n" + "=" * 70)
print("NRR COMPUTATION:")
print("=" * 70)

won_deals = [d for d in with_renewal if is_won(d.get('stage', ''))]
lost_deals = [d for d in with_renewal if is_lost(d.get('stage', ''))]
open_deals = [d for d in with_renewal if not is_won(d.get('stage', '')) and not is_lost(d.get('stage', ''))]

print(f"\nDeal counts: {len(won_deals)} won, {len(lost_deals)} lost, {len(open_deals)} open")

# Closed-only NRR
closed_deals = won_deals + lost_deals
closed_not_lost = won_deals

closed_denominator = sum(d.get('renewal_revenue', 0) for d in closed_deals)
closed_numerator = sum(
    d.get('renewal_revenue', 0) + (d.get('new_arr', 0) or 0) + (d.get('expansion_arr', 0) or 0)
    for d in closed_not_lost
)
closed_nrr = (closed_numerator / closed_denominator) if closed_denominator > 0 else 0

print(f"\nClosed-only NRR:")
print(f"  Denominator: ${closed_denominator:,.2f} ({len(closed_deals)} deals)")
print(f"  Numerator:   ${closed_numerator:,.2f} ({len(closed_not_lost)} won deals)")
print(f"  NRR: {closed_nrr:.1%}")
print(f"  Reference: 107%")
print(f"  Difference: {(closed_nrr - 1.07)*100:+.1f}pp")

# Assume-open-wins NRR
all_not_lost = won_deals + open_deals

all_denominator = total_renewal_revenue
all_numerator = sum(
    d.get('renewal_revenue', 0) + (d.get('new_arr', 0) or 0) + (d.get('expansion_arr', 0) or 0)
    for d in all_not_lost
)
all_nrr = (all_numerator / all_denominator) if all_denominator > 0 else 0

print(f"\nAssume-open-wins NRR:")
print(f"  Denominator: ${all_denominator:,.2f} ({len(with_renewal)} deals)")
print(f"  Numerator:   ${all_numerator:,.2f} ({len(all_not_lost)} won+open deals)")
print(f"  NRR: {all_nrr:.1%}")
print(f"  Reference: 107%")
print(f"  Difference: {(all_nrr - 1.07)*100:+.1f}pp")

# Check if HubSpot might be using deal_value instead
print("\n" + "=" * 70)
print("ALTERNATIVE: Using deal_value instead of renewal_revenue + incremental:")
print("=" * 70)

alt_closed_numerator = sum(d.get('deal_value', 0) or 0 for d in closed_not_lost)
alt_closed_nrr = (alt_closed_numerator / closed_denominator) if closed_denominator > 0 else 0

print(f"\nClosed-only (using deal_value in numerator):")
print(f"  Numerator: ${alt_closed_numerator:,.2f}")
print(f"  NRR: {alt_closed_nrr:.1%}")

print(f"\n" + "=" * 70)
print("FINDING: incremental_arr total is ${:,.2f}".format(total_incremental))
print("This is the expansion being added to NRR numerator.")
print("If HubSpot excludes some of this, that would explain the 4-5pp difference.")
