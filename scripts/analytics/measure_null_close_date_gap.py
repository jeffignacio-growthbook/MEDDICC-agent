#!/usr/bin/env python3
"""
Measure rows with NULL close_date but terminal deal_status.

These pass the current inclusion rule (close_date IS NULL = valid)
but represent closed deals that shouldn't be in open pipeline snapshots.
"""
import os
import sys
from datetime import datetime
from collections import Counter, defaultdict
import yaml

from dotenv import load_dotenv
load_dotenv()

sys.path.insert(0, 'scripts')
from supabase import create_client
from supabase_client import select_all

sb = create_client(os.environ['SUPABASE_URL'], os.environ['SUPABASE_SERVICE_KEY'])

# Load field semantics
with open('config/field_semantics.yaml') as f:
    semantics = yaml.safe_load(f)

stage_map = semantics['stage_map']
outcome_buckets = semantics['outcome_buckets']

# Build terminal stage set
terminal_stages = set()
for stage_id, stage_config in stage_map.items():
    bucket = stage_config.get('bucket')
    if bucket in outcome_buckets.get('won', []) or bucket in outcome_buckets.get('lost', []):
        terminal_stages.add(stage_id)
        # Add aliases
        for alias in stage_config.get('aliases', []):
            terminal_stages.add(str(alias))

print("=" * 80)
print("NULL close_date GAP ANALYSIS")
print("=" * 80)

print(f"\nTerminal stages: {len(terminal_stages)} stage IDs")
print(f"Examples: {sorted(list(terminal_stages))[:5]}")

quarters = ['FY2026 Q4', 'FY2027 Q1', 'FY2027 Q2']
quarter_results = {}

for q_name in quarters:
    print(f"\n" + "=" * 80)
    print(f"{q_name}")
    print("=" * 80)
    
    # Get all snapshots for this quarter
    q_snapshots = select_all(sb, 'deals_snapshot',
                             columns='deal_id, snapshot_date, week_of_quarter, close_date, stage_id, deal_status, pipeline_id',
                             filters=[('eq', 'fiscal_quarter', q_name)])
    
    # Filter to default pipeline
    q_snapshots = [s for s in q_snapshots if s.get('pipeline_id') == 'default']
    
    print(f"\nTotal default pipeline snapshots: {len(q_snapshots):,}")
    
    # Count NULL close_date
    null_close = [s for s in q_snapshots if not s.get('close_date')]
    has_close = [s for s in q_snapshots if s.get('close_date')]
    
    print(f"  With close_date: {len(has_close):,}")
    print(f"  NULL close_date: {len(null_close):,} ({len(null_close)/len(q_snapshots)*100:.1f}%)")
    
    # Of NULL close_date, count terminal deal_status
    terminal_by_status = [s for s in null_close 
                         if s.get('deal_status') in ['won', 'lost']]
    
    terminal_by_stage = [s for s in null_close
                        if str(s.get('stage_id', '')).lower() in terminal_stages]
    
    print(f"\n  NULL close_date AND terminal:")
    print(f"    By deal_status (won/lost): {len(terminal_by_status):,}")
    print(f"    By stage_id (in terminal set): {len(terminal_by_stage):,}")
    
    # Show overlap
    both = set(s['deal_id'] + s['snapshot_date'] for s in terminal_by_status) & \
           set(s['deal_id'] + s['snapshot_date'] for s in terminal_by_stage)
    print(f"    Overlap: {len(both):,}")
    
    # Week-3 analysis
    week3 = [s for s in q_snapshots if s.get('week_of_quarter') == 3]
    week3_date = sorted(set(s['snapshot_date'] for s in week3))[0] if week3 else None
    
    print(f"\n  Week-3 ({week3_date}):")
    print(f"    Total rows: {len(week3):,}")
    
    week3_null_close = [s for s in week3 if not s.get('close_date')]
    print(f"    NULL close_date: {len(week3_null_close):,}")
    
    week3_terminal_status = [s for s in week3_null_close 
                            if s.get('deal_status') in ['won', 'lost']]
    week3_terminal_stage = [s for s in week3_null_close
                           if str(s.get('stage_id', '')).lower() in terminal_stages]
    
    print(f"    NULL + terminal by status: {len(week3_terminal_status):,}")
    print(f"    NULL + terminal by stage: {len(week3_terminal_stage):,}")
    
    # Sample terminal NULL rows
    if week3_terminal_stage:
        print(f"\n  Sample week-3 NULL close_date but terminal stage:")
        for s in week3_terminal_stage[:3]:
            print(f"    Deal {s['deal_id']}: stage={s['stage_id']}, status={s.get('deal_status')}, close_date=NULL")
    
    quarter_results[q_name] = {
        'total_snapshots': len(q_snapshots),
        'null_close_count': len(null_close),
        'null_close_pct': len(null_close)/len(q_snapshots)*100 if q_snapshots else 0,
        'terminal_by_status': len(terminal_by_status),
        'terminal_by_stage': len(terminal_by_stage),
        'week3_total': len(week3),
        'week3_null_close': len(week3_null_close),
        'week3_terminal_status': len(week3_terminal_status),
        'week3_terminal_stage': len(week3_terminal_stage)
    }

