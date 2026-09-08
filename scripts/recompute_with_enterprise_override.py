"""
Recompute Classification with Enterprise Discovery Manual Override

Apply 35-day manual override for Enterprise x Discovery (replacing 19-day fallback).
All other cells unchanged from clean derivation.

Report new Enterprise Discovery flagging rate to confirm drop to plausible level.
"""

import os
from datetime import datetime, timezone
from supabase import create_client, Client
from dotenv import load_dotenv

load_dotenv()

# Supabase setup
SUPABASE_URL = os.getenv('SUPABASE_URL')
SUPABASE_KEY = os.getenv('SUPABASE_SERVICE_KEY')

if not SUPABASE_URL or not SUPABASE_KEY:
    raise ValueError("Missing SUPABASE_URL or SUPABASE_SERVICE_KEY")

sb: Client = create_client(SUPABASE_URL, SUPABASE_KEY)

SIGNAL_3_THRESHOLD = 14

# Clean thresholds with ENTERPRISE DISCOVERY OVERRIDE
THRESHOLDS = {
    # Discovery - OVERRIDE for Enterprise
    ('discovery', 'Enterprise'): (35, 'MANUAL_OVERRIDE'),  # ← MANUAL OVERRIDE (was 19d fallback)
    ('discovery', 'Mid-Market'): (19, 'segment_specific'),
    ('discovery', 'SMB'): (25, 'segment_specific'),
    # Scoping
    ('scoping', 'Enterprise'): (23, 'stage_only'),
    ('scoping', 'Mid-Market'): (23, 'segment_specific'),
    ('scoping', 'SMB'): (23, 'stage_only'),
    # Proposal
    ('proposal', 'Enterprise'): (105, 'stage_only'),
    ('proposal', 'Mid-Market'): (105, 'stage_only'),
    ('proposal', 'SMB'): (105, 'stage_only'),
}

# Stage-only fallbacks (unchanged)
STAGE_FALLBACKS = {
    'discovery': 19,
    'scoping': 23,
    'proposal': 105,
}

def get_stage_bucket(stage):
    """Map stage to bucket"""
    stage_lower = stage.lower() if stage else ''

    if 'appointment' in stage_lower or 'discovery' in stage_lower or '79653122' in stage:
        return 'discovery'
    elif 'qualified' in stage_lower or 'scoping' in stage_lower:
        return 'scoping'
    elif 'presentation' in stage_lower or 'decision' in stage_lower or 'contract' in stage_lower:
        return 'proposal'
    else:
        return 'unknown'

def get_threshold(stage_bucket, segment):
    """Get threshold with Enterprise Discovery override"""
    key = (stage_bucket, segment)

    # Try exact match (includes Enterprise Discovery override)
    if key in THRESHOLDS:
        return THRESHOLDS[key]

    # Fall back to stage-only for unknown segments
    if stage_bucket in STAGE_FALLBACKS:
        return STAGE_FALLBACKS[stage_bucket], 'stage_only'

    return None, 'no_threshold'

def get_active_deals():
    """Fetch all active deals"""
    response = sb.table('deals').select(
        'deal_id, company_name, stage, segment, deal_status, new_arr, expansion_arr'
    ).eq('deal_status', 'active').execute()
    return response.data

def get_time_in_current_stage(deal_id, current_stage):
    """Get days in current stage"""
    response = sb.table('property_history').select(
        'changed_at, new_value'
    ).eq('deal_id', deal_id).eq(
        'property_name', 'dealstage'
    ).order('changed_at', desc=True).execute()

    if not response.data:
        return None

    now = datetime.now(timezone.utc)

    # Find most recent entry to current_stage
    for change in response.data:
        if change['new_value'] == current_stage:
            stage_entry = datetime.fromisoformat(change['changed_at'].replace('Z', '+00:00'))
            return (now - stage_entry).days

    # If not found, use oldest change as approximation
    if response.data:
        oldest = datetime.fromisoformat(response.data[-1]['changed_at'].replace('Z', '+00:00'))
        return (now - oldest).days

    return None

def get_last_activity_date(deal_id):
    """Get most recent notes_last_updated timestamp"""
    response = sb.table('property_history').select(
        'changed_at'
    ).eq('deal_id', deal_id).eq(
        'property_name', 'notes_last_updated'
    ).order('changed_at', desc=True).limit(1).execute()

    if not response.data:
        return None

    return datetime.fromisoformat(response.data[0]['changed_at'].replace('Z', '+00:00'))

