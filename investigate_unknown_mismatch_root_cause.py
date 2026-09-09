#!/usr/bin/env python3
"""
Investigate the actual root cause of UNKNOWN group mismatches.

Since boundary crossing is NOT the cause, what is?
"""

import os
from dotenv import load_dotenv

load_dotenv()

from supabase import create_client
SUPABASE_URL = os.getenv('SUPABASE_URL')
SUPABASE_KEY = os.getenv('SUPABASE_SERVICE_KEY')
sb = create_client(SUPABASE_URL, SUPABASE_KEY)

import sys
sys.path.insert(0, 'scripts')
from supabase_client import select_all

print("Investigating root cause of UNKNOWN group mismatches")
print("=" * 70)

# Pick one week to analyze in detail
test_week = '2025-09-29'
prev_week = '2025-09-22'

print(f"\nDetailed analysis: {prev_week} → {test_week}")
print("=" * 70)

# Get waterfall data
wf = sb.table('waterfall_weekly')\
    .select('*')\
    .eq('week_ending', test_week)\
    .eq('region', 'UNKNOWN')\
    .eq('segment', 'Unknown')\
    .execute()

if not wf.data:
    print("No waterfall data found")
    exit(1)

wf_row = wf.data[0]

print(f"\nWaterfall values:")
print(f"  Beginning:        ${wf_row['beginning_value']:,.2f}")
print(f"  New created:      ${wf_row['new_pipeline_value']:,.2f}")
print(f"  Newly qualified:  ${wf_row['newly_qualified_value']:,.2f}")
print(f"  Won:              ${wf_row['won_value']:,.2f}")
print(f"  Lost:             ${wf_row['lost_value']:,.2f}")
print(f"  Net change:       ${wf_row['net_change']:,.2f}")
print(f"  Expected ending:  ${wf_row['beginning_value'] + wf_row['net_change']:,.2f}")
print(f"  Actual ending:    ${wf_row['ending_value']:,.2f}")
print(f"  Mismatch:         ${wf_row['ending_value'] - (wf_row['beginning_value'] + wf_row['net_change']):,.2f}")

# Load both snapshots
prev_snap = select_all(sb, 'deals_snapshot', '*',
                      filters=[('eq', 'snapshot_date', prev_week)])
new_snap = select_all(sb, 'deals_snapshot', '*',
                     filters=[('eq', 'snapshot_date', test_week)])

prev_dict = {d['deal_id']: d for d in prev_snap}
new_dict = {d['deal_id']: d for d in new_snap}

print(f"\nSnapshot sizes:")
print(f"  {prev_week}: {len(prev_snap)} deals")
print(f"  {test_week}: {len(new_snap)} deals")

# Filter to UNKNOWN/Unknown group
prev_unknown = [d for d in prev_snap
                if (d.get('region') or 'UNKNOWN') == 'UNKNOWN'
                and (d.get('segment') or 'Unknown') == 'Unknown'
                and d.get('deal_status') == 'active']

new_unknown = [d for d in new_snap
               if (d.get('region') or 'UNKNOWN') == 'UNKNOWN'
               and (d.get('segment') or 'Unknown') == 'Unknown'
               and d.get('deal_status') == 'active']

print(f"\nUNKNOWN/Unknown group sizes:")
print(f"  {prev_week}: {len(prev_unknown)} deals")
print(f"  {test_week}: {len(new_unknown)} deals")

# Calculate beginning value manually
prev_unknown_ids = set(d['deal_id'] for d in prev_unknown)
new_unknown_ids = set(d['deal_id'] for d in new_unknown)

prev_values = [d.get('deal_value') for d in prev_unknown if d.get('deal_value') is not None]
new_values = [d.get('deal_value') for d in new_unknown if d.get('deal_value') is not None]

manual_beginning = sum(prev_values)
manual_ending = sum(new_values)

print(f"\nManual calculation:")
print(f"  Beginning (sum of prev values): ${manual_beginning:,.2f}")
print(f"  Ending (sum of new values):     ${manual_ending:,.2f}")
print(f"  Difference:                     ${manual_ending - manual_beginning:,.2f}")

print(f"\nComparison to waterfall:")
print(f"  Waterfall beginning: ${wf_row['beginning_value']:,.2f}")
print(f"  Manual beginning:    ${manual_beginning:,.2f}")
print(f"  Difference:          ${abs(wf_row['beginning_value'] - manual_beginning):,.2f}")

print(f"\n  Waterfall ending: ${wf_row['ending_value']:,.2f}")
print(f"  Manual ending:    ${manual_ending:,.2f}")
print(f"  Difference:       ${abs(wf_row['ending_value'] - manual_ending):,.2f}")

