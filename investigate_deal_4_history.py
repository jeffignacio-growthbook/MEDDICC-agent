#!/usr/bin/env python3
"""
Investigate deal #4 (61149585726): $0 → $150K

Is this:
1. A genuine ARR increase (was $0, became $150K), OR
2. A deal previously excluded from ARR calculations (early stage) that became ARR-bearing?
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

deal_id = '61149585726'
prev_week = '2026-06-22'
test_week = '2026-06-29'

print(f"Investigating Deal {deal_id}: $0 → $150K")
print("=" * 70)

# Get deal record
deal_result = sb.table('deals')\
    .select('*')\
    .eq('deal_id', deal_id)\
    .execute()

if not deal_result.data:
    print("Deal not found in deals table")
    exit(1)

deal = deal_result.data[0]

print(f"\nCurrent deal state:")
print(f"  Deal ID: {deal['deal_id']}")
print(f"  Stage: {deal.get('stage')}")
print(f"  Stage order: {deal.get('stage_order')}")
print(f"  Status: {deal.get('deal_status')}")
print(f"  Value: ${deal.get('deal_value'):,.0f}" if deal.get('deal_value') else "  Value: NULL")
print(f"  Close date: {deal.get('close_date')}")
print(f"  Created date: {deal.get('created_at')}")
print(f"  Qualified date: {deal.get('qualified_date')}")

# Get stage history from property_history
ph_result = sb.table('property_history')\
    .select('changed_at, property_name, old_value, new_value')\
    .eq('deal_id', deal_id)\
    .in_('property_name', ['dealstage', 'amount'])\
    .order('changed_at')\
    .execute()

print(f"\nProperty history:")
if ph_result.data:
    print(f"  Found {len(ph_result.data)} changes")
    for record in ph_result.data:
        print(f"\n    {record['changed_at'][:10]}: {record['property_name']}")
        print(f"      {record['old_value']} → {record['new_value']}")
else:
    print(f"  No property history found")

# Check snapshots around this time period
print(f"\nSnapshot history around June 2026:")

snapshots = select_all(sb, 'deals_snapshot', 'snapshot_date, deal_value, stage_order, deal_status',
                       filters=[('eq', 'deal_id', deal_id)])

if snapshots:
    # Filter to June timeframe
    june_snapshots = [s for s in snapshots if s['snapshot_date'].startswith('2026-06')]
    june_snapshots.sort(key=lambda x: x['snapshot_date'])

    for snap in june_snapshots:
        print(f"\n  {snap['snapshot_date']}:")
        print(f"    Value: ${snap.get('deal_value'):,.0f}" if snap.get('deal_value') is not None else "    Value: 0 or NULL")
        print(f"    Stage order: {snap.get('stage_order')}")
        print(f"    Status: {snap.get('deal_status')}")
else:
    print("  No snapshots found for this deal")

# Check stage semantics
print(f"\n" + "=" * 70)
print("ANALYSIS:")
print("=" * 70)

# Get the actual snapshot records for prev and test week
prev_snap = [s for s in snapshots if s['snapshot_date'] == prev_week]
test_snap = [s for s in snapshots if s['snapshot_date'] == test_week]

if prev_snap and test_snap:
    p = prev_snap[0]
    t = test_snap[0]

    print(f"\nSnapshot comparison:")
    print(f"  {prev_week}:")
    print(f"    Value: {p.get('deal_value')}")
    print(f"    Stage order: {p.get('stage_order')}")
    print(f"    Status: {p.get('deal_status')}")

    print(f"\n  {test_week}:")
    print(f"    Value: {t.get('deal_value')}")
    print(f"    Stage order: {t.get('stage_order')}")
    print(f"    Status: {t.get('deal_status')}")

    # Analyze the change
    prev_val = p.get('deal_value')
    test_val = t.get('deal_value')

    print(f"\nValue change pattern:")
    if prev_val == 0 and test_val > 0:
        print(f"  $0 → ${test_val:,.0f}")

        # Check if stage_order changed
        if p.get('stage_order') != t.get('stage_order'):
            print(f"\n  Stage order CHANGED: {p.get('stage_order')} → {t.get('stage_order')}")

            # Check if this was an early-stage deal
            if p.get('stage_order') and p.get('stage_order') < 2:
                print(f"\n  ✓ LEGITIMATE EXCLUSION PATTERN")
                print(f"    Previous stage was early-stage (order {p.get('stage_order')} < 2)")
                print(f"    Deal had $0 value because it was pre-qualification")
                print(f"    Now has value because it progressed to ARR-bearing stage")
                print(f"\n  This is NOT a bug - it's a deal becoming ARR-bearing")
                print(f"  Should be tracked as 'newly_arr_bearing' category")
            else:
                print(f"\n  ⚠️  Stage changed but was already at qualified level")
                print(f"    This might be a genuine ARR increase, not first-time ARR")
        else:
            print(f"\n  Stage order UNCHANGED: {p.get('stage_order')}")
            print(f"  This is a genuine ARR increase on the same-stage deal")
            print(f"  Should be tracked in arr_change_value")

    elif prev_val is None and test_val is not None:
        print(f"  NULL → ${test_val:,.0f}")
        print(f"\n  This is a NULL-to-value transition")
        print(f"  Could be data quality issue or first-time ARR capture")
    else:
        print(f"  {prev_val} → {test_val}")
        print(f"  Standard value change")

# Check qualification
print(f"\nQualification status:")
qual_date = deal.get('qualified_date')
if qual_date:
    qual_date_obj = date.fromisoformat(qual_date)
    prev_date = date.fromisoformat(prev_week)
    test_date = date.fromisoformat(test_week)

    was_qualified_prev = qual_date_obj <= prev_date
    was_qualified_test = qual_date_obj <= test_date

    print(f"  Qualified date: {qual_date}")
    print(f"  Qualified at {prev_week}: {was_qualified_prev}")
    print(f"  Qualified at {test_week}: {was_qualified_test}")

    if not was_qualified_prev and was_qualified_test:
        print(f"\n  ✓ BECAME QUALIFIED THIS WEEK")
        print(f"    The $0 → $150K might be tied to qualification event")
        print(f"    Should be captured in 'newly_qualified_value'")
else:
    print(f"  No qualified_date recorded")

print(f"\n" + "=" * 70)
print("CONCLUSION:")
print("=" * 70)

# Make determination
if prev_snap and test_snap:
    p = prev_snap[0]
    t = test_snap[0]

    prev_val = p.get('deal_value') or 0
    test_val = t.get('deal_value') or 0

    if prev_val == 0 and test_val > 0:
        # Check if this is legitimately excluded pattern
        if qual_date:
            qual_date_obj = date.fromisoformat(qual_date)
            prev_date = date.fromisoformat(prev_week)

            if qual_date_obj > prev_date:
                print(f"✓ CATEGORY: Newly ARR-bearing (via qualification)")
                print(f"  Deal became qualified ({qual_date}) between snapshots")
                print(f"  The $0 → $150K should be captured in 'newly_qualified_value'")
                print(f"  NOT a bug - correct behavior")
            elif p.get('stage_order', 0) < 2 and t.get('stage_order', 0) >= 2:
                print(f"✓ CATEGORY: Newly ARR-bearing (via stage progression)")
                print(f"  Deal progressed from early stage to ARR-bearing stage")
                print(f"  Should be tracked as separate category")
                print(f"  NOT a bug - need new tracking category")
            else:
                print(f"✗ CATEGORY: Genuine ARR increase bug")
                print(f"  Deal was already qualified/ARR-bearing at prev snapshot")
                print(f"  The $0 → $150K is a true ARR increase")
                print(f"  Should be captured in arr_change_value")
                print(f"  This IS a bug - arr_change_value not tracking $0 transitions")
