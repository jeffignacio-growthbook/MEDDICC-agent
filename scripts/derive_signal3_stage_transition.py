#!/usr/bin/env python3
"""
Signal 3 Derivation - Stage-Transition-Date Fix

For deals with negative gaps (close_date < last_activity):
- Use stage transition date instead of close_date
- Finds when deal entered closed stage from dealstage property history

For all other deals:
- Use close_date as before

This fixes the 114 negative-gap deals caused by close_date being stored
as midnight timestamp while last_activity has full time-of-day precision.

Computes ONE recency metric per deal:
- Gap between LAST activity and outcome date (stage transition or close_date)
- Answers: "How long was this deal silent before it closed?"
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
from field_semantics import is_won, is_lost, stage_bucket

MIN_SAMPLE_PER_CELL = 5

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

def find_stage_transition_date(dealstage_history, target_stage):
    """
    Find the date when a deal first entered the target stage.

    Args:
        dealstage_history: List of dealstage changes sorted by changed_at
        target_stage: The stage value to find (e.g., 'closedwon', 'closedlost')

    Returns:
        datetime when deal first entered target stage, or None if not found
    """
    for change in dealstage_history:
        if change['new_value'] == target_stage:
            return change['changed_at']
    return None

def main():
    sb = get_supabase()

    print("=" * 80)
    print("SIGNAL 3 DERIVATION - STAGE-TRANSITION-DATE FIX")
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

    # Compute LAST-GAP-BEFORE-OUTCOME with stage-transition-date fix
    print("=" * 80)
    print("COMPUTING RECENCY WITH STAGE-TRANSITION-DATE FIX")
    print("=" * 80)
    print()

    recency_by_cell = defaultdict(lambda: {'won': [], 'lost': []})

    stats = {
        'deals_processed': 0,
        'won_with_activity': 0,
        'won_no_activity': 0,
        'lost_with_activity': 0,
        'lost_no_activity': 0,
        'negative_gaps_fixed': 0,
        'stage_transition_not_found': 0
    }

    for deal in closed_deals:
        deal_id = str(deal['deal_id'])

        if deal_id not in history_by_deal:
            continue

        stats['deals_processed'] += 1

        nlu_history = history_by_deal[deal_id]['notes_last_updated']
        dealstage_history = history_by_deal[deal_id]['dealstage']

        close_date = parse_date(deal.get('close_date'))
        create_date = parse_date(deal.get('create_date'))

        if not close_date or not create_date:
            continue

        # Get LAST activity timestamp
        if not nlu_history:
            # No activity recorded
            outcome = deal['outcome']
            if outcome == 'won':
                stats['won_no_activity'] += 1
            else:
                stats['lost_no_activity'] += 1
            continue

        # Find last activity
        activities = []
        for change in nlu_history:
            changed_at = change['changed_at']
            activity_date = parse_date(change['new_value']) if change['new_value'] else changed_at
            if activity_date:
                activities.append(activity_date)

        if not activities:
            outcome = deal['outcome']
            if outcome == 'won':
                stats['won_no_activity'] += 1
            else:
                stats['lost_no_activity'] += 1
            continue

        activities = sorted(activities)
        last_activity = activities[-1]

        # Compute initial gap with close_date
        initial_gap_days = (close_date - last_activity).days

        # If negative gap, use stage transition date instead
        outcome_date = close_date

        if initial_gap_days < 0:
            stats['negative_gaps_fixed'] += 1

            # Find stage transition date from dealstage history
            stage_timeline = sorted(dealstage_history, key=lambda x: x['changed_at'])

            # Determine target closed stage based on outcome
            if deal['outcome'] == 'won':
                # Find when deal entered closedwon
                for change in stage_timeline:
                    if is_won(change['new_value']):
                        outcome_date = change['changed_at']
                        break
            else:
                # Find when deal entered closedlost
                for change in stage_timeline:
                    if is_lost(change['new_value']):
                        outcome_date = change['changed_at']
                        break

            # If we couldn't find stage transition, fall back to close_date
            if outcome_date == close_date:
                stats['stage_transition_not_found'] += 1

        # Compute final gap
        last_gap_days = (outcome_date - last_activity).days

        # Still negative after fix? Skip this deal
        if last_gap_days < 0:
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
            continue

        bucket = stage_bucket(current_stage)

        if bucket in ['closed_won', 'closed_lost', 'unknown']:
            continue

        segment = deal.get('segment') or 'Unknown'
        outcome = deal['outcome']

        cell_key = (bucket, segment)
        recency_by_cell[cell_key][outcome].append(last_gap_days)

        if outcome == 'won':
            stats['won_with_activity'] += 1
        else:
            stats['lost_with_activity'] += 1

    print("PROCESSING STATS:")
    print(f"  Deals processed: {stats['deals_processed']}")
    print(f"  Negative gaps fixed with stage transition: {stats['negative_gaps_fixed']}")
    print(f"  Stage transition not found (fell back to close_date): {stats['stage_transition_not_found']}")
    print()
    print("POPULATION SPLIT (4-way):")
    print(f"  Won with activity: {stats['won_with_activity']}")
    print(f"  Won no activity: {stats['won_no_activity']}")
    print(f"  Lost with activity: {stats['lost_with_activity']}")
    print(f"  Lost no activity: {stats['lost_no_activity']}")
    print()

    if stats['won_no_activity'] > 0:
        won_no_activity_pct = 100 * stats['won_no_activity'] / (stats['won_with_activity'] + stats['won_no_activity'])
        print(f"⚠️  {stats['won_no_activity']} won deals have no activity ({won_no_activity_pct:.1f}% of won)")
    else:
        print("✓ All won deals have activity")

    print()

    # Sample size analysis
    print("=" * 80)
    print("SAMPLE SIZE ANALYSIS (Stage × Segment)")
    print("=" * 80)
    print()

    print(f"{'Stage':<20} {'Segment':<15} {'Won':<8} {'Lost':<8} {'Status':<20}")
    print("-" * 75)

    cells_sufficient = 0
    cells_insufficient = 0

    for (bucket, segment), data in sorted(recency_by_cell.items()):
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

    total_cells = len(recency_by_cell)
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

        for (bucket, segment), data in sorted(recency_by_cell.items()):
            won_recency = data['won']
            lost_recency = data['lost']

            if len(won_recency) < MIN_SAMPLE_PER_CELL or len(lost_recency) < MIN_SAMPLE_PER_CELL:
                continue

            won_median = statistics.median(won_recency)
            lost_sorted = sorted(lost_recency)
            lost_p25 = statistics.quantiles(lost_sorted, n=4)[0] if len(lost_sorted) >= 4 else lost_sorted[0]

            # Derive threshold from distribution separation
            if won_median < lost_p25:
                threshold = round((won_median + lost_p25) / 2)
            else:
                # Won median >= lost P25 (distributions overlap)
                # Use lost P25 as threshold
                threshold = round(lost_p25)

            thresholds[(bucket, segment)] = {
                'threshold_days': threshold,
                'won_median': round(won_median, 1),
                'lost_p25': round(lost_p25, 1),
                'won_sample': len(won_recency),
                'lost_sample': len(lost_recency)
            }

            print(f"{bucket:<20} {segment:<15} {threshold:<10} {won_median:<10.1f} {lost_p25:<10.1f}")

        print()

    # Sanity check: Verify expected direction
    print("=" * 80)
    print("DIRECTION CHECK: Lost P25 > Won Median?")
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

    if len(thresholds) > 0:
        print(f"Cells with correct direction (Lost P25 > Won Med): {correct_direction}/{len(thresholds)}")

        if correct_direction == len(thresholds):
            print("✅ ALL cells show expected direction (lost deals silent longer)")
        elif incorrect_direction > 0:
            print(f"⚠️  {incorrect_direction} cells show incorrect direction")
        print()

    # Final assessment
    print("=" * 80)
    print("FINAL ASSESSMENT")
    print("=" * 80)
    print()

    if cells_sufficient >= (total_cells * 0.5):
        print(f"✅ SIGNAL 3 VIABLE: {cells_sufficient}/{total_cells} cells sufficient")

        if correct_direction == len(thresholds):
            print("✅ All cells show correct direction")
            print()
            print("PROCEED with Signal 3 implementation")
            recommendation = "proceed"
        else:
            print(f"⚠️  {incorrect_direction} cells show incorrect direction")
            print()
            print("CONDITIONAL PROCEED - exclude cells with incorrect direction")
            recommendation = "conditional_proceed"
    else:
        print(f"❌ SIGNAL 3 NOT VIABLE: Only {cells_sufficient}/{total_cells} cells sufficient")
        print()
        print("DEFER Signal 3 - insufficient sample sizes")
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
        'direction_check': {
            'correct': correct_direction,
            'incorrect': incorrect_direction,
            'total': len(thresholds)
        },
        'stats': stats,
        'exclusion_method': 'deal_level',
        'bulk_cleanup_deal_count': len(bulk_cleanup_deal_ids),
        'metric_type': 'recency',
        'fix_applied': 'stage_transition_date_for_negative_gaps'
    }

    output_file = Path(__file__).parent.parent / 'signal3_stage_transition_results.json'
    with open(output_file, 'w') as f:
        json.dump(output, f, indent=2)

    print()
    print(f"Results saved to: {output_file}")

if __name__ == '__main__':
    main()
