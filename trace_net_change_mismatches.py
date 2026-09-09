#!/usr/bin/env python3
"""
Trace the root cause of net_change reconciliation mismatches in properly-enriched groups.

Focus on top offenders:
- NAM/Mid-Market (14 weeks)
- EMEA/Mid-Market (14 weeks)
- EMEA/Enterprise (11 weeks)

For each mismatch, identify:
1. Which deals are causing the discrepancy
2. Whether it's the SAME precedence-masking bug (stage movement masking non-ARR categories)
3. Or a DIFFERENT bug (real boundary crossing, etc.)
"""

import os
import sys
from datetime import date
from pathlib import Path

REPO_ROOT = Path(__file__).parent
sys.path.insert(0, str(REPO_ROOT / 'scripts'))
sys.path.insert(0, str(REPO_ROOT / 'api'))

from dotenv import load_dotenv
load_dotenv()

from supabase import create_client
SUPABASE_URL = os.getenv('SUPABASE_URL')
SUPABASE_KEY = os.getenv('SUPABASE_SERVICE_KEY')
sb = create_client(SUPABASE_URL, SUPABASE_KEY)

from supabase_client import select_all
from field_semantics import is_test_deal

# Pick 3 specific weeks with mismatches to trace
test_cases = [
    ('NAM', 'Mid-Market', '2025-11-10'),
    ('EMEA', 'Mid-Market', '2025-11-24'),
    ('EMEA', 'Enterprise', '2025-09-08'),
]

def is_qualified(deal_id, as_of_date_str, qual_map):
    qd = qual_map.get(deal_id, {}).get('qualified_date')
    if not qd:
        return False
    try:
        return date.fromisoformat(qd) <= date.fromisoformat(as_of_date_str)
    except:
        return False

def should_include(deal_id, snapshot_date, qual_map, company_name):
    return is_qualified(deal_id, snapshot_date, qual_map) and \
           not is_test_deal({'company_name': company_name})

# Load qualification data
qual_data = select_all(sb, 'deals', 'deal_id, qualified_date, company_name')
qual_map = {d['deal_id']: {'qualified_date': d.get('qualified_date'),
                           'company_name': d.get('company_name')}
            for d in qual_data}

