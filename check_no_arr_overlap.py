#!/usr/bin/env python3
"""Check if no-ARR deals overlap with known data_quality_exclusions."""
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent))
sys.path.insert(0, str(Path(__file__).parent / 'api'))

from dotenv import load_dotenv
load_dotenv()

from db import get_supabase

sb = get_supabase()

# Get deals without ARR
result = sb.table('deals').select('deal_id, company_name, owner_email, stage').eq('deal_status', 'active').execute()

no_arr_deals = [
    d for d in result.data
    if d.get('deal_value') is None or d.get('deal_value') == 0
]

print(f"Total active deals: {len(result.data)}")
print(f"Deals without ARR: {len(no_arr_deals)} ({(len(no_arr_deals)/len(result.data))*100:.1f}%)")
print()

# Check if data_quality_exclusions table exists
try:
    exclusions_result = sb.table('data_quality_exclusions').select('deal_id, exclusion_reason').execute()

    excluded_deal_ids = set(e['deal_id'] for e in exclusions_result.data)

    print(f"Known data_quality_exclusions: {len(excluded_deal_ids)}")

    # Find overlap
    no_arr_deal_ids = set(d['deal_id'] for d in no_arr_deals)
    overlap = no_arr_deal_ids & excluded_deal_ids

    print(f"No-ARR deals that are ALREADY EXCLUDED: {len(overlap)} ({(len(overlap)/len(no_arr_deals))*100:.1f}% of no-ARR)")
    print(f"No-ARR deals that are NET NEW: {len(no_arr_deals) - len(overlap)} ({((len(no_arr_deals) - len(overlap))/len(no_arr_deals))*100:.1f}% of no-ARR)")

    print()
    print(f"Adjusted assessment:")
    print(f"  Total active (excluding known bad data): {len(result.data) - len(excluded_deal_ids)}")
    print(f"  Net-new no-ARR: {len(no_arr_deals) - len(overlap)}")
    print(f"  TRUE net-new no-ARR rate: {((len(no_arr_deals) - len(overlap))/(len(result.data) - len(excluded_deal_ids)))*100:.1f}%")

    if len(overlap) > 0:
        print()
        print("Sample overlapping deals (already-excluded bad data):")
        overlapping_deals = [d for d in no_arr_deals if d['deal_id'] in overlap]
        for d in overlapping_deals[:5]:
            print(f"  - {d['deal_id']}: {d.get('company_name', 'Unknown')} ({d.get('owner_email', 'unassigned')})")

except Exception as e:
    print(f"⚠️ Could not check exclusions: {e}")
    print("Assuming no exclusion table exists - all 142 no-ARR deals are net new.")
