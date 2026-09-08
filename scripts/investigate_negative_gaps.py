#!/usr/bin/env python3
"""
Root-cause investigation: Why close_date < last_activity for 114 deals?

Checks:
1. Do close_dates cluster around bulk cleanup dates?
2. Overlap with 750 bulk cleanup deals already excluded?
3. Sample deals to understand the pattern
4. Field meaning verification (HubSpot close_date vs sync timestamp)
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
    print("NEGATIVE GAP ROOT-CAUSE INVESTIGATION")
    print("=" * 80)
    print()

    # Load bulk cleanup deal_ids
    bulk_cleanup_file = Path(__file__).parent.parent / 'bulk_cleanup_deal_ids.json'
    with open(bulk_cleanup_file, 'r') as f:
        bulk_data = json.load(f)

    bulk_cleanup_deal_ids = set(bulk_data['deal_ids'])
    print(f"Bulk cleanup deals (already excluded): {len(bulk_cleanup_deal_ids)}")
    print()

    # Fetch closed deals
    all_deals = sb.table('deals').select(
        'deal_id,company_name,stage,deal_status,segment,create_date,close_date,lost_reason'
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

    # Find all deals with negative gaps
    negative_gap_deals = []

    for deal in closed_deals:
        deal_id = str(deal['deal_id'])

        if deal_id not in history_by_deal:
            continue

        nlu_history = history_by_deal[deal_id]['notes_last_updated']

        if not nlu_history:
            continue

        close_date = parse_date(deal.get('close_date'))
        create_date = parse_date(deal.get('create_date'))

        if not close_date or not create_date:
            continue

        # Find last activity
        activities = []
        for change in nlu_history:
            changed_at = change['changed_at']
            activity_date = parse_date(change['new_value']) if change['new_value'] else changed_at
            if activity_date:
                activities.append(activity_date)

        if not activities:
            continue

        activities = sorted(activities)
        last_activity = activities[-1]

        # Check for negative gap
        last_gap_days = (close_date - last_activity).days

        if last_gap_days < 0:
            negative_gap_deals.append({
                'deal_id': deal_id,
                'company_name': deal.get('company_name'),
                'outcome': deal['outcome'],
                'close_date': close_date,
                'last_activity': last_activity,
                'gap_days': last_gap_days,
                'lost_reason': deal.get('lost_reason'),
                'create_date': create_date
            })

    print(f"Deals with negative gaps: {len(negative_gap_deals)}")
    print()

    # ========================================================================
    # CHECK 1: Do close_dates cluster around bulk cleanup dates?
    # ========================================================================
    print("=" * 80)
    print("CHECK 1: CLOSE_DATE CLUSTERING AROUND BULK CLEANUP DATES")
    print("=" * 80)
    print()

    bulk_cleanup_months = [
        "2023-08", "2024-11", "2026-01", "2026-02", "2026-03",
        "2026-04", "2026-05", "2026-06", "2026-07", "2026-08"
    ]

    close_date_by_month = Counter()
    for deal in negative_gap_deals:
        close_month = deal['close_date'].strftime('%Y-%m')
        close_date_by_month[close_month] += 1

    print("Close date distribution by month:")
    print()
    print(f"{'Month':<15} {'Count':<10} {'Bulk Cleanup?':<20}")
    print("-" * 50)

    for month in sorted(close_date_by_month.keys(), reverse=True)[:12]:
        count = close_date_by_month[month]
        is_bulk = "⚠️ YES" if month in bulk_cleanup_months else ""
        print(f"{month:<15} {count:<10} {is_bulk:<20}")

    print()

    bulk_month_count = sum(count for month, count in close_date_by_month.items() if month in bulk_cleanup_months)
    print(f"Deals with close_date in bulk cleanup months: {bulk_month_count}/{len(negative_gap_deals)} ({100*bulk_month_count/len(negative_gap_deals):.1f}%)")

    if bulk_month_count > len(negative_gap_deals) * 0.5:
        print()
        print("⚠️  FINDING: >50% of negative-gap deals have close_dates in bulk cleanup months")
        print("   This suggests close_date was set administratively during bulk operations")
    else:
        print()
        print("ℹ️  Negative-gap deals are NOT concentrated in bulk cleanup months")

    print()

    # ========================================================================
    # CHECK 2: Overlap with 750 bulk cleanup deals already excluded
    # ========================================================================
    print("=" * 80)
    print("CHECK 2: OVERLAP WITH BULK CLEANUP EXCLUSION LIST")
    print("=" * 80)
    print()

    # This check is a sanity check - these deals should NOT overlap since we
    # already excluded bulk cleanup deals before finding negative gaps
    negative_gap_deal_ids = set(d['deal_id'] for d in negative_gap_deals)
    overlap = negative_gap_deal_ids & bulk_cleanup_deal_ids

    print(f"Negative gap deals: {len(negative_gap_deal_ids)}")
    print(f"Already excluded bulk cleanup deals: {len(bulk_cleanup_deal_ids)}")
    print(f"Overlap: {len(overlap)}")

    if len(overlap) > 0:
        print()
        print("⚠️  UNEXPECTED: Some negative-gap deals ARE in bulk cleanup exclusion list")
        print("   (This should not happen - they were supposed to be excluded already)")
    else:
        print()
        print("✓ Confirmed: Negative-gap deals are SEPARATE from bulk cleanup exclusion")
        print("  → This is a DIFFERENT contamination event, not detected by Q016 criteria")

    print()

    # ========================================================================
    # CHECK 3: Sample deals - detailed inspection
    # ========================================================================
    print("=" * 80)
    print("CHECK 3: SAMPLE DEALS (First 15)")
    print("=" * 80)
    print()

    print(f"{'Company':<25} {'Outcome':<8} {'Close Date':<12} {'Last Activity':<12} {'Gap':<8} {'Lost Reason':<20}")
    print("-" * 100)

    for i, deal in enumerate(negative_gap_deals[:15]):
        company = (deal['company_name'] or 'Unknown')[:24]
        outcome = deal['outcome']
        close_date = deal['close_date'].strftime('%Y-%m-%d')
        last_activity = deal['last_activity'].strftime('%Y-%m-%d')
        gap = f"{deal['gap_days']}d"
        lost_reason = (deal['lost_reason'] or '(blank)')[:19]

        print(f"{company:<25} {outcome:<8} {close_date:<12} {last_activity:<12} {gap:<8} {lost_reason:<20}")

    print()

    # ========================================================================
    # CHECK 4: Lost_reason distribution
    # ========================================================================
    print("=" * 80)
    print("CHECK 4: LOST_REASON DISTRIBUTION")
    print("=" * 80)
    print()

    lost_reason_counts = Counter(d['lost_reason'] or '(blank)' for d in negative_gap_deals if d['outcome'] == 'lost')

    print(f"Lost reason distribution (lost deals only):")
    print()
    for reason, count in sorted(lost_reason_counts.items(), key=lambda x: -x[1])[:10]:
        pct = 100 * count / len([d for d in negative_gap_deals if d['outcome'] == 'lost'])
        print(f"  '{reason}': {count} ({pct:.1f}%)")

    print()

    blank_pct = 100 * lost_reason_counts.get('(blank)', 0) / max(len([d for d in negative_gap_deals if d['outcome'] == 'lost']), 1)

    if blank_pct > 50:
        print(f"⚠️  {blank_pct:.1f}% have blank lost_reason")
        print("   Blank lost_reason indicates administrative cleanup, not sales feedback")
    else:
        print(f"✓ Only {blank_pct:.1f}% have blank lost_reason")

    print()

    # ========================================================================
    # CHECK 5: Won vs Lost breakdown
    # ========================================================================
    print("=" * 80)
    print("CHECK 5: WON VS LOST BREAKDOWN")
    print("=" * 80)
    print()

    won_negative = [d for d in negative_gap_deals if d['outcome'] == 'won']
    lost_negative = [d for d in negative_gap_deals if d['outcome'] == 'lost']

    print(f"Won deals with negative gap: {len(won_negative)}")
    print(f"Lost deals with negative gap: {len(lost_negative)}")
    print()

    if len(won_negative) > 0:
        print(f"⚠️  {len(won_negative)} WON deals have close_date < last_activity")
        print("   This is highly suspicious - won deals should have recent engagement")
        print("   Suggests close_date may be incorrectly set for these deals")
    else:
        print("✓ No won deals with negative gap")

    print()

    # ========================================================================
    # SUMMARY FINDINGS
    # ========================================================================
    print("=" * 80)
    print("SUMMARY FINDINGS")
    print("=" * 80)
    print()

    print(f"1. CLOSE_DATE CLUSTERING:")
    print(f"   {bulk_month_count}/{len(negative_gap_deals)} ({100*bulk_month_count/len(negative_gap_deals):.1f}%) in bulk cleanup months")

    if bulk_month_count > len(negative_gap_deals) * 0.5:
        print("   → CONCLUSION: Close_date likely set administratively during bulk operations")
    else:
        print("   → INCONCLUSIVE: No clear clustering around bulk months")

    print()
    print(f"2. OVERLAP WITH Q016 EXCLUSION:")
    print(f"   {len(overlap)} overlap with 750 bulk cleanup deals")

    if len(overlap) == 0:
        print("   → CONCLUSION: This is a DIFFERENT contamination event")
        print("      (Not detected by Q016 blank lost_reason criteria)")
    else:
        print("   → UNEXPECTED: Some overlap exists")

    print()
    print(f"3. LOST_REASON:")
    print(f"   {blank_pct:.1f}% of lost deals have blank lost_reason")

    if blank_pct > 50:
        print("   → SUPPORTS: Administrative cleanup hypothesis")
    else:
        print("   → SUGGESTS: Real sales losses with post-close activity")

    print()
    print(f"4. WON DEALS:")
    print(f"   {len(won_negative)} won deals with negative gap")

    if len(won_negative) > 10:
        print("   → STRONG EVIDENCE: close_date is unreliable for these deals")
    else:
        print("   → INCONCLUSIVE: Small sample")

    print()

    # Final recommendation
    print("=" * 80)
    print("RECOMMENDATION")
    print("=" * 80)
    print()

    if bulk_month_count > len(negative_gap_deals) * 0.5 and blank_pct > 50:
        print("OPTION A CONFIRMED: Administrative backdating during bulk operations")
        print()
        print("These 114 deals should be EXCLUDED from Signal 3 entirely.")
        print("Their close_date is not trustworthy for ANY purpose.")
        print()
        print("NEXT STEP: Create exclusion list of these 114 deal_ids")
    elif blank_pct < 50:
        print("OPTION B INDICATED: Real post-close activity")
        print()
        print("Use stage-transition-date for these deals (when deal entered closed stage)")
        print()
        print("NEXT STEP: Implement stage-transition-date logic")
    else:
        print("MIXED PATTERN: Further investigation needed")
        print()
        print("Consider hybrid approach:")
        print("- Exclude deals with close_date in bulk months + blank lost_reason")
        print("- Use stage-transition-date for remaining deals")

if __name__ == '__main__':
    main()
