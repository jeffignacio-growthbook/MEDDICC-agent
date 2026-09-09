#!/usr/bin/env python3
"""
Trace Case 2: EMEA/Mid-Market week 2026-05-25 (-$40K mismatch)
Same rigor as Case 1 - identify specific deals, confirm pattern.
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

print("Tracing Case 2: EMEA/Mid-Market week 2026-05-25 (-$40K mismatch)")
print("=" * 70)

prev_week = '2026-05-18'
test_week = '2026-05-25'
region = 'EMEA'
segment = 'Mid-Market'

# Load snapshots
prev_snap = select_all(sb, 'deals_snapshot', '*',
                      filters=[('eq', 'snapshot_date', prev_week)])
new_snap = select_all(sb, 'deals_snapshot', '*',
                     filters=[('eq', 'snapshot_date', test_week)])

prev_dict = {d['deal_id']: d for d in prev_snap}
new_dict = {d['deal_id']: d for d in new_snap}

# Load waterfall to see what it computed
waterfall = select_all(sb, 'waterfall_weekly', '*',
                      filters=[
                          ('eq', 'week_ending', test_week),
                          ('eq', 'region', region),
                          ('eq', 'segment', segment)
                      ])

if waterfall:
    wf = waterfall[0]
    print(f"Waterfall computed:")
    print(f"  Beginning: ${wf['beginning_value']:,.2f}")
    print(f"  Ending: ${wf['ending_value']:,.2f}")
    print(f"  Net change: ${wf['net_change']:,.2f}")
    print(f"  Expected ending: ${wf['beginning_value'] + wf['net_change']:,.2f}")
    print(f"  Mismatch: ${wf['ending_value'] - (wf['beginning_value'] + wf['net_change']):,.2f}")
    print()
    print(f"  Movements:")
    print(f"    New pipeline: ${wf.get('new_pipeline_value', 0):,.2f}")
    print(f"    Newly qualified: ${wf.get('newly_qualified_value', 0):,.2f}")
    print(f"    Newly ARR-bearing: ${wf.get('newly_arr_bearing_value', 0):,.2f}")
    print(f"    Won: ${wf.get('won_value', 0):,.2f}")
    print(f"    Lost: ${wf.get('lost_value', 0):,.2f}")
    print(f"    ARR change: ${wf.get('arr_change_value', 0):,.2f}")
    print(f"    Pulled in: ${wf.get('pulled_in_value', 0):,.2f}")
    print(f"    Pushed out: ${wf.get('pushed_out_value', 0):,.2f}")
else:
    print("No waterfall row found")

print()
print("=" * 70)
print("Actual snapshot values:")
print("-" * 70)

# Filter to EMEA/Mid-Market active, qualified deals (same as waterfall logic)
def in_group(snap):
    return [d for d in snap
            if (d.get('region') or 'UNKNOWN') == region
            and (d.get('segment') or 'Unknown') == segment
            and d.get('deal_status') == 'active']

prev_group = in_group(prev_snap)
new_group = in_group(new_snap)

prev_total = sum(d.get('deal_value') or 0 for d in prev_group)
new_total = sum(d.get('deal_value') or 0 for d in new_group)

print(f"Prev week ({prev_week}): {len(prev_group)} deals, ${prev_total:,.2f}")
print(f"New week ({test_week}): {len(new_group)} deals, ${new_total:,.2f}")
print(f"Actual delta: ${new_total - prev_total:,.2f}")
print()

# Compare with waterfall beginning/ending
if waterfall:
    print(f"Waterfall beginning vs actual prev: ${wf['beginning_value']:,.2f} vs ${prev_total:,.2f}")
    print(f"Difference: ${abs(wf['beginning_value'] - prev_total):,.2f}")
    print()
    print(f"Waterfall ending vs actual new: ${wf['ending_value']:,.2f} vs ${new_total:,.2f}")
    print(f"Difference: ${abs(wf['ending_value'] - new_total):,.2f}")

print()
print("=" * 70)
print("Deal movements:")
print("-" * 70)

prev_ids = set(d['deal_id'] for d in prev_group)
new_ids = set(d['deal_id'] for d in new_group)
stayed = prev_ids & new_ids
entered = new_ids - prev_ids
exited = prev_ids - new_ids

print(f"Stayed: {len(stayed)} deals")
print(f"Entered: {len(entered)} deals")
print(f"Exited: {len(exited)} deals")

# Check ARR changes in stayed deals
print()
print("ARR changes in stayed deals:")
arr_changes = []
for deal_id in stayed:
    p = prev_dict[deal_id]
    n = new_dict[deal_id]

    delta, category = arr_delta(deal_id, p, n)

    if delta is not None and abs(delta) > 0.01:
        arr_changes.append({
            'deal_id': deal_id,
            'delta': delta,
            'category': category,
            'prev_value': p.get('deal_value'),
            'new_value': n.get('deal_value')
        })

if arr_changes:
    total_arr_delta = sum(d['delta'] for d in arr_changes)
    print(f"Found {len(arr_changes)} deals with ARR changes (total: ${total_arr_delta:,.2f}):")
    for d in arr_changes:
        print(f"  {d['deal_id']}: ${d['prev_value']:,.0f} → ${d['new_value']:,.0f} = ${d['delta']:,.0f} ({d['category']})")
else:
    print("No ARR changes detected")

# Check entered deals
print()
print("Entered deals (new to this group):")
entered_total = 0
for deal_id in list(entered)[:10]:  # Show first 10
    n = new_dict[deal_id]
    value = n.get('deal_value') or 0
    entered_total += value
    p = prev_dict.get(deal_id)

    if p:
        print(f"  {deal_id}: ${value:,.0f} (was {p.get('region')}/{p.get('segment')})")
    else:
        print(f"  {deal_id}: ${value:,.0f} (new to snapshots)")

if len(entered) > 10:
    print(f"  ... and {len(entered) - 10} more")

print(f"Total entered value: ${entered_total:,.2f}")

# Check exited deals
print()
print("Exited deals (left this group):")
exited_total = 0
exited_phantom = []
for deal_id in exited:
    p = prev_dict[deal_id]
    value = p.get('deal_value') or 0
    exited_total += value

    n = new_dict.get(deal_id)

    if n:
        print(f"  {deal_id}: ${value:,.0f} → moved to {n.get('region')}/{n.get('segment')}, status={n.get('deal_status')}")
    else:
        print(f"  {deal_id}: ${value:,.0f} → DISAPPEARED from snapshot")
        exited_phantom.append((deal_id, value))

print(f"Total exited value: ${exited_total:,.2f}")

if exited_phantom:
    print()
    print(f"WARNING: {len(exited_phantom)} deals DISAPPEARED from snapshot:")
    for deal_id, value in exited_phantom:
        print(f"  {deal_id}: ${value:,.0f}")

    # Check these deals in deals table
    print()
    print("Checking disappeared deals in deals table:")
    phantom_ids = [deal_id for deal_id, _ in exited_phantom]
    deals_data = select_all(sb, 'deals', 'deal_id,deal_status,close_date,stage,deal_value',
                            filters=[('in_', 'deal_id', phantom_ids)])

    for d in deals_data:
        print(f"  {d['deal_id']}: status={d.get('deal_status')}, close={d.get('close_date')}, value=${d.get('deal_value') or 0:,.0f}")

    # Check snapshot history for each phantom deal
    print()
    print("Checking snapshot history for phantom deals:")
    for deal_id, value in exited_phantom:
        snapshots = select_all(sb, 'deals_snapshot', 'snapshot_date,deal_value,deal_status,region,segment',
                              filters=[('eq', 'deal_id', deal_id)])

        # Show snapshots around the test week
        relevant = [s for s in snapshots if '2026-05' in s['snapshot_date'] or '2026-04' in s['snapshot_date']]
        if relevant:
            print(f"\n  Deal {deal_id}:")
            for s in sorted(relevant, key=lambda x: x['snapshot_date']):
                print(f"    {s['snapshot_date']}: value=${s.get('deal_value') or 0:,.0f}, status={s.get('deal_status')}, {s.get('region')}/{s.get('segment')}")

print()
print("=" * 70)
print("DIAGNOSIS")
print("=" * 70)
print("Check if this is:")
print("  1. Phantom exit pattern (deals missing from snapshot) - same as Case 1")
print("  2. Different pattern (moved groups, won/lost not detected, etc.)")
print()
print("The -$40K mismatch needs to be fully accounted for by specific deal movements")
