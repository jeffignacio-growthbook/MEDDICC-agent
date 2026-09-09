#!/usr/bin/env python3
"""
Investigate EMEA zero-movement report from Sept 9 Slack query.
Check if this is: (1) regression from yesterday's fix, (2) genuine flatness, or (3) sync gap.
"""
import os
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).parent
sys.path.insert(0, str(REPO_ROOT / 'scripts'))

from dotenv import load_dotenv
load_dotenv()

from supabase import create_client
SUPABASE_URL = os.getenv('SUPABASE_URL')
SUPABASE_KEY = os.getenv('SUPABASE_SERVICE_KEY')
sb = create_client(SUPABASE_URL, SUPABASE_KEY)

from supabase_client import select_all

print("=" * 70)
print("EMEA Flatness Investigation - Sept 9, 2026")
print("=" * 70)
print()

# Check 1: Verify waterfall_weekly reconciliation for EMEA rows
print("CHECK 1: Waterfall Reconciliation for EMEA (Aug 17 - Sep 8)")
print("-" * 70)

waterfall_emea = select_all(sb, 'waterfall_weekly', '*',
                            filters=[
                                ('eq', 'region', 'EMEA'),
                                ('gte', 'week_ending', '2026-08-17'),
                                ('lte', 'week_ending', '2026-09-08')
                            ])

print(f"Found {len(waterfall_emea)} EMEA waterfall rows in this period")
print()

# Check reconciliation for each row
reconciliation_issues = []
for row in sorted(waterfall_emea, key=lambda x: (x['week_ending'], x['segment'])):
    expected_ending = row['beginning_value'] + row['net_change']
    actual_ending = row['ending_value']
    reconciles = abs(expected_ending - actual_ending) <= 0.01

    segment = row['segment']
    week = row['week_ending']

    print(f"{week} {segment:15s}: ", end='')
    print(f"Beginning ${row['beginning_value']:>10,.0f} + Net ${row['net_change']:>10,.0f} = ", end='')
    print(f"Expected ${expected_ending:>10,.0f}, Actual ${actual_ending:>10,.0f} ", end='')

    if reconciles:
        print("✓")
    else:
        print(f"✗ MISMATCH ${actual_ending - expected_ending:,.0f}")
        reconciliation_issues.append((week, segment, actual_ending - expected_ending))

    # Show movements if any are non-zero
    movements = {
        'new_pipeline': row.get('new_pipeline_value', 0),
        'newly_qualified': row.get('newly_qualified_value', 0),
        'newly_arr_bearing': row.get('newly_arr_bearing_value', 0),
        'won': row.get('won_value', 0),
        'lost': row.get('lost_value', 0),
        'arr_change': row.get('arr_change_value', 0),
    }

    if any(abs(v) > 0.01 for v in movements.values()):
        print(f"    Movements: ", end='')
        for name, value in movements.items():
            if abs(value) > 0.01:
                print(f"{name}=${value:,.0f} ", end='')
        print()

print()
if reconciliation_issues:
    print(f"✗ {len(reconciliation_issues)} RECONCILIATION ISSUES FOUND")
    print("  This suggests a REGRESSION from yesterday's fix")
else:
    print("✓ All EMEA rows reconcile perfectly")
    print("  Yesterday's fix is still working correctly")

print()
print("=" * 70)
print("CHECK 2: Raw Deals Activity in EMEA (Aug 17 - Sep 8)")
print("-" * 70)

# Check raw deals for any activity in this period
deals_emea = select_all(sb, 'deals',
                        'deal_id,company_name,deal_status,close_date,deal_value,segment,stage,create_date',
                        filters=[('eq', 'region', 'EMEA')])

print(f"Total EMEA deals in database: {len(deals_emea)}")
print()

# Check for deals that closed in this window
closed_in_window = []
for deal in deals_emea:
    close_date = deal.get('close_date')
    if close_date and '2026-08-17' <= close_date <= '2026-09-08':
        closed_in_window.append(deal)

print(f"Deals that closed in window (Aug 17 - Sep 8): {len(closed_in_window)}")
if closed_in_window:
    for d in closed_in_window[:10]:
        print(f"  {d['deal_id']}: {d['company_name'][:30]:30s} ${d.get('deal_value') or 0:>10,.0f} {d['deal_status']:8s} closed {d['close_date']}")
    if len(closed_in_window) > 10:
        print(f"  ... and {len(closed_in_window) - 10} more")
else:
    print("  None found")

print()

# Check for deals created in this window
created_in_window = []
for deal in deals_emea:
    create_date = deal.get('create_date')
    if create_date and '2026-08-17' <= create_date <= '2026-09-08':
        created_in_window.append(deal)

print(f"Deals created in window (Aug 17 - Sep 8): {len(created_in_window)}")
if created_in_window:
    for d in created_in_window[:10]:
        print(f"  {d['deal_id']}: {d['company_name'][:30]:30s} ${d.get('deal_value') or 0:>10,.0f} {d['deal_status']:8s} created {d['create_date']}")
    if len(created_in_window) > 10:
        print(f"  ... and {len(created_in_window) - 10} more")
else:
    print("  None found")

print()
print("=" * 70)
print("CHECK 3: Snapshot Coverage for Recent Weeks")
print("-" * 70)

# Check what snapshot dates we have
snapshots = select_all(sb, 'deals_snapshot', 'snapshot_date',
                      filters=[
                          ('gte', 'snapshot_date', '2026-08-17'),
                          ('lte', 'snapshot_date', '2026-09-08')
                      ])

snapshot_dates = sorted(set(s['snapshot_date'] for s in snapshots))
print(f"Snapshot dates in window: {len(snapshot_dates)}")
for date in snapshot_dates:
    # Count EMEA deals in each snapshot
    snap_emea = [s for s in snapshots if s['snapshot_date'] == date]
    print(f"  {date}: {len(snap_emea)} total snapshots (need to query for EMEA count)")

print()
print("=" * 70)
print("DIAGNOSIS")
print("=" * 70)

if reconciliation_issues:
    print("✗ REGRESSION: Waterfall reconciliation is broken for EMEA")
    print("  Yesterday's fix may have introduced a new issue")
    print("  Action: Investigate reconciliation failures immediately")
elif len(closed_in_window) > 0 or len(created_in_window) > 0:
    print("✗ DATA SYNC GAP: Raw deals show activity but waterfall shows $0")
    print(f"  Found {len(closed_in_window)} closes and {len(created_in_window)} creates")
    print("  Action: Check if snapshot ETL or waterfall compute is stale")
else:
    print("✓ GENUINE FLATNESS: No EMEA deals activity in this window")
    print("  No closes, no creates - the flatness is real")
    print("  Action: No fix needed, report is accurate")

print()
print("Raw activity summary:")
print(f"  Deals closed: {len(closed_in_window)}")
print(f"  Deals created: {len(created_in_window)}")
print(f"  Waterfall reconciliation: {'FAILED' if reconciliation_issues else 'PASSED'}")
