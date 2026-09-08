"""
Signal 2 Discovery Threshold Sanity Check

Check for contamination patterns in Discovery stage P75 derivation:
1. Distribution analysis - outlier-driven?
2. Renewal contamination - did renewals slip through?
3. Negative cycle time exclusion - was universal rule applied?
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
    """Fetch all won deals with full details"""
    response = sb.table('deals').select(
        'deal_id, company_name, stage, segment, deal_status, create_date, close_date, '
        'new_arr, expansion_arr, renewal_revenue, pipeline_id'
    ).eq('deal_status', 'won').execute()

    return response.data

def parse_date(date_str):
    """Parse date string to datetime"""
    if not date_str:
        return None
    try:
        dt = datetime.fromisoformat(date_str.replace('Z', '+00:00'))
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        return dt
    except:
        return None

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

def is_renewal_deal(deal):
    """Check if deal is a renewal (contamination check)"""
    # Check pipeline_id (renewal pipeline is 866608541)
    if deal.get('pipeline_id') == '866608541':
        return True

    # Check ARR pattern (renewal_revenue > 0)
    renewal_revenue = deal.get('renewal_revenue')
    if renewal_revenue and float(renewal_revenue) > 0:
        return True

    return False

def has_negative_cycle_time(deal):
    """Check for negative cycle time (create_date > close_date)"""
    create_date = parse_date(deal.get('create_date'))
    close_date = parse_date(deal.get('close_date'))

    if not create_date or not close_date:
        return False

    return create_date > close_date

def main():
    print("=" * 80)
    print("SIGNAL 2 DISCOVERY THRESHOLD SANITY CHECK")
    print("=" * 80)

    # Get all won deals
    print("\nFetching won deals...")
    all_won_deals = get_won_deals()
    print(f"Total won deals: {len(all_won_deals)}")

    # Check 1: Renewal contamination
    print("\n" + "=" * 80)
    print("CHECK 1: RENEWAL CONTAMINATION")
    print("=" * 80)

    renewal_deals = [d for d in all_won_deals if is_renewal_deal(d)]
    non_renewal_deals = [d for d in all_won_deals if not is_renewal_deal(d)]

    print(f"\nRenewal deals found: {len(renewal_deals)}/{len(all_won_deals)} ({len(renewal_deals)/len(all_won_deals)*100:.1f}%)")
    print(f"Non-renewal deals: {len(non_renewal_deals)}/{len(all_won_deals)} ({len(non_renewal_deals)/len(all_won_deals)*100:.1f}%)")

    if renewal_deals:
        print(f"\n⚠️  WARNING: {len(renewal_deals)} renewal deals found in won population")
        print("   These should have been excluded from Signal 2 derivation")
        print("\n   Sample renewal deals:")
        for deal in renewal_deals[:5]:
            print(f"     - {deal['company_name']}: pipeline_id={deal.get('pipeline_id')}, renewal_revenue={deal.get('renewal_revenue')}")

    # Check 2: Negative cycle time
    print("\n" + "=" * 80)
    print("CHECK 2: NEGATIVE CYCLE TIME")
    print("=" * 80)

    negative_cycle_deals = [d for d in all_won_deals if has_negative_cycle_time(d)]

    print(f"\nDeals with negative cycle time: {len(negative_cycle_deals)}/{len(all_won_deals)} ({len(negative_cycle_deals)/len(all_won_deals)*100:.1f}%)")

    if negative_cycle_deals:
        print(f"\n⚠️  WARNING: {len(negative_cycle_deals)} deals with create_date > close_date")
        print("   These should be excluded per universal data integrity rule")
        print("\n   Sample negative cycle time deals:")
        for deal in negative_cycle_deals[:5]:
            create = parse_date(deal.get('create_date'))
            close = parse_date(deal.get('close_date'))
            if create and close:
                days = (close - create).days
                print(f"     - {deal['company_name']}: {days} days (create {create.date()}, close {close.date()})")

    # Apply filters
    print("\n" + "=" * 80)
    print("APPLYING FILTERS")
    print("=" * 80)

    clean_won_deals = [d for d in all_won_deals if not is_renewal_deal(d) and not has_negative_cycle_time(d)]

    print(f"\nWon deals after filters:")
    print(f"  Original: {len(all_won_deals)}")
    print(f"  After renewal exclusion: {len(non_renewal_deals)}")
    print(f"  After negative cycle exclusion: {len(clean_won_deals)}")
    print(f"  Removed: {len(all_won_deals) - len(clean_won_deals)} deals")

    # Re-compute Discovery distributions
    print("\n" + "=" * 80)
    print("CHECK 3: DISCOVERY DISTRIBUTION ANALYSIS")
    print("=" * 80)

    print("\nComputing time-in-stage for clean won deals...")
    discovery_by_segment = defaultdict(list)
    discovery_deal_details = defaultdict(list)

    for i, deal in enumerate(clean_won_deals):
        if (i + 1) % 50 == 0:
            print(f"  Processed {i+1}/{len(clean_won_deals)}...")

        deal_id = deal['deal_id']
        segment = deal.get('segment', 'Unknown')

        time_in_stages = compute_time_in_stage_for_deal(deal_id)

        if 'discovery' in time_in_stages:
            discovery_days = time_in_stages['discovery']
            discovery_by_segment[segment].append(discovery_days)
            discovery_deal_details[segment].append({
                'company': deal['company_name'],
                'days': discovery_days,
                'create_date': deal.get('create_date'),
                'close_date': deal.get('close_date')
            })

    print(f"\nCompleted time-in-stage computation")

    # Analyze Discovery distributions
    for segment in ['Enterprise', 'Mid-Market', 'SMB']:
        days_list = discovery_by_segment[segment]
        details = discovery_deal_details[segment]

        if not days_list:
            print(f"\n{segment}: No Discovery data")
            continue

        days_sorted = sorted(days_list)
        n = len(days_sorted)

        # Calculate statistics
        median = days_sorted[n // 2]
        p25 = days_sorted[n // 4]
        p75 = days_sorted[int(n * 0.75)]
        mean = sum(days_sorted) / n
        max_val = max(days_sorted)
        min_val = min(days_sorted)

        print(f"\n{segment} Discovery (n={n}):")
        print(f"  Min: {min_val} days")
        print(f"  P25: {p25} days")
        print(f"  Median: {median} days")
        print(f"  P75: {p75} days")
        print(f"  Mean: {mean:.0f} days")
        print(f"  Max: {max_val} days")

        # Check for outliers (values > P75 + 1.5*IQR)
        iqr = p75 - p25
        outlier_threshold = p75 + 1.5 * iqr

        outliers = [d for d in days_sorted if d > outlier_threshold]
        outlier_pct = len(outliers) / n * 100

        print(f"\n  Outliers (>{outlier_threshold:.0f} days): {len(outliers)}/{n} ({outlier_pct:.1f}%)")

        if outliers:
            # Check if P75 is heavily influenced by outliers
            # Re-compute P75 without outliers
            non_outlier_days = [d for d in days_sorted if d <= outlier_threshold]
            if non_outlier_days:
                p75_without_outliers = sorted(non_outlier_days)[int(len(non_outlier_days) * 0.75)]
                print(f"  P75 without outliers: {p75_without_outliers} days (vs {p75} with outliers)")

                if p75 - p75_without_outliers > 50:
                    print(f"  ⚠️  P75 heavily influenced by outliers ({p75 - p75_without_outliers} day difference)")

        # Show top outliers
        if outliers:
            print(f"\n  Top outliers:")
            outlier_details = [(d['company'], d['days']) for d in details if d['days'] in outliers[-5:]]
            for company, days in sorted(outlier_details, key=lambda x: -x[1])[:5]:
                print(f"    - {company}: {days} days")

    # Compare before/after filtering
    print("\n" + "=" * 80)
    print("BEFORE vs AFTER FILTERING")
    print("=" * 80)

    # Re-compute with original population (before filters)
    print("\nRe-computing Discovery with UNFILTERED population...")
    discovery_unfiltered = defaultdict(list)

    for deal in all_won_deals:
        deal_id = deal['deal_id']
        segment = deal.get('segment', 'Unknown')

        time_in_stages = compute_time_in_stage_for_deal(deal_id)

        if 'discovery' in time_in_stages:
            discovery_unfiltered[segment].append(time_in_stages['discovery'])

    print(f"\n{'Segment':<15} {'Before n':>10} {'Before P75':>12} {'After n':>10} {'After P75':>12} {'Diff':>10}")
    print("-" * 75)

    for segment in ['Enterprise', 'Mid-Market', 'SMB']:
        before_days = discovery_unfiltered[segment]
        after_days = discovery_by_segment[segment]

        if before_days:
            before_p75 = sorted(before_days)[int(len(before_days) * 0.75)]
            before_n = len(before_days)
        else:
            before_p75 = 0
            before_n = 0

        if after_days:
            after_p75 = sorted(after_days)[int(len(after_days) * 0.75)]
            after_n = len(after_days)
        else:
            after_p75 = 0
            after_n = 0

        diff = after_p75 - before_p75

        print(f"{segment:<15} {before_n:>10} {before_p75:>12} {after_n:>10} {after_p75:>12} {diff:>+10}")

    # Final recommendation
    print("\n" + "=" * 80)
    print("RECOMMENDATION")
    print("=" * 80)

    if renewal_deals or negative_cycle_deals:
        print("\n⚠️  CONTAMINATION DETECTED")
        print(f"   - {len(renewal_deals)} renewal deals not excluded")
        print(f"   - {len(negative_cycle_deals)} negative cycle time deals not excluded")
        print("\n✅ FILTERS SHOULD BE APPLIED:")
        print("   1. Exclude renewal pipeline (pipeline_id = 866608541)")
        print("   2. Exclude deals with renewal_revenue > 0")
        print("   3. Exclude deals with negative cycle time (create_date > close_date)")
        print("\n   Re-run Signal 2 derivation with these filters applied.")
    else:
        print("\n✅ No contamination detected")
        print("   Discovery thresholds appear valid")

    # Check if distributions are outlier-driven
    outlier_driven = []
    for segment in ['Enterprise', 'Mid-Market', 'SMB']:
        days_list = discovery_by_segment[segment]
        if days_list:
            days_sorted = sorted(days_list)
            n = len(days_sorted)
            p75 = days_sorted[int(n * 0.75)]
            p25 = days_sorted[n // 4]
            iqr = p75 - p25
            outlier_threshold = p75 + 1.5 * iqr

            outliers = [d for d in days_sorted if d > outlier_threshold]
            outlier_pct = len(outliers) / n * 100

            if outlier_pct > 15:
                outlier_driven.append(segment)

    if outlier_driven:
        print(f"\n⚠️  OUTLIER-DRIVEN THRESHOLDS: {', '.join(outlier_driven)}")
        print("   These segments have >15% outliers influencing P75")
        print("   Consider using median instead of P75, or capping extreme values")

if __name__ == '__main__':
    main()
