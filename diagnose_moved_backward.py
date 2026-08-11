#!/usr/bin/env python3
"""
Diagnostic: Find deals counted as moved_backward
"""

import os
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).parent
sys.path.insert(0, str(REPO_ROOT / 'scripts'))

from supabase import create_client
from supabase_client import select_all

SUPABASE_URL = os.getenv('SUPABASE_URL')
SUPABASE_KEY = os.getenv('SUPABASE_SERVICE_KEY')

if not SUPABASE_URL or not SUPABASE_KEY:
    print("⚠️  SUPABASE_URL or SUPABASE_SERVICE_KEY not set")
    exit(1)

sb = create_client(SUPABASE_URL, SUPABASE_KEY)

# Get all snapshot records for both dates
prev_snap = select_all(
    sb, 'deals_snapshot',
    'deal_id, stage_order, deal_value, deal_status',
    filters=[('eq', 'snapshot_date', '2026-08-09')]
)

curr_snap = select_all(
    sb, 'deals_snapshot',
    'deal_id, stage_order, deal_value, deal_status',
    filters=[('eq', 'snapshot_date', '2026-08-11')]
)

# Create lookup dicts
prev_dict = {r['deal_id']: r for r in prev_snap}
curr_dict = {r['deal_id']: r for r in curr_snap}

# Find deals that moved backward
backward_deals = []

for deal_id, curr in curr_dict.items():
    if deal_id not in prev_dict:
        continue

    prev = prev_dict[deal_id]

    # Apply same logic as compute_waterfall.py
    curr_status = curr.get('deal_status', 'active')
    prev_status = prev.get('deal_status', 'active')

    # Skip won/lost deals
    if curr_status in ('won', 'lost') or prev_status in ('won', 'lost'):
        continue

    # Get real stage orders (excluding 0/null)
    curr_order = curr.get('stage_order')
    prev_order = prev.get('stage_order')

    curr_order_real = curr_order if (curr_order or 0) > 0 else None
    prev_order_real = prev_order if (prev_order or 0) > 0 else None

    # Check if both are real and backward movement occurred
    if curr_order_real and prev_order_real:
        if curr_order_real < prev_order_real:
            backward_deals.append({
                'deal_id': deal_id,
                'prev_order': prev_order,
                'curr_order': curr_order,
                'deal_value': curr.get('deal_value', 0)
            })

# Sort by value descending
backward_deals.sort(key=lambda x: x['deal_value'] or 0, reverse=True)

print("Deals Moving Backward (active deals, stage_order > 0):")
print("=" * 80)
print(f"{'Deal ID':<30} {'Prev→Curr':<15} {'Value':>15}")
print("-" * 80)

total_value = 0
for deal in backward_deals[:20]:  # Top 20
    deal_id = str(deal['deal_id'])[:29]
    movement = f"{deal['prev_order']} → {deal['curr_order']}"
    value = deal['deal_value'] or 0
    total_value += value
    print(f"{deal_id:<30} {movement:<15} {value:>15,.0f}")

print("-" * 80)
print(f"Total shown: {len(backward_deals[:20])} deals, ${total_value:,.0f}")
print(f"Total backward: {len(backward_deals)} deals, ${sum(d['deal_value'] or 0 for d in backward_deals):,.0f}")
