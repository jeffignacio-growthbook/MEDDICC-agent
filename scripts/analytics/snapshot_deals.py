#!/usr/bin/env python3
"""
Weekly (or nightly) snapshot of all deals into deals_snapshot.
Idempotent — running twice same day upserts, not duplicates.
Must be run AFTER etl_deals.py --mode analytics so the
deals table is current.

Usage: python scripts/analytics/snapshot_deals.py
"""

import os
import json
from datetime import date, datetime
from pathlib import Path

REPO_ROOT = Path(__file__).parent.parent.parent


def get_week_of_quarter(snapshot_date, quarter_start):
    """
    Calculate week number within fiscal quarter (1-13).

    Args:
        snapshot_date: Date of the snapshot
        quarter_start: Start date of the fiscal quarter

    Returns:
        int: Week number (1-13)
    """
    if isinstance(snapshot_date, str):
        snapshot_date = datetime.strptime(snapshot_date, '%Y-%m-%d').date()
    if isinstance(quarter_start, str):
        quarter_start = datetime.strptime(quarter_start, '%Y-%m-%d').date()

    days_into_quarter = (snapshot_date - quarter_start).days
    week_num = (days_into_quarter // 7) + 1

    # Cap at 13 weeks (91 days)
    return min(week_num, 13)


def main():
    SUPABASE_URL = os.getenv('SUPABASE_URL')
    SUPABASE_KEY = os.getenv('SUPABASE_SERVICE_KEY')
    if not SUPABASE_URL or not SUPABASE_KEY:
        print("⚠️  SUPABASE_URL or SUPABASE_SERVICE_KEY not set")
        return

    from supabase import create_client
    import sys
    sys.path.insert(0, str(REPO_ROOT / 'scripts'))
    from supabase_client import select_all

    sb = create_client(SUPABASE_URL, SUPABASE_KEY)

    today = date.today().isoformat()
    today_date = date.today()

    # Calculate fiscal quarter and week for today's snapshot
    from utils import get_fiscal_quarter
    q_start, q_end, fiscal_quarter_label = get_fiscal_quarter(today_date)
    week_of_quarter = get_week_of_quarter(today_date, q_start)

    # Read all current deals from Supabase (paginated)
    deals = select_all(
        sb, 'deals',
        'deal_id, pipeline_id, stage, deal_value, '
        'close_date, owner_email, deal_status, '
        'highest_stage_order_reached, forecast_category'
    )
    if not deals:
        print("No deals in Supabase — run etl_deals.py first")
        return

    # Build snapshot rows
    from utils import get_stage_order

    snapshots = []
    for d in deals:
        order = get_stage_order(d.get('stage', '')) or 0
        snapshots.append({
            'deal_id': d['deal_id'],
            'snapshot_date': today,
            'pipeline_id': d.get('pipeline_id', 'default'),
            'stage_id': d.get('stage'),
            'stage_order': order,
            'deal_value': d.get('deal_value'),
            'close_date': d.get('close_date'),
            'owner_email': d.get('owner_email'),
            'deal_status': d.get('deal_status', 'active'),
            'snapshot_source': 'prospective',
            'forecast_category': d.get('forecast_category'),
            'fiscal_quarter': fiscal_quarter_label,
            'week_of_quarter': week_of_quarter,
        })

    # Upsert (idempotent on deal_id + snapshot_date PK)
    written = 0
    batch_size = 100
    for i in range(0, len(snapshots), batch_size):
        batch = snapshots[i:i + batch_size]
        sb.table('deals_snapshot').upsert(
            batch,
            on_conflict='deal_id,snapshot_date'
        ).execute()
        written += len(batch)

    print(f"✓ Snapshot {today}: {written} deals written to "
          f"deals_snapshot")


if __name__ == '__main__':
    main()
