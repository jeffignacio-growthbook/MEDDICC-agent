#!/usr/bin/env python3
"""
Measure snapshot coverage using point-in-time data.

For each quarter at week-3, mid-quarter, and quarter-end:
- Count genuinely open deals (point-in-time create/close/status)
- Count deals in snapshot
- Report coverage ratio vs 80% gate
"""
import os
import sys
from datetime import datetime
from collections import defaultdict
from dotenv import load_dotenv

load_dotenv()

sys.path.insert(0, 'scripts')
from supabase import create_client
from supabase_client import select_all

sb = create_client(os.environ['SUPABASE_URL'], os.environ['SUPABASE_SERVICE_KEY'])

print("=" * 80)
print("SNAPSHOT COVERAGE ANALYSIS (Point-in-Time)")
print("=" * 80)

quarters = {
    'FY2026 Q4': {
        'week_3': '2025-11-18',
        'mid_quarter': '2025-12-16',  # Week 7
        'quarter_end': '2026-01-27'   # Week 13
    },
    'FY2027 Q1': {
        'week_3': '2026-02-17',
        'mid_quarter': '2026-03-17',
        'quarter_end': '2026-04-28'
    },
    'FY2027 Q2': {
        'week_3': '2026-05-19',
        'mid_quarter': '2026-06-16',
        'quarter_end': '2026-07-28'
    }
}

# Get all snapshots for analyzed quarters
all_snapshots = select_all(sb, 'deals_snapshot',
                           columns='deal_id, snapshot_date, fiscal_quarter, week_of_quarter, pipeline_id')

# Get all deals with their point-in-time fields from snapshots
# We'll use snapshots themselves as the source of point-in-time data
snapshot_deals_by_date = defaultdict(set)
for snap in all_snapshots:
    if snap.get('pipeline_id') == 'default':
        key = (snap['fiscal_quarter'], snap['snapshot_date'])
        snapshot_deals_by_date[key].add(snap['deal_id'])

# For genuinely open, we need point-in-time create_date and close_date
# These should come from the deals_snapshot table (backfilled point-in-time data)
# But we need to get a complete view across all deals, not just snapshotted ones

# Alternative approach: Use the first snapshot appearance as proxy for create_date
# and last snapshot appearance before a date as proxy for still being open

print("\nFetching snapshot metadata for coverage calculation...")

# Get unique deals and their snapshot date ranges per quarter
deals_snapshot_ranges = defaultdict(lambda: {'first_snap': None, 'last_snap': None, 'all_dates': set()})

for snap in all_snapshots:
    if snap.get('pipeline_id') != 'default':
        continue
    
    q = snap['fiscal_quarter']
    if q not in quarters:
        continue
    
    deal_id = snap['deal_id']
    snap_date = snap['snapshot_date']
    key = (q, deal_id)
    
    deals_snapshot_ranges[key]['all_dates'].add(snap_date)
    
    if deals_snapshot_ranges[key]['first_snap'] is None or snap_date < deals_snapshot_ranges[key]['first_snap']:
        deals_snapshot_ranges[key]['first_snap'] = snap_date
    
    if deals_snapshot_ranges[key]['last_snap'] is None or snap_date > deals_snapshot_ranges[key]['last_snap']:
        deals_snapshot_ranges[key]['last_snap'] = snap_date

# Actually, this approach won't work because we need the true create_date and close_date
# from the deals table, but using point-in-time values from the snapshot backfill.

# Better approach: Get create_date and close_date from deals_snapshot table
# For a given snapshot date D, a deal is "genuinely open" if:
# - Any snapshot on or before D has this deal (meaning it was created by D)
# - Either it never has a close_date < D in any snapshot, or its close_date >= D

# Let's use the deals table but recognize it has current state, not point-in-time
# We need to fetch close_date from snapshots to get point-in-time close_date

print("\nFetching deals table and snapshot close_date history...")

deals = select_all(sb, 'deals',
                  columns='deal_id, create_date, pipeline_id')

# Get close_date from snapshots (point-in-time)
snapshot_close_dates = {}
for snap in all_snapshots:
    if snap.get('pipeline_id') != 'default':
        continue
    key = (snap['deal_id'], snap['snapshot_date'])
    # We need close_date from snapshot, but it's not in our query
    # Let me fetch it

print("\nFetching snapshot close_date data for point-in-time comparison...")

# Fetch close_date for all snapshots
all_snapshots_with_close = select_all(sb, 'deals_snapshot',
                                      columns='deal_id, snapshot_date, fiscal_quarter, pipeline_id, close_date')

# Build point-in-time close_date lookup
snapshot_close_lookup = {}
for snap in all_snapshots_with_close:
    if snap.get('pipeline_id') == 'default':
        key = (snap['deal_id'], snap['snapshot_date'])
        snapshot_close_lookup[key] = snap.get('close_date')

print(f"Loaded {len(snapshot_close_lookup):,} snapshot close_date entries")

# Now calculate genuinely open for each date
coverage_results = {}

