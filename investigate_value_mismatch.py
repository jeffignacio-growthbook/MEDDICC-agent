#!/usr/bin/env python3
"""
Investigate why waterfall beginning/ending values are massively different
from actual snapshot totals for EMEA/Mid-Market 2026-05-25.

Waterfall: $725K beginning, $645K ending
Actual: $2,083K beginning, $1,973K ending

Difference: ~$1.3M missing from both beginning and ending
"""
import os
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).parent
sys.path.insert(0, str(REPO_ROOT / 'scripts'))
sys.path.insert(0, str(REPO_ROOT / 'scripts/analytics'))

from dotenv import load_dotenv
load_dotenv()

from supabase import create_client
SUPABASE_URL = os.getenv('SUPABASE_URL')
SUPABASE_KEY = os.getenv('SUPABASE_SERVICE_KEY')
sb = create_client(SUPABASE_URL, SUPABASE_KEY)

from supabase_client import select_all

print("Investigating $1.3M value mismatch in EMEA/Mid-Market")
print("=" * 70)

prev_week = '2026-05-18'
test_week = '2026-05-25'
region = 'EMEA'
segment = 'Mid-Market'

# Load snapshots
prev_snap = select_all(sb, 'deals_snapshot', '*',
                      filters=[('eq', 'snapshot_date', prev_week)])

# Load qualification data from deals table
qual_data = select_all(sb, 'deals', 'deal_id,qualified_date')
qual_map = {d['deal_id']: d.get('qualified_date') for d in qual_data}

print(f"Loaded {len(prev_snap)} deals from {prev_week} snapshot")
print(f"Loaded {len(qual_map)} qualification records")
print()

# Filter EMEA/Mid-Market deals
emea_mm_deals = [d for d in prev_snap
                 if (d.get('region') or 'UNKNOWN') == region
                 and (d.get('segment') or 'Unknown') == segment]

print(f"Found {len(emea_mm_deals)} EMEA/Mid-Market deals in snapshot")
print()

# Apply waterfall filters one by one
print("Applying waterfall filters:")
print("-" * 70)

# Filter 1: deal_status == 'active'
active_deals = [d for d in emea_mm_deals if d.get('deal_status') == 'active']
print(f"1. Active deals: {len(active_deals)} ({len(emea_mm_deals) - len(active_deals)} filtered out)")

# Filter 2: qualified as of prev_week
qualified_deals = []
for d in active_deals:
    deal_id = d['deal_id']
    qual_date = qual_map.get(deal_id)

    if qual_date and qual_date <= prev_week:
        qualified_deals.append(d)

print(f"2. Qualified as of {prev_week}: {len(qualified_deals)} ({len(active_deals) - len(qualified_deals)} filtered out)")

# Filter 3: non-null values
valued_deals = [d for d in qualified_deals if d.get('deal_value') is not None]
print(f"3. Non-null values: {len(valued_deals)} ({len(qualified_deals) - len(valued_deals)} filtered out)")

# Calculate totals at each stage
total_emea_mm = sum(d.get('deal_value') or 0 for d in emea_mm_deals)
total_active = sum(d.get('deal_value') or 0 for d in active_deals)
total_qualified = sum(d.get('deal_value') or 0 for d in qualified_deals)
total_valued = sum(d.get('deal_value') or 0 for d in valued_deals)

print()
print("Value totals at each stage:")
print(f"  All EMEA/Mid-Market: ${total_emea_mm:,.2f}")
print(f"  After active filter: ${total_active:,.2f}")
print(f"  After qualified filter: ${total_qualified:,.2f}")
print(f"  After non-null filter: ${total_valued:,.2f}")
print()
print(f"Waterfall beginning value: $725,000.00")
print(f"Difference from actual: ${abs(total_active - 725000):,.2f}")

# Check what deals were filtered out by qualification
print()
print("=" * 70)
print("Deals filtered out by qualification threshold:")
print("-" * 70)

unqualified = [d for d in active_deals if d['deal_id'] not in [q['deal_id'] for q in qualified_deals]]
unqualified_value = sum(d.get('deal_value') or 0 for d in unqualified)

print(f"Found {len(unqualified)} unqualified deals worth ${unqualified_value:,.2f}")
print()
print("Sample unqualified deals:")
for d in sorted(unqualified, key=lambda x: -(x.get('deal_value') or 0))[:10]:
    deal_id = d['deal_id']
    value = d.get('deal_value') or 0
    qual_date = qual_map.get(deal_id, 'NO RECORD')

    print(f"  {deal_id}: ${value:,.0f} (qualified: {qual_date})")

print()
print("=" * 70)
print("DIAGNOSIS")
print("=" * 70)
print("The qualification filter is excluding $1.3M of deals from beginning_value.")
print("This might be correct behavior (only tracking qualified pipeline),")
print("or it might indicate that qualification dates are incomplete/wrong.")
