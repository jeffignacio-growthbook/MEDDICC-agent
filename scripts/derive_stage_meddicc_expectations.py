"""
Derive Stage-Relative MEDDICC Component Expectations

Test whether each MEDDICC component's band (red/yellow/green) at each stage
actually differentiates win/loss outcome, using the same empirical approach
as Signal 2 threshold derivation.

Method:
1. Pull historical closed deals (won + lost) with MEDDICC analyses
2. Apply same exclusions as Signal 2 (renewal deals, negative cycle time)
3. Bucket deals by stage at time of analysis
4. For each component × stage cell, check outcome distribution
5. Determine if band status correlates with outcome (predictive) or is neutral (acceptable)

Expected findings:
- EB-red at Discovery: neutral (no split) → acceptable at that stage
- EB-red at Proposal: correlates with loss → genuine risk signal
- Champion-yellow: correlates with loss at any stage → coordinator not champion

Sample size: apply same n≥5 threshold per cell as Signal 2.
If insufficient data, mark as HAND_PICKED pending re-derivation.
"""

import os
import sys
from datetime import datetime, timezone
from pathlib import Path
from collections import defaultdict
from supabase import create_client, Client
from dotenv import load_dotenv

# Add parent directory to path for imports
REPO_ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(REPO_ROOT))
sys.path.insert(0, str(REPO_ROOT / "api"))

from field_semantics import is_valid_cycle_deal, is_renewal_base, stage_bucket

load_dotenv()

SUPABASE_URL = os.getenv('SUPABASE_URL')
SUPABASE_KEY = os.getenv('SUPABASE_SERVICE_KEY')

if not SUPABASE_URL or not SUPABASE_KEY:
    raise ValueError("Missing SUPABASE_URL or SUPABASE_SERVICE_KEY")

sb: Client = create_client(SUPABASE_URL, SUPABASE_KEY)

# MEDDICC components to analyze
COMPONENTS = [
    'metrics_score',
    'economic_buyer_score',
    'decision_criteria_score',
    'decision_process_score',
    'pain_score',
    'champion_score',
    'competition_score',
]

COMPONENT_LABELS = {
    'metrics_score': 'Metrics',
    'economic_buyer_score': 'Economic Buyer',
    'decision_criteria_score': 'Decision Criteria',
    'decision_process_score': 'Decision Process',
    'pain_score': 'Pain',
    'champion_score': 'Champion',
    'competition_score': 'Competition',
}

# Band thresholds (from api/rubric.py)
def get_band(score: int) -> str:
    """Return band name for a score (0-10)."""
    if score is None:
        return 'unknown'
    if 0 <= score <= 3:
        return 'red'
    elif 4 <= score <= 6:
        return 'yellow'
    elif 7 <= score <= 10:
        return 'green'
    return 'unknown'

def fetch_closed_deals_with_analyses():
    """
    Fetch all closed deals (won + lost) with their MEDDICC analyses.
    Apply same exclusions as Signal 2 derivation.
    """
    print("Fetching closed deals from Supabase...")

    # Fetch all deals
    response = sb.table('deals').select(
        'deal_id, company_name, deal_status, stage, '
        'create_date, close_date, '
        'pipeline_id, renewal_revenue'
    ).execute()

    all_deals = response.data
    print(f"  Fetched {len(all_deals)} total deals")

    # Apply exclusions (same as Signal 2)
    closed_deals = []
    for deal in all_deals:
        # Only closed deals
        if deal.get('deal_status') not in ['won', 'lost']:
            continue

        # Exclude renewals
        if is_renewal_base(deal):
            continue

        # Exclude negative cycle time
        if not is_valid_cycle_deal(deal):
            continue

        closed_deals.append(deal)

    print(f"  After exclusions: {len(closed_deals)} closed deals (won + lost)")

    # Fetch analyses for these deals
    print("Fetching MEDDICC analyses...")
    deal_ids = [d['deal_id'] for d in closed_deals]

    analyses_response = sb.table('analyses').select(
        'deal_id, analyzed_at, '
        'metrics_score, economic_buyer_score, '
        'decision_criteria_score, decision_process_score, '
        'pain_score, champion_score, competition_score, '
        'overall_score, passed'
    ).in_('deal_id', deal_ids).execute()

    analyses = analyses_response.data
    print(f"  Fetched {len(analyses)} analyses")

    # Filter to passed analyses only (same quality gate as Signal 2)
    passed_analyses = [a for a in analyses if a.get('passed')]
    print(f"  Passed analyses: {len(passed_analyses)}")

    return closed_deals, passed_analyses

