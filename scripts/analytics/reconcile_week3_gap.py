#!/usr/bin/env python3
"""
Reconcile FY2026 Q4 week-3: 221 snapshot rows vs genuinely open deals.

Identify which deals are in genuinely_open but not in snapshot, and why.
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
print("FY2026 Q4 WEEK-3 RECONCILIATION")
print("=" * 80)

quarter = 'FY2026 Q4'
week3_date = '2025-11-18'
week3_dt = datetime.fromisoformat(week3_date).date()

# Set 1: Snapshot rows (what inclusion rule retained)
snapshot_rows = select_all(sb, 'deals_snapshot',
                           columns='deal_id, snapshot_date, pipeline_id',
                           filters=[('eq', 'fiscal_quarter', quarter),
                                   ('eq', 'week_of_quarter', 3)])

snapshot_default = [s for s in snapshot_rows if s.get('pipeline_id') == 'default']
snapshot_deal_ids = set(s['deal_id'] for s in snapshot_default)

print(f"\nSet 1: Snapshot rows at week-3 ({week3_date})")
print(f"  Total: {len(snapshot_rows):,}")
print(f"  Default pipeline: {len(snapshot_default):,}")
print(f"  Unique deal IDs: {len(snapshot_deal_ids):,}")

# Set 2: Genuinely open deals (from deals table logic)
deals = select_all(sb, 'deals',
                  columns='deal_id, create_date, close_date, pipeline_id')

genuinely_open = []
for deal in deals:
    create_date = deal.get('create_date')
    close_date = deal.get('close_date')
    pipeline_id = deal.get('pipeline_id')
    
    # Must be default pipeline
    if pipeline_id != 'default':
        continue
    
    if not create_date:
        continue
    
    create_dt = datetime.fromisoformat(create_date).date()
    
    # Created before or on week-3
    if create_dt > week3_dt:
        continue
    
    # Still open OR closed after week-3
    if not close_date:
        genuinely_open.append(deal)
    else:
        close_dt = datetime.fromisoformat(close_date).date()
        if close_dt >= week3_dt:
            genuinely_open.append(deal)

genuinely_open_ids = set(d['deal_id'] for d in genuinely_open)

print(f"\nSet 2: Genuinely open on {week3_date} (from deals table)")
print(f"  Deals meeting criteria: {len(genuinely_open):,}")
print(f"  Unique deal IDs: {len(genuinely_open_ids):,}")

# Find overlap and gaps
in_both = snapshot_deal_ids & genuinely_open_ids
in_snapshot_only = snapshot_deal_ids - genuinely_open_ids
in_genuinely_open_only = genuinely_open_ids - snapshot_deal_ids

print(f"\n" + "=" * 80)
print("VENN DIAGRAM")
print("=" * 80)

print(f"\nIn both sets: {len(in_both):,}")
print(f"In snapshot only: {len(in_snapshot_only):,}")
print(f"In genuinely_open only: {len(in_genuinely_open_only):,}")

# Investigate snapshot-only deals (shouldn't exist if logic is correct)
if in_snapshot_only:
    print(f"\n{'='*80}")
    print(f"INVESTIGATING: In snapshot but NOT genuinely open ({len(in_snapshot_only):,} deals)")
    print(f"{'='*80}")
    print(f"These deals are in the snapshot but fail the 'genuinely open' criteria.")
    
    for deal_id in list(in_snapshot_only)[:5]:
        deal = next((d for d in deals if d['deal_id'] == deal_id), None)
        if deal:
            create_date = deal.get('create_date')
            close_date = deal.get('close_date')
            
            # Check why it fails
            if not create_date:
                reason = "No create_date"
            else:
                create_dt = datetime.fromisoformat(create_date).date()
                if create_dt > week3_dt:
                    reason = f"Created after week-3 ({create_date} > {week3_date})"
                elif close_date:
                    close_dt = datetime.fromisoformat(close_date).date()
                    if close_dt < week3_dt:
                        reason = f"Closed before week-3 ({close_date} < {week3_date})"
                    else:
                        reason = "Unknown (closed on/after week-3 - should be included)"
                else:
                    reason = "Unknown (should be included)"
            
            print(f"  Deal {deal_id}: create={create_date}, close={close_date} → {reason}")

# Investigate genuinely-open-only deals (the gap we need to explain)
if in_genuinely_open_only:
    print(f"\n{'='*80}")
    print(f"INVESTIGATING: Genuinely open but NOT in snapshot ({len(in_genuinely_open_only):,} deals)")
    print(f"{'='*80}")
    print(f"These are deals that should be in the snapshot but are missing.")
    
    reasons = Counter()
    
    # Check a sample
    for deal_id in list(in_genuinely_open_only)[:100]:
        # Check if deal appears in ANY snapshot for this quarter
        all_q_snapshots = select_all(sb, 'deals_snapshot',
                                     columns='snapshot_date, week_of_quarter',
                                     filters=[('eq', 'deal_id', deal_id),
                                             ('eq', 'fiscal_quarter', quarter)])
        
        if not all_q_snapshots:
            reasons["Never in any quarter snapshot"] += 1
        else:
            weeks = sorted(set(s.get('week_of_quarter') for s in all_q_snapshots if s.get('week_of_quarter')))
            if 3 not in weeks:
                reasons[f"In weeks {weeks} but not week-3"] += 1
            else:
                # Present in week-3 snapshots, but not in default pipeline?
                w3_pipelines = [s for s in all_q_snapshots if s.get('week_of_quarter') == 3]
                reasons["Week-3 snapshot but non-default pipeline"] += 1
    
    print(f"\n  Reason breakdown (sample of 100):")
    for reason, count in sorted(reasons.items(), key=lambda x: -x[1]):
        print(f"    {reason}: {count}")

print(f"\n{'='*80}")
print("SUMMARY")
print(f"{'='*80}")

print(f"\nSnapshot rows: {len(snapshot_deal_ids):,}")
print(f"Genuinely open: {len(genuinely_open_ids):,}")
print(f"Gap: {len(genuinely_open_ids) - len(snapshot_deal_ids):,} deals")

if len(in_genuinely_open_only) > 0:
    pct_missing = len(in_genuinely_open_only) / len(genuinely_open_ids) * 100
    print(f"\n{len(in_genuinely_open_only):,} deals ({pct_missing:.1f}%) are genuinely open but missing from snapshot")
    print(f"Primary reason: {reasons.most_common(1)[0] if reasons else 'Unknown'}")

