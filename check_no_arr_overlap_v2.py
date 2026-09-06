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

# Get ALL columns from a sample deal first to see what's available
sample = sb.table('deals').select('*').eq('deal_status', 'active').limit(1).execute()
if sample.data:
    print("Sample deal columns:")
    print(sorted(sample.data[0].keys()))
    print()

# Get deals - check multiple possible ARR column names
result = sb.table('deals').select('deal_id, company_name, owner_email, stage, deal_value, arr_usd, amount').eq('deal_status', 'active').execute()

# Check which column has data
for d in result.data[:3]:
    print(f"Sample: deal_value={d.get('deal_value')}, arr_usd={d.get('arr_usd')}, amount={d.get('amount')}")

print()

# Try multiple ARR columns
no_arr_deals = []
for d in result.data:
    # Check deal_value, arr_usd, and amount
    value = d.get('deal_value') or d.get('arr_usd') or d.get('amount')
    if value is None or value == 0:
        no_arr_deals.append(d)

print(f"Total active deals: {len(result.data)}")
print(f"Deals without ARR (any column): {len(no_arr_deals)} ({(len(no_arr_deals)/len(result.data))*100:.1f}%)")
