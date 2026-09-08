"""
Check Proposal Stage for Renewal Contamination

Report actual count of renewal deals in Proposal-stage won population.
If nonzero, show before/after threshold comparison like Discovery got.
"""

import os
import sys
from datetime import datetime, timezone
from collections import defaultdict
from supabase import create_client, Client
from dotenv import load_dotenv

# Add api directory to path for centralized functions
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))
from api.field_semantics import is_valid_cycle_deal

load_dotenv()

# Supabase setup
SUPABASE_URL = os.getenv('SUPABASE_URL')
SUPABASE_KEY = os.getenv('SUPABASE_SERVICE_KEY')

if not SUPABASE_URL or not SUPABASE_KEY:
    raise ValueError("Missing SUPABASE_URL or SUPABASE_SERVICE_KEY")

sb: Client = create_client(SUPABASE_URL, SUPABASE_KEY)

RENEWAL_PIPELINE_ID = "866608541"

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
    """Fetch all won deals with fields needed for filtering"""
    response = sb.table('deals').select(
        'deal_id, company_name, stage, segment, deal_status, create_date, close_date, '
        'pipeline_id, renewal_revenue, new_arr, expansion_arr'
    ).eq('deal_status', 'won').execute()

    return response.data

def is_renewal_deal(deal):
    """Check if deal is a renewal"""
    pipeline_id = deal.get('pipeline_id', '')
    renewal_revenue = deal.get('renewal_revenue', 0) or 0

    if pipeline_id == RENEWAL_PIPELINE_ID:
        return True
    if renewal_revenue > 0:
        return True
    return False

def get_dealstage_history(deal_id):
    """Get dealstage changes for a deal"""
    response = sb.table('property_history').select(
        'changed_at, new_value'
    ).eq('deal_id', deal_id).eq(
        'property_name', 'dealstage'
    ).order('changed_at').execute()

    return response.data

def compute_time_in_stage_for_deal(deal_id):
    """Compute time spent in each stage for a deal"""
    history = get_dealstage_history(deal_id)

    if not history:
        return {}

    time_by_stage = {}

    for i in range(len(history) - 1):
        current_stage = history[i]['new_value']

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