# Summary table
print("\n" + "=" * 80)
print("SUMMARY: NULL close_date + Terminal Status Gap")
print("=" * 80)

print(f"\n{'Quarter':<15} {'Total':>8} {'NULL':>8} {'%':>6} {'Term(st)':>9} {'Term(sg)':>9} {'W3 Total':>9} {'W3 NULL':>9} {'W3 Term':>9}")
print("-" * 100)

for q_name in quarters:
    r = quarter_results[q_name]
    print(f"{q_name:<15} {r['total_snapshots']:>8,} {r['null_close_count']:>8,} "
          f"{r['null_close_pct']:>5.1f}% {r['terminal_by_status']:>9,} "
          f"{r['terminal_by_stage']:>9,} {r['week3_total']:>9,} "
          f"{r['week3_null_close']:>9,} {r['week3_terminal_stage']:>9,}")

# Assessment
print("\n" + "=" * 80)
print("ASSESSMENT")
print("=" * 80)

total_week3_terminal = sum(r['week3_terminal_stage'] for r in quarter_results.values())
total_week3_rows = sum(r['week3_total'] for r in quarter_results.values())

print(f"\nWeek-3 aggregate:")
print(f"  Total rows: {total_week3_rows:,}")
print(f"  NULL close_date + terminal stage: {total_week3_terminal:,}")
print(f"  Impact on denominator: {total_week3_terminal/total_week3_rows*100:.2f}%")

if total_week3_terminal == 0:
    print(f"\n✓ Gap is ZERO - current inclusion rule is sufficient")
    print(f"  All NULL close_date rows have open deal_status/stage_id")
    print(f"  Proceed with verification")
elif total_week3_terminal < 10:
    print(f"\n✓ Gap is MINIMAL ({total_week3_terminal} rows) - likely acceptable")
    print(f"  Impact on denominators: <{total_week3_terminal/total_week3_rows*100:.1f}%")
    print(f"  Recommend: Proceed with verification, optionally flag for review")
else:
    print(f"\n⚠️  Gap is MATERIAL ({total_week3_terminal} rows)")
    print(f"  Impact on week-3 denominators: {total_week3_terminal/total_week3_rows*100:.1f}%")
    print(f"\n  RECOMMENDATION:")
    print(f"  Refined inclusion rule needed:")
    print(f"    create_date <= D AND")
    print(f"    (close_date IS NULL OR close_date >= D) AND")
    print(f"    stage_id NOT IN (terminal_stages)")
    print(f"\n  This would require a follow-up purge of {total_week3_terminal:,} week-3 rows")
    print(f"  (Extrapolate to all weeks for full quarter impact)")
    print(f"\n  Do NOT run automatically - requires separate approval")

print("\n" + "=" * 80)

