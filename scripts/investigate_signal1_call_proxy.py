"""
Signal 1 Proxy Investigation: Contact Count via Call Participants

Tests feasibility of using call participant emails as a proxy for stakeholder count.
Addresses 5 key questions before implementation:
1. Coverage: Is participant_emails populated even when calls exist?
2. Emails vs domains: Which metric is the actual signal?
3. Internal filtering: Are there domains beyond growthbook.io to exclude?
4. Won/lost separation: Does this correlate with outcomes?
5. Sample sizes: Is 23% coverage sufficient for stage × segment derivation?
"""

import os
import json
from datetime import datetime
from collections import defaultdict, Counter
from supabase import create_client, Client
from dotenv import load_dotenv

load_dotenv()

# Supabase setup
SUPABASE_URL = os.getenv('SUPABASE_URL')
SUPABASE_KEY = os.getenv('SUPABASE_SERVICE_KEY')

if not SUPABASE_URL or not SUPABASE_KEY:
    raise ValueError("Missing SUPABASE_URL or SUPABASE_SERVICE_KEY")

sb: Client = create_client(SUPABASE_URL, SUPABASE_KEY)

# Known internal domains (expand as needed)
INTERNAL_DOMAINS = [
    'growthbook.io',
    'growthbook.com',
    # Add others as discovered
]

def get_bulk_cleanup_deals():
    """Load bulk cleanup exclusion list from Q016"""
    # For now, return empty - will implement if needed
    return set()

def get_closed_deals():
    """Fetch all closed deals (won and lost)"""
    response = sb.table('deals').select(
        'deal_id, company_name, stage, segment, deal_status, create_date, close_date'
    ).in_('deal_status', ['won', 'lost']).execute()

    return response.data

def get_calls_for_deal(deal_id):
    """Fetch all calls for a deal with participant emails"""
    response = sb.table('calls').select(
        'call_id, participant_emails, call_date'
    ).eq('deal_id', deal_id).execute()

    return response.data

def extract_emails(participant_emails):
    """
    Extract list of emails from participant_emails field.
    Handle both JSON array and comma-separated string formats.
    """
    if not participant_emails:
        return []

    # If it's already a list
    if isinstance(participant_emails, list):
        return [e.strip().lower() for e in participant_emails if e]

    # If it's a JSON string
    if isinstance(participant_emails, str):
        # Try parsing as JSON array
        try:
            emails = json.loads(participant_emails)
            if isinstance(emails, list):
                return [e.strip().lower() for e in emails if e]
        except:
            pass

        # Fall back to comma-separated
        return [e.strip().lower() for e in participant_emails.split(',') if e.strip()]

    return []

def extract_domain(email):
    """Extract domain from email address"""
    if '@' not in email:
        return None
    return email.split('@')[1].lower()

def is_internal_domain(domain):
    """Check if domain is internal (should be excluded)"""
    return domain in INTERNAL_DOMAINS

def analyze_deal_participants(deal_id):
    """
    Analyze call participants for a deal.
    Returns dict with distinct counts and metadata.
    """
    calls = get_calls_for_deal(deal_id)

    if not calls:
        return {
            'has_calls': False,
            'call_count': 0,
            'has_participant_data': False,
            'all_emails': set(),
            'external_emails': set(),
            'all_domains': set(),
            'external_domains': set(),
            'internal_domains_found': set()
        }

    all_emails = set()
    external_emails = set()
    all_domains = set()
    external_domains = set()
    internal_domains_found = set()

    has_any_participant_data = False

    for call in calls:
        emails = extract_emails(call.get('participant_emails'))

        if emails:
            has_any_participant_data = True

            for email in emails:
                domain = extract_domain(email)
                if not domain:
                    continue

                all_emails.add(email)
                all_domains.add(domain)

                if is_internal_domain(domain):
                    internal_domains_found.add(domain)
                else:
                    external_emails.add(email)
                    external_domains.add(domain)

    return {
        'has_calls': True,
        'call_count': len(calls),
        'has_participant_data': has_any_participant_data,
        'all_emails': all_emails,
        'external_emails': external_emails,
        'all_domains': all_domains,
        'external_domains': external_domains,
        'internal_domains_found': internal_domains_found
    }

def get_stage_bucket(stage):
    """Map stage to bucket (simplified)"""
    stage_lower = stage.lower()

    if 'appointment' in stage_lower or 'discovery' in stage_lower:
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

