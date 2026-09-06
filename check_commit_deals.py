#!/usr/bin/env python3
"""Check the 2 COMMIT deals to see what ARR fields they have."""
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent))
sys.path.insert(0, str(Path(__file__).parent / 'api'))

from dotenv import load_dotenv
load_dotenv()

from db import get_supabase

sb = get_supabase()

# Get all active deals with all amount-related fields
result = sb.table('deals').select(
    'deal_id, company_name, forecast_category, '
    'deal_value, arr_usd, new_arr, expansion_arr, '
    'incremental_arr, renewal_revenue, owner_email'
).eq('deal_status', 'active').execute()

print(f"Total active deals: {len(result.data)}")
print()

# Check case variations of COMMIT
commit_upper = [d for d in result.data if d.get('forecast_category') == 'COMMIT']
commit_lower = [d for d in result.data if d.get('forecast_category') == 'commit']
commit_mixed = [d for d in result.data if (d.get('forecast_category') or '').upper() == 'COMMIT']

print(f"COMMIT (uppercase):     {len(commit_upper)} deals")
print(f"commit (lowercase):     {len(commit_lower)} deals")
print(f"COMMIT (case-insensitive): {len(commit_mixed)} deals")
print()

if commit_upper:
    print("=" * 100)
    print("COMMIT DEALS (uppercase) - All ARR Fields")
    print("=" * 100)
    for d in commit_upper:
        print(f"\nDeal: {d.get('company_name', 'Unknown')} ({d['deal_id']})")
        print(f"  Owner: {d.get('owner_email', 'unassigned')}")
        print(f"  deal_value:       ${d.get('deal_value', 0):,.2f}" if d.get('deal_value') is not None else "  deal_value:       NULL")
        print(f"  arr_usd:          ${d.get('arr_usd', 0):,.2f}" if d.get('arr_usd') is not None else "  arr_usd:          NULL")
        print(f"  new_arr:          ${d.get('new_arr', 0):,.2f}" if d.get('new_arr') is not None else "  new_arr:          NULL")
        print(f"  expansion_arr:    ${d.get('expansion_arr', 0):,.2f}" if d.get('expansion_arr') is not None else "  expansion_arr:    NULL")
        print(f"  incremental_arr:  ${d.get('incremental_arr', 0):,.2f}" if d.get('incremental_arr') is not None else "  incremental_arr:  NULL")
        print(f"  renewal_revenue:  ${d.get('renewal_revenue', 0):,.2f}" if d.get('renewal_revenue') is not None else "  renewal_revenue:  NULL")

if commit_lower:
    print("\n" + "=" * 100)
    print("commit DEALS (lowercase)")
    print("=" * 100)
    for d in commit_lower:
        print(f"\nDeal: {d.get('company_name', 'Unknown')} ({d['deal_id']})")
        print(f"  Owner: {d.get('owner_email', 'unassigned')}")
        print(f"  deal_value: ${d.get('deal_value', 0):,.2f}")

# Calculate total using different fields
print("\n" + "=" * 100)
print("TOTALS BY FIELD (COMMIT deals, case-insensitive)")
print("=" * 100)

total_deal_value = sum(d.get('deal_value', 0) or 0 for d in commit_mixed)
total_arr_usd = sum(d.get('arr_usd', 0) or 0 for d in commit_mixed)
total_new_arr = sum(d.get('new_arr', 0) or 0 for d in commit_mixed)
total_incremental = sum(d.get('incremental_arr', 0) or 0 for d in commit_mixed)

print(f"deal_value:      ${total_deal_value:,.2f}")
print(f"arr_usd:         ${total_arr_usd:,.2f}")
print(f"new_arr:         ${total_new_arr:,.2f}")
print(f"incremental_arr: ${total_incremental:,.2f}")
print()
print(f"HubSpot dashboard shows: $170,000")
print(f"Which field matches?")
