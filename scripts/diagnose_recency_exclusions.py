#!/usr/bin/env python3
"""
Diagnose why 137 deals with notes_last_updated → only 79 with activity
"""
import sys
import json
from pathlib import Path
from dotenv import load_dotenv
from datetime import datetime, timezone
from collections import defaultdict, Counter

env_path = Path(__file__).parent.parent / ".env"
load_dotenv(env_path)

sys.path.insert(0, str(Path(__file__).parent.parent / 'api'))
from db import get_supabase
from field_semantics import is_won, stage_bucket

TRUNCATION_THRESHOLD_DAYS = 30

def parse_date(date_str):
    if not date_str:
        return None
    try:
        if isinstance(date_str, datetime):
            return date_str
        dt = datetime.fromisoformat(str(date_str).replace('Z', '+00:00'))
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        return dt
    except:
        return None

def main():
    sb = get_supabase()

    # Load bulk cleanup deal_ids
    bulk_cleanup_file = Path(__file__).parent.parent / 'bulk_cleanup_deal_ids.json'
    with open(bulk_cleanup_file, 'r') as f:
        bulk_data = json.load(f)

    bulk_cleanup_deal_ids = set(bulk_data['deal_ids'])

    # Fetch closed deals
    all_deals = sb.table('deals').select(
        'deal_id,company_name,stage,deal_status,segment,create_date,close_date'
    ).execute().data

    closed_deals = []
    for deal in all_deals:
        if str(deal['deal_id']) in bulk_cleanup_deal_ids:
            continue

        if is_won(deal.get('stage')):
            deal['outcome'] = 'won'
            closed_deals.append(deal)
        elif deal.get('deal_status') == 'lost':
            deal['outcome'] = 'lost'
            closed_deals.append(deal)

    # Fetch property history
    deal_ids = [str(d['deal_id']) for d in closed_deals]

    batch_size = 100
    all_history = []

    for i in range(0, len(deal_ids), batch_size):
        batch = deal_ids[i:i+batch_size]
        history_batch = sb.table('property_history').select(
            'deal_id,property_name,changed_at,new_value'
        ).in_('deal_id', batch).order('changed_at', desc=False).execute()
        all_history.extend(history_batch.data)

    # Group by deal
    history_by_deal = defaultdict(lambda: {'notes_last_updated': [], 'dealstage': []})

    for row in all_history:
        deal_id = row['deal_id']
        prop_name = row['property_name']
        changed_at = parse_date(row['changed_at'])
        new_value = row['new_value']

        if prop_name in ['notes_last_updated', 'dealstage'] and changed_at:
            history_by_deal[deal_id][prop_name].append({
                'changed_at': changed_at,
                'new_value': new_value
            })

    # Count exclusions
    exclusion_reasons = Counter()
    included_count = 0

    for deal in closed_deals:
        deal_id = str(deal['deal_id'])

        if deal_id not in history_by_deal:
            exclusion_reasons['no_property_history'] += 1
            continue

        nlu_history = history_by_deal[deal_id]['notes_last_updated']
        dealstage_history = history_by_deal[deal_id]['dealstage']

        close_date = parse_date(deal.get('close_date'))
        create_date = parse_date(deal.get('create_date'))

        if not close_date or not create_date:
            exclusion_reasons['no_dates'] += 1
            continue

        if not nlu_history:
            exclusion_reasons['no_nlu_history'] += 1
            continue

        # Find last activity
        activities = []
        for change in nlu_history:
            changed_at = change['changed_at']
            activity_date = parse_date(change['new_value']) if change['new_value'] else changed_at
            if activity_date:
                activities.append(activity_date)

        if not activities:
            exclusion_reasons['no_parseable_activities'] += 1
            continue

        activities = sorted(activities)
        last_activity = activities[-1]

        # Compute last gap
        last_gap_days = (close_date - last_activity).days

        if last_gap_days < 0:
            exclusion_reasons['negative_gap'] += 1
            continue

        # Determine stage at time of last activity
        stage_timeline = sorted(dealstage_history, key=lambda x: x['changed_at'])

        current_stage = None
        for change in stage_timeline:
            if change['changed_at'] <= last_activity:
                current_stage = change['new_value']
            else:
                break

        if not current_stage:
            exclusion_reasons['no_stage_at_last_activity'] += 1
            continue

        bucket = stage_bucket(current_stage)

        if bucket in ['closed_won', 'closed_lost', 'unknown']:
            exclusion_reasons[f'stage_bucket_{bucket}'] += 1
            continue

        # This deal would be INCLUDED
        included_count += 1

    print("=" * 80)
    print("RECENCY EXCLUSION DIAGNOSIS")
    print("=" * 80)
    print()

    print(f"Total clean closed deals: {len(closed_deals)}")
    print(f"Deals with notes_last_updated in property_history: 137 (expected)")
    print(f"Deals included in recency analysis: {included_count}")
    print()

    print("Exclusion reasons:")
    for reason, count in sorted(exclusion_reasons.items(), key=lambda x: -x[1]):
        print(f"  {reason}: {count}")

    print()
    print(f"Expected discrepancy: 137 - {included_count} = {137 - included_count}")

if __name__ == '__main__':
    main()
