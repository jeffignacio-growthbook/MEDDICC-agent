#!/usr/bin/env python3
"""
Trace the specific $206K discrepancy in UNKNOWN/Unknown week 2026-06-29.

Find the EXACT deals causing:
  Expected ending: $8,344,508.45
  Actual ending:   $8,550,508.45
  Mismatch:        +$206,000.00
"""

import os
from datetime import date
from dotenv import load_dotenv

load_dotenv()

from supabase import create_client
SUPABASE_URL = os.getenv('SUPABASE_URL')
SUPABASE_KEY = os.getenv('SUPABASE_SERVICE_KEY')
sb = create_client(SUPABASE_URL, SUPABASE_KEY)

import sys
sys.path.insert(0, 'scripts')
from supabase_client import select_all

print("Tracing $206K discrepancy: UNKNOWN/Unknown week 2026-06-29")
print("=" * 70)

prev_week = '2026-06-22'
test_week = '2026-06-29'

# Load waterfall
wf = sb.table('waterfall_weekly')\
    .select('*')\
    .eq('week_ending', test_week)\
    .eq('region', 'UNKNOWN')\
    .eq('segment', 'Unknown')\
    .execute()

if not wf.data:
    print("No waterfall found")
    exit(1)

wf_row = wf.data[0]

print(f"\nWaterfall (computed by script):")
print(f"  Beginning:       ${wf_row['beginning_value']:,.2f}")
print(f"  Net change:      ${wf_row['net_change']:,.2f}")
print(f"  Expected ending: ${wf_row['beginning_value'] + wf_row['net_change']:,.2f}")
print(f"  Actual ending:   ${wf_row['ending_value']:,.2f}")
print(f"  Mismatch:        ${wf_row['ending_value'] - (wf_row['beginning_value'] + wf_row['net_change']):,.2f}")

# Load snapshots
prev_snap = select_all(sb, 'deals_snapshot', '*',
                      filters=[('eq', 'snapshot_date', prev_week)])
new_snap = select_all(sb, 'deals_snapshot', '*',
                     filters=[('eq', 'snapshot_date', test_week)])

print(f"\nTotal snapshot sizes:")
print(f"  {prev_week}: {len(prev_snap)} deals")
print(f"  {test_week}: {len(new_snap)} deals")

prev_dict = {d['deal_id']: d for d in prev_snap}
new_dict = {d['deal_id']: d for d in new_snap}

# Load qualification and test deal filter
qual_data = select_all(sb, 'deals', 'deal_id, qualified_date, company_name')
qual_map = {d['deal_id']: {'qualified_date': d.get('qualified_date'),
                           'company_name': d.get('company_name')}
            for d in qual_data}

def is_qualified(deal_id, as_of_date_str):
    qd = qual_map.get(deal_id, {}).get('qualified_date')
    if not qd:
        return False
    try:
        return date.fromisoformat(qd) <= date.fromisoformat(as_of_date_str)
    except:
        return False

# Import test deal filter
sys.path.insert(0, 'api')
from field_semantics import is_test_deal

def should_include(deal_id, snapshot_date):
    """Check if deal should be in qualified pipeline for this snapshot."""
    return is_qualified(deal_id, snapshot_date) and \
           not is_test_deal({'company_name': qual_map.get(deal_id, {}).get('company_name')})

# Filter to UNKNOWN/Unknown qualified active deals
prev_unknown = [d for d in prev_snap
                if (d.get('region') or 'UNKNOWN') == 'UNKNOWN'
                and (d.get('segment') or 'Unknown') == 'Unknown'
                and d.get('deal_status') == 'active'
                and should_include(d['deal_id'], prev_week)]

new_unknown = [d for d in new_snap
               if (d.get('region') or 'UNKNOWN') == 'UNKNOWN'
               and (d.get('segment') or 'Unknown') == 'Unknown'
               and d.get('deal_status') == 'active'
               and should_include(d['deal_id'], test_week)]

