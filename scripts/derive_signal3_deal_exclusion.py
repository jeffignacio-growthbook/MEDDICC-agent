#!/usr/bin/env python3
"""
Signal 3 Derivation with DEAL-LEVEL Bulk Exclusion

Key change from previous version:
- DEAL-LEVEL exclusion (specific 750 bulk cleanup deal_ids)
- NOT month-based exclusion

Applies:
1. Bulk event exclusion (750 specific deals from Q016 criteria)
2. Truncation handling (exclude gaps spanning truncation boundary)
3. Won vs Lost separation methodology

Queries property_history table directly - no HubSpot API calls needed.
"""
import sys
import json
from pathlib import Path
from dotenv import load_dotenv
import statistics
from datetime import datetime, timezone
from collections import defaultdict

env_path = Path(__file__).parent.parent / ".env"
load_dotenv(env_path)

sys.path.insert(0, str(Path(__file__).parent.parent / 'api'))
from db import get_supabase
from field_semantics import is_won, stage_bucket

MIN_SAMPLE_PER_CELL = 5
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
    print("SIGNAL 3 DERIVATION WITH DEAL-LEVEL BULK EXCLUSION")
    print("=" * 80)
    print()

    # Load bulk cleanup deal_ids
    bulk_cleanup_file = Path(__file__).parent.parent / 'bulk_cleanup_deal_ids.json'
    with open(bulk_cleanup_file, 'r') as f:
        bulk_data = json.load(f)

    bulk_cleanup_deal_ids = set(bulk_data['deal_ids'])
    print(f"Loaded {len(bulk_cleanup_deal_ids)} bulk cleanup deal_ids for exclusion")
    print()

    # Fetch closed deals
    print("Fetching closed deals...")
    all_deals = sb.table('deals').select(
        'deal_id,company_name,stage,deal_status,segment,create_date,close_date'
    ).execute().data

    closed_deals = []
    excluded_bulk_deals = 0

    for deal in all_deals:
        # Skip bulk cleanup deals
        if str(deal['deal_id']) in bulk_cleanup_deal_ids:
            excluded_bulk_deals += 1
            continue

        if is_won(deal.get('stage')):
            deal['outcome'] = 'won'
            closed_deals.append(deal)
        elif deal.get('deal_status') == 'lost':
            deal['outcome'] = 'lost'
            closed_deals.append(deal)

    print(f"Total closed deals (after bulk exclusion): {len(closed_deals)}")
    print(f"Bulk cleanup deals excluded: {excluded_bulk_deals}")
    print()

    # Fetch property history for closed deals
    print("Fetching property history from Supabase...")
    deal_ids = [str(d['deal_id']) for d in closed_deals]

    # Fetch in batches
    batch_size = 100
    all_history = []

    for i in range(0, len(deal_ids), batch_size):
        batch = deal_ids[i:i+batch_size]
        history_batch = sb.table('property_history').select(
            'deal_id,property_name,changed_at,new_value'
        ).in_('deal_id', batch).order('changed_at', desc=False).execute()
        all_history.extend(history_batch.data)

        if (i + batch_size) % 500 == 0:
            print(f"  Fetched {min(i+batch_size, len(deal_ids))}/{len(deal_ids)} deals...")

    print(f"Total property changes fetched: {len(all_history)}")
    print()

    # Group by deal and property
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

    print(f"Deals with property history: {len(history_by_deal)}")
    print()

    # Compute gaps with truncation handling (NO month-based bulk exclusion)
    print("=" * 80)
    print("COMPUTING ACTIVITY GAPS")
    print("=" * 80)
    print()

    gaps_by_cell = defaultdict(lambda: {'won': [], 'lost': []})

    stats = {
        'deals_processed': 0,
        'deals_with_both_histories': 0,
        'gaps_excluded_truncation': 0,
        'valid_gaps': 0
    }

    for deal in closed_deals:
        deal_id = str(deal['deal_id'])

        if deal_id not in history_by_deal:
            continue

        stats['deals_processed'] += 1

        nlu_history = history_by_deal[deal_id]['notes_last_updated']
        dealstage_history = history_by_deal[deal_id]['dealstage']

        if not nlu_history or not dealstage_history:
            continue

        stats['deals_with_both_histories'] += 1

        create_date = parse_date(deal.get('create_date'))
        close_date = parse_date(deal.get('close_date'))

        if not create_date or not close_date:
            continue

        # Build activity list (NO bulk month exclusion)
        activities = []
        for change in nlu_history:
            changed_at = change['changed_at']

            # Parse activity date from new_value if it's a date
            activity_date = parse_date(change['new_value']) if change['new_value'] else changed_at
            if activity_date:
                activities.append(activity_date)

        if len(activities) < 2:
            continue

        activities = sorted(activities)

        # EXCLUSION: Detect truncation
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

            # Skip gaps spanning truncation boundary
            if truncation_boundary and activity_1 < truncation_boundary:
                stats['gaps_excluded_truncation'] += 1
                continue

            gap_days = (activity_2 - activity_1).days
            midpoint = activity_1 + (activity_2 - activity_1) / 2
            stage = get_stage_at_time(midpoint)

            if stage:
                bucket = stage_bucket(stage)

                if bucket not in ['closed_won', 'closed_lost', 'unknown']:
                    cell_key = (bucket, segment)
                    gaps_by_cell[cell_key][outcome].append(gap_days)
                    stats['valid_gaps'] += 1

        # Final gap to close
        if activities:
            last_activity = activities[-1]
            if not truncation_boundary or last_activity >= truncation_boundary:
                final_gap = (close_date - last_activity).days
                final_stage = get_stage_at_time(last_activity)

                if final_stage and final_gap >= 0:
                    bucket = stage_bucket(final_stage)
                    if bucket not in ['closed_won', 'closed_lost', 'unknown']:
                        cell_key = (bucket, segment)
                        gaps_by_cell[cell_key][outcome].append(final_gap)
                        stats['valid_gaps'] += 1

    print("PROCESSING STATS:")
    print(f"  Deals processed: {stats['deals_processed']}")
    print(f"  Deals with both histories: {stats['deals_with_both_histories']}")
    print(f"  Bulk cleanup deals excluded: {excluded_bulk_deals} (deal-level)")
    print(f"  Gaps excluded (truncation): {stats['gaps_excluded_truncation']}")
    print(f"  Valid gaps computed: {stats['valid_gaps']}")
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

    # Derive thresholds
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

            # Derive threshold from distribution separation
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

    # Sanity check: Verify expected direction
    print("=" * 80)
    print("SANITY CHECK: THRESHOLD DIRECTION")
    print("=" * 80)
    print()

    correct_direction = 0
    incorrect_direction = 0

    for (bucket, segment), threshold_data in thresholds.items():
        won_median = threshold_data['won_median']
        lost_p25 = threshold_data['lost_p25']

        if lost_p25 > won_median:
            correct_direction += 1
        else:
            incorrect_direction += 1
            print(f"⚠️  {bucket} x {segment}: Lost P25 ({lost_p25}) <= Won Med ({won_median})")

    print(f"Cells with correct direction (Lost P25 > Won Med): {correct_direction}/{len(thresholds)}")

    if incorrect_direction > 0:
        print(f"⚠️  Cells with incorrect direction: {incorrect_direction}")
        print("   This may indicate insufficient data or overlap in distributions")
    else:
        print("✅ All cells show expected direction (lost deals have longer gaps)")

    print()

    # Final assessment
    print("=" * 80)
    print("FINAL ASSESSMENT")
    print("=" * 80)
    print()

    if cells_sufficient >= (total_cells * 0.5):
        print(f"✅ SIGNAL 3 VIABLE: {cells_sufficient}/{total_cells} cells sufficient")
        print()
        print("PROCEED with Signal 3 implementation")
        recommendation = "proceed"
    else:
        print(f"❌ SIGNAL 3 NOT VIABLE: Only {cells_sufficient}/{total_cells} cells sufficient")
        print()
        print("DEFER Signal 3 - insufficient sample sizes after exclusions")
        recommendation = "defer"

    # Save results
    output = {
        'recommendation': recommendation,
        'thresholds': {f"{k[0]}_{k[1]}": v for k, v in thresholds.items()},
        'coverage': {
            'total_cells': total_cells,
            'sufficient': cells_sufficient,
            'insufficient': cells_insufficient
        },
        'stats': {
            **stats,
            'bulk_cleanup_deals_excluded': excluded_bulk_deals
        },
        'exclusion_method': 'deal_level',
        'bulk_cleanup_deal_count': len(bulk_cleanup_deal_ids)
    }

    output_file = Path(__file__).parent.parent / 'signal3_deal_exclusion_results.json'
    with open(output_file, 'w') as f:
        json.dump(output, f, indent=2)

    print()
    print(f"Results saved to: {output_file}")

if __name__ == '__main__':
    main()
