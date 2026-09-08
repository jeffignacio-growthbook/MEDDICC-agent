"""
Signal 3 Active Pipeline Analysis

After fetching property_history for active deals, analyze:
1. Actual notes_last_updated coverage on active deals
2. Signal 3 threshold comparison (7 vs 14 days) on active pipeline
3. Signal 3 evaluation breakdown (fires/doesn't fire/no_signal)
4. CRITICAL deals (Signal 2 + Signal 3) vs Signal 2-only comparison
"""

import os
from datetime import datetime, timezone
from collections import defaultdict
from supabase import create_client, Client
from dotenv import load_dotenv

load_dotenv()

# Supabase setup
SUPABASE_URL = os.getenv('SUPABASE_URL')
SUPABASE_KEY = os.getenv('SUPABASE_SERVICE_KEY')

if not SUPABASE_URL or not SUPABASE_KEY:
    raise ValueError("Missing SUPABASE_URL or SUPABASE_SERVICE_KEY")

sb: Client = create_client(SUPABASE_URL, SUPABASE_KEY)

# Signal 3 thresholds to compare
THRESHOLD_7_DAYS = 7
THRESHOLD_14_DAYS = 14

def get_active_deals():
    """Fetch all active deals with stage and segment"""
    response = sb.table('deals').select(
        'deal_id, company_name, stage, segment, deal_status'
    ).eq('deal_status', 'active').execute()

    return response.data

def get_last_activity_date(deal_id):
    """Get most recent notes_last_updated timestamp for a deal"""
    response = sb.table('property_history').select(
        'changed_at'
    ).eq('deal_id', deal_id).eq(
        'property_name', 'notes_last_updated'
    ).order('changed_at', desc=True).limit(1).execute()

    if not response.data:
        return None

    return datetime.fromisoformat(response.data[0]['changed_at'].replace('Z', '+00:00'))

def get_stage_bucket(stage):
    """Map stage to bucket"""
    stage_lower = stage.lower() if stage else ''

    if 'appointment' in stage_lower or 'discovery' in stage_lower:
        return 'discovery'
    elif 'qualified' in stage_lower or 'scoping' in stage_lower:
        return 'scoping'
    elif 'presentation' in stage_lower or 'decision' in stage_lower or 'contract' in stage_lower:
        return 'proposal'
    else:
        return 'unknown'

