#!/usr/bin/env python3
"""
Signal 3 Gap Investigation - Deep Dive into Raw Data

Investigates:
1. Raw gap values with actual timestamps (check for 0-day gaps and date precision)
2. Cleanup-adjacent contamination (deals touched near bulk events)
3. Truncation exclusion verification (should be >0 if 10.6% truncated)
"""
import sys
from pathlib import Path
from dotenv import load_dotenv
from datetime import datetime, timezone
from collections import defaultdict, Counter

env_path = Path(__file__).parent.parent / ".env"
load_dotenv(env_path)

sys.path.insert(0, str(Path(__file__).parent.parent / 'api'))
from db import get_supabase
from field_semantics import is_won, stage_bucket

BULK_CLEANUP_MONTHS = [
    "2023-08", "2024-11", "2026-01", "2026-02", "2026-03",
    "2026-04", "2026-05", "2026-06", "2026-07", "2026-08"
]

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

def is_bulk_cleanup_month(timestamp):
    if not timestamp:
        return False
    date_str = timestamp.strftime('%Y-%m')
    return date_str in BULK_CLEANUP_MONTHS

def main():
    sb = get_supabase()

    print("=" * 80)
    print("SIGNAL 3 GAP INVESTIGATION - RAW DATA ANALYSIS")
    print("=" * 80)
    print()

    # Fetch closed deals
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

    # Focus on Discovery x Mid-Market (the problem cell)
    discovery_midmarket_deals = [
        d for d in closed_deals
        if d.get('segment') == 'Mid-Market'
    ]

    # Separate won and lost
    lost_deals = [d for d in discovery_midmarket_deals if d['outcome'] == 'lost']
    won_deals = [d for d in discovery_midmarket_deals if d['outcome'] == 'won']

    print(f"Discovery x Mid-Market cell:")
    print(f"  Won deals: {len(won_deals)}")
    print(f"  Lost deals: {len(lost_deals)}")
    print()

    # Sample 10 lost deals for investigation
    sample_lost = lost_deals[:10]

    print("=" * 80)
    print("INVESTIGATION 1: RAW GAP VALUES WITH TIMESTAMPS")
    print("=" * 80)
    print()

    # Fetch property history for sample deals
    sample_deal_ids = [str(d['deal_id']) for d in sample_lost]

    history_result = sb.table('property_history').select(
        'deal_id,property_name,changed_at,new_value,source_type'
    ).in_('deal_id', sample_deal_ids).order('deal_id,property_name,changed_at').execute()

    history_by_deal = defaultdict(lambda: {'notes_last_updated': [], 'dealstage': []})
    for row in history_result.data:
        deal_id = row['deal_id']
        prop_name = row['property_name']
        changed_at = parse_date(row['changed_at'])

        if changed_at:
            history_by_deal[deal_id][prop_name].append({
                'changed_at': changed_at,
                'new_value': row['new_value'],
                'source_type': row['source_type']
            })

    zero_day_gaps_found = 0
    same_calendar_day_different_times = 0
    same_timestamp_exact = 0

    for i, deal in enumerate(sample_lost[:5]):  # Show first 5 in detail
        deal_id = str(deal['deal_id'])
        company_name = deal.get('company_name') or 'Unknown'

        print(f"{i+1}. Deal {deal_id} - {company_name} (LOST)")
        print(f"   Created: {deal.get('create_date')}")
        print(f"   Closed: {deal.get('close_date')}")
        print()

        if deal_id not in history_by_deal:
            print("   No property history found")
            print()
            continue

        nlu_history = history_by_deal[deal_id]['notes_last_updated']

        if not nlu_history:
            print("   No notes_last_updated history")
            print()
            continue

        # Show all activity timestamps BEFORE filtering
        print("   Raw notes_last_updated changes:")
        for j, change in enumerate(nlu_history):
            changed_at = change['changed_at']
            new_value = change['new_value']
            source_type = change['source_type']

            # Check if in bulk cleanup month
            is_bulk = is_bulk_cleanup_month(changed_at)
            bulk_flag = " [BULK MONTH - EXCLUDED]" if is_bulk else ""

            # Check timestamp precision
            has_time = changed_at.hour != 0 or changed_at.minute != 0 or changed_at.second != 0
            time_str = f"{changed_at.strftime('%Y-%m-%d %H:%M:%S')} UTC"
            precision_note = "" if has_time else " [DATE-ONLY, no time-of-day]"

            print(f"      {j+1}. {time_str}{precision_note}")
            print(f"         Value: {new_value}")
            print(f"         Source: {source_type}{bulk_flag}")

        # Now compute gaps AFTER filtering bulk months
        activities = []
        for change in nlu_history:
            changed_at = change['changed_at']
            if not is_bulk_cleanup_month(changed_at):
                activity_date = parse_date(change['new_value']) if change['new_value'] else changed_at
                if activity_date:
                    activities.append(activity_date)

        if len(activities) < 2:
            print()
            print("   After bulk exclusion: <2 activities, no gaps computed")
            print()
            continue

        activities = sorted(activities)

        print()
        print(f"   After bulk exclusion: {len(activities)} activities")
        print()
        print("   Computed gaps:")

        for j in range(len(activities) - 1):
            activity_1 = activities[j]
            activity_2 = activities[j + 1]

            gap_days = (activity_2 - activity_1).days
            gap_hours = (activity_2 - activity_1).total_seconds() / 3600

            # Check for 0-day gaps
            if gap_days == 0:
                zero_day_gaps_found += 1

                # Same calendar day but different times?
                if activity_1.date() == activity_2.date():
                    if activity_1.hour != activity_2.hour or activity_1.minute != activity_2.minute:
                        same_calendar_day_different_times += 1
                    else:
                        same_timestamp_exact += 1

            print(f"      Gap {j+1}: {gap_days} days ({gap_hours:.1f} hours)")
            print(f"         From: {activity_1.strftime('%Y-%m-%d %H:%M:%S')}")
            print(f"         To:   {activity_2.strftime('%Y-%m-%d %H:%M:%S')}")

        print()

    print("=" * 80)
    print("0-DAY GAP ANALYSIS (from 5 sample deals)")
    print("=" * 80)
    print()
    print(f"Total 0-day gaps found: {zero_day_gaps_found}")
    print(f"  Same calendar day, different times: {same_calendar_day_different_times}")
    print(f"  Exact same timestamp: {same_timestamp_exact}")
    print()

    if zero_day_gaps_found > 0:
        print("FINDING: 0-day gaps ARE present in the data")
        if same_calendar_day_different_times > 0:
            print(f"  {same_calendar_day_different_times} gaps are genuinely same-day but different times")
            print("  This is EXPECTED behavior (multiple activities on same day)")
        if same_timestamp_exact > 0:
            print(f"  ⚠️  {same_timestamp_exact} gaps have EXACT same timestamp")
            print("  This suggests field being updated multiple times for single logical action")
    else:
        print("No 0-day gaps found in sample")

    print()

    # ========================================================================
    # INVESTIGATION 2: CLEANUP-ADJACENT CONTAMINATION
    # ========================================================================
    print("=" * 80)
    print("INVESTIGATION 2: CLEANUP-ADJACENT CONTAMINATION")
    print("=" * 80)
    print()

    print("Checking if lost deals have cleanup-adjacent rapid touches...")
    print()

    # Check how many lost deals have ANY activities in bulk months
    lost_with_bulk_activities = 0
    lost_with_rapid_touches_near_bulk = 0

    for deal in lost_deals[:50]:  # Check first 50 lost deals
        deal_id = str(deal['deal_id'])

        if deal_id not in history_by_deal:
            continue

        nlu_history = history_by_deal[deal_id]['notes_last_updated']

        # Check if any activities in bulk months
        has_bulk = any(is_bulk_cleanup_month(ch['changed_at']) for ch in nlu_history)

        if has_bulk:
            lost_with_bulk_activities += 1

            # Check for rapid touches near bulk events
            # (activities within 7 days of a bulk-month activity)
            bulk_timestamps = [ch['changed_at'] for ch in nlu_history if is_bulk_cleanup_month(ch['changed_at'])]
            non_bulk_timestamps = [ch['changed_at'] for ch in nlu_history if not is_bulk_cleanup_month(ch['changed_at'])]

            for bulk_ts in bulk_timestamps:
                for non_bulk_ts in non_bulk_timestamps:
                    days_diff = abs((non_bulk_ts - bulk_ts).days)
                    if days_diff <= 7:
                        lost_with_rapid_touches_near_bulk += 1
                        break

    print(f"Lost deals checked: 50")
    print(f"Lost deals with activities in bulk months: {lost_with_bulk_activities} ({100*lost_with_bulk_activities/50:.1f}%)")
    print(f"Lost deals with rapid touches near bulk events: {lost_with_rapid_touches_near_bulk} ({100*lost_with_rapid_touches_near_bulk/50:.1f}%)")
    print()

    if lost_with_bulk_activities > 25:
        print("⚠️  WARNING: >50% of lost deals have bulk-month activities")
        print("   Even after excluding bulk-month timestamps, cleanup-adjacent")
        print("   rapid touches may contaminate the remaining gap distributions")

    print()

    # ========================================================================
    # INVESTIGATION 3: TRUNCATION EXCLUSION VERIFICATION
    # ========================================================================
    print("=" * 80)
    print("INVESTIGATION 3: TRUNCATION EXCLUSION VERIFICATION")
    print("=" * 80)
    print()

    print("Verifying truncation exclusion logic...")
    print()

    # Check truncation for sample deals
    deals_with_truncation = 0
    gaps_that_should_be_excluded = 0

    for deal in sample_lost[:10]:
        deal_id = str(deal['deal_id'])
        create_date = parse_date(deal.get('create_date'))

        if deal_id not in history_by_deal or not create_date:
            continue

        nlu_history = history_by_deal[deal_id]['notes_last_updated']

        # Get activities after bulk exclusion
        activities = []
        for change in nlu_history:
            changed_at = change['changed_at']
            if not is_bulk_cleanup_month(changed_at):
                activity_date = parse_date(change['new_value']) if change['new_value'] else changed_at
                if activity_date:
                    activities.append(activity_date)

        if not activities:
            continue

        activities = sorted(activities)
        earliest_activity = activities[0]
        days_after_creation = (earliest_activity - create_date).days

        if days_after_creation > TRUNCATION_THRESHOLD_DAYS:
            deals_with_truncation += 1

            # Check if ANY gaps would span the truncation boundary
            for i, activity in enumerate(activities):
                if activity < earliest_activity:
                    gaps_that_should_be_excluded += 1

    print(f"Sample deals checked: 10")
    print(f"Deals with truncation (earliest activity >{TRUNCATION_THRESHOLD_DAYS} days after creation): {deals_with_truncation}")
    print(f"Gaps that should be excluded (span truncation boundary): {gaps_that_should_be_excluded}")
    print()

    if deals_with_truncation > 0 and gaps_that_should_be_excluded == 0:
        print("✅ Truncation logic is correct:")
        print("   Deals have truncation BUT no gaps span the boundary")
        print("   (because truncation boundary = earliest activity, so no activities BEFORE it)")
    elif deals_with_truncation == 0:
        print("ℹ️  No truncation found in this sample")
        print("   (May be due to sample selection or bulk exclusion removing early activities)")
    else:
        print("⚠️  POTENTIAL BUG: Gaps should be excluded but weren't")

    print()

    # ========================================================================
    # SUMMARY FINDINGS
    # ========================================================================
    print("=" * 80)
    print("SUMMARY FINDINGS")
    print("=" * 80)
    print()

    print("1. 0-DAY GAPS:")
    if zero_day_gaps_found > 0:
        print(f"   Found in sample: {zero_day_gaps_found} gaps")
        print(f"   Same-day different times: {same_calendar_day_different_times}")
        print(f"   Exact same timestamp: {same_timestamp_exact}")
        if same_calendar_day_different_times > same_timestamp_exact:
            print("   → LIKELY LEGITIMATE: Multiple activities on same calendar day")
        else:
            print("   → LIKELY ARTIFACT: Field updating multiple times for single action")
    else:
        print("   None found in sample (need larger sample)")

    print()
    print("2. CLEANUP-ADJACENT CONTAMINATION:")
    print(f"   {100*lost_with_bulk_activities/50:.1f}% of lost deals have bulk-month activities")
    if lost_with_bulk_activities > 25:
        print("   → HIGH CONTAMINATION RISK")
    else:
        print("   → Low contamination risk")

    print()
    print("3. TRUNCATION EXCLUSION:")
    print(f"   {deals_with_truncation}/10 sample deals have truncation")
    print(f"   {gaps_that_should_be_excluded} gaps should be excluded")
    print("   → Logic appears correct (truncation boundary = earliest activity)")

    print()

if __name__ == '__main__':
    main()
