#!/usr/bin/env python3
"""
Investigate the 2 remaining reconciliation mismatches:
1. default/ROW/SMB week 2026-04-13: $20,000 difference
2. default/EMEA/Mid-Market week 2026-05-25: $40,000 difference
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
from arr_delta import arr_delta

print("Investigating 2 remaining reconciliation mismatches")
print("=" * 70)

# Case 1: default/ROW/SMB week 2026-04-13 (diff: -$20,000)
print("\nCase 1: default/ROW/SMB week 2026-04-13")
print("-" * 70)

prev_week_1 = '2026-04-06'
test_week_1 = '2026-04-13'
region_1 = 'ROW'
segment_1 = 'SMB'

# Load snapshots
prev_snap_1 = select_all(sb, 'deals_snapshot', '*',
                         filters=[('eq', 'snapshot_date', prev_week_1)])
new_snap_1 = select_all(sb, 'deals_snapshot', '*',
                        filters=[('eq', 'snapshot_date', test_week_1)])

prev_dict_1 = {d['deal_id']: d for d in prev_snap_1}
new_dict_1 = {d['deal_id']: d for d in new_snap_1}

# Filter to this group
def in_group_1(snap):
    return [d for d in snap
            if (d.get('region') or 'UNKNOWN') == region_1
            and (d.get('segment') or 'Unknown') == segment_1]

prev_group_1 = in_group_1(prev_snap_1)
new_group_1 = in_group_1(new_snap_1)

print(f"Prev week deals: {len(prev_group_1)}")
print(f"New week deals: {len(new_group_1)}")

# Calculate expected ending value
prev_total_1 = sum(d.get('deal_value') or 0 for d in prev_group_1)
new_total_1 = sum(d.get('deal_value') or 0 for d in new_group_1)

print(f"\nBeginning value: ${prev_total_1:,.2f}")
print(f"Ending value: ${new_total_1:,.2f}")
print(f"Difference: ${new_total_1 - prev_total_1:,.2f}")

# Trace all movements
prev_ids_1 = set(d['deal_id'] for d in prev_group_1)
new_ids_1 = set(d['deal_id'] for d in new_group_1)
stayed_1 = prev_ids_1 & new_ids_1
entered_1 = new_ids_1 - prev_ids_1
exited_1 = prev_ids_1 - new_ids_1

print(f"\nDeal movements:")
print(f"  Stayed: {len(stayed_1)}")
print(f"  Entered: {len(entered_1)}")
print(f"  Exited: {len(exited_1)}")

# Check for won/lost in exited deals
print(f"\nExited deals (potential won/lost):")
for deal_id in list(exited_1)[:5]:  # Show first 5
    p = prev_dict_1.get(deal_id)
    n = new_dict_1.get(deal_id)

    if p and n:
        print(f"  {deal_id}:")
        print(f"    Prev: value=${p.get('deal_value')}, status={p.get('deal_status')}, region={p.get('region')}, segment={p.get('segment')}")
        print(f"    New:  value=${n.get('deal_value')}, status={n.get('deal_status')}, region={n.get('region')}, segment={n.get('segment')}")

        # Check if deal actually left the group (region/segment changed) or closed won/lost
        if n.get('deal_status') in ('won', 'lost'):
            print(f"    → Deal closed {n.get('deal_status')}")
        elif n.get('region') != p.get('region') or n.get('segment') != p.get('segment'):
            print(f"    → Deal moved to {n.get('region')}/{n.get('segment')}")

# Check for ARR changes in stayed deals
print(f"\nARR changes in stayed deals:")
arr_changes_1 = []
for deal_id in stayed_1:
    p = prev_dict_1[deal_id]
    n = new_dict_1[deal_id]

    delta, category = arr_delta(deal_id, p, n)

    if delta is not None and abs(delta) > 0.01:
        arr_changes_1.append({
            'deal_id': deal_id,
            'delta': delta,
            'category': category,
            'prev_value': p.get('deal_value'),
            'new_value': n.get('deal_value')
        })

if arr_changes_1:
    print(f"Found {len(arr_changes_1)} deals with ARR changes:")
    for d in arr_changes_1:
        print(f"  {d['deal_id']}: ${d['prev_value']:,.0f} → ${d['new_value']:,.0f} = ${d['delta']:,.0f} ({d['category']})")
else:
    print("No ARR changes detected")

print("\n" + "=" * 70)
print()

# Case 2: default/EMEA/Mid-Market week 2026-05-25 (diff: -$40,000)
print("Case 2: default/EMEA/Mid-Market week 2026-05-25")
print("-" * 70)

prev_week_2 = '2026-05-18'
test_week_2 = '2026-05-25'
region_2 = 'EMEA'
segment_2 = 'Mid-Market'

# Load snapshots
prev_snap_2 = select_all(sb, 'deals_snapshot', '*',
                         filters=[('eq', 'snapshot_date', prev_week_2)])
new_snap_2 = select_all(sb, 'deals_snapshot', '*',
                        filters=[('eq', 'snapshot_date', test_week_2)])

prev_dict_2 = {d['deal_id']: d for d in prev_snap_2}
new_dict_2 = {d['deal_id']: d for d in new_snap_2}

# Filter to this group
def in_group_2(snap):
    return [d for d in snap
            if (d.get('region') or 'UNKNOWN') == region_2
            and (d.get('segment') or 'Unknown') == segment_2]

prev_group_2 = in_group_2(prev_snap_2)
new_group_2 = in_group_2(new_snap_2)

print(f"Prev week deals: {len(prev_group_2)}")
print(f"New week deals: {len(new_group_2)}")

# Calculate expected ending value
prev_total_2 = sum(d.get('deal_value') or 0 for d in prev_group_2)
new_total_2 = sum(d.get('deal_value') or 0 for d in new_group_2)

print(f"\nBeginning value: ${prev_total_2:,.2f}")
print(f"Ending value: ${new_total_2:,.2f}")
print(f"Difference: ${new_total_2 - prev_total_2:,.2f}")

# Trace all movements
prev_ids_2 = set(d['deal_id'] for d in prev_group_2)
new_ids_2 = set(d['deal_id'] for d in new_group_2)
stayed_2 = prev_ids_2 & new_ids_2
entered_2 = new_ids_2 - prev_ids_2
exited_2 = prev_ids_2 - new_ids_2

print(f"\nDeal movements:")
print(f"  Stayed: {len(stayed_2)}")
print(f"  Entered: {len(entered_2)}")
print(f"  Exited: {len(exited_2)}")

# Check for won/lost in exited deals
print(f"\nExited deals (potential won/lost):")
for deal_id in list(exited_2)[:5]:  # Show first 5
    p = prev_dict_2.get(deal_id)
    n = new_dict_2.get(deal_id)

    if p and n:
        print(f"  {deal_id}:")
        print(f"    Prev: value=${p.get('deal_value')}, status={p.get('deal_status')}, region={p.get('region')}, segment={p.get('segment')}")
        print(f"    New:  value=${n.get('deal_value')}, status={n.get('deal_status')}, region={n.get('region')}, segment={n.get('segment')}")

        # Check if deal actually left the group (region/segment changed) or closed won/lost
        if n.get('deal_status') in ('won', 'lost'):
            print(f"    → Deal closed {n.get('deal_status')}")
        elif n.get('region') != p.get('region') or n.get('segment') != p.get('segment'):
            print(f"    → Deal moved to {n.get('region')}/{n.get('segment')}")

# Check for ARR changes in stayed deals
print(f"\nARR changes in stayed deals:")
arr_changes_2 = []
for deal_id in stayed_2:
    p = prev_dict_2[deal_id]
    n = new_dict_2[deal_id]

    delta, category = arr_delta(deal_id, p, n)

    if delta is not None and abs(delta) > 0.01:
        arr_changes_2.append({
            'deal_id': deal_id,
            'delta': delta,
            'category': category,
            'prev_value': p.get('deal_value'),
            'new_value': n.get('deal_value')
        })

if arr_changes_2:
    print(f"Found {len(arr_changes_2)} deals with ARR changes:")
    for d in arr_changes_2:
        print(f"  {d['deal_id']}: ${d['prev_value']:,.0f} → ${d['new_value']:,.0f} = ${d['delta']:,.0f} ({d['category']})")
else:
    print("No ARR changes detected")

print("\n" + "=" * 70)
print("SUMMARY")
print("=" * 70)
print("These 2 cases need detailed movement tracing to identify the gap")