def main():
    print("=" * 80)
    print("SIGNAL 1 PROXY INVESTIGATION: Call Participant Count")
    print("=" * 80)

    # Get closed deals
    print("\nFetching closed deals...")
    closed_deals = get_closed_deals()
    print(f"Total closed deals: {len(closed_deals)}")

    won_deals = [d for d in closed_deals if d['deal_status'] == 'won']
    lost_deals = [d for d in closed_deals if d['deal_status'] == 'lost']
    print(f"  Won: {len(won_deals)}")
    print(f"  Lost: {len(lost_deals)}")

    # Exclude bulk cleanup (if needed)
    bulk_cleanup_ids = get_bulk_cleanup_deals()
    if bulk_cleanup_ids:
        closed_deals = [d for d in closed_deals if d['deal_id'] not in bulk_cleanup_ids]
        print(f"  After bulk cleanup exclusion: {len(closed_deals)}")

    # Analyze coverage and participant data
    print("\n" + "=" * 80)
    print("1. COVERAGE CHECK")
    print("=" * 80)

    deals_with_calls = 0
    deals_with_participant_data = 0
    deals_with_external_participants = 0

    all_internal_domains_seen = set()

    results_by_deal = {}

    print("\nAnalyzing calls and participant data...")
    for i, deal in enumerate(closed_deals):
        if (i + 1) % 50 == 0:
            print(f"  Processed {i + 1}/{len(closed_deals)} deals...")

        deal_id = deal['deal_id']
        analysis = analyze_deal_participants(deal_id)

        results_by_deal[deal_id] = {
            'deal': deal,
            'analysis': analysis
        }

        if analysis['has_calls']:
            deals_with_calls += 1

        if analysis['has_participant_data']:
            deals_with_participant_data += 1

        if len(analysis['external_emails']) > 0:
            deals_with_external_participants += 1

        all_internal_domains_seen.update(analysis['internal_domains_found'])

    print(f"\nCompleted analysis of {len(closed_deals)} closed deals")

    # Coverage report
    coverage_calls = (deals_with_calls / len(closed_deals) * 100) if closed_deals else 0
    coverage_participants = (deals_with_participant_data / len(closed_deals) * 100) if closed_deals else 0
    coverage_external = (deals_with_external_participants / len(closed_deals) * 100) if closed_deals else 0

    print(f"\nCoverage Summary:")
    print(f"  Deals with calls: {deals_with_calls}/{len(closed_deals)} ({coverage_calls:.1f}%)")
    print(f"  Deals with participant data: {deals_with_participant_data}/{len(closed_deals)} ({coverage_participants:.1f}%)")
    print(f"  Deals with external participants: {deals_with_external_participants}/{len(closed_deals)} ({coverage_external:.1f}%)")

    print(f"\nParticipant data population rate among deals WITH calls:")
    if deals_with_calls > 0:
        participant_rate = (deals_with_participant_data / deals_with_calls * 100)
        print(f"  {deals_with_participant_data}/{deals_with_calls} ({participant_rate:.1f}%)")
    else:
        print("  No deals with calls")

    # Check 2: Emails vs Domains
    print("\n" + "=" * 80)
    print("2. EMAILS VS DOMAINS")
    print("=" * 80)

    email_counts = []
    domain_counts = []

    for deal_id, result in results_by_deal.items():
        analysis = result['analysis']
        if analysis['has_participant_data']:
            email_counts.append(len(analysis['external_emails']))
            domain_counts.append(len(analysis['external_domains']))

    if email_counts:
        print(f"\nDistinct external EMAILS per deal (n={len(email_counts)}):")
        print(f"  Median: {sorted(email_counts)[len(email_counts)//2]}")
        print(f"  P25: {sorted(email_counts)[len(email_counts)//4]}")
        print(f"  P75: {sorted(email_counts)[3*len(email_counts)//4]}")
        print(f"  Max: {max(email_counts)}")

        print(f"\nDistinct external DOMAINS per deal (n={len(domain_counts)}):")
        print(f"  Median: {sorted(domain_counts)[len(domain_counts)//2]}")
        print(f"  P25: {sorted(domain_counts)[len(domain_counts)//4]}")
        print(f"  P75: {sorted(domain_counts)[3*len(domain_counts)//4]}")
        print(f"  Max: {max(domain_counts)}")

        # Compare email vs domain for same deals
        single_domain_multi_email = 0
        for i, email_count in enumerate(email_counts):
            domain_count = domain_counts[i]
            if email_count > 1 and domain_count == 1:
                single_domain_multi_email += 1

        print(f"\nDeals with multiple emails from SINGLE domain:")
        print(f"  {single_domain_multi_email}/{len(email_counts)} ({single_domain_multi_email/len(email_counts)*100:.1f}%)")
        print(f"  (Using domains would undercount stakeholder engagement for these deals)")

    # Check 3: Internal domains
    print("\n" + "=" * 80)
    print("3. INTERNAL DOMAIN FILTERING")
    print("=" * 80)

    print(f"\nInternal domains found in participant data:")
    if all_internal_domains_seen:
        for domain in sorted(all_internal_domains_seen):
            count = sum(1 for r in results_by_deal.values() if domain in r['analysis']['internal_domains_found'])
            print(f"  {domain}: {count} deals")
    else:
        print("  (none found)")

    print(f"\nConfigured internal domain exclusion list:")
    for domain in INTERNAL_DOMAINS:
        print(f"  {domain}")

    # Check for common domains that might be internal but not in exclusion list
    all_domains_counter = Counter()
    for result in results_by_deal.values():
        all_domains_counter.update(result['analysis']['all_domains'])

    print(f"\nTop 20 most common domains (may reveal missing internal domains):")
    for domain, count in all_domains_counter.most_common(20):
        is_internal = domain in INTERNAL_DOMAINS
        marker = "[INTERNAL]" if is_internal else ""
        print(f"  {domain}: {count} deals {marker}")

    # Check 4: Won/Lost separation
    print("\n" + "=" * 80)
    print("4. WON/LOST SEPARATION TEST")
    print("=" * 80)

    won_external_emails = []
    lost_external_emails = []
    won_external_domains = []
    lost_external_domains = []

    for deal_id, result in results_by_deal.items():
        deal = result['deal']
        analysis = result['analysis']

        if not analysis['has_participant_data']:
            continue

        email_count = len(analysis['external_emails'])
        domain_count = len(analysis['external_domains'])

        if deal['deal_status'] == 'won':
            won_external_emails.append(email_count)
            won_external_domains.append(domain_count)
        else:
            lost_external_emails.append(email_count)
            lost_external_domains.append(domain_count)

    print(f"\nExternal EMAIL counts:")
    print(f"\n  Won deals (n={len(won_external_emails)}):")
    if won_external_emails:
        print(f"    Median: {sorted(won_external_emails)[len(won_external_emails)//2]}")
        print(f"    P25: {sorted(won_external_emails)[len(won_external_emails)//4]}")
        print(f"    Mean: {sum(won_external_emails)/len(won_external_emails):.1f}")

    print(f"\n  Lost deals (n={len(lost_external_emails)}):")
    if lost_external_emails:
        print(f"    Median: {sorted(lost_external_emails)[len(lost_external_emails)//2]}")
        print(f"    P25: {sorted(lost_external_emails)[len(lost_external_emails)//4]}")
        print(f"    Mean: {sum(lost_external_emails)/len(lost_external_emails):.1f}")

    print(f"\nExternal DOMAIN counts:")
    print(f"\n  Won deals (n={len(won_external_domains)}):")
    if won_external_domains:
        print(f"    Median: {sorted(won_external_domains)[len(won_external_domains)//2]}")
        print(f"    P25: {sorted(won_external_domains)[len(won_external_domains)//4]}")
        print(f"    Mean: {sum(won_external_domains)/len(won_external_domains):.1f}")

    print(f"\n  Lost deals (n={len(lost_external_domains)}):")
    if lost_external_domains:
        print(f"    Median: {sorted(lost_external_domains)[len(lost_external_domains)//2]}")
        print(f"    P25: {sorted(lost_external_domains)[len(lost_external_domains)//4]}")
        print(f"    Mean: {sum(lost_external_domains)/len(lost_external_domains):.1f}")

    # Direction check
    if won_external_emails and lost_external_emails:
        won_median_emails = sorted(won_external_emails)[len(won_external_emails)//2]
        lost_median_emails = sorted(lost_external_emails)[len(lost_external_emails)//2]

        print(f"\nDirection check (EMAILS):")
        print(f"  Won median: {won_median_emails}")
        print(f"  Lost median: {lost_median_emails}")

        if won_median_emails > lost_median_emails:
            print(f"  ✅ EXPECTED DIRECTION: Won > Lost (multi-threaded wins)")
        elif won_median_emails < lost_median_emails:
            print(f"  ❌ INVERTED: Won < Lost (unexpected)")
        else:
            print(f"  ⚠️  NO SEPARATION: Won = Lost")

    # Check 5: Sample sizes by stage × segment
    print("\n" + "=" * 80)
    print("5. SAMPLE SIZE VIABILITY (Stage × Segment)")
    print("=" * 80)

    # Count deals with participant data by stage × segment × outcome
    stage_segment_counts = defaultdict(lambda: {'won': 0, 'lost': 0})

    for deal_id, result in results_by_deal.items():
        deal = result['deal']
        analysis = result['analysis']

        if not analysis['has_participant_data']:
            continue

        stage_bucket = get_stage_bucket(deal['stage'])
        segment = deal.get('segment', 'Unknown')
        outcome = deal['deal_status']

        key = (stage_bucket, segment)
        stage_segment_counts[key][outcome] += 1

    print("\nSample sizes per stage × segment cell:")
    print(f"{'Stage':<15} {'Segment':<15} {'Won':>6} {'Lost':>6} {'Total':>6} {'Viable?':<10}")
    print("-" * 70)

    viable_cells = 0
    total_cells = 0

    for (stage, segment), counts in sorted(stage_segment_counts.items()):
        won = counts['won']
        lost = counts['lost']
        total = won + lost

        # Consider viable if both won AND lost have ≥5 samples
        is_viable = won >= 5 and lost >= 5
        viable_marker = "✅" if is_viable else "❌"

        if is_viable:
            viable_cells += 1
        total_cells += 1

        print(f"{stage:<15} {segment:<15} {won:>6} {lost:>6} {total:>6} {viable_marker:<10}")

    print(f"\nViable cells: {viable_cells}/{total_cells} ({viable_cells/total_cells*100:.1f}%)")
    print(f"Threshold for production: ≥50% cells viable")

    if viable_cells / total_cells >= 0.5:
        print("✅ SUFFICIENT sample sizes for stage × segment derivation")
    else:
        print("❌ INSUFFICIENT sample sizes (same issue as Signal 3)")

    # Final summary
    print("\n" + "=" * 80)
    print("SUMMARY & RECOMMENDATION")
    print("=" * 80)

    print(f"\n1. Coverage: {coverage_participants:.1f}% of closed deals have participant data")
    print(f"   - Inherits same {coverage_calls:.1f}% calls coverage ceiling as Signal 3")
    if deals_with_calls > 0:
        participant_rate = (deals_with_participant_data / deals_with_calls * 100)
        print(f"   - Among deals WITH calls, {participant_rate:.1f}% have participant emails")

    print(f"\n2. Metric choice:")
    if email_counts:
        email_median = sorted(email_counts)[len(email_counts)//2]
        domain_median = sorted(domain_counts)[len(domain_counts)//2]
        print(f"   - Distinct emails: median {email_median} per deal")
        print(f"   - Distinct domains: median {domain_median} per deal")
        if single_domain_multi_email > 0:
            print(f"   - Recommendation: Use EMAILS (captures multi-person buying committees)")

    print(f"\n3. Internal filtering:")
    if all_internal_domains_seen:
        print(f"   - {len(all_internal_domains_seen)} internal domains found and excluded")
    else:
        print(f"   - No internal domains found (may need to expand exclusion list)")

    print(f"\n4. Won/Lost separation:")
    if won_external_emails and lost_external_emails:
        won_median_emails = sorted(won_external_emails)[len(won_external_emails)//2]
        lost_median_emails = sorted(lost_external_emails)[len(lost_external_emails)//2]

        if won_median_emails > lost_median_emails:
            print(f"   - ✅ Expected direction: Won deals have MORE stakeholders")
        elif won_median_emails < lost_median_emails:
            print(f"   - ❌ Inverted: Lost deals have more stakeholders (unexpected)")
        else:
            print(f"   - ⚠️  No separation: Won = Lost")
    else:
        print(f"   - Insufficient data for comparison")

    print(f"\n5. Sample sizes:")
    print(f"   - {viable_cells}/{total_cells} cells viable ({viable_cells/total_cells*100:.1f}%)")
    if viable_cells / total_cells >= 0.5:
        print(f"   - ✅ Sufficient for stage × segment thresholds")
    else:
        print(f"   - ❌ Insufficient (same thin-sample problem as Signal 3)")

    print(f"\n{'=' * 80}")
    print("RECOMMENDATION:")
    print("=" * 80)

    # Determine overall recommendation
    sufficient_coverage = coverage_participants >= 50
    correct_direction = (won_external_emails and lost_external_emails and
                        sorted(won_external_emails)[len(won_external_emails)//2] >
                        sorted(lost_external_emails)[len(lost_external_emails)//2])
    sufficient_samples = viable_cells / total_cells >= 0.5 if total_cells > 0 else False

    if sufficient_coverage and correct_direction and sufficient_samples:
        print("\n✅ VIABLE: All checks passed")
        print("   - Sufficient coverage")
        print("   - Expected won/lost separation")
        print("   - Adequate sample sizes")
        print("\nProceed with Signal 1 derivation using external email counts.")
    else:
        print("\n❌ NOT VIABLE: Failed one or more checks")
        if not sufficient_coverage:
            print(f"   - Coverage too low ({coverage_participants:.1f}% < 50% threshold)")
        if not correct_direction:
            print(f"   - No expected won/lost separation")
        if not sufficient_samples:
            print(f"   - Sample sizes insufficient ({viable_cells/total_cells*100:.1f}% < 50% threshold)")
        print("\nDEFER Signal 1 (same outcome as Signal 3)")

if __name__ == '__main__':
    main()
