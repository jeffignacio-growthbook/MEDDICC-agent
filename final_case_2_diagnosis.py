#!/usr/bin/env python3
"""
Final diagnosis of Case 2: EMEA/Mid-Market week 2026-05-25 (-$40K mismatch)
Focus only on the 12 QUALIFIED deals that waterfall tracks.
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

print("Final Case 2 Diagnosis: Qualified EMEA/Mid-Market deals only")
print("=" * 70)

prev_week = '2026-05-18'
test_week = '2026-05-25'
region = 'EMEA'
segment = 'Mid-Market'

# Load data
prev_snap = select_all(sb, 'deals_snapshot', '*',
                      filters=[('eq', 'snapshot_date', prev_week)])
new_snap = select_all(sb, 'deals_snapshot', '*',
                     filters=[('eq', 'snapshot_date', test_week)])

qual_data = select_all(sb, 'deals', 'deal_id,qualified_date')
qual_map = {d['deal_id']: d.get('qualified_date') for d in qual_data}

prev_dict = {d['deal_id']: d for d in prev_snap}
new_dict = {d['deal_id']: d for d in new_snap}

# Filter to qualified EMEA/Mid-Market deals (EXACT waterfall logic)
def qualified_active(snap, snapshot_date):
    deals = []
    for d in snap:
        if ((d.get('region') or 'UNKNOWN') == region and
            (d.get('segment') or 'Unknown') == segment and
            d.get('deal_status') == 'active'):

            deal_id = d['deal_id']
            qual_date = qual_map.get(deal_id)

            # Check if qualified as of snapshot_date
            if qual_date and qual_date <= snapshot_date:
                deals.append(d)

    return deals

prev_qualified = qualified_active(prev_snap, prev_week)
new_qualified = qualified_active(new_snap, test_week)

prev_ids = set(d['deal_id'] for d in prev_qualified)
new_ids = set(d['deal_id'] for d in new_qualified)

print(f"Prev week ({prev_week}): {len(prev_qualified)} qualified deals")
print(f"New week ({test_week}): {len(new_qualified)} qualified deals")
print()

# Calculate beginning/ending values
prev_total = sum(d.get('deal_value') or 0 for d in prev_qualified)
new_total = sum(d.get('deal_value') or 0 for d in new_qualified)

print(f"Beginning value: ${prev_total:,.2f}")
print(f"Ending value: ${new_total:,.2f}")
print(f"Actual delta: ${new_total - prev_total:,.2f}")
print()

# Trace movements
stayed = prev_ids & new_ids
entered = new_ids - prev_ids
exited = prev_ids - new_ids

print(f"Stayed: {len(stayed)}")
print(f"Entered: {len(entered)}")
print(f"Exited: {len(exited)}")
print()

# Exited deals
print("EXITED qualified deals:")
print("-" * 70)
exited_total = 0
for deal_id in exited:
    p = prev_dict[deal_id]
    value = p.get('deal_value') or 0
    exited_total += value

    n = new_dict.get(deal_id)
    if n:
        print(f"  {deal_id}: ${value:,.0f} → {n.get('region')}/{n.get('segment')}, status={n.get('deal_status')}")
    else:
        print(f"  {deal_id}: ${value:,.0f} → DISAPPEARED from snapshot")

        # Check deals table
        deal_data = select_all(sb, 'deals', 'deal_id,deal_status,close_date',
                              filters=[('eq', 'deal_id', deal_id)])
        if deal_data:
            d = deal_data[0]
            print(f"      Deals table: status={d.get('deal_status')}, close={d.get('close_date')}")

print(f"\nTotal exited value: ${exited_total:,.2f}")

# ARR changes in stayed deals
print()
print("ARR CHANGES in stayed qualified deals:")
print("-" * 70)
arr_total = 0
for deal_id in stayed:
    p = prev_dict[deal_id]
    n = new_dict[deal_id]

    delta, category = arr_delta(deal_id, p, n)

    if delta is not None and abs(delta) > 0.01:
        arr_total += delta
        print(f"  {deal_id}: ${p.get('deal_value'):,.0f} → ${n.get('deal_value'):,.0f} = ${delta:,.0f} ({category})")

if arr_total == 0:
    print("  None")

print(f"\nTotal ARR change: ${arr_total:,.2f}")

# Entered deals
print()
print("ENTERED qualified deals:")
print("-" * 70)
entered_total = 0
for deal_id in entered:
    n = new_dict[deal_id]
    value = n.get('deal_value') or 0
    entered_total += value

    p = prev_dict.get(deal_id)
    if p:
        print(f"  {deal_id}: ${value:,.0f} (was {p.get('region')}/{p.get('segment')})")
    else:
        print(f"  {deal_id}: ${value:,.0f} (new to snapshots)")

print(f"\nTotal entered value: ${entered_total:,.2f}")

print()
print("=" * 70)
print("RECONCILIATION")
print("=" * 70)
print(f"Beginning: ${prev_total:,.2f}")
print(f"Entered: +${entered_total:,.2f}")
print(f"Exited: -${exited_total:,.2f}")
print(f"ARR changes: ${arr_total:+,.2f}")
print(f"Expected ending: ${prev_total + entered_total - exited_total + arr_total:,.2f}")
print(f"Actual ending: ${new_total:,.2f}")
print(f"Mismatch: ${new_total - (prev_total + entered_total - exited_total + arr_total):,.2f}")

print()
print("ROOT CAUSES:")
print("1. Phantom exits (deals missing from snapshot): ${:,.2f}".format(
    sum(p.get('deal_value') or 0 for deal_id in exited if deal_id not in new_dict)
))
print("2. Won/lost not detected: Check if any exited deals should be in won/lost_value")
