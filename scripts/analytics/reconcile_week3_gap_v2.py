#!/usr/bin/env python3
"""
Reconcile FY2026 Q4 week-3: snapshot vs genuinely open.

Match the logic from analyze_snapshot_violations.py (lines 124-160).
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
print("FY2026 Q4 WEEK-3: Snapshot vs Genuinely Open (All Pipelines)")
print("=" * 80)

quarter = 'FY2026 Q4'
week3_date = '2025-11-18'
week3_dt = datetime.fromisoformat(week3_date).date()

# Set 1: Snapshot rows (default pipeline only, as per snapshot_deals.py)
snapshot_rows = select_all(sb, 'deals_snapshot',
                           columns='deal_id, snapshot_date, pipeline_id',
                           filters=[('eq', 'fiscal_quarter', quarter),
                                   ('eq', 'week_of_quarter', 3)])

snapshot_default = [s for s in snapshot_rows if s.get('pipeline_id') == 'default']
snapshot_deal_ids = set(s['deal_id'] for s in snapshot_default)

print(f"\nSet 1: Snapshot week-3 rows (default pipeline)")
print(f"  Snapshot rows: {len(snapshot_default):,}")
print(f"  Unique deal IDs: {len(snapshot_deal_ids):,}")

# Set 2: Genuinely open deals (ALL pipelines, matching analysis script logic)
deals = select_all(sb, 'deals',
                  columns='deal_id, create_date, close_date, pipeline_id')

genuinely_open_all_pipelines = []
for deal in deals:
    create_date = deal.get('create_date')
    close_date = deal.get('close_date')
    
    if not create_date:
        continue
    
    create_dt = datetime.fromisoformat(create_date).date()
    
    # Created before or on week-3
    if create_dt > week3_dt:
        continue
    
    # Still open OR closed after week-3
    if not close_date:
        genuinely_open_all_pipelines.append(deal)
    else:
        close_dt = datetime.fromisoformat(close_date).date()
        if close_dt >= week3_dt:
            genuinely_open_all_pipelines.append(deal)

genuinely_open_default = [d for d in genuinely_open_all_pipelines 
                          if d.get('pipeline_id') == 'default']

genuinely_open_all_ids = set(d['deal_id'] for d in genuinely_open_all_pipelines)
genuinely_open_default_ids = set(d['deal_id'] for d in genuinely_open_default)

print(f"\nSet 2: Genuinely open on {week3_date} (from deals table)")
print(f"  All pipelines: {len(genuinely_open_all_pipelines):,} deals")
print(f"  Default pipeline only: {len(genuinely_open_default):,} deals")

# Compare snapshot (default) to genuinely open (default)
in_both = snapshot_deal_ids & genuinely_open_default_ids
in_snapshot_only = snapshot_deal_ids - genuinely_open_default_ids
in_genuinely_open_only = genuinely_open_default_ids - snapshot_deal_ids

print(f"\n" + "=" * 80)
print("COMPARISON: Snapshot (default) vs Genuinely Open (default)")
print("=" * 80)

print(f"\nIn both sets: {len(in_both):,}")
print(f"In snapshot only: {len(in_snapshot_only):,} (shouldn't exist)")
print(f"In genuinely_open only: {len(in_genuinely_open_only):,} (missing from snapshot)")

# Investigate missing deals
if in_genuinely_open_only:
    print(f"\n{'='*80}")
    print(f"WHY ARE {len(in_genuinely_open_only):,} DEALS MISSING FROM SNAPSHOT?")
    print(f"{'='*80}")
    
    reasons = Counter()
    
    for deal_id in list(in_genuinely_open_only)[:200]:
        # Check if deal appears in ANY snapshot for FY2026 Q4
        q4_snapshots = select_all(sb, 'deals_snapshot',
                                  columns='snapshot_date, week_of_quarter',
                                  filters=[('eq', 'deal_id', deal_id),
                                          ('eq', 'fiscal_quarter', quarter)])
        
        if not q4_snapshots:
            reasons["Never in FY2026 Q4 snapshot"] += 1
        else:
            weeks = sorted(set(s.get('week_of_quarter') for s in q4_snapshots if s.get('week_of_quarter')))
            if 3 not in weeks:
                reasons[f"In Q4 snapshot but not week-3"] += 1
            else:
                reasons["In week-3 but wrong pipeline"] += 1
    
    print(f"\nReason breakdown (sampled {min(200, len(in_genuinely_open_only))} of {len(in_genuinely_open_only)} missing deals):")
    for reason, count in sorted(reasons.items(), key=lambda x: -x[1]):
        pct = count / min(200, len(in_genuinely_open_only)) * 100
        print(f"  {reason}: {count} ({pct:.1f}%)")

# Investigate deals in snapshot only (shouldn't exist)
if in_snapshot_only:
    print(f"\n{'='*80}")
    print(f"WHY ARE {len(in_snapshot_only):,} DEALS IN SNAPSHOT BUT NOT GENUINELY OPEN?")
    print(f"{'='*80}")
    
    for deal_id in list(in_snapshot_only)[:10]:
        deal = next((d for d in deals if d['deal_id'] == deal_id), None)
        if deal:
            create = deal.get('create_date')
            close = deal.get('close_date')
            pipeline = deal.get('pipeline_id')
            
            if not create:
                reason = "Missing create_date"
            else:
                create_dt = datetime.fromisoformat(create).date()
                if create_dt > week3_dt:
                    reason = f"Created AFTER week-3"
                elif close:
                    close_dt = datetime.fromisoformat(close).date()
                    if close_dt < week3_dt:
                        reason = f"Closed BEFORE week-3"
                    else:
                        reason = "Should be in genuinely_open (logic mismatch)"
                else:
                    reason = "Should be in genuinely_open (logic mismatch)"
            
            print(f"  Deal {deal_id}: create={create}, close={close}, pipeline={pipeline} → {reason}")

print(f"\n{'='*80}")
print("SUMMARY")
print(f"{'='*80}")

print(f"\nSnapshot (default pipeline): {len(snapshot_deal_ids):,} deals")
print(f"Genuinely open (default pipeline): {len(genuinely_open_default_ids):,} deals")
print(f"Gap: {len(genuinely_open_default_ids) - len(snapshot_deal_ids):,} deals")

print(f"\nBreakdown:")
print(f"  Missing from snapshot: {len(in_genuinely_open_only):,} ({len(in_genuinely_open_only)/len(genuinely_open_default_ids)*100:.1f}%)")
print(f"  In snapshot but not genuinely open: {len(in_snapshot_only):,} ({len(in_snapshot_only)/len(snapshot_deal_ids)*100:.1f}%)")

if reasons:
    top_reason = reasons.most_common(1)[0]
    print(f"\nPrimary reason for gap: {top_reason[0]} ({top_reason[1]} deals)")