def main():
    print("=" * 80)
    print("SIGNAL 3 ACTIVE PIPELINE ANALYSIS")
    print("=" * 80)

    # Get active deals
    print("\nFetching active deals...")
    active_deals = get_active_deals()
    print(f"Total active deals: {len(active_deals)}")

    # Current time
    now = datetime.now(timezone.utc)

    # Analyze coverage and flagging
    print("\n" + "=" * 80)
    print("1. ACTUAL COVERAGE ON ACTIVE DEALS")
    print("=" * 80)

    deals_with_activity = []
    deals_no_activity = []

    for deal in active_deals:
        last_activity = get_last_activity_date(deal['deal_id'])

        if last_activity:
            days_since = (now - last_activity).days
            deals_with_activity.append({
                'deal': deal,
                'last_activity': last_activity,
                'days_since': days_since
            })
        else:
            deals_no_activity.append(deal)

    coverage_pct = len(deals_with_activity) / len(active_deals) * 100

    print(f"\nActive deals with notes_last_updated: {len(deals_with_activity)}/{len(active_deals)} ({coverage_pct:.1f}%)")
    print(f"Active deals WITHOUT notes_last_updated: {len(deals_no_activity)}/{len(active_deals)} ({100-coverage_pct:.1f}%)")

    # Threshold comparison
    print("\n" + "=" * 80)
    print("2. SIGNAL 3 THRESHOLD COMPARISON (7 vs 14 DAYS)")
    print("=" * 80)

    flagged_7_days = []
    flagged_14_days = []

    for item in deals_with_activity:
        days_since = item['days_since']

        if days_since > 7:
            flagged_7_days.append(item)

        if days_since > 14:
            flagged_14_days.append(item)

    print(f"\nActive deals with activity data: {len(deals_with_activity)}")
    print(f"  Flagged at 7-day threshold: {len(flagged_7_days)} ({len(flagged_7_days)/len(deals_with_activity)*100:.1f}%)")
    print(f"  Flagged at 14-day threshold: {len(flagged_14_days)} ({len(flagged_14_days)/len(deals_with_activity)*100:.1f}%)")

    reduction = len(flagged_7_days) - len(flagged_14_days)
    if len(flagged_7_days) > 0:
        reduction_pct = (reduction / len(flagged_7_days)) * 100
        print(f"\nReduction: {reduction} deals ({reduction_pct:.1f}% fewer flags at 14 days)")

    # Show deals in 8-14 day range
    flagged_7_only = [f for f in flagged_7_days if f not in flagged_14_days]

    if flagged_7_only:
        print(f"\nDeals flagged at 7 days but NOT at 14 days ({len(flagged_7_only)} deals):")
        print(f"  (8-14 days since last activity)\n")

        for item in sorted(flagged_7_only, key=lambda x: x['days_since'])[:10]:
            deal = item['deal']
            days = item['days_since']
            print(f"  {deal['company_name']}: {days} days")
            print(f"    Stage: {deal['stage']}, Segment: {deal.get('segment', 'Unknown')}")

        if len(flagged_7_only) > 10:
            print(f"\n  ... and {len(flagged_7_only) - 10} more")

    # Signal 3 evaluation breakdown
    print("\n" + "=" * 80)
    print("3. SIGNAL 3 EVALUATION BREAKDOWN (14-Day Threshold)")
    print("=" * 80)

    signal_3_fires = len(flagged_14_days)
    signal_3_no_fire = len(deals_with_activity) - len(flagged_14_days)
    signal_3_no_data = len(deals_no_activity)

    print(f"\nSignal 3 evaluation on {len(active_deals)} active deals:")
    print(f"  Fires (>14 days): {signal_3_fires} ({signal_3_fires/len(active_deals)*100:.1f}%)")
    print(f"  Doesn't fire (≤14 days): {signal_3_no_fire} ({signal_3_no_fire/len(active_deals)*100:.1f}%)")
    print(f"  No data (no history): {signal_3_no_data} ({signal_3_no_data/len(active_deals)*100:.1f}%)")

    print(f"\nOf deals WITH activity data ({len(deals_with_activity)}):")
    print(f"  Fires: {signal_3_fires} ({signal_3_fires/len(deals_with_activity)*100:.1f}%)")
    print(f"  Doesn't fire: {signal_3_no_fire} ({signal_3_no_fire/len(deals_with_activity)*100:.1f}%)")

    # Modified-AND classification
    print("\n" + "=" * 80)
    print("4. MODIFIED-AND CLASSIFICATION (Signal 2 + Signal 3)")
    print("=" * 80)

    print("\nNote: Signal 2 thresholds not yet derived.")
    print("For this analysis, using placeholder Signal 2 logic:")
    print("  - Discovery: >60 days in stage")
    print("  - Scoping: >45 days in stage")
    print("  - Proposal: >30 days in stage")

    # Get stage entry dates (simplified - using dealstage history)
    def get_time_in_current_stage(deal_id, current_stage):
        """Get days in current stage (simplified)"""
        response = sb.table('property_history').select(
            'changed_at, new_value'
        ).eq('deal_id', deal_id).eq(
            'property_name', 'dealstage'
        ).order('changed_at', desc=True).execute()

        if not response.data:
            return None

        # Find most recent entry to current_stage
        for change in response.data:
            if change['new_value'] == current_stage:
                stage_entry = datetime.fromisoformat(change['changed_at'].replace('Z', '+00:00'))
                return (now - stage_entry).days

        # If not found, use oldest change as approximation
        oldest = datetime.fromisoformat(response.data[-1]['changed_at'].replace('Z', '+00:00'))
        return (now - oldest).days

    # Placeholder Signal 2 thresholds
    SIGNAL_2_THRESHOLDS = {
        'discovery': 60,
        'scoping': 45,
        'proposal': 30
    }

    # Classify all active deals
    critical_deals = []
    warn_deals = []
    no_signal_at_risk = []
    healthy_deals = []
    no_signal_healthy = []

    print("\nClassifying active deals...")
    for i, deal in enumerate(active_deals):
        if (i + 1) % 50 == 0:
            print(f"  Processed {i+1}/{len(active_deals)}...")

        deal_id = deal['deal_id']
        stage_bucket = get_stage_bucket(deal['stage'])

        # Signal 2: Time in stage
        time_in_stage = get_time_in_current_stage(deal_id, deal['stage'])
        signal_2_threshold = SIGNAL_2_THRESHOLDS.get(stage_bucket)

        if time_in_stage and signal_2_threshold:
            signal_2_fires = time_in_stage > signal_2_threshold
        else:
            signal_2_fires = False

        # Signal 3: Activity recency
        last_activity = get_last_activity_date(deal_id)

        if last_activity:
            days_since = (now - last_activity).days
            signal_3_fires = days_since > THRESHOLD_14_DAYS
            signal_3_result = 'fires' if signal_3_fires else 'no_fire'
        else:
            signal_3_result = 'no_data'

        # Modified-AND classification
        if signal_2_fires and signal_3_result == 'fires':
            critical_deals.append({
                'deal': deal,
                'time_in_stage': time_in_stage,
                'days_since_activity': days_since if last_activity else None
            })
        elif signal_2_fires and signal_3_result == 'no_fire':
            warn_deals.append({
                'deal': deal,
                'time_in_stage': time_in_stage,
                'days_since_activity': days_since if last_activity else None
            })
        elif signal_2_fires and signal_3_result == 'no_data':
            no_signal_at_risk.append({
                'deal': deal,
                'time_in_stage': time_in_stage
            })
        elif not signal_2_fires and signal_3_result == 'no_data':
            no_signal_healthy.append({
                'deal': deal,
                'time_in_stage': time_in_stage
            })
        else:
            healthy_deals.append({
                'deal': deal,
                'time_in_stage': time_in_stage,
                'days_since_activity': days_since if last_activity else None
            })

    print(f"\nClassification results:")
    print(f"  CRITICAL (Signal 2 + Signal 3): {len(critical_deals)}")
    print(f"  WARN (Signal 2 only): {len(warn_deals)}")
    print(f"  no_signal_at_risk (Signal 2, no S3 data): {len(no_signal_at_risk)}")
    print(f"  HEALTHY: {len(healthy_deals)}")
    print(f"  no_signal_healthy (no S2 or S3 fire, no S3 data): {len(no_signal_healthy)}")

    # Sample critical deals
    if critical_deals:
        print("\n" + "=" * 80)
        print("SAMPLE CRITICAL DEALS (Both Signals Fire)")
        print("=" * 80)
        print("\nTop 10 deals by time in stage:\n")

        for item in sorted(critical_deals, key=lambda x: -x['time_in_stage'])[:10]:
            deal = item['deal']
            time_in_stage = item['time_in_stage']
            days_since = item['days_since_activity']

            print(f"{deal['company_name']}")
            print(f"  Stage: {deal['stage']} ({deal.get('segment', 'Unknown')})")
            print(f"  Time in stage: {time_in_stage} days")
            print(f"  Last activity: {days_since} days ago")
            print(f"  ⚠️  CRITICAL: Long in stage AND no recent activity\n")

    # Sample warn deals (Signal 2 only)
    if warn_deals:
        print("\n" + "=" * 80)
        print("SAMPLE WARN DEALS (Signal 2 Only)")
        print("=" * 80)
        print("\nTop 10 deals by time in stage:\n")

        for item in sorted(warn_deals, key=lambda x: -x['time_in_stage'])[:10]:
            deal = item['deal']
            time_in_stage = item['time_in_stage']
            days_since = item['days_since_activity']

            print(f"{deal['company_name']}")
            print(f"  Stage: {deal['stage']} ({deal.get('segment', 'Unknown')})")
            print(f"  Time in stage: {time_in_stage} days")
            print(f"  Last activity: {days_since} days ago")
            print(f"  ⚠️  WARN: Long in stage BUT recent activity\n")

    # Compare critical vs warn
    print("\n" + "=" * 80)
    print("CRITICAL vs WARN COMPARISON")
    print("=" * 80)

    if critical_deals and warn_deals:
        critical_avg_time = sum(d['time_in_stage'] for d in critical_deals) / len(critical_deals)
        critical_avg_activity = sum(d['days_since_activity'] for d in critical_deals) / len(critical_deals)

        warn_avg_time = sum(d['time_in_stage'] for d in warn_deals) / len(warn_deals)
        warn_avg_activity = sum(d['days_since_activity'] for d in warn_deals) / len(warn_deals)

        print(f"\nCRITICAL deals (n={len(critical_deals)}):")
        print(f"  Average time in stage: {critical_avg_time:.0f} days")
        print(f"  Average days since activity: {critical_avg_activity:.0f} days")

        print(f"\nWARN deals (n={len(warn_deals)}):")
        print(f"  Average time in stage: {warn_avg_time:.0f} days")
        print(f"  Average days since activity: {warn_avg_activity:.0f} days")

        print(f"\nDifference:")
        print(f"  Time in stage: {critical_avg_time - warn_avg_time:+.0f} days")
        print(f"  Days since activity: {critical_avg_activity - warn_avg_activity:+.0f} days")

        print(f"\n✅ Adding Signal 3 separates:")
        print(f"   - CRITICAL: Long in stage + disengaged (no activity)")
        print(f"   - WARN: Long in stage + actively working (recent activity)")

    print("\n" + "=" * 80)
    print("SUMMARY")
    print("=" * 80)

    print(f"\n1. Coverage: {coverage_pct:.1f}% of active deals have activity data")
    print(f"   - Lower than closed deals (73.7%) - likely due to newer deals")

    print(f"\n2. Threshold: 14 days flags {len(flagged_14_days)} deals ({len(flagged_14_days)/len(deals_with_activity)*100:.1f}% of those with data)")
    print(f"   - 7 days would flag {len(flagged_7_days)} ({reduction} more deals, +{reduction_pct:.1f}%)")

    print(f"\n3. Signal 3 evaluation:")
    print(f"   - Fires: {signal_3_fires}/{len(active_deals)} ({signal_3_fires/len(active_deals)*100:.1f}%)")
    print(f"   - Doesn't fire: {signal_3_no_fire}/{len(active_deals)} ({signal_3_no_fire/len(active_deals)*100:.1f}%)")
    print(f"   - No data: {signal_3_no_data}/{len(active_deals)} ({signal_3_no_data/len(active_deals)*100:.1f}%)")

    print(f"\n4. Modified-AND classification:")
    print(f"   - CRITICAL (both signals): {len(critical_deals)}")
    print(f"   - WARN (Signal 2 only): {len(warn_deals)}")
    print(f"   - no_signal_at_risk: {len(no_signal_at_risk)}")

    if critical_deals and warn_deals:
        print(f"\n✅ Signal 3 adds value:")
        print(f"   - Separates disengaged deals (CRITICAL) from actively working deals (WARN)")
        print(f"   - Even with 55.6% coverage, provides actionable distinction")

if __name__ == '__main__':
    main()
