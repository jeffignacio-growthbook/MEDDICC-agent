#!/usr/bin/env python3
"""
Export raw gap distributions to CSV for analysis

Shows the FULL distribution of gaps for won vs lost in each cell,
so we can see exactly why Lost P25 = 0.
"""
import sys
import json
import csv
from pathlib import Path
from dotenv import load_dotenv
import statistics
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

    print("=" * 80)
    print("EXPORTING RAW GAP DISTRIBUTIONS")
    print("=" * 80)
    print()

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

    # Compute gaps by cell
    gaps_by_cell = defaultdict(lambda: {'won': [], 'lost': []})

    for deal in closed_deals:
        deal_id = str(deal['deal_id'])

        if deal_id not in history_by_deal:
            continue

        nlu_history = history_by_deal[deal_id]['notes_last_updated']
        dealstage_history = history_by_deal[deal_id]['dealstage']

        if not nlu_history or not dealstage_history:
            continue

        create_date = parse_date(deal.get('create_date'))
        close_date = parse_date(deal.get('close_date'))

        if not create_date or not close_date:
            continue

        # Build activities
        activities = []
        for change in nlu_history:
            activity_date = parse_date(change['new_value']) if change['new_value'] else change['changed_at']
            if activity_date:
                activities.append(activity_date)

        if len(activities) < 2:
            continue

        activities = sorted(activities)

        # Truncation handling
        earliest_activity = activities[0]
        days_after_creation = (earliest_activity - create_date).days
        truncation_boundary = earliest_activity if days_after_creation > TRUNCATION_THRESHOLD_DAYS else None

        # Build stage timeline
        stage_timeline = sorted(dealstage_history, key=lambda x: x['changed_at'])

        def get_stage_at_time(timestamp):
            current_stage = None
            for change in stage_timeline:
                if change['changed_at'] <= timestamp:
                    current_stage = change['new_value']
                else:
                    break
            return current_stage

        # Compute gaps
        segment = deal.get('segment') or 'Unknown'
        outcome = deal['outcome']

        for i in range(len(activities) - 1):
            activity_1 = activities[i]
            activity_2 = activities[i + 1]

            if truncation_boundary and activity_1 < truncation_boundary:
                continue

            gap_days = (activity_2 - activity_1).days
            midpoint = activity_1 + (activity_2 - activity_1) / 2
            stage = get_stage_at_time(midpoint)

            if stage:
                bucket = stage_bucket(stage)

                if bucket not in ['closed_won', 'closed_lost', 'unknown']:
                    cell_key = (bucket, segment)
                    gaps_by_cell[cell_key][outcome].append(gap_days)

    # Export to CSV
    output_file = Path(__file__).parent.parent / 'signal3_raw_gaps.csv'

    with open(output_file, 'w', newline='') as csvfile:
        writer = csv.writer(csvfile)
        writer.writerow(['stage', 'segment', 'outcome', 'gap_days'])

        for (bucket, segment), data in sorted(gaps_by_cell.items()):
            for gap in data['won']:
                writer.writerow([bucket, segment, 'won', gap])
            for gap in data['lost']:
                writer.writerow([bucket, segment, 'lost', gap])

    print(f"Raw gaps exported to: {output_file}")
    print()

    # Print percentile breakdown for each cell
    print("=" * 80)
    print("PERCENTILE BREAKDOWN BY CELL")
    print("=" * 80)
    print()

    for (bucket, segment), data in sorted(gaps_by_cell.items()):
        won_gaps = sorted(data['won'])
        lost_gaps = sorted(data['lost'])

        if not won_gaps or not lost_gaps:
            continue

        print(f"{bucket} x {segment}:")
        print(f"  Won (n={len(won_gaps)}):")
        print(f"    P0 (min): {won_gaps[0]}")
        print(f"    P25: {statistics.quantiles(won_gaps, n=4)[0] if len(won_gaps) >= 4 else won_gaps[0]}")
        print(f"    P50 (median): {statistics.median(won_gaps)}")
        print(f"    P75: {statistics.quantiles(won_gaps, n=4)[2] if len(won_gaps) >= 4 else won_gaps[-1]}")
        print(f"    P100 (max): {won_gaps[-1]}")
        print(f"    0-day gaps: {sum(1 for g in won_gaps if g == 0)} ({100*sum(1 for g in won_gaps if g == 0)/len(won_gaps):.1f}%)")

        print(f"  Lost (n={len(lost_gaps)}):")
        print(f"    P0 (min): {lost_gaps[0]}")
        print(f"    P25: {statistics.quantiles(lost_gaps, n=4)[0] if len(lost_gaps) >= 4 else lost_gaps[0]}")
        print(f"    P50 (median): {statistics.median(lost_gaps)}")
        print(f"    P75: {statistics.quantiles(lost_gaps, n=4)[2] if len(lost_gaps) >= 4 else lost_gaps[-1]}")
        print(f"    P100 (max): {lost_gaps[-1]}")
        print(f"    0-day gaps: {sum(1 for g in lost_gaps if g == 0)} ({100*sum(1 for g in lost_gaps if g == 0)/len(lost_gaps):.1f}%)")

        print()

if __name__ == '__main__':
    main()