# Check if beginning/ending match
if abs(wf_row['beginning_value'] - manual_beginning) < 0.01 and \
   abs(wf_row['ending_value'] - manual_ending) < 0.01:
    print(f"\n✓ Beginning and ending values match manual calculation")
    print(f"  This means the snapshots are correct")
    print(f"  The mismatch must be in the NET CHANGE calculation")
else:
    print(f"\n✗ Beginning or ending values DON'T match manual calculation")
    print(f"  This indicates an issue with snapshot filtering or aggregation")

# Analyze what changed
left_pipeline = prev_unknown_ids - new_unknown_ids
joined_pipeline = new_unknown_ids - prev_unknown_ids
stayed = prev_unknown_ids & new_unknown_ids

print(f"\nPipeline movement:")
print(f"  Left pipeline:   {len(left_pipeline)} deals")
print(f"  Joined pipeline: {len(joined_pipeline)} deals")
print(f"  Stayed:          {len(stayed)} deals")

# Check if any deals left due to region/segment change within UNKNOWN
# (e.g., UNKNOWN/Unknown → UNKNOWN/SMB)
intra_unknown_moves = []
for deal_id in prev_unknown_ids:
    p = prev_dict.get(deal_id)
    n = new_dict.get(deal_id)

    if p and n:
        p_region = p.get('region') or 'UNKNOWN'
        n_region = n.get('region') or 'UNKNOWN'
        p_segment = p.get('segment') or 'Unknown'
        n_segment = n.get('segment') or 'Unknown'

        # Both in UNKNOWN region, but segment changed
        if p_region == 'UNKNOWN' and n_region == 'UNKNOWN' and p_segment != n_segment:
            intra_unknown_moves.append({
                'deal_id': deal_id,
                'prev_segment': p_segment,
                'new_segment': n_segment,
                'value': n.get('deal_value') or p.get('deal_value') or 0
            })

if intra_unknown_moves:
    intra_value = sum(d['value'] for d in intra_unknown_moves)
    print(f"\n  Intra-UNKNOWN segment moves: {len(intra_unknown_moves)} deals (${intra_value:,.0f})")
    print(f"    These deals stayed in UNKNOWN region but changed segment")
    print(f"    This WOULD cause mismatch if they're counted in beginning but not ending")

    for d in intra_unknown_moves[:5]:
        print(f"      {d['deal_id']}: ${d['value']:,.0f} - Unknown→{d['new_segment']}")

# Check value changes for deals that stayed
value_changes = []
for deal_id in stayed:
    p = prev_dict[deal_id]
    n = new_dict[deal_id]

    p_val = p.get('deal_value')
    n_val = n.get('deal_value')

    if p_val is not None and n_val is not None and abs(p_val - n_val) > 0.01:
        value_changes.append({
            'deal_id': deal_id,
            'prev_value': p_val,
            'new_value': n_val,
            'change': n_val - p_val
        })

if value_changes:
    total_change = sum(d['change'] for d in value_changes)
    print(f"\n  Deals with ARR changes: {len(value_changes)} deals")
    print(f"    Total ARR change: ${total_change:,.2f}")
    print(f"    Waterfall arr_change_value: ${wf_row['arr_change_value']:,.2f}")

# Calculate what net_change SHOULD be
expected_net_change = (
    wf_row['new_pipeline_value'] +
    wf_row['newly_qualified_value'] -
    wf_row['won_value'] -
    wf_row['lost_value']
)

actual_delta = manual_ending - manual_beginning

print(f"\n" + "="*70)
print("ROOT CAUSE ANALYSIS:")
print("="*70)

print(f"\nExpected net_change (formula): ${expected_net_change:,.2f}")
print(f"Actual delta (ending - beginning): ${actual_delta:,.2f}")
print(f"Waterfall net_change: ${wf_row['net_change']:,.2f}")

if abs(expected_net_change - wf_row['net_change']) > 0.01:
    print(f"\n✗ NET_CHANGE FORMULA ERROR")
    print(f"  Formula result doesn't match waterfall net_change")
elif abs(actual_delta - expected_net_change) > 0.01:
    print(f"\n✗ MOVEMENT TRACKING ERROR")
    print(f"  Actual delta doesn't match formula (movement categories incomplete)")
    print(f"  Missing: ${abs(actual_delta - expected_net_change):,.2f}")

    if intra_unknown_moves:
        intra_value = sum(d['value'] for d in intra_unknown_moves)
        if abs(intra_value - abs(actual_delta - expected_net_change)) < 1000:
            print(f"\n  ✓ LIKELY CAUSE: Intra-UNKNOWN segment moves (${intra_value:,.0f})")
            print(f"    Deals moving from UNKNOWN/Unknown to UNKNOWN/SMB or UNKNOWN/Mid-Market")
            print(f"    Are counted in beginning but NOT in ending of Unknown segment")
            print(f"    This is SEGMENT boundary crossing within UNKNOWN region")
else:
    print(f"\n✓ No obvious formula error - reconciliation should work")
