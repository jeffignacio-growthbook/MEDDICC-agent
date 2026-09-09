#!/usr/bin/env python3
"""
Trace a net_change mismatch that has arr_change_value populated
but still doesn't reconcile, to identify the OTHER root cause.

Example: NAM/Mid-Market week 2025-10-06
- diff -$52,725
- arr_change $102,000
- Still doesn't reconcile even with arr_change included
"""

import os
import sys
from datetime import date, timedelta
from pathlib import Path

REPO_ROOT = Path(__file__).parent
sys.path.insert(0, str(REPO_ROOT / 'scripts'))
sys.path.insert(0, str(REPO_ROOT / 'scripts/analytics'))
sys.path.insert(0, str(REPO_ROOT / 'api'))

from dotenv import load_dotenv
load_dotenv()

from supabase import create_client
SUPABASE_URL = os.getenv('SUPABASE_URL')
SUPABASE_KEY = os.getenv('SUPABASE_SERVICE_KEY')
sb = create_client(SUPABASE_URL, SUPABASE_KEY)

from supabase_client import select_all
from field_semantics import is_test_deal
from deal_status_history import get_deal_status_as_of

# Test case: NAM/Mid-Market week 2025-10-06
region = 'NAM'
segment = 'Mid-Market'
week_ending = '2025-10-06'
prev_week = '2025-09-29'

print(f"Tracing: {region}/{segment} week {week_ending}")
print("=" * 70)

# Get waterfall
wf = sb.table('waterfall_weekly')\
    .select('*')\
    .eq('week_ending', week_ending)\
    .eq('region', region)\
    .eq('segment', segment)\
    .execute()

wf_row = wf.data[0]

print(f"\nWaterfall values:")
print(f"  Beginning:              ${wf_row['beginning_value']:,.2f}")
print(f"  Net change:             ${wf_row['net_change']:,.2f}")
print(f"  ARR change value:       ${wf_row['arr_change_value']:,.2f}")
print(f"  Expected (no ARR):      ${wf_row['beginning_value'] + wf_row['net_change']:,.2f}")
print(f"  Expected (with ARR):    ${wf_row['beginning_value'] + wf_row['net_change'] + wf_row['arr_change_value']:,.2f}")
print(f"  Actual ending:          ${wf_row['ending_value']:,.2f}")
print(f"  Mismatch (no ARR):      ${wf_row['ending_value'] - (wf_row['beginning_value'] + wf_row['net_change']):,.2f}")
print(f"  Mismatch (with ARR):    ${wf_row['ending_value'] - (wf_row['beginning_value'] + wf_row['net_change'] + wf_row['arr_change_value']):,.2f}")

print(f"\nWaterfall components:")
print(f"  New pipeline:    ${wf_row['new_pipeline_value']:,.2f}")
print(f"  Newly qualified: ${wf_row['newly_qualified_value']:,.2f}")
print(f"  Won:             ${wf_row['won_value']:,.2f}")
print(f"  Lost:            ${wf_row['lost_value']:,.2f}")
print(f"  Moved forward:   ${wf_row['moved_forward_value']:,.2f}")
print(f"  Moved backward:  ${wf_row['moved_backward_value']:,.2f}")
print(f"  Pulled in:       ${wf_row['pulled_in_value']:,.2f}")
print(f"  Pushed out:      ${wf_row['pushed_out_value']:,.2f}")

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

# Load snapshots
prev_snap = select_all(sb, 'deals_snapshot', '*',
                      filters=[('eq', 'snapshot_date', prev_week)])
new_snap = select_all(sb, 'deals_snapshot', '*',
                     filters=[('eq', 'snapshot_date', week_ending)])

prev_dict = {d['deal_id']: d for d in prev_snap}
new_dict = {d['deal_id']: d for d in new_snap}

# Filter to this group
def in_group(snap, snapshot_date):
    return [d for d in snap
            if (d.get('region') or 'UNKNOWN') == region
            and (d.get('segment') or 'Unknown') == segment
            and d.get('deal_status') == 'active'
            and is_qualified(d['deal_id'], snapshot_date)
            and not is_test_deal({'company_name': qual_map.get(d['deal_id'], {}).get('company_name')})]

prev_group = in_group(prev_snap, prev_week)
new_group = in_group(new_snap, week_ending)

def get_value(d):
    v = d.get('deal_value')
    return float(v) if v is not None else None

manual_beginning = sum(v for d in prev_group if (v := get_value(d)) is not None)
manual_ending = sum(v for d in new_group if (v := get_value(d)) is not None)

print(f"\nManual calculation:")
print(f"  Beginning: ${manual_beginning:,.2f} ({len(prev_group)} deals)")
print(f"  Ending:    ${manual_ending:,.2f} ({len(new_group)} deals)")
print(f"  Delta:     ${manual_ending - manual_beginning:,.2f}")

# Check all movements in detail
prev_ids = set(d['deal_id'] for d in prev_group)
new_ids = set(d['deal_id'] for d in new_group)

left = prev_ids - new_ids
joined = new_ids - prev_ids
stayed = prev_ids & new_ids

print(f"\nMovement breakdown:")
print(f"  Left:   {len(left)} deals")
print(f"  Joined: {len(joined)} deals")
print(f"  Stayed: {len(stayed)} deals")

# Check ARR changes
arr_changes = []
for deal_id in stayed:
    p = prev_dict[deal_id]
    n = new_dict[deal_id]
    p_val = get_value(p)
    n_val = get_value(n)
    if p_val is not None and n_val is not None and abs(p_val - n_val) > 0.01:
        arr_changes.append({
            'deal_id': deal_id,
            'prev': p_val,
            'new': n_val,
            'delta': n_val - p_val
        })

if arr_changes:
    total_arr = sum(d['delta'] for d in arr_changes)
    print(f"\n  ARR changes: {len(arr_changes)} deals, total ${total_arr:,.2f}")
    print(f"    Waterfall arr_change_value: ${wf_row['arr_change_value']:,.2f}")
    print(f"    Difference: ${abs(total_arr - wf_row['arr_change_value']):,.2f}")

print(f"\nDEBUG: Trying to explain the mismatch...")
print(f"  Manual delta: ${manual_ending - manual_beginning:,.2f}")
print(f"  Waterfall net_change: ${wf_row['net_change']:,.2f}")
print(f"  Difference: ${abs((manual_ending - manual_beginning) - wf_row['net_change']):,.2f}")

# The key question: why doesn't the waterfall net_change match the manual delta?
# Possible reasons:
# 1. Precedence system masking non-ARR movements
# 2. moved_forward/moved_backward counted in wrong direction
# 3. Other movements not captured