def main():
    print("=" * 80)
    print("PROPOSAL STAGE CONTAMINATION CHECK")
    print("=" * 80)

    # Get won deals
    print("\nFetching won deals...")
    all_won_deals = get_won_deals()
    print(f"Total won deals: {len(all_won_deals)}")

    # Filter to only valid cycle deals
    valid_cycle_deals = [d for d in all_won_deals if is_valid_cycle_deal(d)]
    print(f"Valid cycle deals: {len(valid_cycle_deals)}")

    # Compute time-in-stage for all valid cycle deals
    print("\nComputing time-in-stage for Proposal bucket...")
    proposal_times = defaultdict(list)
    proposal_deal_details = defaultdict(list)

    for i, deal in enumerate(valid_cycle_deals):
        if (i + 1) % 50 == 0:
            print(f"  Processed {i+1}/{len(valid_cycle_deals)}...")

        deal_id = deal['deal_id']
        segment = deal.get('segment', 'Unknown')

        time_in_stages = compute_time_in_stage_for_deal(deal_id)

        # Only interested in Proposal stage
        if 'proposal' in time_in_stages:
            proposal_days = time_in_stages['proposal']

            # Track whether this is a renewal
            is_renewal = is_renewal_deal(deal)

            proposal_times['all'].append(proposal_days)
            proposal_deal_details['all'].append({
                'company': deal['company_name'],
                'segment': segment,
                'days': proposal_days,
                'is_renewal': is_renewal,
                'pipeline_id': deal.get('pipeline_id'),
                'renewal_revenue': deal.get('renewal_revenue', 0)
            })

            if is_renewal:
                proposal_times['renewal'].append(proposal_days)
                proposal_deal_details['renewal'].append({
                    'company': deal['company_name'],
                    'segment': segment,
                    'days': proposal_days,
                    'pipeline_id': deal.get('pipeline_id'),
                    'renewal_revenue': deal.get('renewal_revenue', 0)
                })
            else:
                proposal_times['clean'].append(proposal_days)

    print(f"\nCompleted time-in-stage computation")

    # Report contamination
    print("\n" + "=" * 80)
    print("PROPOSAL STAGE POPULATION BREAKDOWN")
    print("=" * 80)

    total_proposal = len(proposal_times['all'])
    renewal_proposal = len(proposal_times['renewal'])
    clean_proposal = len(proposal_times['clean'])

    print(f"\nTotal won deals with Proposal stage time: {total_proposal}")
    print(f"  Renewal deals: {renewal_proposal} ({renewal_proposal/total_proposal*100:.1f}%)")
    print(f"  Clean deals: {clean_proposal} ({clean_proposal/total_proposal*100:.1f}%)")

    if renewal_proposal == 0:
        print("\n✅ NO CONTAMINATION FOUND")
        print("   The assumption 'renewals rarely reach proposal' is correct.")
        print(f"   Proposal's 105-day threshold is based entirely on clean deals (n={clean_proposal})")
        return

    # If renewals found, show details and before/after comparison
    print("\n⚠️  RENEWAL CONTAMINATION FOUND IN PROPOSAL STAGE")
    print(f"   {renewal_proposal} renewal deals included in Proposal derivation")

    print("\n" + "=" * 80)
    print("RENEWAL DEALS IN PROPOSAL STAGE")
    print("=" * 80)

    print(f"\nShowing all {renewal_proposal} renewal deals in Proposal:\n")
    for detail in sorted(proposal_deal_details['renewal'], key=lambda x: -x['days']):
        print(f"  {detail['company']} ({detail['segment']})")
        print(f"    Days in Proposal: {detail['days']}")
        print(f"    pipeline_id: {detail['pipeline_id']}")
        print(f"    renewal_revenue: {detail['renewal_revenue']}")
        print()

    # Before/After threshold comparison
    print("\n" + "=" * 80)
    print("BEFORE vs AFTER THRESHOLD COMPARISON")
    print("=" * 80)

    # Compute P75 with all deals (contaminated)
    all_times = sorted(proposal_times['all'])
    p75_contaminated = all_times[int(len(all_times) * 0.75)]

    # Compute P75 with clean deals only
    clean_times = sorted(proposal_times['clean'])
    if clean_times:
        p75_clean = clean_times[int(len(clean_times) * 0.75)]
    else:
        p75_clean = None

    print(f"\nProposal Stage P75 (stage-only threshold):")
    print(f"  Contaminated (with {renewal_proposal} renewals): {p75_contaminated} days (n={total_proposal})")
    if p75_clean:
        print(f"  Clean (renewals excluded): {p75_clean} days (n={clean_proposal})")
        print(f"  Difference: {p75_contaminated - p75_clean} days")

        if abs(p75_contaminated - p75_clean) < 5:
            print("\n✅ MINIMAL IMPACT")
            print(f"   Difference is < 5 days - renewal contamination negligible")
        elif p75_contaminated > p75_clean:
            print("\n⚠️  INFLATION DETECTED")
            print(f"   Contaminated threshold {p75_contaminated - p75_clean} days higher than clean")
        else:
            print("\n⚠️  DEFLATION DETECTED")
            print(f"   Contaminated threshold {p75_clean - p75_contaminated} days lower than clean")
    else:
        print(f"  Clean: INSUFFICIENT DATA (n=0)")
        print("\n⚠️  ALL PROPOSAL DEALS ARE RENEWALS")
        print("   Cannot derive clean threshold - no clean deals in sample")

    # Statistics
    print("\n" + "=" * 80)
    print("DISTRIBUTION STATISTICS")
    print("=" * 80)

    print(f"\nAll Proposal deals (n={total_proposal}):")
    print(f"  Min: {min(all_times)} days")
    print(f"  P25: {all_times[len(all_times)//4]} days")
    print(f"  Median: {all_times[len(all_times)//2]} days")
    print(f"  P75: {p75_contaminated} days")
    print(f"  Max: {max(all_times)} days")

    if clean_times:
        print(f"\nClean Proposal deals (n={clean_proposal}):")
        print(f"  Min: {min(clean_times)} days")
        print(f"  P25: {clean_times[len(clean_times)//4]} days")
        print(f"  Median: {clean_times[len(clean_times)//2]} days")
        print(f"  P75: {p75_clean} days")
        print(f"  Max: {max(clean_times)} days")

    if renewal_proposal > 0:
        renewal_times = sorted(proposal_times['renewal'])
        print(f"\nRenewal Proposal deals (n={renewal_proposal}):")
        print(f"  Min: {min(renewal_times)} days")
        print(f"  P25: {renewal_times[len(renewal_times)//4] if len(renewal_times) >= 4 else 'N/A'} days")
        print(f"  Median: {renewal_times[len(renewal_times)//2]} days")
        print(f"  P75: {renewal_times[int(len(renewal_times)*0.75)] if len(renewal_times) >= 4 else 'N/A'} days")
        print(f"  Max: {max(renewal_times)} days")

if __name__ == '__main__':
    main()