for q_name, dates in quarters.items():
    print(f"\n{'='*80}")
    print(f"{q_name}")
    print(f"{'='*80}")
    
    q_results = {}
    
    for period_name, target_date in dates.items():
        target_dt = datetime.fromisoformat(target_date).date()
        
        # Count snapshot deals on this date
        snapshot_key = (q_name, target_date)
        snapshot_deals = snapshot_deals_by_date.get(snapshot_key, set())
        
        # Count genuinely open deals using point-in-time data
        genuinely_open = set()
        
        for deal in deals:
            if deal.get('pipeline_id') != 'default':
                continue
            
            deal_id = deal['deal_id']
            create_date = deal.get('create_date')
            
            if not create_date:
                continue
            
            create_dt = datetime.fromisoformat(create_date).date()
            
            # Must be created by target_date
            if create_dt > target_dt:
                continue
            
            # Check if closed before target_date using point-in-time close_date from snapshot
            # Look for this deal's close_date in the snapshot on or nearest before target_date
            
            # Find the closest snapshot date on or before target_date for this deal in this quarter
            relevant_snaps = [(snap['deal_id'], snap['snapshot_date'], snap.get('close_date'))
                            for snap in all_snapshots_with_close
                            if snap['deal_id'] == deal_id 
                            and snap.get('fiscal_quarter') == q_name
                            and snap.get('pipeline_id') == 'default'
                            and datetime.fromisoformat(snap['snapshot_date']).date() <= target_dt]
            
            if not relevant_snaps:
                # Deal not in any snapshot on or before target_date
                # Could be created after, or missing from backfill
                # Check if created before target_date - if so, it's missing from backfill
                if create_dt <= target_dt:
                    # Should be in snapshot but isn't - count as genuinely open but missing
                    genuinely_open.add(deal_id)
                continue
            
            # Get the latest snapshot before or on target_date
            latest_snap = max(relevant_snaps, key=lambda x: x[1])
            close_date = latest_snap[2]
            
            if not close_date:
                # Still open as of target_date
                genuinely_open.add(deal_id)
            else:
                close_dt = datetime.fromisoformat(close_date).date()
                if close_dt >= target_dt:
                    # Closed on or after target_date - still open as of target_date
                    genuinely_open.add(deal_id)
                # else: closed before target_date - not open
        
        snapshot_count = len(snapshot_deals)
        genuinely_open_count = len(genuinely_open)
        coverage_pct = (snapshot_count / genuinely_open_count * 100) if genuinely_open_count > 0 else 0
        
        in_both = snapshot_deals & genuinely_open
        in_snapshot_only = snapshot_deals - genuinely_open
        missing = genuinely_open - snapshot_deals
        
        gate_status = "✓ PASS" if coverage_pct >= 80 else "✗ FAIL"
        
        print(f"\n{period_name.upper().replace('_', ' ')} ({target_date}):")
        print(f"  Snapshot deals: {snapshot_count:>4}")
        print(f"  Genuinely open: {genuinely_open_count:>4}")
        print(f"  Coverage: {coverage_pct:>6.1f}% {gate_status} (80% gate)")
        print(f"  In both: {len(in_both):>4}")
        print(f"  Missing from snapshot: {len(missing):>4} ({len(missing)/genuinely_open_count*100:.1f}%)")
        print(f"  In snapshot only: {len(in_snapshot_only):>4}")
        
        q_results[period_name] = {
            'date': target_date,
            'snapshot_count': snapshot_count,
            'genuinely_open_count': genuinely_open_count,
            'coverage_pct': coverage_pct,
            'missing': missing,
            'in_snapshot_only': in_snapshot_only
        }
    
    coverage_results[q_name] = q_results

# Summary table
print(f"\n{'='*80}")
print("COVERAGE SUMMARY (80% Gate)")
print(f"{'='*80}")

print(f"\n{'Quarter':<12} {'Period':<15} {'Date':<12} {'Snapshot':>9} {'Open':>9} {'Coverage':>10} {'Status':<10}")
print("-" * 95)

for q_name in ['FY2026 Q4', 'FY2027 Q1', 'FY2027 Q2']:
    for period_name in ['week_3', 'mid_quarter', 'quarter_end']:
        result = coverage_results[q_name][period_name]
        status = "✓ PASS" if result['coverage_pct'] >= 80 else "✗ FAIL"
        print(f"{q_name:<12} {period_name.replace('_', ' '):<15} {result['date']:<12} "
              f"{result['snapshot_count']:>9} {result['genuinely_open_count']:>9} "
              f"{result['coverage_pct']:>9.1f}% {status:<10}")

# Gate assessment
print(f"\n{'='*80}")
print("COVERAGE GATE ASSESSMENT")
print(f"{'='*80}")

for q_name in ['FY2026 Q4', 'FY2027 Q1', 'FY2027 Q2']:
    week3_coverage = coverage_results[q_name]['week_3']['coverage_pct']
    week3_missing = len(coverage_results[q_name]['week_3']['missing'])
    
    if week3_coverage >= 80:
        print(f"\n✓ {q_name}: {week3_coverage:.1f}% coverage (PASS)")
        print(f"  Week-3 denominator is valid for conversion analysis")
    else:
        print(f"\n✗ {q_name}: {week3_coverage:.1f}% coverage (FAIL)")
        print(f"  {week3_missing} deals missing from snapshot ({100-week3_coverage:.1f}% gap)")
        print(f"  Denominators are understated - conversion analysis NOT VALID")

all_pass = all(coverage_results[q]['week_3']['coverage_pct'] >= 80 
               for q in ['FY2026 Q4', 'FY2027 Q1', 'FY2027 Q2'])

print(f"\n{'='*80}")
if all_pass:
    print("✓ All quarters pass coverage gate - proceed with conversion analysis")
else:
    print("✗ One or more quarters fail coverage gate")
    print("  No conversion analysis is valid until snapshot backfill is fixed")
    print("  Next step: Investigate why deals are missing and recover them")

