"""
Signal 1 Segment Mix Check

Verify whether won/lost email-count separation is explained by segment mix
rather than genuine multi-threading signal.

If won deals with participant data skew Enterprise (more stakeholders naturally)
and lost deals skew SMB (fewer stakeholders naturally), the "won > lost" finding
is just rediscovering segment differences, not validating the multi-threading
hypothesis.
"""

import os
import json
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

INTERNAL_DOMAINS = ['growthbook.io', 'growthbook.com']

def get_closed_deals():
    """Fetch all closed deals"""
    response = sb.table('deals').select(
        'deal_id, company_name, stage, segment, deal_status'
    ).in_('deal_status', ['won', 'lost']).execute()
    return response.data

def get_calls_for_deal(deal_id):
    """Fetch calls with participant emails"""
    response = sb.table('calls').select(
        'call_id, participant_emails'
    ).eq('deal_id', deal_id).execute()
    return response.data

def extract_emails(participant_emails):
    """Extract list of emails from participant_emails field"""
    if not participant_emails:
        return []

    if isinstance(participant_emails, list):
        return [e.strip().lower() for e in participant_emails if e]

    if isinstance(participant_emails, str):
        try:
            emails = json.loads(participant_emails)
            if isinstance(emails, list):
                return [e.strip().lower() for e in emails if e]
        except:
            pass
        return [e.strip().lower() for e in participant_emails.split(',') if e.strip()]

    return []

def extract_domain(email):
    """Extract domain from email"""
    if '@' not in email:
        return None
    return email.split('@')[1].lower()

def is_internal_domain(domain):
    """Check if domain is internal"""
    return domain in INTERNAL_DOMAINS

def get_external_email_count(deal_id):
    """Get count of distinct external participant emails for a deal"""
    calls = get_calls_for_deal(deal_id)

    if not calls:
        return None

    external_emails = set()

    for call in calls:
        emails = extract_emails(call.get('participant_emails'))

        for email in emails:
            domain = extract_domain(email)
            if domain and not is_internal_domain(domain):
                external_emails.add(email)

    return len(external_emails) if external_emails else None

