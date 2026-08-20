#!/usr/bin/env python3
"""
Verify coverage on backfilled weeks (FY2027 Q3 weeks 1-3).
"""
import os
import sys
from datetime import datetime, date
from dotenv import load_dotenv

load_dotenv()

sys.path.insert(0, 'scripts')
from supabase import create_client
from supabase_client import select_all

sb = create_client(os.environ['SUPABASE_URL'], os.environ['SUPABASE_SERVICE_KEY'])

print("=" * 80)
print("BACKFILLED WEEKS COVERAGE VERIFICATION")
print("=" * 80)

# Check weeks 1-3 of FY2027 Q3
backfilled_dates = [
    ('Week 1', '2026-08-03'),
    ('Week 2', '2026-08-10'),
    ('Week 3', '2026-08-17')
]

# Get all deals
deals = select_all(sb, 'deals',
                  columns='deal_id, create_date, close_date, pipeline_id')

for week_label, snapshot_date in backfilled_dates:
    snapshot_dt = datetime.fromisoformat(snapshot_date).date()
    
    print(f"\n{'='*80}")
    print(f"{week_label} ({snapshot_date})")
    print(f"{'='*80}")
    
    # Get snapshot for this date
    snapshot = select_all(sb, 'deals_snapshot',
                          columns='deal_id, pipeline_id',
                          filters=[('eq', 'snapshot_date', snapshot_date)])
    
    # Get pipelines
    pipelines = set(d.get('pipeline_id') for d in deals if d.get('pipeline_id'))
    
    all_pass = True
    
    for pipeline_id in sorted(pipelines, key=lambda x: (x != 'default', x)):
        # Snapshot count
        snapshot_pipeline = [s for s in snapshot if s.get('pipeline_id') == pipeline_id]
        snapshot_count = len(snapshot_pipeline)
        
        # Genuinely open count
        genuinely_open = []
        for d in deals:
            if d.get('pipeline_id') != pipeline_id:
                continue
            
            create_date = d.get('create_date')
            if not create_date:
                continue
            
            create_dt = datetime.fromisoformat(create_date).date()
            if create_dt > snapshot_dt:
                continue
            
            close_date = d.get('close_date')
            if close_date:
                close_dt = datetime.fromisoformat(close_date).date()
                if close_dt < snapshot_dt:
                    continue
            
            genuinely_open.append(d)
        
        genuinely_open_count = len(genuinely_open)
        coverage_pct = (snapshot_count / genuinely_open_count * 100) if genuinely_open_count > 0 else 0
        
        status = "✓ PASS" if coverage_pct >= 95 else "✗ FAIL"
        if coverage_pct < 95:
            all_pass = False
        
        print(f"  {pipeline_id:<20} Open: {genuinely_open_count:>4}  Captured: {snapshot_count:>4}  "
              f"Coverage: {coverage_pct:>5.1f}%  {status}")
    
    if not all_pass:
        print(f"\n  ⚠️  {week_label} has pipelines below 95% threshold")

print(f"\n{'='*80}")
print("VERDICT")
print(f"{'='*80}")

print(f"\nAll backfilled weeks checked against 95% coverage threshold")
print(f"If all weeks passed, backfill reconstruction is reliable")
print(f"If any failed, backfill has same class of problem as historical snapshots")

