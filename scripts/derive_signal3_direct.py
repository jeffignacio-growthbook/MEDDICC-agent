#!/usr/bin/env python3
"""
Signal 3 Direct Derivation with Bulk Event Exclusion and Truncation Handling

Fetches property history directly (no cache dependency) and applies exclusions.
"""
import os
import sys
import json
import statistics
import requests
import time
from pathlib import Path
from datetime import datetime, timezone
from collections import defaultdict, Counter
from dotenv import load_dotenv

env_path = Path(__file__).parent.parent / ".env"
load_dotenv(env_path)

sys.path.insert(0, str(Path(__file__).parent.parent / 'api'))
from db import get_supabase
from field_semantics import is_won, stage_bucket

# Bulk cleanup months from business_events_registry.yaml
BULK_CLEANUP_MONTHS = [
    "2023-08",
    "2024-11",
    "2026-01",
    "2026-02",
    "2026-03",
    "2026-04",
    "2026-05",
    "2026-06",
    "2026-07",
    "2026-08"
]

MIN_SAMPLE_PER_CELL = 5
TRUNCATION_THRESHOLD_DAYS = 30

HUBSPOT_API_KEY = os.getenv('HUBSPOT_API_KEY')
if not HUBSPOT_API_KEY:
    print("❌ HUBSPOT_API_KEY not set")
    sys.exit(1)

def parse_date(date_str):
    if not date_str:
        return None
    try:
        dt = datetime.fromisoformat(date_str.replace('Z', '+00:00'))
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        return dt
    except:
        return None

def fetch_property_history(deal_id):
    """Fetch notes_last_updated and dealstage history from HubSpot API."""
    url = f"https://api.hubapi.com/crm/v3/objects/deals/{deal_id}"
    params = {
        'properties': 'notes_last_updated,dealstage',
        'propertiesWithHistory': 'notes_last_updated,dealstage'
    }
    headers = {
        'Authorization': f'Bearer {HUBSPOT_API_KEY}',
        'Content-Type': 'application/json'
    }

    time.sleep(0.2)  # Rate limit: 5 calls/sec

    try:
        response = requests.get(url, params=params, headers=headers, timeout=10)
        if response.status_code == 200:
            data = response.json()
            history = data.get('propertiesWithHistory', {})
            return {
                'notes_last_updated_history': history.get('notes_last_updated', []),
                'dealstage_history': history.get('dealstage', [])
            }
    except Exception as e:
        pass

    return None

def is_bulk_cleanup_month(timestamp):
    if not timestamp:
        return False
    date_str = timestamp.strftime('%Y-%m')
    return date_str in BULK_CLEANUP_MONTHS

def compute_gaps_with_exclusions(deal, nlu_history, dealstage_history):
    """Compute gaps with bulk exclusion and truncation handling."""
    if not nlu_history or not dealstage_history:
        return []

    create_date = parse_date(deal.get('create_date'))
    close_date = parse_date(deal.get('close_date'))

    if not create_date or not close_date:
        return []

    # Extract activities (excluding bulk cleanup months)
    activities = []
    for change in nlu_history:
        ts_str = change.get('timestamp')
        value_str = change.get('value')

        if ts_str:
            ts = parse_date(ts_str)
            if ts:
                # EXCLUSION 1: Skip bulk cleanup months
                if is_bulk_cleanup_month(ts):
                    continue

                activity_date = parse_date(value_str) if value_str else ts
                if activity_date:
                    activities.append(activity_date)

    if len(activities) < 2:
        return []

    activities = sorted(activities)

    # EXCLUSION 2: Detect truncation
    earliest_activity = activities[0]
    days_after_creation = (earliest_activity - create_date).days
    truncation_boundary = earliest_activity if days_after_creation > TRUNCATION_THRESHOLD_DAYS else None

    # Build stage timeline
    stage_timeline = []
    for change in dealstage_history:
        ts_str = change.get('timestamp')
        stage_value = change.get('value')
        if ts_str and stage_value:
            ts = parse_date(ts_str)
            if ts:
                stage_timeline.append((ts, stage_value))

    stage_timeline = sorted(stage_timeline, key=lambda x: x[0])

    def get_stage_at_time(timestamp):
        current_stage = None
        for stage_ts, stage_value in stage_timeline:
            if stage_ts <= timestamp:
                current_stage = stage_value
            else:
                break
        return current_stage

    # Compute gaps
    gaps = []

    for i in range(len(activities) - 1):
        activity_1 = activities[i]
        activity_2 = activities[i + 1]

        # Skip gaps spanning truncation boundary
        if truncation_boundary and activity_1 < truncation_boundary:
            continue

        gap_days = (activity_2 - activity_1).days
        midpoint = activity_1 + (activity_2 - activity_1) / 2
        stage = get_stage_at_time(midpoint)

        if stage:
            gaps.append((gap_days, stage))

    # Final gap to close
    if activities:
        last_activity = activities[-1]
        if not truncation_boundary or last_activity >= truncation_boundary:
            final_gap = (close_date - last_activity).days
            final_stage = get_stage_at_time(last_activity)
            if final_stage and final_gap >= 0:
                gaps.append((final_gap, final_stage))

    return gaps