def build_stage_component_outcome_matrix(deals, analyses):
    """
    Build matrix: stage × component × band → win/loss counts

    Returns:
        dict: {
            stage_bucket: {
                component: {
                    band: {'won': count, 'lost': count, 'total': count}
                }
            }
        }
    """
    # Create deal_id → outcome mapping
    deal_outcomes = {d['deal_id']: d['deal_status'] for d in deals}

    # Initialize matrix
    matrix = defaultdict(lambda: defaultdict(lambda: defaultdict(lambda: {'won': 0, 'lost': 0, 'total': 0})))

    for analysis in analyses:
        deal_id = analysis['deal_id']
        outcome = deal_outcomes.get(deal_id)

        if not outcome:
            continue

        # Get stage from deal (analyses table doesn't have stage_at_analysis)
        deal = next((d for d in deals if d['deal_id'] == deal_id), None)
        if not deal:
            continue

        stage = deal.get('stage')
        if not stage:
            continue

        bucket = stage_bucket(stage)

        # For each component, bucket its score and count outcome
        for component in COMPONENTS:
            score = analysis.get(component)
            if score is None:
                continue

            band = get_band(score)
            if band == 'unknown':
                continue

            matrix[bucket][component][band][outcome] += 1
            matrix[bucket][component][band]['total'] += 1

    return matrix

def analyze_predictiveness(matrix, min_sample=5):
    """
    Analyze whether component × stage × band combinations are predictive of outcome.

    Returns:
        dict: {
            stage_bucket: {
                component: {
                    band: {
                        'sample_size': int,
                        'won_rate': float,
                        'lost_rate': float,
                        'predictive': bool,  # True if meaningful split from 50/50
                        'interpretation': str
                    }
                }
            }
        }
    """
    results = defaultdict(lambda: defaultdict(dict))

    for bucket, components in matrix.items():
        for component, bands in components.items():
            for band, outcomes in bands.items():
                n = outcomes['total']
                won = outcomes['won']
                lost = outcomes['lost']

                if n < min_sample:
                    results[bucket][component][band] = {
                        'sample_size': n,
                        'won_rate': None,
                        'lost_rate': None,
                        'predictive': None,
                        'interpretation': f'INSUFFICIENT_DATA (n={n}, need n≥{min_sample})',
                        'status': 'HAND_PICKED'
                    }
                    continue

                won_rate = won / n
                lost_rate = lost / n

                # Predictive if significantly different from 50/50
                # Using simple threshold: difference > 20% (0.7 vs 0.3 or more extreme)
                predictive = abs(won_rate - lost_rate) > 0.2

                if predictive:
                    if won_rate > lost_rate:
                        interpretation = f'POSITIVE_SIGNAL (won {won_rate:.0%} vs lost {lost_rate:.0%})'
                    else:
                        interpretation = f'RISK_SIGNAL (won {won_rate:.0%} vs lost {lost_rate:.0%})'
                else:
                    interpretation = f'NEUTRAL (won {won_rate:.0%} vs lost {lost_rate:.0%}, no meaningful split)'

                results[bucket][component][band] = {
                    'sample_size': n,
                    'won_rate': won_rate,
                    'lost_rate': lost_rate,
                    'predictive': predictive,
                    'interpretation': interpretation,
                    'status': 'DERIVED'
                }

    return results

def generate_stage_scoring_expectations(results):
    """
    Generate stage_scoring_expectations config structure from analysis results.

    Returns YAML-compatible dict with acceptable_bands, concerning_threshold,
    and interpretation_notes for each stage × component.
    """
    expectations = {}

    for bucket in ['discovery', 'scoping', 'proposal']:
        expectations[bucket] = {}

        for component in COMPONENTS:
            label = COMPONENT_LABELS[component]

            # Analyze each band's predictiveness at this stage
            red_result = results.get(bucket, {}).get(component, {}).get('red', {})
            yellow_result = results.get(bucket, {}).get(component, {}).get('yellow', {})
            green_result = results.get(bucket, {}).get(component, {}).get('green', {})

            # Check if we have ANY data for this component at this stage
            has_any_data = any(r.get('sample_size') is not None for r in [red_result, yellow_result, green_result])

            if not has_any_data:
                # No data for this component at this stage - mark as insufficient
                expectations[bucket][label] = {
                    'acceptable_bands': None,
                    'concerning_threshold': None,
                    'interpretation_notes': 'INSUFFICIENT_DATA - no analyses at this stage',
                    'derivation_status': 'INSUFFICIENT_DATA'
                }
                continue

            # Determine acceptable bands based on predictiveness
            acceptable_bands = []
            concerning_threshold = None
            interpretation_notes = []

            # Green is always acceptable (by definition)
            acceptable_bands.append('green')

            # Yellow: acceptable if neutral or positive signal
            if yellow_result.get('predictive') is False or yellow_result.get('won_rate', 0) > 0.5:
                acceptable_bands.append('yellow')
            elif yellow_result.get('predictive') and yellow_result.get('won_rate', 0) < 0.5:
                concerning_threshold = 'yellow'
                interpretation_notes.append(f"Yellow is risk signal at {bucket}: {yellow_result['interpretation']}")

            # Red: acceptable only if truly neutral (no split)
            if red_result.get('predictive') is False:
                acceptable_bands.append('red')
                interpretation_notes.append(f"Red is acceptable at {bucket}: {red_result['interpretation']}")
            elif red_result.get('predictive'):
                if not concerning_threshold:
                    concerning_threshold = 'red'
                interpretation_notes.append(f"Red is risk signal at {bucket}: {red_result['interpretation']}")

            # Add data provenance notes
            if red_result.get('status') == 'HAND_PICKED':
                interpretation_notes.append(f"Red band: {red_result['interpretation']}")
            if yellow_result.get('status') == 'HAND_PICKED':
                interpretation_notes.append(f"Yellow band: {yellow_result['interpretation']}")

            expectations[bucket][label] = {
                'acceptable_bands': sorted(acceptable_bands, key=lambda b: ['red', 'yellow', 'green'].index(b)),
                'concerning_threshold': concerning_threshold,
                'interpretation_notes': ' | '.join(interpretation_notes) if interpretation_notes else None,
                'derivation_status': 'PARTIALLY_DERIVED' if any(
                    r.get('status') == 'HAND_PICKED'
                    for r in [red_result, yellow_result, green_result]
                ) else 'DERIVED'
            }

    return expectations

