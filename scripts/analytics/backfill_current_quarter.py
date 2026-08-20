#!/usr/bin/env python3
"""
Backfill elapsed weeks of current quarter.

Creates point-in-time snapshots for each Monday that has passed
in the current fiscal quarter, using current deals table state
(which is valid for recent weeks since deals don't change pipeline/stage frequently).
"""
import os
import sys
from datetime import date, timedelta
from pathlib import Path
from dotenv import load_dotenv

load_dotenv()

REPO_ROOT = Path(__file__).parent.parent.parent
sys.path.insert(0, str(REPO_ROOT / 'scripts'))

from utils import get_fiscal_quarter, get_stage_order
from supabase import create_client
from supabase_client import select_all

def get_week_of_quarter(snapshot_date, quarter_start):
    """Calculate week number within fiscal quarter (1-13)."""
    from datetime import datetime
    if isinstance(snapshot_date, str):
        snapshot_date = datetime.strptime(snapshot_date, '%Y-%m-%d').date()
    if isinstance(quarter_start, str):
        quarter_start = datetime.strptime(quarter_start, '%Y-%m-%d').date()
    
    days_into_quarter = (snapshot_date - quarter_start).days
    week_num = (days_into_quarter // 7) + 1
    return min(week_num, 13)

def main():
    sb = create_client(os.getenv('SUPABASE_URL'), os.getenv('SUPABASE_SERVICE_KEY'))
    
    today = date.today()
    q_start, q_end, q_label = get_fiscal_quarter(today)
    
    print("=" * 80)
    print(f"BACKFILL CURRENT QUARTER: {q_label}")
    print("=" * 80)
    
    print(f"\nQuarter dates: {q_start} to {q_end}")
    print(f"Today: {today}")
    
    # Calculate weeks elapsed
    days_in = (today - q_start).days
    current_week = (days_in // 7) + 1
    
    print(f"Current week: {current_week}")
    
    # Generate Mondays for weeks 1 through current_week
    mondays = []
    for week_num in range(1, current_week + 1):
        # Find Monday of this week
        days_offset = (week_num - 1) * 7
        monday = q_start + timedelta(days=days_offset)
        
        # Adjust to actual Monday (q_start might not be Monday)
        days_to_monday = (0 - monday.weekday()) % 7
        if days_to_monday == 0 and monday.weekday() != 0:
            days_to_monday = 7
        monday = monday + timedelta(days=days_to_monday) if monday.weekday() != 0 else monday
        
        # Only include Mondays that have passed
        if monday <= today:
            mondays.append((week_num, monday))
    
    print(f"\nMondays to backfill: {len(mondays)}")
    for week_num, monday in mondays:
        print(f"  Week {week_num}: {monday}")
    
    # Get all deals
    deals = select_all(sb, 'deals',
                      'deal_id, pipeline_id, stage, deal_value, '
                      'close_date, owner_email, deal_status, create_date, '
                      'highest_stage_order_reached, forecast_category')
    
    print(f"\nTotal deals in database: {len(deals):,}")
    
    # For each Monday, create snapshot
    from datetime import datetime
    
    total_written = 0
    
    for week_num, snapshot_date in mondays:
        snapshot_dt = snapshot_date
        
        # Filter to deals that belong in this snapshot
        qualified_deals = []
        for d in deals:
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
            
            qualified_deals.append(d)
        
        # Build snapshot rows
        snapshots = []
        for d in qualified_deals:
            order = get_stage_order(d.get('stage', '')) or 0
            snapshots.append({
                'deal_id': d['deal_id'],
                'snapshot_date': snapshot_dt.isoformat(),
                'pipeline_id': d.get('pipeline_id', 'default'),
                'stage_id': d.get('stage'),
                'stage_order': order,
                'deal_value': d.get('deal_value'),
                'close_date': d.get('close_date'),
                'owner_email': d.get('owner_email'),
                'deal_status': d.get('deal_status', 'active'),
                'snapshot_source': 'backfill_current_quarter',
                'forecast_category': d.get('forecast_category'),
                'fiscal_quarter': q_label,
                'week_of_quarter': week_num,
            })
        
        # Upsert
        batch_size = 100
        written = 0
        for i in range(0, len(snapshots), batch_size):
            batch = snapshots[i:i + batch_size]
            sb.table('deals_snapshot').upsert(
                batch,
                on_conflict='deal_id,snapshot_date'
            ).execute()
            written += len(batch)
        
        total_written += written
        print(f"\n  Week {week_num} ({snapshot_dt}): {written} deals")
    
    print(f"\n{'='*80}")
    print(f"BACKFILL COMPLETE")
    print(f"{'='*80}")
    print(f"\nTotal snapshots written: {total_written}")
    print(f"Weeks backfilled: {len(mondays)}")
    print(f"\n✓ {q_label} now has complete snapshot history from week 1")

if __name__ == '__main__':
    main()