def main():
    print("=" * 80)
    print("SIGNAL 1 SEGMENT MIX VERIFICATION")
    print("=" * 80)
    print("\nChecking if won/lost email-count separation is segment-independent...")

    # Get all closed deals
    closed_deals = get_closed_deals()
    print(f"\nTotal closed deals: {len(closed_deals)}")

    won_deals = [d for d in closed_deals if d['deal_status'] == 'won']
    lost_deals = [d for d in closed_deals if d['deal_status'] == 'lost']

    # Analyze participant data by segment
    won_by_segment = defaultdict(list)
    lost_by_segment = defaultdict(list)

    deals_analyzed = 0
    deals_with_data = 0

    print("\nAnalyzing participant data by segment...")
    for deal in closed_deals:
        deals_analyzed += 1
        if deals_analyzed % 100 == 0:
            print(f"  Processed {deals_analyzed}/{len(closed_deals)} deals...")

        email_count = get_external_email_count(deal['deal_id'])

        if email_count is None:
            continue

        deals_with_data += 1
        segment = deal.get('segment', 'Unknown')

        if deal['deal_status'] == 'won':
            won_by_segment[segment].append(email_count)
        else:
            lost_by_segment[segment].append(email_count)

    print(f"\nCompleted analysis: {deals_with_data} deals with participant data")

    # Report segment distribution
    print("\n" + "=" * 80)
    print("SEGMENT DISTRIBUTION")
    print("=" * 80)

    all_segments = sorted(set(list(won_by_segment.keys()) + list(lost_by_segment.keys())))

    print(f"\nSegment distribution of deals WITH participant data:")
    print(f"{'Segment':<15} {'Won':>6} {'Lost':>6} {'Total':>6} {'Won %':>8}")
    print("-" * 50)

    won_total = sum(len(counts) for counts in won_by_segment.values())
    lost_total = sum(len(counts) for counts in lost_by_segment.values())

    for segment in all_segments:
        won_count = len(won_by_segment[segment])
        lost_count = len(lost_by_segment[segment])
        total = won_count + lost_count
        won_pct = (won_count / total * 100) if total > 0 else 0

        print(f"{segment:<15} {won_count:>6} {lost_count:>6} {total:>6} {won_pct:>7.1f}%")

    print("-" * 50)
    print(f"{'TOTAL':<15} {won_total:>6} {lost_total:>6} {won_total + lost_total:>6}")

    # Check for segment mix bias
    print("\n" + "=" * 80)
    print("SEGMENT MIX BIAS CHECK")
    print("=" * 80)

    # Compare won vs lost segment distribution
    won_enterprise_pct = (len(won_by_segment['Enterprise']) / won_total * 100) if won_total > 0 else 0
    lost_enterprise_pct = (len(lost_by_segment['Enterprise']) / lost_total * 100) if lost_total > 0 else 0

    won_smb_pct = (len(won_by_segment['SMB']) / won_total * 100) if won_total > 0 else 0
    lost_smb_pct = (len(lost_by_segment['SMB']) / lost_total * 100) if lost_total > 0 else 0

    print(f"\nWon deals segment mix:")
    print(f"  Enterprise: {won_enterprise_pct:.1f}%")
    print(f"  Mid-Market: {(len(won_by_segment['Mid-Market']) / won_total * 100) if won_total > 0 else 0:.1f}%")
    print(f"  SMB: {won_smb_pct:.1f}%")

    print(f"\nLost deals segment mix:")
    print(f"  Enterprise: {lost_enterprise_pct:.1f}%")
    print(f"  Mid-Market: {(len(lost_by_segment['Mid-Market']) / lost_total * 100) if lost_total > 0 else 0:.1f}%")
    print(f"  SMB: {lost_smb_pct:.1f}%")

    # Check for significant bias
    enterprise_bias = abs(won_enterprise_pct - lost_enterprise_pct)
    smb_bias = abs(won_smb_pct - lost_smb_pct)

    print(f"\nSegment mix difference:")
    print(f"  Enterprise: {enterprise_bias:.1f} percentage points")
    print(f"  SMB: {smb_bias:.1f} percentage points")

    if enterprise_bias > 15 or smb_bias > 15:
        print("\n⚠️  SIGNIFICANT SEGMENT MIX BIAS DETECTED (>15 percentage points)")
        print("   Won/lost email-count separation may be explained by segment mix")
    else:
        print("\n✅ No significant segment mix bias (< 15 percentage points)")

    # Within-segment separation analysis
    print("\n" + "=" * 80)
    print("WITHIN-SEGMENT SEPARATION TEST")
    print("=" * 80)

    print("\nChecking if multi-threading signal holds WITHIN each segment...")

    for segment in all_segments:
        won_counts = won_by_segment[segment]
        lost_counts = lost_by_segment[segment]

        if not won_counts or not lost_counts:
            print(f"\n{segment}:")
            print(f"  ❌ Cannot test (missing won or lost deals with data)")
            continue

        won_median = sorted(won_counts)[len(won_counts)//2]
        lost_median = sorted(lost_counts)[len(lost_counts)//2]

        print(f"\n{segment}:")
        print(f"  Won deals (n={len(won_counts)}): median {won_median} emails")
        print(f"  Lost deals (n={len(lost_counts)}): median {lost_median} emails")

        if won_median > lost_median:
            direction = "✅ Won > Lost (expected)"
        elif won_median < lost_median:
            direction = "❌ Won < Lost (inverted)"
        else:
            direction = "⚠️  Won = Lost (no separation)"

        print(f"  Direction: {direction}")

        # Check if sample is large enough to trust
        min_sample = min(len(won_counts), len(lost_counts))
        if min_sample < 5:
            print(f"  ⚠️  WARNING: Small sample (n={min_sample} < 5) - pattern unreliable")

    # Natural baseline: segment differences
    print("\n" + "=" * 80)
    print("NATURAL BASELINE: SEGMENT STAKEHOLDER COUNTS")
    print("=" * 80)

    print("\nExpected stakeholder counts by segment (all deals with data):")

    for segment in all_segments:
        all_counts = won_by_segment[segment] + lost_by_segment[segment]

        if not all_counts:
            continue

        median = sorted(all_counts)[len(all_counts)//2]
        mean = sum(all_counts) / len(all_counts)

        print(f"\n{segment} (n={len(all_counts)}):")
        print(f"  Median: {median} emails")
        print(f"  Mean: {mean:.1f} emails")

    # Final verdict
    print("\n" + "=" * 80)
    print("VERDICT")
    print("=" * 80)

    # Check if we have enough samples for within-segment test
    testable_segments = 0
    segments_with_separation = 0
    segments_with_correct_direction = 0

    for segment in all_segments:
        won_counts = won_by_segment[segment]
        lost_counts = lost_by_segment[segment]

        if len(won_counts) >= 5 and len(lost_counts) >= 5:
            testable_segments += 1

            won_median = sorted(won_counts)[len(won_counts)//2]
            lost_median = sorted(lost_counts)[len(lost_counts)//2]

            if won_median != lost_median:
                segments_with_separation += 1

            if won_median > lost_median:
                segments_with_correct_direction += 1

    print(f"\nWithin-segment test viability:")
    print(f"  Segments with sufficient samples (n≥5 both outcomes): {testable_segments}/3")

    if testable_segments == 0:
        print("\n❌ CANNOT VERIFY segment-independent separation")
        print("   Sample sizes too thin to test within-segment hypothesis")
        print("\n⚠️  The aggregate won > lost finding is UNCONFIRMED as segment-independent")
        print("   Could be explained by segment mix bias rather than genuine multi-threading signal")
        print("\nRECOMMENDATION: Do not over-interpret the correct-direction finding")
        print("   Note as 'promising future signal' but insufficient evidence to validate hypothesis")

    elif testable_segments > 0:
        if segments_with_correct_direction == testable_segments:
            print(f"\n✅ CONFIRMED: All {testable_segments} testable segments show won > lost")
            print("   Multi-threading signal appears segment-independent")
        elif segments_with_correct_direction > testable_segments / 2:
            print(f"\n⚠️  MIXED: {segments_with_correct_direction}/{testable_segments} segments show won > lost")
            print("   Multi-threading signal not consistent across segments")
        else:
            print(f"\n❌ INVERTED: Most segments show won < lost or no separation")
            print("   Aggregate finding not supported by within-segment analysis")

    # Check segment mix bias impact
    if enterprise_bias > 15 or smb_bias > 15:
        print("\n⚠️  ADDITIONAL CONCERN: Significant segment mix bias detected")
        print("   Won deals skew toward high-stakeholder segments")
        print("   Lost deals skew toward low-stakeholder segments")
        print("   Aggregate finding may primarily reflect segment differences")

if __name__ == '__main__':
    main()