print(f"\nFiltered UNKNOWN/Unknown qualified active deals:")
print(f"  {prev_week}: {len(prev_unknown)} deals")
print(f"  {test_week}: {len(new_unknown)} deals")

prev_unknown_ids = set(d['deal_id'] for d in prev_unknown)
new_unknown_ids = set(d['deal_id'] for d in new_unknown)

# Calculate beginning and ending with NULL handling
prev_values = [d.get('deal_value') for d in prev_unknown if d.get('deal_value') is not None]
new_values = [d.get('deal_value') for d in new_unknown if d.get('deal_value') is not None]

manual_beginning = sum(prev_values)
manual_ending = sum(new_values)

print(f"\nManual calculation (excluding NULL values):")
print(f"  Beginning: ${manual_beginning:,.2f} ({len(prev_values)} deals with values)")
print(f"  Ending:    ${manual_ending:,.2f} ({len(new_values)} deals with values)")
print(f"  Delta:     ${manual_ending - manual_beginning:,.2f}")

print(f"\nComparison to waterfall:")
print(f"  Waterfall beginning: ${wf_row['beginning_value']:,.2f}")
print(f"  Manual beginning:    ${manual_beginning:,.2f}")
print(f"  Difference:          ${abs(wf_row['beginning_value'] - manual_beginning):,.2f}")

print(f"\n  Waterfall ending: ${wf_row['ending_value']:,.2f}")
print(f"  Manual ending:    ${manual_ending:,.2f}")
print(f"  Difference:       ${abs(wf_row['ending_value'] - manual_ending):,.2f}")

if abs(wf_row['beginning_value'] - manual_beginning) < 1.0 and \
   abs(wf_row['ending_value'] - manual_ending) < 1.0:
    print(f"\n✓ Beginning and ending match - snapshot filtering is correct")
    print(f"  Issue must be in NET CHANGE computation")
else:
    print(f"\n✗ Beginning or ending DON'T match - snapshot filtering issue")

# Now trace the $206K discrepancy
print(f"\n" + "="*70)
print("TRACING THE $206K DISCREPANCY")
print("="*70)

# The discrepancy is: actual ending - expected ending = +$206K
# Expected: beginning + net_change = $8,344,508.45
# Actual: $8,550,508.45
# So actual is $206K higher than expected

# This could be:
# 1. Net_change is too LOW (missing positive movements)
# 2. Ending is too HIGH (includes deals it shouldn't)
# 3. Beginning is too LOW (excludes deals it should)

actual_delta = manual_ending - manual_beginning
expected_net_change = wf_row['net_change']

print(f"\nActual delta (ending - beginning): ${actual_delta:,.2f}")
print(f"Waterfall net_change:              ${expected_net_change:,.2f}")
print(f"Difference:                        ${actual_delta - expected_net_change:,.2f}")

if abs(actual_delta - expected_net_change) > 1000:
    print(f"\n✗ NET_CHANGE IS WRONG")
    print(f"  The waterfall is not capturing ${abs(actual_delta - expected_net_change):,.2f} of movement")
    print(f"  Let me trace what movements are missing...")

    # Check waterfall components
    print(f"\n  Waterfall components:")
    print(f"    New pipeline:     ${wf_row['new_pipeline_value']:,.2f}")
    print(f"    Newly qualified:  ${wf_row['newly_qualified_value']:,.2f}")
    print(f"    Won:              ${wf_row['won_value']:,.2f}")
    print(f"    Lost:             ${wf_row['lost_value']:,.2f}")
    print(f"    Pulled in:        ${wf_row['pulled_in_value']:,.2f}")
    print(f"    Pushed out:       ${wf_row['pushed_out_value']:,.2f}")
    print(f"    ARR change:       ${wf_row['arr_change_value']:,.2f}")

    captured_movement = (
        wf_row['new_pipeline_value'] +
        wf_row['newly_qualified_value'] -
        wf_row['won_value'] -
        wf_row['lost_value']
    )

    print(f"\n  Formula (new + qualified - won - lost): ${captured_movement:,.2f}")
    print(f"  Actual delta: ${actual_delta:,.2f}")
    print(f"  Gap: ${actual_delta - captured_movement:,.2f}")

