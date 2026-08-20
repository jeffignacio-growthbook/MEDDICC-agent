#!/usr/bin/env python3
"""
Investigate why 600-1000+ deals per quarter are missing from snapshots.

Check for:
1. Row cap in backfill
2. Date range filter
3. Pipeline filter  
4. Pagination bug
5. Deal characteristics of missing vs captured deals
"""
import os
import sys
from datetime import datetime
from collections import Counter
from dotenv import load_dotenv

load_dotenv()

sys.path.insert(0, 'scripts')
from supabase import create_client
from supabase_client import select_all

sb = create_client(os.environ['SUPABASE_URL'], os.environ['SUPABASE_SERVICE_KEY'])

print("=" * 80)
print("INVESTIGATING MISSING DEALS")
print("=" * 80)

# Focus on FY2026 Q4 week-3 for investigation
quarter = 'FY2026 Q4'
target_date = '2025-11-18'
target_dt = datetime.fromisoformat(target_date).date()

print(f"\nTarget: {quarter} week-3 ({target_date})")
print(f"Coverage: 26.6% (221 snapshot / 830 genuinely open)")
print(f"Missing: 637 deals")

# Get snapshot deals
snapshots = select_all(sb, 'deals_snapshot',
                       columns='deal_id, snapshot_date',
                       filters=[('eq', 'fiscal_quarter', quarter),
                               ('eq', 'snapshot_date', target_date)])

snapshot_deal_ids = set(s['deal_id'] for s in snapshots if s.get('pipeline_id') == 'default')

# Get all deals
deals = select_all(sb, 'deals',
                  columns='deal_id, create_date, close_date, pipeline_id, deal_status, stage_id')

# Find genuinely open deals
genuinely_open_deals = []
for deal in deals:
    if deal.get('pipeline_id') != 'default':
        continue
    
    create_date = deal.get('create_date')
    if not create_date:
        continue
    
    create_dt = datetime.fromisoformat(create_date).date()
    if create_dt > target_dt:
        continue
    
    # Use snapshot data for point-in-time close_date
    snap = next((s for s in select_all(sb, 'deals_snapshot',
                                       columns='close_date',
                                       filters=[('eq', 'deal_id', deal['deal_id']),
                                               ('eq', 'snapshot_date', target_date)])
                if s.get('close_date')), None)
    
    if snap:
        close_date = snap.get('close_date')
        if close_date:
            close_dt = datetime.fromisoformat(close_date).date()
            if close_dt < target_dt:
                continue  # Closed before target
    
    # If no snapshot, check deals table close_date
    close_date = deal.get('close_date')
    if close_date:
        close_dt = datetime.fromisoformat(close_date).date()
        if close_dt < target_dt:
            continue
    
    genuinely_open_deals.append(deal)

genuinely_open_ids = set(d['deal_id'] for d in genuinely_open_deals)
missing_ids = genuinely_open_ids - set(s['deal_id'] for s in snapshots)

print(f"\nGenuinely open deals: {len(genuinely_open_deals):,}")
print(f"In snapshot: {len(snapshots):,}")
print(f"Missing: {len(missing_ids):,}")

# Sample missing deals
missing_deals = [d for d in genuinely_open_deals if d['deal_id'] in missing_ids]

print(f"\n{'='*80}")
print("HYPOTHESIS 1: Row Cap or Pagination Bug")
print(f"{'='*80}")

# Check if all quarters hit a similar row limit
all_q_snapshots = select_all(sb, 'deals_snapshot',
                             columns='fiscal_quarter, snapshot_date',
                             filters=[])

from collections import defaultdict
rows_per_quarter_date = defaultdict(int)
for snap in all_q_snapshots:
    key = (snap.get('fiscal_quarter'), snap.get('snapshot_date'))
    rows_per_quarter_date[key] += 1

print(f"\nSnapshot row counts by quarter and date (sample):")
for q in ['FY2026 Q4', 'FY2027 Q1', 'FY2027 Q2']:
    q_dates = sorted(set(k[1] for k in rows_per_quarter_date.keys() if k[0] == q))
    counts = [rows_per_quarter_date[(q, d)] for d in q_dates]
    print(f"{q}: {len(q_dates)} dates, row counts: {min(counts)} to {max(counts)}")
    print(f"  Example: {q_dates[0]}: {rows_per_quarter_date[(q, q_dates[0])]} rows")