def main():
    sb = get_supabase()

    print("=" * 80)
    print("SIGNAL 3 DIRECT DERIVATION")
    print("With Bulk Event Exclusion & Truncation Handling")
    print("=" * 80)
    print()

    # Fetch closed deals
    print("Fetching closed deals...")
    all_deals = sb.table('deals').select(
        'deal_id,company_name,stage,deal_status,segment,create_date,close_date'
    ).execute().data

    closed_deals = []
    for deal in all_deals:
        if is_won(deal.get('stage')):
            deal['outcome'] = 'won'
            closed_deals.append(deal)
        elif deal.get('deal_status') == 'lost':
            deal['outcome'] = 'lost'
            closed_deals.append(deal)

    print(f"Total closed deals: {len(closed_deals)}")
    print()

    print(f"Fetching property history for {len(closed_deals)} deals...")
    print("This will take ~2.5 minutes with rate limiting")
    print()

    gaps_by_cell = defaultdict(lambda: {'won': [], 'lost': []})

    stats = {
        'deals_processed': 0,
        'deals_with_both_histories': 0,
        'api_errors': 0,
        'valid_gaps': 0
    }

    for i, deal in enumerate(closed_deals):
        deal_id = deal['deal_id']

        if (i + 1) % 50 == 0:
            print(f"  Progress: {i+1}/{len(closed_deals)} deals...")

        # Fetch property history
        history = fetch_property_history(deal_id)

        if not history:
            stats['api_errors'] += 1
            continue

        stats['deals_processed'] += 1

        nlu_history = history['notes_last_updated_history']
        dealstage_history = history['dealstage_history']

        if not nlu_history or not dealstage_history:
            continue

        stats['deals_with_both_histories'] += 1

        # Compute gaps with exclusions
        gaps = compute_gaps_with_exclusions(deal, nlu_history, dealstage_history)

        if not gaps:
            continue

        segment = deal.get('segment') or 'Unknown'
        outcome = deal['outcome']

        for gap_days, stage in gaps:
            bucket = stage_bucket(stage)

            if bucket in ['closed_won', 'closed_lost', 'unknown']:
                continue

            cell_key = (bucket, segment)
            gaps_by_cell[cell_key][outcome].append(gap_days)
            stats['valid_gaps'] += 1

    print()
    print("PROCESSING STATS:")
    print(f"  Deals processed: {stats['deals_processed']}")
    print(f"  Deals with both histories: {stats['deals_with_both_histories']}")
    print(f"  Valid gaps computed: {stats['valid_gaps']}")
    print(f"  API errors: {stats['api_errors']}")
    print()

    # Sample size analysis
    print("=" * 80)
    print("SAMPLE SIZE ANALYSIS")
    print("=" * 80)
    print()

    print(f"{'Stage':<20} {'Segment':<15} {'Won':<8} {'Lost':<8} {'Status':<20}")
    print("-" * 75)

    cells_sufficient = 0
    cells_insufficient = 0

    for (bucket, segment), data in sorted(gaps_by_cell.items()):
        won_count = len(data['won'])
        lost_count = len(data['lost'])

        if won_count >= MIN_SAMPLE_PER_CELL and lost_count >= MIN_SAMPLE_PER_CELL:
            status = "✅ Sufficient"
            cells_sufficient += 1
        else:
            status = "❌ Insufficient"
            cells_insufficient += 1

        print(f"{bucket:<20} {segment:<15} {won_count:<8} {lost_count:<8} {status:<20}")

    print()

    total_cells = len(gaps_by_cell)
    print(f"Total cells: {total_cells}")
    print(f"Sufficient: {cells_sufficient} ({100*cells_sufficient/total_cells:.1f}%)")
    print(f"Insufficient: {cells_insufficient}")
    print()

    # Derive thresholds if sufficient
    thresholds = {}

    if cells_sufficient > 0:
        print("=" * 80)
        print("DERIVED THRESHOLDS")
        print("=" * 80)
        print()

        print(f"{'Stage':<20} {'Segment':<15} {'Threshold':<10} {'Won Med':<10} {'Lost P25':<10}")
        print("-" * 75)

        for (bucket, segment), data in sorted(gaps_by_cell.items()):
            won_gaps = data['won']
            lost_gaps = data['lost']

            if len(won_gaps) < MIN_SAMPLE_PER_CELL or len(lost_gaps) < MIN_SAMPLE_PER_CELL:
                continue

            won_median = statistics.median(won_gaps)
            lost_sorted = sorted(lost_gaps)
            lost_p25 = statistics.quantiles(lost_sorted, n=4)[0] if len(lost_sorted) >= 4 else lost_sorted[0]

            if won_median < lost_p25:
                threshold = round((won_median + lost_p25) / 2)
            else:
                threshold = round(lost_p25)

            thresholds[(bucket, segment)] = {
                'threshold_days': threshold,
                'won_median': round(won_median, 1),
                'lost_p25': round(lost_p25, 1),
                'won_sample': len(won_gaps),
                'lost_sample': len(lost_gaps)
            }

            print(f"{bucket:<20} {segment:<15} {threshold:<10} {won_median:<10.1f} {lost_p25:<10.1f}")

        print()

    # Final assessment
    print("=" * 80)
    print("FINAL ASSESSMENT")
    print("=" * 80)
    print()

    if cells_sufficient >= (total_cells * 0.5):
        print(f"✅ SIGNAL 3 VIABLE: {cells_sufficient}/{total_cells} cells sufficient")
        recommendation = "proceed"
    else:
        print(f"❌ SIGNAL 3 NOT VIABLE: Only {cells_sufficient}/{total_cells} cells sufficient")
        recommendation = "defer"

    # Save results
    output = {
        'recommendation': recommendation,
        'thresholds': thresholds,
        'coverage': {
            'total_cells': total_cells,
            'sufficient': cells_sufficient,
            'insufficient': cells_insufficient
        },
        'stats': stats
    }

    output_file = Path(__file__).parent.parent / 'signal3_direct_results.json'
    with open(output_file, 'w') as f:
        json.dump(output, f, indent=2)

    print()
    print(f"Results saved to: {output_file}")

if __name__ == '__main__':
    main()
