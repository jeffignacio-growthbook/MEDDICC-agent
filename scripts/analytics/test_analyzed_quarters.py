#!/usr/bin/env python3
"""
Guard test for analyzed quarters only (FY2026 Q4, FY2027 Q1, FY2027 Q2).
"""
import os
import sys
from datetime import datetime
from dotenv import load_dotenv

load_dotenv()

sys.path.insert(0, 'scripts')
from supabase import create_client
from supabase_client import select_all

sb = create_client(os.environ['SUPABASE_URL'], os.environ['SUPABASE_SERVICE_KEY'])

analyzed_quarters = ['FY2026 Q4', 'FY2027 Q1', 'FY2027 Q2']

print("=" * 80)
print("GUARD TEST: Analyzed Quarters Only")
print("=" * 80)

violations_by_quarter = {}

for q_name in analyzed_quarters:
    snapshots = select_all(sb, 'deals_snapshot',
                          columns='deal_id, snapshot_date, close_date',
                          filters=[('eq', 'fiscal_quarter', q_name)])
    
    violations = []
    for snap in snapshots:
        snapshot_date = snap.get('snapshot_date')
        close_date = snap.get('close_date')
        
        if not close_date or not snapshot_date:
            continue
        
        snapshot_dt = datetime.fromisoformat(snapshot_date).date()
        close_dt = datetime.fromisoformat(close_date).date()
        
        if close_dt < snapshot_dt:
            violations.append({
                'deal_id': snap['deal_id'],
                'snapshot_date': snapshot_date,
                'close_date': close_date,
                'days_before': (snapshot_dt - close_dt).days
            })
    
    violations_by_quarter[q_name] = violations
    print(f"\n{q_name}: {len(snapshots):,} rows, {len(violations):,} violations")
    
    if violations:
        print(f"  Sample violations:")
        for v in violations[:3]:
            print(f"    Deal {v['deal_id']}: closed {v['close_date']}, "
                  f"in snapshot {v['snapshot_date']} ({v['days_before']} days before)")

total_violations = sum(len(v) for v in violations_by_quarter.values())

print("\n" + "=" * 80)
if total_violations == 0:
    print("✓ TEST PASSED: No violations in analyzed quarters")
    print("  All three analyzed quarters are clean")
    sys.exit(0)
else:
    print(f"✗ TEST FAILED: {total_violations} violations in analyzed quarters")
    sys.exit(1)