def main():
    print("=" * 80)
    print("CLASSIFICATION WITH ENTERPRISE DISCOVERY OVERRIDE")
    print("=" * 80)

    print("\nApplying manual override:")
    print("  Enterprise x Discovery: 35 days (MANUAL_OVERRIDE)")
    print("  Was: 19 days (stage_only fallback)")
    print("\nAll other cells unchanged from clean derivation.")

    # Get active deals
    active_deals = get_active_deals()
    now = datetime.now(timezone.utc)

    results = {
        'critical': [],
        'warn': [],
        'no_signal_at_risk': [],
        'healthy': [],
        'no_signal_healthy': []
    }

    # Track Enterprise Discovery specifically
    enterprise_discovery_deals = []

    print(f"\n\nClassifying {len(active_deals)} active deals...")

    for i, deal in enumerate(active_deals):
        if (i + 1) % 50 == 0:
            print(f"  Processed {i+1}/{len(active_deals)}...")

        deal_id = deal['deal_id']
        stage_bucket = get_stage_bucket(deal['stage'])
        segment = deal.get('segment', 'Unknown')

        # Signal 2: Time in stage
        time_in_stage = get_time_in_current_stage(deal_id, deal['stage'])
        threshold, threshold_type = get_threshold(stage_bucket, segment)

        if time_in_stage and threshold:
            signal_2_fires = time_in_stage > threshold
        else:
            signal_2_fires = False

        # Signal 3: Activity recency
        last_activity = get_last_activity_date(deal_id)

        if last_activity:
            days_since = (now - last_activity).days
            signal_3_fires = days_since > SIGNAL_3_THRESHOLD
            signal_3_result = 'fires' if signal_3_fires else 'no_fire'
        else:
            signal_3_fires = False
            signal_3_result = 'no_data'

        # Modified-AND classification
        deal_info = {
            'deal': deal,
            'time_in_stage': time_in_stage,
            'threshold': threshold,
            'threshold_type': threshold_type,
            'days_since_activity': days_since if last_activity else None,
            'signal_2_fires': signal_2_fires,
            'signal_3_result': signal_3_result
        }

        if signal_2_fires and signal_3_result == 'fires':
            results['critical'].append(deal_info)
        elif signal_2_fires and signal_3_result == 'no_fire':
            results['warn'].append(deal_info)
        elif signal_2_fires and signal_3_result == 'no_data':
            results['no_signal_at_risk'].append(deal_info)
        elif not signal_2_fires and signal_3_result == 'no_data':
            results['no_signal_healthy'].append(deal_info)
        else:
            results['healthy'].append(deal_info)

        # Track Enterprise Discovery deals specifically
        if segment == 'Enterprise' and stage_bucket == 'discovery':
            enterprise_discovery_deals.append({
                'company': deal['company_name'],
                'stage': deal['stage'],
                'time_in_stage': time_in_stage,
                'threshold': threshold,
                'threshold_type': threshold_type,
                'signal_2_fires': signal_2_fires,
                'days_since_activity': days_since if last_activity else None,
                'signal_3_result': signal_3_result,
                'classification': 'CRITICAL' if signal_2_fires and signal_3_result == 'fires'
                                  else 'WARN' if signal_2_fires and signal_3_result == 'no_fire'
                                  else 'no_signal_at_risk' if signal_2_fires and signal_3_result == 'no_data'
                                  else 'HEALTHY',
                'deal_value': (deal.get('new_arr', 0) or 0) + (deal.get('expansion_arr', 0) or 0)
            })

    # Report overall results
    print("\n" + "=" * 80)
    print("OVERALL CLASSIFICATION RESULTS (WITH OVERRIDE)")
    print("=" * 80)

    print(f"\nCRITICAL (Signal 2 + Signal 3): {len(results['critical'])}")
    print(f"WARN (Signal 2 only): {len(results['warn'])}")
    print(f"no_signal_at_risk: {len(results['no_signal_at_risk'])}")
    print(f"HEALTHY: {len(results['healthy'])}")
    print(f"no_signal_healthy: {len(results['no_signal_healthy'])}")

    total_at_risk = len(results['critical']) + len(results['warn'])
    print(f"\nTotal at-risk (CRITICAL + WARN): {total_at_risk}/{len(active_deals)} ({total_at_risk/len(active_deals)*100:.1f}%)")

    # Compare against clean (no override)
    print("\n" + "=" * 80)
    print("COMPARISON: CLEAN (19d fallback) vs OVERRIDE (35d)")
    print("=" * 80)

    clean_counts = {
        'critical': 102,
        'warn': 47,
        'no_signal_at_risk': 49,
        'healthy': 98,
        'no_signal_healthy': 148
    }

    print(f"\n{'Classification':<25} {'Clean (19d)':>15} {'Override (35d)':>15} {'Diff':>12}")
    print("-" * 75)

    for key in ['critical', 'warn', 'no_signal_at_risk', 'healthy', 'no_signal_healthy']:
        clean = clean_counts[key]
        override = len(results[key])
        diff = override - clean

        print(f"{key:<25} {clean:>15} {override:>15} {diff:>+12}")

    total_at_risk_clean = clean_counts['critical'] + clean_counts['warn']
    total_at_risk_override = len(results['critical']) + len(results['warn'])

    print("-" * 75)
    print(f"{'Total at-risk':<25} {total_at_risk_clean:>15} {total_at_risk_override:>15} {total_at_risk_override - total_at_risk_clean:>+12}")

    # Enterprise Discovery specific analysis
    print("\n" + "=" * 80)
    print("ENTERPRISE DISCOVERY FLAGGING RATE (PRIMARY VALIDATION)")
    print("=" * 80)

    ent_disc_flagged = [d for d in enterprise_discovery_deals if d['signal_2_fires']]
    ent_disc_healthy = [d for d in enterprise_discovery_deals if not d['signal_2_fires']]

    print(f"\nTotal Enterprise Discovery deals: {len(enterprise_discovery_deals)}")
    print(f"  Flagged by 35-day override: {len(ent_disc_flagged)}")
    print(f"  Healthy (≤ 35 days): {len(ent_disc_healthy)}")
    print(f"\n  Flagging rate: {len(ent_disc_flagged)/len(enterprise_discovery_deals)*100:.1f}%")

    print("\nComparison:")
    print(f"  19-day fallback: 34/46 flagged (73.9%)")
    print(f"  35-day override: {len(ent_disc_flagged)}/{len(enterprise_discovery_deals)} flagged ({len(ent_disc_flagged)/len(enterprise_discovery_deals)*100:.1f}%)")
    print(f"  Reduction: {34 - len(ent_disc_flagged)} deals no longer flagged")

    # Show newly healthy Enterprise Discovery deals
    print("\n" + "=" * 80)
    print("ENTERPRISE DISCOVERY DEALS NO LONGER FLAGGED")
    print("=" * 80)

    print("\nDeals between 19-35 days (now HEALTHY under override):\n")
    newly_healthy = [d for d in ent_disc_healthy if d['time_in_stage'] and d['time_in_stage'] > 19]

    if newly_healthy:
        for deal in sorted(newly_healthy, key=lambda x: -x['time_in_stage']):
            print(f"{deal['company']}")
            print(f"  Time in stage: {deal['time_in_stage']} days")
            print(f"  Deal value: ${deal['deal_value']:,.0f}")
            if deal['days_since_activity']:
                print(f"  Last activity: {deal['days_since_activity']} days ago")
            else:
                print(f"  Last activity: No data")
            print()
    else:
        print("  None (all deals either > 35 days or ≤ 19 days)")

    # Show still-flagged Enterprise Discovery deals
    print("\n" + "=" * 80)
    print("ENTERPRISE DISCOVERY DEALS STILL FLAGGED (>35 days)")
    print("=" * 80)

    if ent_disc_flagged:
        print(f"\nShowing top 10 by time in stage:\n")
        for deal in sorted(ent_disc_flagged, key=lambda x: -x['time_in_stage'])[:10]:
            print(f"{deal['company']} ({deal['classification']})")
            print(f"  Time in stage: {deal['time_in_stage']} days (threshold: {deal['threshold']} days)")
            print(f"  Deal value: ${deal['deal_value']:,.0f}")
            if deal['days_since_activity']:
                print(f"  Last activity: {deal['days_since_activity']} days ago")
            else:
                print(f"  Last activity: No data")
            print()
    else:
        print("\nNo Enterprise Discovery deals flagged (all ≤ 35 days)")

    # Assessment
    print("\n" + "=" * 80)
    print("ASSESSMENT")
    print("=" * 80)

    flagging_rate = len(ent_disc_flagged)/len(enterprise_discovery_deals)*100

    if flagging_rate < 30:
        print(f"\n✅ REASONABLE FLAGGING RATE ({flagging_rate:.1f}%)")
        print("   Less than 30% of Enterprise Discovery deals flagged.")
        print("   35-day override appears appropriate for Enterprise evaluation cycles.")
    elif flagging_rate < 50:
        print(f"\n⚠️  MODERATE FLAGGING RATE ({flagging_rate:.1f}%)")
        print("   30-50% of Enterprise Discovery deals flagged.")
        print("   Review flagged deals - do they look genuinely at-risk?")
    else:
        print(f"\n⚠️  STILL HIGH FLAGGING RATE ({flagging_rate:.1f}%)")
        print("   More than 50% of Enterprise Discovery deals still flagged.")
        print("   May need higher override (45-60 days) or indicates real pipeline issue.")

    print("\n" + "=" * 80)
    print("✅ CLASSIFICATION WITH OVERRIDE COMPLETE")
    print("=" * 80)

    print("\nNext steps:")
    print("  1. Update config/field_semantics.yaml with MANUAL_OVERRIDE status")
    print("  2. Document rationale and re-derivation trigger (n≥5)")
    print("  3. Proceed to Slack validation with these thresholds")

if __name__ == '__main__':
    main()