def print_results(results):
    """Print human-readable results."""
    print("\n" + "=" * 80)
    print("STAGE-RELATIVE MEDDICC COMPONENT EXPECTATIONS")
    print("=" * 80)

    for bucket in ['discovery', 'scoping', 'proposal']:
        print(f"\n{'=' * 80}")
        print(f"STAGE: {bucket.upper()}")
        print("=" * 80)

        for component in COMPONENTS:
            label = COMPONENT_LABELS[component]
            print(f"\n{label}:")

            for band in ['red', 'yellow', 'green']:
                result = results.get(bucket, {}).get(component, {}).get(band, {})

                if not result:
                    print(f"  {band.upper()}: No data")
                    continue

                n = result.get('sample_size', 0)
                interpretation = result.get('interpretation', 'N/A')
                status = result.get('status', 'UNKNOWN')

                print(f"  {band.upper()}: n={n}, {interpretation} [{status}]")

def main():
    print("=" * 80)
    print("DERIVE STAGE-RELATIVE MEDDICC EXPECTATIONS")
    print("=" * 80)
    print()
    print("Method: Same empirical approach as Signal 2 threshold derivation")
    print("Question: Does component band at stage correlate with win/loss outcome?")
    print()

    # Fetch data
    deals, analyses = fetch_closed_deals_with_analyses()

    if not deals or not analyses:
        print("\n❌ Insufficient data to derive expectations")
        return

    # Build matrix
    print("\nBuilding stage × component × band outcome matrix...")
    matrix = build_stage_component_outcome_matrix(deals, analyses)

    # DEBUG: Check if matrix has any data
    total_entries = sum(
        sum(sum(band['total'] for band in bands.values()) for bands in components.values())
        for components in matrix.values()
    )
    print(f"  Matrix total entries: {total_entries}")
    print(f"  Matrix buckets populated: {list(matrix.keys())}")

    # Analyze predictiveness
    print("Analyzing predictiveness (min_sample=5)...")
    results = analyze_predictiveness(matrix, min_sample=5)

    # DEBUG: Check results population
    results_entries = sum(
        sum(len(bands) for bands in components.values())
        for components in results.values()
    )
    print(f"  Results entries: {results_entries}")

    # Print results
    print_results(results)

    # Generate config structure
    print("\n" + "=" * 80)
    print("GENERATED stage_scoring_expectations CONFIG")
    print("=" * 80)

    expectations = generate_stage_scoring_expectations(results)

    import yaml
    print("\n" + yaml.dump({'stage_scoring_expectations': expectations}, default_flow_style=False, sort_keys=False))

    # Summary
    print("\n" + "=" * 80)
    print("SUMMARY")
    print("=" * 80)

    # Count at component level (not band level) from expectations
    total_components = len(['discovery', 'scoping', 'proposal']) * len(COMPONENTS)
    insufficient_count = sum(
        1 for stage in expectations.values()
        for component in stage.values()
        if component.get('derivation_status') == 'INSUFFICIENT_DATA'
    )
    derived_count = sum(
        1 for stage in expectations.values()
        for component in stage.values()
        if component.get('derivation_status') in ['DERIVED', 'PARTIALLY_DERIVED']
    )

    print(f"\nTotal component × stage cells: {total_components}")
    print(f"Derived or partially derived: {derived_count}")
    print(f"Insufficient data: {insufficient_count}")
    if derived_count > 0:
        print(f"Coverage: {derived_count / total_components * 100:.1f}%")
    else:
        print(f"Coverage: 0% (no cells had sufficient data for derivation)")

    if insufficient_count > 0:
        print(f"\n⚠️  {insufficient_count} component × stage cells have insufficient data")
        print("Stage bucketing may be broken (check that deals.stage contains")
        print("HubSpot canonical stage names, not human-readable labels)")

    print("\nNext steps:")
    print("1. Review results for face validity")
    print("2. Add stage_scoring_expectations to config/coaching_client.yaml")
    print("3. Wire query_deal to load_coaching_config and pass stage context")
    print("4. Monitor for inconsistent LLM interpretation before pursuing Option D")

if __name__ == "__main__":
    main()