print(f"\n{'='*80}")
print("HYPOTHESIS 2: Date Range Filter")
print(f"{'='*80}")

# Check create_date distribution of missing vs captured
missing_creates = [datetime.fromisoformat(d['create_date']).date() 
                   for d in missing_deals if d.get('create_date')]
captured_creates = [datetime.fromisoformat(d['create_date']).date()
                    for d in genuinely_open_deals if d['deal_id'] not in missing_ids 
                    and d.get('create_date')]

if missing_creates and captured_creates:
    print(f"\nCreate date ranges:")
    print(f"  Missing: {min(missing_creates)} to {max(missing_creates)}")
    print(f"  Captured: {min(captured_creates)} to {max(captured_creates)}")
    
    # Check if there's a cutoff
    missing_before_2024 = sum(1 for d in missing_creates if d.year < 2024)
    captured_before_2024 = sum(1 for d in captured_creates if d.year < 2024)
    
    print(f"\nDeals created before 2024:")
    print(f"  Missing: {missing_before_2024} ({missing_before_2024/len(missing_creates)*100:.1f}%)")
    print(f"  Captured: {captured_before_2024} ({captured_before_2024/len(captured_creates)*100:.1f}%)")

print(f"\n{'='*80}")
print("HYPOTHESIS 3: Deal Characteristics")
print(f"{'='*80}")

# Compare stage distribution
missing_stages = Counter(d.get('stage_id') for d in missing_deals)
captured_deals = [d for d in genuinely_open_deals if d['deal_id'] not in missing_ids]
captured_stages = Counter(d.get('stage_id') for d in captured_deals)

print(f"\nTop 5 stages in missing deals:")
for stage, count in missing_stages.most_common(5):
    pct = count / len(missing_deals) * 100
    print(f"  {stage}: {count} ({pct:.1f}%)")

print(f"\nTop 5 stages in captured deals:")
for stage, count in captured_stages.most_common(5):
    pct = count / len(captured_deals) * 100
    print(f"  {stage}: {count} ({pct:.1f}%)")

print(f"\n{'='*80}")
print("HYPOTHESIS 4: Backfill Logic")
print(f"{'='*80}")

# Check if missing deals appear in ANY snapshot (other quarters/dates)
print(f"\nChecking if missing deals appear elsewhere...")
sample_missing = list(missing_ids)[:50]

never_in_any_snapshot = []
in_other_quarters = []

for deal_id in sample_missing:
    all_snaps = select_all(sb, 'deals_snapshot',
                          columns='fiscal_quarter, snapshot_date',
                          filters=[('eq', 'deal_id', deal_id)])
    
    if not all_snaps:
        never_in_any_snapshot.append(deal_id)
    else:
        quarters_present = set(s.get('fiscal_quarter') for s in all_snaps)
        if quarter not in quarters_present:
            in_other_quarters.append((deal_id, quarters_present))

print(f"\nSample of {len(sample_missing)} missing deals:")
print(f"  Never in any snapshot: {len(never_in_any_snapshot)} ({len(never_in_any_snapshot)/len(sample_missing)*100:.1f}%)")
print(f"  In other quarters only: {len(in_other_quarters)} ({len(in_other_quarters)/len(sample_missing)*100:.1f}%)")

if in_other_quarters:
    print(f"\n  Examples in other quarters:")
    for deal_id, quarters in in_other_quarters[:5]:
        print(f"    Deal {deal_id}: present in {quarters}")

print(f"\n{'='*80}")
print("CONCLUSION")
print(f"{'='*80}")

print(f"\nMissing deals represent {len(missing_ids)/len(genuinely_open_deals)*100:.1f}% of open pipeline")
print(f"This suggests:")

if len(never_in_any_snapshot) / len(sample_missing) > 0.8:
    print(f"  - PRIMARY CAUSE: Deals never captured by backfill at all")
    print(f"  - Likely a systematic exclusion in original backfill logic")
    print(f"  - Check snapshot_deals.py history for filters/limits")
else:
    print(f"  - Mixed causes - some never captured, some timing issues")

print(f"\nNext steps:")
print(f"  1. Review snapshot_deals.py backfill implementation")
print(f"  2. Check HubSpot API logs for row limits or pagination failures")
print(f"  3. Re-run backfill with fixed inclusion rule to recover missing deals")
print(f"  4. Verify recovered deals against genuinely open calculation")