for region, segment, week_ending in test_cases:
    prev_week = date.fromisoformat(week_ending)
    prev_week = (prev_week - __import__('datetime').timedelta(days=7)).isoformat()

    print("=" * 70)
    print(f"Tracing: {region}/{segment} week {week_ending}")
    print("=" * 70)

    # Get waterfall for this group/week
    wf = sb.table('waterfall_weekly')\
        .select('*')\
        .eq('week_ending', week_ending)\
        .eq('region', region)\
        .eq('segment', segment)\
        .execute()

    if not wf.data:
        print("  No waterfall found")
        continue

    wf_row = wf.data[0]

    print(f"\nWaterfall values:")
    print(f"  Beginning:       ${wf_row['beginning_value']:,.2f}")
    print(f"  Net change:      ${wf_row['net_change']:,.2f}")
    print(f"  Expected ending: ${wf_row['beginning_value'] + wf_row['net_change']:,.2f}")
    print(f"  Actual ending:   ${wf_row['ending_value']:,.2f}")
    print(f"  Mismatch:        ${wf_row['ending_value'] - (wf_row['beginning_value'] + wf_row['net_change']):,.2f}")

    # Load both snapshots
    prev_snap = select_all(sb, 'deals_snapshot', '*',
                          filters=[('eq', 'snapshot_date', prev_week)])
    new_snap = select_all(sb, 'deals_snapshot', '*',
                         filters=[('eq', 'snapshot_date', week_ending)])

    prev_dict = {d['deal_id']: d for d in prev_snap}
    new_dict = {d['deal_id']: d for d in new_snap}

    # Filter to this group's qualified active deals
    def in_group(snap, snapshot_date):
        return [d for d in snap
                if (d.get('region') or 'UNKNOWN') == region
                and (d.get('segment') or 'Unknown') == segment
                and d.get('deal_status') == 'active'
                and should_include(d['deal_id'], snapshot_date, qual_map,
                                 qual_map.get(d['deal_id'], {}).get('company_name'))]

    prev_group = in_group(prev_snap, prev_week)
    new_group = in_group(new_snap, week_ending)

    prev_ids = set(d['deal_id'] for d in prev_group)
    new_ids = set(d['deal_id'] for d in new_group)

    # Calculate manual beginning and ending
    def get_value(d):
        v = d.get('deal_value')
        return float(v) if v is not None else None

    manual_beginning = sum(v for d in prev_group if (v := get_value(d)) is not None)
    manual_ending = sum(v for d in new_group if (v := get_value(d)) is not None)

    print(f"\nManual calculation:")
    print(f"  Beginning: ${manual_beginning:,.2f} ({len(prev_group)} deals)")
    print(f"  Ending:    ${manual_ending:,.2f} ({len(new_group)} deals)")
    print(f"  Delta:     ${manual_ending - manual_beginning:,.2f}")

    # Check if manual matches waterfall
    if abs(manual_beginning - wf_row['beginning_value']) > 0.01:
        print(f"\n  ⚠️  Manual beginning doesn't match waterfall beginning")
    if abs(manual_ending - wf_row['ending_value']) > 0.01:
        print(f"\n  ⚠️  Manual ending doesn't match waterfall ending")

    # Analyze movement
    left = prev_ids - new_ids
    joined = new_ids - prev_ids
    stayed = prev_ids & new_ids

    print(f"\nPipeline movement:")
    print(f"  Left:   {len(left)} deals")
    print(f"  Joined: {len(joined)} deals")
    print(f"  Stayed: {len(stayed)} deals")

    # Check for boundary crossing (deals moving to OTHER region/segment)
    boundary_crossers = []
    for deal_id in left:
        # Deal left this group - where did it go?
        n = new_dict.get(deal_id)
        if n and n.get('deal_status') == 'active':
            new_region = n.get('region') or 'UNKNOWN'
            new_segment = n.get('segment') or 'Unknown'
            if new_region != region or new_segment != segment:
                p = prev_dict[deal_id]
                value = get_value(p)
                boundary_crossers.append({
                    'deal_id': deal_id,
                    'from': f"{region}/{segment}",
                    'to': f"{new_region}/{new_segment}",
                    'value': value,
                    'reason': 'enrichment_change'
                })

    for deal_id in joined:
        # Deal joined this group - where did it come from?
        p = prev_dict.get(deal_id)
        if p and p.get('deal_status') == 'active':
            prev_region = p.get('region') or 'UNKNOWN'
            prev_segment = p.get('segment') or 'Unknown'
            if prev_region != region or prev_segment != segment:
                n = new_dict[deal_id]
                value = get_value(n)
                boundary_crossers.append({
                    'deal_id': deal_id,
                    'from': f"{prev_region}/{prev_segment}",
                    'to': f"{region}/{segment}",
                    'value': value,
                    'reason': 'enrichment_change'
                })

    if boundary_crossers:
        total_boundary = sum(abs(d['value']) for d in boundary_crossers if d['value'] is not None)
        print(f"\n  Boundary crossers: {len(boundary_crossers)} deals (${total_boundary:,.0f} total)")
        for d in boundary_crossers[:5]:
            print(f"    {d['deal_id']}: ${d['value']:,.0f} - {d['from']} → {d['to']}")
    else:
        print(f"\n  ✓ No boundary crossers (no deals changed region/segment)")

    # Check for ARR changes in stayed deals
    arr_changes = []
    for deal_id in stayed:
        p = prev_dict[deal_id]
        n = new_dict[deal_id]

        p_val = get_value(p)
        n_val = get_value(n)

        if p_val is not None and n_val is not None and abs(p_val - n_val) > 0.01:
            arr_changes.append({
                'deal_id': deal_id,
                'prev_value': p_val,
                'new_value': n_val,
                'delta': n_val - p_val
            })

    if arr_changes:
        total_arr_delta = sum(d['delta'] for d in arr_changes)
        print(f"\n  ARR changes in stayed deals: {len(arr_changes)} deals")
        print(f"    Total ARR delta: ${total_arr_delta:,.2f}")
        print(f"    Waterfall arr_change_value: ${wf_row['arr_change_value']:,.2f}")

        if abs(total_arr_delta - wf_row['arr_change_value']) > 1.0:
            print(f"    ⚠️  ARR delta NOT CAPTURED in arr_change_value")
            print(f"       Missing: ${abs(total_arr_delta - wf_row['arr_change_value']):,.0f}")

    # Compute expected net_change from waterfall components
    expected_net_change = (
        wf_row['new_pipeline_value'] +
        wf_row['newly_qualified_value'] -
        wf_row['won_value'] -
        wf_row['lost_value']
    )

    actual_delta = manual_ending - manual_beginning

    print(f"\nReconciliation analysis:")
    print(f"  Expected net_change (formula): ${expected_net_change:,.2f}")
    print(f"  Actual delta (ending - beginning): ${actual_delta:,.2f}")
    print(f"  Difference: ${actual_delta - expected_net_change:,.2f}")

    # Determine root cause
    print(f"\nRoot cause determination:")

    if boundary_crossers:
        boundary_value = sum(abs(d['value']) for d in boundary_crossers if d['value'] is not None)
        if abs(boundary_value - abs(actual_delta - expected_net_change)) < 1000:
            print(f"  ✓ BOUNDARY CROSSING explains the mismatch")
            print(f"    {len(boundary_crossers)} deals changed region/segment")
            print(f"    Total value: ${boundary_value:,.0f}")
        else:
            print(f"  ⚠️  Boundary crossing exists but doesn't fully explain mismatch")
    elif arr_changes:
        if abs(total_arr_delta - abs(actual_delta - expected_net_change)) < 1000:
            print(f"  ✓ ARR MASKING (precedence bug) explains the mismatch")
            print(f"    {len(arr_changes)} deals had ARR changes")
            print(f"    But were masked by higher-priority movements")
        else:
            print(f"  ⚠️  ARR changes exist but don't fully explain mismatch")
    else:
        print(f"  ⚠️  Root cause unclear - need deeper investigation")

    print()
