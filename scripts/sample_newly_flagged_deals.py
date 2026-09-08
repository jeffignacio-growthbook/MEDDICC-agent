"""
Sample Newly Flagged Deals - Gut Check for +413% Swing

Pull random sample of 10-15 deals that are:
- Flagged as CRITICAL or WARN under CLEAN thresholds
- Were HEALTHY under CONTAMINATED thresholds

For each, report: deal name, stage, segment, time-in-stage, Signal 3 status.

Gut check: Do these look like genuinely at-risk deals, or is the threshold
swung too far and now over-flagging normal pipeline?
"""

import os
import random
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

# Clean thresholds (segment-specific)
CLEAN_THRESHOLDS = {
    ('discovery', 'Mid-Market'): 19,
    ('discovery', 'SMB'): 25,
    ('scoping', 'Mid-Market'): 23,
}

# Stage-only fallbacks
STAGE_FALLBACKS = {
    'discovery': 19,
    'scoping': 23,
    'proposal': 105,
}

# Contaminated thresholds (for comparison)
CONTAMINATED_THRESHOLDS = {
    ('discovery', 'Enterprise'): 463,
    ('discovery', 'Mid-Market'): 184,
    ('discovery', 'SMB'): 454,
    ('scoping', 'Mid-Market'): 23,  # unchanged
    ('proposal', 'Enterprise'): 105,  # stage-only
    ('proposal', 'Mid-Market'): 105,  # stage-only
    ('proposal', 'SMB'): 105,  # stage-only
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

def get_clean_threshold(stage_bucket, segment):
    """Get clean threshold with fallback"""
    key = (stage_bucket, segment)

    # Try segment-specific
    if key in CLEAN_THRESHOLDS:
        return CLEAN_THRESHOLDS[key], 'segment_specific'

    # Fall back to stage-only
    if stage_bucket in STAGE_FALLBACKS:
        return STAGE_FALLBACKS[stage_bucket], 'stage_only'

    return None, 'no_threshold'

def get_contaminated_threshold(stage_bucket, segment):
    """Get contaminated threshold (for comparison)"""
    key = (stage_bucket, segment)

    # Try exact match
    if key in CONTAMINATED_THRESHOLDS:
        return CONTAMINATED_THRESHOLDS[key]

    # Fall back to stage defaults (very high for discovery, reasonable for others)
    if stage_bucket == 'discovery':
        return 382  # stage-only contaminated
    elif stage_bucket == 'scoping':
        return 41  # stage-only contaminated
    elif stage_bucket == 'proposal':
        return 105  # unchanged

    return None

def main():
    print("=" * 80)
    print("NEWLY FLAGGED DEALS SAMPLE - GUT CHECK FOR +413% SWING")
    print("=" * 80)

    print("\nObjective: Pull random sample of deals that are:")
    print("  - Flagged CRITICAL or WARN under CLEAN thresholds")
    print("  - Were HEALTHY under CONTAMINATED thresholds")
    print("\nGut check: Do these look genuinely at-risk, or just normal pipeline?")

    # Get active deals
    active_deals = get_active_deals()
    now = datetime.now(timezone.utc)

    newly_flagged = []

    print(f"\n\nScanning {len(active_deals)} active deals...")

    for deal in active_deals:
        deal_id = deal['deal_id']
        stage_bucket = get_stage_bucket(deal['stage'])
        segment = deal.get('segment', 'Unknown')

        # Get time in stage
        time_in_stage = get_time_in_current_stage(deal_id, deal['stage'])
        if not time_in_stage:
            continue

        # Clean threshold
        clean_threshold, fallback_type = get_clean_threshold(stage_bucket, segment)
        if not clean_threshold:
            continue

        # Contaminated threshold
        contaminated_threshold = get_contaminated_threshold(stage_bucket, segment)
        if not contaminated_threshold:
            continue

        # Signal 2 under both thresholds
        clean_signal_2_fires = time_in_stage > clean_threshold
        contaminated_signal_2_fires = time_in_stage > contaminated_threshold

        # Signal 3
        last_activity = get_last_activity_date(deal_id)
        if last_activity:
            days_since = (now - last_activity).days
            signal_3_fires = days_since > SIGNAL_3_THRESHOLD
            signal_3_status = 'fires' if signal_3_fires else 'no_fire'
        else:
            signal_3_fires = False
            signal_3_status = 'no_data'

        # Classification under clean thresholds
        if clean_signal_2_fires and signal_3_status == 'fires':
            clean_classification = 'CRITICAL'
        elif clean_signal_2_fires and signal_3_status == 'no_fire':
            clean_classification = 'WARN'
        elif clean_signal_2_fires and signal_3_status == 'no_data':
            clean_classification = 'no_signal_at_risk'
        else:
            clean_classification = 'HEALTHY'

        # Classification under contaminated thresholds
        if contaminated_signal_2_fires and signal_3_status == 'fires':
            contaminated_classification = 'CRITICAL'
        elif contaminated_signal_2_fires and signal_3_status == 'no_fire':
            contaminated_classification = 'WARN'
        elif contaminated_signal_2_fires and signal_3_status == 'no_data':
            contaminated_classification = 'no_signal_at_risk'
        else:
            contaminated_classification = 'HEALTHY'

        # NEWLY FLAGGED: clean flags as CRITICAL/WARN, contaminated was HEALTHY
        if clean_classification in ['CRITICAL', 'WARN'] and contaminated_classification == 'HEALTHY':
            new_arr = deal.get('new_arr', 0) or 0
            expansion_arr = deal.get('expansion_arr', 0) or 0
            deal_value = new_arr + expansion_arr

            newly_flagged.append({
                'company': deal['company_name'],
                'stage': deal['stage'],
                'stage_bucket': stage_bucket,
                'segment': segment,
                'time_in_stage': time_in_stage,
                'clean_threshold': clean_threshold,
                'contaminated_threshold': contaminated_threshold,
                'fallback_type': fallback_type,
                'days_since_activity': days_since if last_activity else None,
                'signal_3_status': signal_3_status,
                'clean_classification': clean_classification,
                'contaminated_classification': contaminated_classification,
                'deal_value': deal_value
            })

    print(f"Found {len(newly_flagged)} newly flagged deals\n")

    # Random sample (10-15 deals)
    sample_size = min(15, len(newly_flagged))
    sample = random.sample(newly_flagged, sample_size) if len(newly_flagged) >= sample_size else newly_flagged

    print("=" * 80)
    print(f"RANDOM SAMPLE OF NEWLY FLAGGED DEALS (n={len(sample)})")
    print("=" * 80)

    for i, deal in enumerate(sample, 1):
        print(f"\n{i}. {deal['company']}")
        print(f"   Stage: {deal['stage']} ({deal['segment']}, {deal['stage_bucket']})")
        print(f"   Deal value: ${deal['deal_value']:,.0f}")
        print(f"   Time in stage: {deal['time_in_stage']} days")
        print(f"   Clean threshold: {deal['clean_threshold']} days ({deal['fallback_type']})")
        print(f"   Contaminated threshold: {deal['contaminated_threshold']} days")

        if deal['days_since_activity']:
            print(f"   Last activity: {deal['days_since_activity']} days ago")
        else:
            print(f"   Last activity: No data")

        print(f"   Signal 3: {deal['signal_3_status']}")
        print(f"   Classification: {deal['contaminated_classification']} → {deal['clean_classification']}")

    # Statistics
    print("\n" + "=" * 80)
    print("SAMPLE STATISTICS")
    print("=" * 80)

    critical_count = sum(1 for d in sample if d['clean_classification'] == 'CRITICAL')
    warn_count = sum(1 for d in sample if d['clean_classification'] == 'WARN')

    print(f"\nClassification breakdown:")
    print(f"  CRITICAL: {critical_count}/{len(sample)} ({critical_count/len(sample)*100:.1f}%)")
    print(f"  WARN: {warn_count}/{len(sample)} ({warn_count/len(sample)*100:.1f}%)")

    # Segment breakdown
    segment_counts = {}
    for d in sample:
        seg = d['segment']
        segment_counts[seg] = segment_counts.get(seg, 0) + 1

    print(f"\nSegment breakdown:")
    for seg, count in sorted(segment_counts.items(), key=lambda x: -x[1]):
        print(f"  {seg}: {count}/{len(sample)} ({count/len(sample)*100:.1f}%)")

    # Stage breakdown
    stage_counts = {}
    for d in sample:
        stage = d['stage_bucket']
        stage_counts[stage] = stage_counts.get(stage, 0) + 1

    print(f"\nStage breakdown:")
    for stage, count in sorted(stage_counts.items(), key=lambda x: -x[1]):
        print(f"  {stage}: {count}/{len(sample)} ({count/len(sample)*100:.1f}%)")

    # Time in stage distribution
    times = [d['time_in_stage'] for d in sample]
    print(f"\nTime in stage distribution:")
    print(f"  Min: {min(times)} days")
    print(f"  Median: {sorted(times)[len(times)//2]} days")
    print(f"  Max: {max(times)} days")

    # Gut check prompts
    print("\n" + "=" * 80)
    print("GUT CHECK QUESTIONS")
    print("=" * 80)

    print("\nFor the sample above, consider:")
    print("  1. Do these deals look genuinely stale/neglected?")
    print("  2. Or do they look like normal pipeline being worked actively?")
    print("  3. Is the +413% swing (29 → 149 flagged deals) catching real issues?")
    print("  4. Or is the clean threshold now over-aggressive?")

    print("\n" + "=" * 80)
    print("INTERPRETATION GUIDE")
    print("=" * 80)

    print("\nIf sample looks GENUINELY AT-RISK:")
    print("  → Clean thresholds are correct")
    print("  → Contaminated thresholds were severely under-flagging")
    print("  → +413% swing is a real problem being surfaced, not over-flagging")

    print("\nIf sample looks MOSTLY HEALTHY:")
    print("  → Clean thresholds may be over-aggressive")
    print("  → Especially for Enterprise Discovery (73.9% flagging rate)")
    print("  → Consider segment-specific adjustments or wait for more data")

    print("\n" + "=" * 80)
    print(f"✅ SAMPLE COMPLETE - {len(sample)} deals reviewed")
    print("=" * 80)

if __name__ == '__main__':
    main()
