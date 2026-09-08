"""
Signal 2 Threshold Derivation and Full Re-Classification

1. Derive Signal 2 thresholds: P75 of won deal time-in-stage per stage × segment
2. Report threshold table with sample sizes and fallback indicators
3. Re-run CRITICAL/WARN classification on 444 active deals with REAL thresholds
4. Compare against placeholder-based counts
5. Re-check specific example deals for classification changes
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

# Signal 3 threshold (validated)
SIGNAL_3_THRESHOLD = 14

# Minimum sample size for segment-specific threshold
MIN_SAMPLE_SIZE = 5

def get_stage_bucket(stage):
    """Map stage to bucket"""
    stage_lower = stage.lower() if stage else ''

    if 'appointment' in stage_lower or 'discovery' in stage_lower or '79653122' in stage:
        return 'discovery'
    elif 'qualified' in stage_lower or 'scoping' in stage_lower:
        return 'scoping'
    elif 'presentation' in stage_lower or 'decision' in stage_lower or 'contract' in stage_lower:
        return 'proposal'
    elif 'won' in stage_lower:
        return 'closed_won'
    elif 'lost' in stage_lower:
        return 'closed_lost'
    else:
        return 'unknown'

def get_won_deals():
    """Fetch all won deals"""
    response = sb.table('deals').select(
        'deal_id, company_name, stage, segment, deal_status, create_date, close_date'
    ).eq('deal_status', 'won').execute()

    return response.data

def get_dealstage_history(deal_id):
    """Get dealstage changes for a deal"""
    response = sb.table('property_history').select(
        'changed_at, new_value'
    ).eq('deal_id', deal_id).eq(
        'property_name', 'dealstage'
    ).order('changed_at').execute()

    return response.data

def compute_time_in_stage_for_deal(deal_id):
    """
    Compute time spent in each stage for a deal.
    Returns dict: {stage_bucket: days_in_stage}
    """
    history = get_dealstage_history(deal_id)

    if not history:
        return {}

    time_by_stage = {}

    for i in range(len(history) - 1):
        current_stage = history[i]['new_value']
        next_stage = history[i + 1]['new_value']

        start_time = datetime.fromisoformat(history[i]['changed_at'].replace('Z', '+00:00'))
        end_time = datetime.fromisoformat(history[i + 1]['changed_at'].replace('Z', '+00:00'))

        days_in_stage = (end_time - start_time).days

        stage_bucket = get_stage_bucket(current_stage)

        # Skip closed stages
        if stage_bucket in ['closed_won', 'closed_lost']:
            continue

        # Accumulate time if stage appears multiple times
        if stage_bucket in time_by_stage:
            time_by_stage[stage_bucket] += days_in_stage
        else:
            time_by_stage[stage_bucket] = days_in_stage

    return time_by_stage

def derive_signal2_thresholds():
    """
    Derive Signal 2 thresholds: P75 of won deal time-in-stage per stage × segment.
    Returns: thresholds dict, sample sizes, fallback indicators
    """
    print("=" * 80)
    print("SIGNAL 2 THRESHOLD DERIVATION")
    print("=" * 80)

    # Get won deals
    print("\nFetching won deals...")
    won_deals = get_won_deals()
    print(f"Total won deals: {len(won_deals)}")

    # Compute time-in-stage for each deal
    print("\nComputing time-in-stage for each deal...")
    time_by_cell = defaultdict(list)

    for i, deal in enumerate(won_deals):
        if (i + 1) % 20 == 0:
            print(f"  Processed {i+1}/{len(won_deals)}...")

        deal_id = deal['deal_id']
        segment = deal.get('segment', 'Unknown')

        time_in_stages = compute_time_in_stage_for_deal(deal_id)

        for stage_bucket, days in time_in_stages.items():
            if stage_bucket not in ['closed_won', 'closed_lost', 'unknown']:
                key = (stage_bucket, segment)
                time_by_cell[key].append(days)

    print(f"\nCompleted time-in-stage computation")

    # Derive thresholds per cell
    print("\n" + "=" * 80)
    print("THRESHOLD DERIVATION PER CELL")
    print("=" * 80)

    thresholds_segment_specific = {}
    thresholds_stage_only = {}
    sample_sizes = {}

    stages = ['discovery', 'scoping', 'proposal']
    segments = ['Enterprise', 'Mid-Market', 'SMB']

    print(f"\n{'Stage':<15} {'Segment':<15} {'n':>6} {'P75':>8} {'Fallback':<15}")
    print("-" * 70)

    for stage in stages:
        for segment in segments:
            key = (stage, segment)
            times = time_by_cell.get(key, [])

            if len(times) >= MIN_SAMPLE_SIZE:
                # Segment-specific threshold
                times_sorted = sorted(times)
                p75_idx = int(len(times) * 0.75)
                threshold = times_sorted[p75_idx]

                thresholds_segment_specific[key] = threshold
                sample_sizes[key] = len(times)

                print(f"{stage:<15} {segment:<15} {len(times):>6} {threshold:>8} {'Segment-specific':<15}")
            else:
                sample_sizes[key] = len(times)
                print(f"{stage:<15} {segment:<15} {len(times):>6} {'N/A':>8} {'Insufficient':<15}")

    # Compute stage-only fallbacks
    print("\n" + "=" * 80)
    print("STAGE-ONLY FALLBACKS")
    print("=" * 80)

    print(f"\n{'Stage':<15} {'n':>6} {'P75':>8}")
    print("-" * 35)

    for stage in stages:
        # Aggregate across all segments
        all_times = []
        for segment in segments:
            key = (stage, segment)
            all_times.extend(time_by_cell.get(key, []))

        if len(all_times) >= MIN_SAMPLE_SIZE:
            times_sorted = sorted(all_times)
            p75_idx = int(len(times_sorted) * 0.75)
            threshold = times_sorted[p75_idx]

            thresholds_stage_only[stage] = threshold
            print(f"{stage:<15} {len(all_times):>6} {threshold:>8}")
        else:
            print(f"{stage:<15} {len(all_times):>6} {'N/A':>8}")

    # Build final threshold lookup with fallback logic
    def get_threshold(stage_bucket, segment):
        """Get threshold with fallback hierarchy"""
        key = (stage_bucket, segment)

        # Try segment-specific
        if key in thresholds_segment_specific:
            return thresholds_segment_specific[key], 'segment_specific'

        # Fall back to stage-only
        if stage_bucket in thresholds_stage_only:
            return thresholds_stage_only[stage_bucket], 'stage_only'

        return None, 'no_threshold'

    return get_threshold, thresholds_segment_specific, thresholds_stage_only, sample_sizes

def get_active_deals():
    """Fetch all active deals"""
    response = sb.table('deals').select(
        'deal_id, company_name, stage, segment, deal_status'
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

def classify_active_deals(get_threshold_func):
    """
    Classify all active deals using real Signal 2 thresholds + 14-day Signal 3.
    Returns classification results and deal details.
    """
    print("\n" + "=" * 80)
    print("CLASSIFYING ACTIVE DEALS WITH REAL THRESHOLDS")
    print("=" * 80)

    active_deals = get_active_deals()
    print(f"\nClassifying {len(active_deals)} active deals...")

    now = datetime.now(timezone.utc)

    results = {
        'critical': [],
        'warn': [],
        'no_signal_at_risk': [],
        'healthy': [],
        'no_signal_healthy': []
    }

    for i, deal in enumerate(active_deals):
        if (i + 1) % 50 == 0:
            print(f"  Processed {i+1}/{len(active_deals)}...")

        deal_id = deal['deal_id']
        stage_bucket = get_stage_bucket(deal['stage'])
        segment = deal.get('segment', 'Unknown')

        # Signal 2: Time in stage
        time_in_stage = get_time_in_current_stage(deal_id, deal['stage'])
        threshold, fallback_type = get_threshold_func(stage_bucket, segment)

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
            signal_3_result = 'no_data'

        # Modified-AND classification
        deal_info = {
            'deal': deal,
            'time_in_stage': time_in_stage,
            'threshold': threshold,
            'fallback_type': fallback_type,
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

    return results

def main():
    # Derive Signal 2 thresholds
    get_threshold, seg_specific, stage_only, sample_sizes = derive_signal2_thresholds()

    # Classify active deals with real thresholds
    results = classify_active_deals(get_threshold)

    # Report results
    print("\n" + "=" * 80)
    print("CLASSIFICATION RESULTS (REAL THRESHOLDS)")
    print("=" * 80)

    print(f"\nCRITICAL (Signal 2 + Signal 3): {len(results['critical'])}")
    print(f"WARN (Signal 2 only): {len(results['warn'])}")
    print(f"no_signal_at_risk: {len(results['no_signal_at_risk'])}")
    print(f"HEALTHY: {len(results['healthy'])}")
    print(f"no_signal_healthy: {len(results['no_signal_healthy'])}")

    # Compare against placeholder
    print("\n" + "=" * 80)
    print("COMPARISON: REAL vs PLACEHOLDER THRESHOLDS")
    print("=" * 80)

    placeholder_counts = {
        'critical': 48,
        'warn': 24,
        'no_signal_at_risk': 23,
        'healthy': 175,
        'no_signal_healthy': 174
    }

    print(f"\n{'Classification':<25} {'Placeholder':>12} {'Real':>12} {'Diff':>12}")
    print("-" * 65)

    for key in ['critical', 'warn', 'no_signal_at_risk', 'healthy', 'no_signal_healthy']:
        placeholder = placeholder_counts[key]
        real = len(results[key])
        diff = real - placeholder

        print(f"{key:<25} {placeholder:>12} {real:>12} {diff:>+12}")

    # Check specific example deals
    print("\n" + "=" * 80)
    print("SPECIFIC DEAL RE-CHECK")
    print("=" * 80)

    example_companies = [
        'Perplexity AI',
        'OpenTable',
        'Natera',
        'Crunchyroll',
        'Samsung Electronics',
        'Little Caesars',
        'Deepgram'
    ]

    print("\nRe-checking specific deals under REAL thresholds:\n")

    for company in example_companies:
        # Find deal in results
        found = False
        classification = None
        deal_info = None

        for cls, deals in results.items():
            for info in deals:
                if info['deal']['company_name'] == company:
                    found = True
                    classification = cls
                    deal_info = info
                    break
            if found:
                break

        if found:
            deal = deal_info['deal']
            print(f"{company}:")
            print(f"  Stage: {deal['stage']} ({deal.get('segment', 'Unknown')})")
            print(f"  Time in stage: {deal_info['time_in_stage']} days")
            print(f"  Threshold: {deal_info['threshold']} days ({deal_info['fallback_type']})")
            print(f"  Signal 2 fires: {deal_info['signal_2_fires']}")

            if deal_info['days_since_activity']:
                print(f"  Last activity: {deal_info['days_since_activity']} days ago")
                print(f"  Signal 3 fires: {deal_info['signal_3_result'] == 'fires'}")
            else:
                print(f"  Last activity: No data")
                print(f"  Signal 3: no_data")

            print(f"  Classification: {classification.upper()}")
            print()
        else:
            print(f"{company}: Not found in active deals\n")

    # Sample CRITICAL deals
    print("\n" + "=" * 80)
    print("SAMPLE CRITICAL DEALS (Top 10 by time in stage)")
    print("=" * 80)

    if results['critical']:
        print()
        for info in sorted(results['critical'], key=lambda x: -x['time_in_stage'])[:10]:
            deal = info['deal']
            print(f"{deal['company_name']}")
            print(f"  Stage: {deal['stage']} ({deal.get('segment', 'Unknown')})")
            print(f"  Time in stage: {info['time_in_stage']} days (threshold: {info['threshold']} days)")
            print(f"  Last activity: {info['days_since_activity']} days ago")
            print(f"  Threshold type: {info['fallback_type']}")
            print()

    # Sample WARN deals
    print("\n" + "=" * 80)
    print("SAMPLE WARN DEALS (Top 10 by time in stage)")
    print("=" * 80)

    if results['warn']:
        print()
        for info in sorted(results['warn'], key=lambda x: -x['time_in_stage'])[:10]:
            deal = info['deal']
            print(f"{deal['company_name']}")
            print(f"  Stage: {deal['stage']} ({deal.get('segment', 'Unknown')})")
            print(f"  Time in stage: {info['time_in_stage']} days (threshold: {info['threshold']} days)")
            print(f"  Last activity: {info['days_since_activity']} days ago")
            print(f"  Threshold type: {info['fallback_type']}")
            print()

    print("\n" + "=" * 80)
    print("✅ SIGNAL 2 DERIVATION AND RE-CLASSIFICATION COMPLETE")
    print("=" * 80)

if __name__ == '__main__':
    main()