# Find specific deals that moved
left = prev_unknown_ids - new_unknown_ids
joined = new_unknown_ids - prev_unknown_ids
stayed = prev_unknown_ids & new_unknown_ids

print(f"\nPipeline movement:")
print(f"  Left:   {len(left)} deals")
print(f"  Joined: {len(joined)} deals")
print(f"  Stayed: {len(stayed)} deals")

# Check deals that joined - were they captured as "new" or "newly_qualified"?
if joined:
    print(f"\n  Analyzing {len(joined)} deals that joined...")

    joined_not_captured = []
    for deal_id in joined:
        n = new_dict[deal_id]
        value = n.get('deal_value')

        # Check if this deal was in prev snapshot at all
        was_in_prev = deal_id in prev_dict

        # Check if qualified this week
        prev_qualified = is_qualified(deal_id, prev_week)
        new_qualified = is_qualified(deal_id, test_week)

        # This deal should be captured as either:
        # 1. "new" if not in prev snapshot
        # 2. "newly_qualified" if was in prev but not qualified

        if not was_in_prev:
            category = "new"
        elif not prev_qualified and new_qualified:
            category = "newly_qualified"
        else:
            category = "UNCAPTURED"
            joined_not_captured.append({
                'deal_id': deal_id,
                'value': value,
                'was_in_prev': was_in_prev,
                'prev_qualified': prev_qualified,
                'new_qualified': new_qualified,
                'prev_region': prev_dict.get(deal_id, {}).get('region'),
                'new_region': n.get('region')
            })

    if joined_not_captured:
        total_uncaptured = sum(d['value'] or 0 for d in joined_not_captured)
        print(f"\n  ⚠️  Found {len(joined_not_captured)} deals that joined but weren't captured")
        print(f"      Total value: ${total_uncaptured:,.0f}")

        if abs(total_uncaptured - 206000) < 1000:
            print(f"\n  ✓ THIS EXPLAINS THE $206K DISCREPANCY!")

        print(f"\n      Analyzing first 5:")
        for d in joined_not_captured[:5]:
            print(f"\n        Deal {d['deal_id']}: ${d['value']:,.0f}")
            print(f"          Was in prev snapshot: {d['was_in_prev']}")
            print(f"          Qualified at prev week: {d['prev_qualified']}")
            print(f"          Qualified at test week: {d['new_qualified']}")
            print(f"          Region prev: {d['prev_region']}")
            print(f"          Region new: {d['new_region']}")

            # Get more detail
            if d['was_in_prev']:
                p = prev_dict[d['deal_id']]
                print(f"          Previous snapshot values:")
                print(f"            Region: {p.get('region')}")
                print(f"            Segment: {p.get('segment')}")
                print(f"            Status: {p.get('deal_status')}")
                print(f"            Value: {p.get('deal_value')}")

print(f"\n" + "="*70)
print("ROOT CAUSE SUMMARY:")
print("="*70)

if joined_not_captured:
    print(f"✓ FOUND THE ROOT CAUSE")
    print(f"  {len(joined_not_captured)} deals joined the UNKNOWN/Unknown qualified pipeline")
    print(f"  but were NOT captured in any waterfall movement category")
    print(f"  Total value: ${sum(d['value'] or 0 for d in joined_not_captured):,.0f}")
    print(f"\n  These deals:")
    print(f"    - Were in the previous snapshot")
    print(f"    - Were already qualified at previous week")
    print(f"    - But were NOT in the UNKNOWN/Unknown group at previous week")
    print(f"    - Moved INTO UNKNOWN/Unknown by test week")
    print(f"\n  This is INTRA-SNAPSHOT SEGMENT/REGION BOUNDARY CROSSING")
    print(f"  (NOT crossing in/out of UNKNOWN region, but crossing in/out of")
    print(f"   the UNKNOWN/Unknown segment combination specifically)")
else:
    print(f"Root cause not yet identified - need deeper investigation")
