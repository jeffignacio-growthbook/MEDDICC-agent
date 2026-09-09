#!/usr/bin/env python3
"""Trace the $830K that vanished from UNKNOWN/Unknown between Aug 24-28."""

import os
from pathlib import Path
from dotenv import load_dotenv

load_dotenv()
REPO_ROOT = Path(__file__).parent

from supabase import create_client
import sys
sys.path.insert(0, str(REPO_ROOT / 'scripts'))
from supabase_client import select_all

SUPABASE_URL = os.getenv('SUPABASE_URL')
SUPABASE_KEY = os.getenv('SUPABASE_SERVICE_KEY')
sb = create_client(SUPABASE_URL, SUPABASE_KEY)

# Load snapshots
prev_snap = select_all(sb, 'deals_snapshot', '*',
                       filters=[('eq', 'snapshot_date', '2026-08-24')])
new_snap = select_all(sb, 'deals_snapshot', '*',
                      filters=[('eq', 'snapshot_date', '2026-08-28')])

prev_dict = {d['deal_id']: d for d in prev_snap}
new_dict = {d['deal_id']: d for d in new_snap}

# Load qualification data
deals = select_all(sb, 'deals', 'deal_id, qualified_date')
qual_map = {d['deal_id']: d.get('qualified_date') for d in deals}

# Find deals in Aug 24 but not Aug 28
prev_ids = set(prev_dict.keys())
new_ids = set(new_dict.keys())

left_pipeline = prev_ids - new_ids
joined_pipeline = new_ids - prev_ids
stayed = prev_ids & new_ids

print(f"Pipeline movement Aug 24 → Aug 28:")
print(f"  Deals in Aug 24: {len(prev_ids)}")
print(f"  Deals in Aug 28: {len(new_ids)}")
print(f"  Left pipeline: {len(left_pipeline)}")
print(f"  Joined pipeline: {len(joined_pipeline)}")
print(f"  Stayed: {len(stayed)}")

# Calculate value of deals that left
left_value = sum(prev_dict[deal_id].get('deal_value') or 0
                 for deal_id in left_pipeline)
joined_value = sum(new_dict[deal_id].get('deal_value') or 0
                   for deal_id in joined_pipeline)

print(f"\nValue impact:")
print(f"  Left pipeline: ${left_value:,.2f}")
print(f"  Joined pipeline: ${joined_value:,.2f}")
print(f"  Net: ${joined_value - left_value:,.2f}")

# Check deals that stayed but changed value
value_changers = []
for deal_id in stayed:
    prev_val = prev_dict[deal_id].get('deal_value') or 0
    new_val = new_dict[deal_id].get('deal_value') or 0
    if abs(prev_val - new_val) > 0.01:
        value_changers.append({
            'deal_id': deal_id,
            'prev_value': prev_val,
            'new_value': new_val,
            'change': new_val - prev_val
        })

if value_changers:
    total_change = sum(d['change'] for d in value_changers)
    print(f"\nDeals that changed value: {len(value_changers)}")
    print(f"  Total ARR change: ${total_change:,.2f}")

    print(f"\n  Top 5 changes:")
    for d in sorted(value_changers, key=lambda x: abs(x['change']), reverse=True)[:5]:
        print(f"    Deal {d['deal_id']}: ${d['prev_value']:,.0f} → ${d['new_value']:,.0f} ({d['change']:+,.0f})")

# Check qualification status
print(f"\nQualification check for deals that left:")
qual_count = 0
unqual_count = 0
for deal_id in list(left_pipeline)[:10]:
    qual_date = qual_map.get(deal_id)
    if qual_date:
        qual_count += 1
    else:
        unqual_count += 1

print(f"  Sample of 10 deals that left:")
print(f"    Had qualified_date: {qual_count}")
print(f"    No qualified_date: {unqual_count}")

# Calculate total discrepancy
prev_total = sum(d.get('deal_value') or 0 for d in prev_snap)
new_total = sum(d.get('deal_value') or 0 for d in new_snap)

print(f"\n" + "=" * 70)
print(f"Reconciliation summary:")
print(f"  Aug 24 total value: ${prev_total:,.2f}")
print(f"  Aug 28 total value: ${new_total:,.2f}")
print(f"  Actual change: ${new_total - prev_total:,.2f}")
print(f"  Reported mismatch: $-830,000.00")
print(f"\nExpected reconciliation:")
print(f"  Beginning: ${prev_total:,.2f}")
print(f"  - Left: ${-left_value:,.2f}")
print(f"  + Joined: ${joined_value:,.2f}")
print(f"  +/- ARR changes: ${sum(d['change'] for d in value_changers) if value_changers else 0:,.2f}")
print(f"  = Expected ending: ${prev_total - left_value + joined_value + (sum(d['change'] for d in value_changers) if value_changers else 0):,.2f}")
print(f"  Actual ending: ${new_total:,.2f}")
