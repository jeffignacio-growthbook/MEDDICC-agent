#!/usr/bin/env python3
"""
Diagnose Gap Distributions - Why are all Lost P25 = 0?

Checks:
1. Sample of raw gap values for won vs lost
2. Distribution of 0-day gaps
3. Check if lost deals have MORE activity than won deals
"""
import sys
import json
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
    print("GAP DISTRIBUTION DIAGNOSIS")
    print("=" * 80)
    print()

    # Load bulk cleanup deal_ids
    bulk_cleanup_file = Path(__file__).parent.parent / 'bulk_cleanup_deal_ids.json'
    with open(bulk_cleanup_file, 'r') as f:
        bulk_data = json.load(f)

    bulk_cleanup_deal_ids = set(bulk_data['deal_ids'])

    # Fetch closed deals (excluding bulk cleanup)
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

    # Focus on Discovery x Mid-Market (problem cell)
    discovery_midmarket = [
        d for d in closed_deals
        if d.get('segment') == 'Mid-Market'
    ]

    won_deals = [d for d in discovery_midmarket if d['outcome'] == 'won']
    lost_deals = [d for d in discovery_midmarket if d['outcome'] == 'lost']

    print(f"Discovery x Mid-Market:")
    print(f"  Won: {len(won_deals)}")
    print(f"  Lost: {len(lost_deals)}")
    print()

    # Fetch property history
    deal_ids = [str(d['deal_id']) for d in discovery_midmarket[:20]]  # Sample 20 deals

    history_result = sb.table('property_history').select(
        'deal_id,property_name,changed_at,new_value'
    ).in_('deal_id', deal_ids).order('deal_id,property_name,changed_at').execute()

    history_by_deal = defaultdict(lambda: {'notes_last_updated': [], 'dealstage': []})
    for row in history_result.data:
        deal_id = row['deal_id']
        prop_name = row['property_name']
        changed_at = parse_date(row['changed_at'])

        if changed_at and prop_name in ['notes_last_updated', 'dealstage']:
            history_by_deal[deal_id][prop_name].append({
                'changed_at': changed_at,
                'new_value': row['new_value']
            })

    # Analyze gaps for won vs lost
    print("=" * 80)
    print("GAP ANALYSIS - SAMPLE DEALS")
    print("=" * 80)
    print()

    won_all_gaps = []
    lost_all_gaps = []

    # Sample 5 won, 5 lost
    sample_won = [d for d in discovery_midmarket if d['outcome'] == 'won'][:5]
    sample_lost = [d for d in discovery_midmarket if d['outcome'] == 'lost'][:5]

    for i, deal in enumerate(sample_won):
        deal_id = str(deal['deal_id'])
        company = deal.get('company_name') or 'Unknown'

        if deal_id not in history_by_deal:
            continue

        nlu_history = history_by_deal[deal_id]['notes_last_updated']

        # Build activities
        activities = []
        for change in nlu_history:
            activity_date = parse_date(change['new_value']) if change['new_value'] else change['changed_at']
            if activity_date:
                activities.append(activity_date)

        if len(activities) < 2:
            continue

        activities = sorted(activities)

        # Compute gaps
        gaps = []
        for j in range(len(activities) - 1):
            gap_days = (activities[j+1] - activities[j]).days
            gaps.append(gap_days)

        won_all_gaps.extend(gaps)

        print(f"WON {i+1}: {company} (deal_id={deal_id})")
        print(f"  Activities: {len(activities)}")
        print(f"  Gaps: {gaps}")
        print(f"  Median gap: {statistics.median(gaps) if gaps else 'N/A'}")
        print()

    for i, deal in enumerate(sample_lost):
        deal_id = str(deal['deal_id'])
        company = deal.get('company_name') or 'Unknown'

        if deal_id not in history_by_deal:
            continue

        nlu_history = history_by_deal[deal_id]['notes_last_updated']

        # Build activities
        activities = []
        for change in nlu_history:
            activity_date = parse_date(change['new_value']) if change['new_value'] else change['changed_at']
            if activity_date:
                activities.append(activity_date)

        if len(activities) < 2:
            continue

        activities = sorted(activities)

        # Compute gaps
        gaps = []
        for j in range(len(activities) - 1):
            gap_days = (activities[j+1] - activities[j]).days
            gaps.append(gap_days)

        lost_all_gaps.extend(gaps)

        print(f"LOST {i+1}: {company} (deal_id={deal_id})")
        print(f"  Activities: {len(activities)}")
        print(f"  Gaps: {gaps}")
        print(f"  Median gap: {statistics.median(gaps) if gaps else 'N/A'}")
        print()

    # Summary statistics
    print("=" * 80)
    print("SUMMARY STATISTICS (Sample)")
    print("=" * 80)
    print()

    if won_all_gaps:
        print(f"WON gaps (n={len(won_all_gaps)}):")
        print(f"  Median: {statistics.median(won_all_gaps)}")
        print(f"  Mean: {statistics.mean(won_all_gaps):.1f}")
        print(f"  Min: {min(won_all_gaps)}")
        print(f"  Max: {max(won_all_gaps)}")
        print(f"  P25: {statistics.quantiles(won_all_gaps, n=4)[0] if len(won_all_gaps) >= 4 else 'N/A'}")
        print(f"  0-day gaps: {sum(1 for g in won_all_gaps if g == 0)} ({100*sum(1 for g in won_all_gaps if g == 0)/len(won_all_gaps):.1f}%)")
    else:
        print("No won gaps found")

    print()

    if lost_all_gaps:
        print(f"LOST gaps (n={len(lost_all_gaps)}):")
        print(f"  Median: {statistics.median(lost_all_gaps)}")
        print(f"  Mean: {statistics.mean(lost_all_gaps):.1f}")
        print(f"  Min: {min(lost_all_gaps)}")
        print(f"  Max: {max(lost_all_gaps)}")
        print(f"  P25: {statistics.quantiles(lost_all_gaps, n=4)[0] if len(lost_all_gaps) >= 4 else 'N/A'}")
        print(f"  0-day gaps: {sum(1 for g in lost_all_gaps if g == 0)} ({100*sum(1 for g in lost_all_gaps if g == 0)/len(lost_all_gaps):.1f}%)")
    else:
        print("No lost gaps found")

    print()

    # Check 0-day gap distribution
    print("=" * 80)
    print("0-DAY GAP ANALYSIS")
    print("=" * 80)
    print()

    if lost_all_gaps:
        lost_0day = sum(1 for g in lost_all_gaps if g == 0)
        lost_0day_pct = 100 * lost_0day / len(lost_all_gaps)

        print(f"Lost deals: {lost_0day}/{len(lost_all_gaps)} gaps are 0-day ({lost_0day_pct:.1f}%)")

        if lost_0day_pct > 25:
            print()
            print("⚠️  HIGH FREQUENCY OF 0-DAY GAPS IN LOST DEALS")
            print()
            print("This suggests:")
            print("1. Lost deals have multiple activities on same calendar day")
            print("2. OR lost deals have cleanup-adjacent rapid touches")
            print("3. This pushes Lost P25 down to 0")
        else:
            print("✓ Normal distribution of 0-day gaps")

    print()

    # Activity count comparison
    print("=" * 80)
    print("ACTIVITY COUNT COMPARISON")
    print("=" * 80)
    print()

    won_activity_counts = []
    lost_activity_counts = []

    for deal in discovery_midmarket:
        deal_id = str(deal['deal_id'])

        if deal_id not in history_by_deal:
            continue

        nlu_history = history_by_deal[deal_id]['notes_last_updated']
        activity_count = len(nlu_history)

        if deal['outcome'] == 'won':
            won_activity_counts.append(activity_count)
        else:
            lost_activity_counts.append(activity_count)

    if won_activity_counts and lost_activity_counts:
        print(f"Won deals - avg activities: {statistics.mean(won_activity_counts):.1f}")
        print(f"Lost deals - avg activities: {statistics.mean(lost_activity_counts):.1f}")
        print()

        if statistics.mean(lost_activity_counts) > statistics.mean(won_activity_counts):
            print("⚠️  LOST DEALS HAVE MORE ACTIVITIES THAN WON DEALS")
            print()
            print("This is unexpected - lost deals should have FEWER touchpoints")
            print("This may indicate cleanup-adjacent contamination or data quality issues")
        else:
            print("✓ Won deals have more activities (expected)")

if __name__ == '__main__':
    main()
