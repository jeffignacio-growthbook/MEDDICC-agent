"""
Enterprise Discovery Fallback Sanity Check

Enterprise Discovery (n=2) falls back to stage-only 19-day threshold.
This threshold is derived mostly from Mid-Market/SMB deals.

Check: Are Enterprise deals flagged CRITICAL/WARN due to this fallback
genuinely at-risk, or just normal Enterprise evaluation cycles?
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

def get_active_deals():
    """Fetch all active deals"""
    response = sb.table('deals').select(
        'deal_id, company_name, stage, segment, deal_status, new_arr, expansion_arr, create_date'
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

def get_deal_create_date_parsed(deal):
    """Parse create_date"""
    create_date_str = deal.get('create_date')
    if not create_date_str:
        return None
    try:
        dt = datetime.fromisoformat(create_date_str.replace('Z', '+00:00'))
        # Ensure timezone aware
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        return dt
    except:
        return None

def main():
    print("=" * 80)
    print("ENTERPRISE DISCOVERY FALLBACK SANITY CHECK")
    print("=" * 80)

    # Discovery threshold (stage-only fallback)
    DISCOVERY_THRESHOLD = 19

    print(f"\nDiscovery threshold (stage-only): {DISCOVERY_THRESHOLD} days")
    print("  Derived from: n=14 clean won deals (mostly Mid-Market/SMB)")
    print("  Applied to: Enterprise Discovery deals (n=2 insufficient for segment-specific)")

    # Get active Enterprise deals in Discovery
    active_deals = get_active_deals()
    enterprise_discovery_deals = [
        d for d in active_deals
        if d.get('segment') == 'Enterprise' and get_stage_bucket(d['stage']) == 'discovery'
    ]

    print(f"\n\nTotal active Enterprise Discovery deals: {len(enterprise_discovery_deals)}")

    if not enterprise_discovery_deals:
        print("\n✅ No Enterprise Discovery deals to check")
        return

    # Classify each deal
    now = datetime.now(timezone.utc)

    flagged_deals = []
    healthy_deals = []

    for deal in enterprise_discovery_deals:
        deal_id = deal['deal_id']
        time_in_stage = get_time_in_current_stage(deal_id, deal['stage'])

        if not time_in_stage:
            continue

        # Signal 2
        signal_2_fires = time_in_stage > DISCOVERY_THRESHOLD

        # Signal 3
        last_activity = get_last_activity_date(deal_id)
        if last_activity:
            days_since = (now - last_activity).days
            signal_3_fires = days_since > SIGNAL_3_THRESHOLD
            signal_3_status = 'fires' if signal_3_fires else 'no_fire'
        else:
            signal_3_fires = False
            signal_3_status = 'no_data'

        # Classification
        if signal_2_fires and signal_3_status == 'fires':
            classification = 'CRITICAL'
        elif signal_2_fires and signal_3_status == 'no_fire':
            classification = 'WARN'
        elif signal_2_fires and signal_3_status == 'no_data':
            classification = 'no_signal_at_risk'
        else:
            classification = 'HEALTHY'

        # Deal age (from create_date)
        create_date = get_deal_create_date_parsed(deal)
        if create_date:
            deal_age = (now - create_date).days
        else:
            deal_age = None

        # Calculate deal value
        new_arr = deal.get('new_arr', 0) or 0
        expansion_arr = deal.get('expansion_arr', 0) or 0
        deal_value = new_arr + expansion_arr

        deal_info = {
            'company': deal['company_name'],
            'stage': deal['stage'],
            'segment': deal['segment'],
            'amount': deal_value,
            'time_in_stage': time_in_stage,
            'threshold': DISCOVERY_THRESHOLD,
            'signal_2_fires': signal_2_fires,
            'days_since_activity': days_since if last_activity else None,
            'signal_3_status': signal_3_status,
            'classification': classification,
            'deal_age': deal_age
        }

        if signal_2_fires:
            flagged_deals.append(deal_info)
        else:
            healthy_deals.append(deal_info)

    # Report flagged deals
    print("\n" + "=" * 80)
    print(f"ENTERPRISE DISCOVERY DEALS FLAGGED BY 19-DAY THRESHOLD")
    print("=" * 80)

    print(f"\nFlagged: {len(flagged_deals)}/{len(enterprise_discovery_deals)} Enterprise Discovery deals")

    if not flagged_deals:
        print("\n✅ No Enterprise Discovery deals flagged")
        print("   19-day threshold appears appropriate (no over-flagging)")
        return

    print("\n" + "-" * 80)
    print("FLAGGED ENTERPRISE DISCOVERY DEALS")
    print("-" * 80)

    for info in sorted(flagged_deals, key=lambda x: -x['time_in_stage']):
        print(f"\n{info['company']}")
        print(f"  Stage: {info['stage']}")
        print(f"  Amount: ${info['amount']:,.0f}")
        print(f"  Time in stage: {info['time_in_stage']} days (threshold: {info['threshold']} days)")
        print(f"  Deal age: {info['deal_age']} days" if info['deal_age'] else "  Deal age: Unknown")

        if info['days_since_activity']:
            print(f"  Last activity: {info['days_since_activity']} days ago")
        else:
            print(f"  Last activity: No data")

        print(f"  Signal 2: {'FIRES' if info['signal_2_fires'] else 'No'}")
        print(f"  Signal 3: {info['signal_3_status']}")
        print(f"  Classification: {info['classification']}")

    # Gut check questions
    print("\n" + "=" * 80)
    print("GUT CHECK QUESTIONS")
    print("=" * 80)

    print("\nFor each flagged deal above, consider:")
    print("  1. Is this deal genuinely stale/neglected, or just normal Enterprise evaluation cycle?")
    print("  2. Is 19 days (2.7 weeks) a reasonable threshold for Enterprise Discovery?")
    print("  3. Do these deals look like they need intervention, or are they being worked actively?")

    # Show healthy deals for comparison
    if healthy_deals:
        print("\n" + "=" * 80)
        print(f"HEALTHY ENTERPRISE DISCOVERY DEALS (for comparison)")
        print("=" * 80)

        print(f"\nHealthy: {len(healthy_deals)}/{len(enterprise_discovery_deals)} deals")
        print("\nShowing deals NOT flagged (time in stage ≤ 19 days):\n")

        for info in sorted(healthy_deals, key=lambda x: -x['time_in_stage']):
            print(f"{info['company']}: {info['time_in_stage']} days in stage (${info['amount']:,.0f})")

    # Statistics
    print("\n" + "=" * 80)
    print("STATISTICS")
    print("=" * 80)

    all_times = [d['time_in_stage'] for d in flagged_deals + healthy_deals]
    flagged_times = [d['time_in_stage'] for d in flagged_deals]

    print(f"\nAll Enterprise Discovery deals (n={len(all_times)}):")
    if all_times:
        print(f"  Min: {min(all_times)} days")
        print(f"  Median: {sorted(all_times)[len(all_times)//2]} days")
        print(f"  Max: {max(all_times)} days")
        print(f"  Flagged by 19-day threshold: {len(flagged_times)}/{len(all_times)} ({len(flagged_times)/len(all_times)*100:.1f}%)")

    if flagged_times:
        print(f"\nFlagged Enterprise Discovery deals (n={len(flagged_times)}):")
        print(f"  Min: {min(flagged_times)} days")
        print(f"  Median: {sorted(flagged_times)[len(flagged_times)//2]} days")
        print(f"  Max: {max(flagged_times)} days")

    # Recommendation
    print("\n" + "=" * 80)
    print("RECOMMENDATION")
    print("=" * 80)

    flagging_rate = len(flagged_deals) / len(enterprise_discovery_deals) * 100

    if flagging_rate > 50:
        print(f"\n⚠️  HIGH FLAGGING RATE ({flagging_rate:.1f}%)")
        print("   More than half of Enterprise Discovery deals flagged.")
        print("   This suggests 19-day threshold may be over-aggressive for Enterprise segment.")
        print("\n   Consider:")
        print("   - Accept higher threshold for Enterprise (30-45 days) via manual override")
        print("   - Wait for more Enterprise won deals to derive segment-specific threshold")
        print("   - Validate with sales team: is 2.7 weeks reasonable for Enterprise Discovery?")
    elif flagging_rate > 30:
        print(f"\n⚠️  MODERATE FLAGGING RATE ({flagging_rate:.1f}%)")
        print("   ~1/3 of Enterprise Discovery deals flagged.")
        print("   Review flagged deals above - do they look genuinely at-risk?")
        print("\n   If yes: 19-day threshold is appropriate, even for Enterprise")
        print("   If no: Consider segment-specific adjustment once n≥5")
    else:
        print(f"\n✅ REASONABLE FLAGGING RATE ({flagging_rate:.1f}%)")
        print("   Minority of Enterprise Discovery deals flagged.")
        print("   19-day threshold appears appropriate, even as fallback for Enterprise.")

if __name__ == '__main__':
    main()
