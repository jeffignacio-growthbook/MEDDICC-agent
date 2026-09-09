#!/usr/bin/env python3
"""
Trace the specific 2 deals that joined UNKNOWN/Unknown in week 2026-06-29.
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

prev_week = '2026-06-22'
test_week = '2026-06-29'

# Load snapshots
prev_snap = select_all(sb, 'deals_snapshot', '*',
                      filters=[('eq', 'snapshot_date', prev_week)])
new_snap = select_all(sb, 'deals_snapshot', '*',
                     filters=[('eq', 'snapshot_date', test_week)])

prev_dict = {d['deal_id']: d for d in prev_snap}
new_dict = {d['deal_id']: d for d in new_snap}

# Load qualification data
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

sys.path.insert(0, 'api')
from field_semantics import is_test_deal

def should_include(deal_id, snapshot_date):
    return is_qualified(deal_id, snapshot_date) and \
           not is_test_deal({'company_name': qual_map.get(deal_id, {}).get('company_name')})

# Get UNKNOWN/Unknown deals in each snapshot
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

prev_ids = set(d['deal_id'] for d in prev_unknown)
new_ids = set(d['deal_id'] for d in new_unknown)

joined = new_ids - prev_ids

print(f"2 deals that joined UNKNOWN/Unknown group:")
print("=" * 70)

for deal_id in joined:
    n = new_dict[deal_id]
    p = prev_dict.get(deal_id)

    print(f"\nDeal {deal_id}:")
    print(f"  Value: ${n.get('deal_value'):,.0f}" if n.get('deal_value') else "  Value: NULL")

    print(f"\n  Previous snapshot ({prev_week}):")
    if p:
        print(f"    In snapshot: YES")
        print(f"    Region: {p.get('region')}")
        print(f"    Segment: {p.get('segment')}")
        print(f"    Status: {p.get('deal_status')}")
        print(f"    Value: {p.get('deal_value')}")
        print(f"    Qualified: {is_qualified(deal_id, prev_week)}")

        # Check why it wasn't in prev UNKNOWN/Unknown
        is_unknown_region = (p.get('region') or 'UNKNOWN') == 'UNKNOWN'
        is_unknown_segment = (p.get('segment') or 'Unknown') == 'Unknown'
        is_active = p.get('deal_status') == 'active'
        is_qual = is_qualified(deal_id, prev_week)
        not_test = not is_test_deal({'company_name': qual_map.get(deal_id, {}).get('company_name')})

        print(f"\n    Why not in prev UNKNOWN/Unknown group?")
        print(f"      Region='UNKNOWN': {is_unknown_region}")
        print(f"      Segment='Unknown': {is_unknown_segment}")
        print(f"      Status='active': {is_active}")
        print(f"      Qualified: {is_qual}")
        print(f"      Not test deal: {not_test}")

        if not is_unknown_segment:
            print(f"      → Was in UNKNOWN/{p.get('segment')} (different segment)")
        elif not is_unknown_region:
            print(f"      → Was in {p.get('region')}/Unknown (different region)")
    else:
        print(f"    In snapshot: NO")
        print(f"    This is a NEW deal (should be captured as 'new')")

    print(f"\n  New snapshot ({test_week}):")
    print(f"    Region: {n.get('region')}")
    print(f"    Segment: {n.get('segment')}")
    print(f"    Status: {n.get('deal_status')}")
    print(f"    Value: {n.get('deal_value')}")
    print(f"    Qualified: {is_qualified(deal_id, test_week)}")

    # Determine what category this should be in
    if not p:
        category = "NEW (created this week)"
    elif not is_qualified(deal_id, prev_week):
        category = "NEWLY QUALIFIED (crossed threshold)"
    else:
        # Deal was in snapshot and qualified, but not in UNKNOWN/Unknown
        # This is a SEGMENT/REGION boundary crossing
        prev_region = p.get('region') or 'UNKNOWN'
        prev_segment = p.get('segment') or 'Unknown'
        category = f"BOUNDARY CROSSING (from {prev_region}/{prev_segment})"

    print(f"\n  Category: {category}")

print(f"\n" + "=" * 70)
print("ANALYSIS:")
print("=" * 70)

# Check if these 2 deals explain the gap
joined_list = list(joined)
if len(joined_list) == 2:
    total_value = sum(new_dict[did].get('deal_value') or 0 for did in joined_list)
    print(f"\nTotal value of 2 joined deals: ${total_value:,.0f}")
    print(f"Gap to explain: $206,000")

    if abs(total_value - 206000) < 1000:
        print(f"\n✓ THE 2 JOINED DEALS EXPLAIN THE FULL $206K GAP")
        print(f"  These deals moved INTO UNKNOWN/Unknown from other segments")
        print(f"  They were NOT captured in any waterfall movement category")
        print(f"  This is INTRA-GROUP BOUNDARY CROSSING")
    elif total_value > 206000:
        print(f"\n⚠️  The 2 deals total ${total_value:,.0f}, more than the $206K gap")
        print(f"  This means SOME of their value WAS captured")
        print(f"  But not all of it - investigate which category captured partial value")
    else:
        print(f"\n⚠️  The 2 deals only total ${total_value:,.0f}, less than $206K gap")
        print(f"  Need to investigate other sources of the discrepancy")

# Also check for deals that LEFT (even though script said 0)
left = prev_ids - new_ids
if left:
    print(f"\nNote: {len(left)} deals LEFT the group (script said 0 - recheck)")

# Check for ARR changes in stayed deals
stayed = prev_ids & new_ids
arr_changes = []
for deal_id in stayed:
    p = prev_dict[deal_id]
    n = new_dict[deal_id]

    p_val = p.get('deal_value')
    n_val = n.get('deal_value')

    if p_val is not None and n_val is not None and abs(p_val - n_val) > 0.01:
        arr_changes.append({
            'deal_id': deal_id,
            'prev': p_val,
            'new': n_val,
            'change': n_val - p_val
        })

if arr_changes:
    total_arr_change = sum(d['change'] for d in arr_changes)
    print(f"\nARR changes in stayed deals: {len(arr_changes)} deals")
    print(f"  Total change: ${total_arr_change:,.0f}")
    print(f"  Waterfall arr_change_value: $0")

    if abs(total_arr_change) > 1000:
        print(f"\n  ⚠️  ARR changes NOT CAPTURED in waterfall")
        print(f"     This could contribute to the discrepancy")
