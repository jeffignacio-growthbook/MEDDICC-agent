"""
Check MEDDICC Score Availability for Validation Deals

Verify that MEDDICC scores exist and are recent (not stale) for the 16
boundary case deals before incorporating into validation approach.
"""

import os
from datetime import datetime, timezone, timedelta
from supabase import create_client, Client
from dotenv import load_dotenv

load_dotenv()

# Supabase setup
SUPABASE_URL = os.getenv('SUPABASE_URL')
SUPABASE_KEY = os.getenv('SUPABASE_SERVICE_KEY')

if not SUPABASE_URL or not SUPABASE_KEY:
    raise ValueError("Missing SUPABASE_URL or SUPABASE_SERVICE_KEY")

sb: Client = create_client(SUPABASE_URL, SUPABASE_KEY)

# 16 boundary case deals
validation_deals = [
    'Rippling',
    'DocPlanner',
    'TRT',
    'Deel',
    'GitLab Inc.',
    'Amazon',
    'Hy-Vee',
    'Electronic Arts',
    'Expedia Group',
    'Virgin Media O2 UK Limited',
    'Zynga',
    'Guidepoint',
    'Zurich Insurance Group',
    'Zurich Insurance',
    'ATrack Solutions',
    'Robinhood'
]

def get_deal_id(company_name):
    """Get deal_id from deals table"""
    response = sb.table('deals').select(
        'deal_id, company_name'
    ).eq('company_name', company_name).eq('deal_status', 'active').execute()

    if response.data:
        return response.data[0]['deal_id']
    return None

def get_meddicc_scores(deal_id):
    """Get MEDDICC scores from analyses table"""
    response = sb.table('analyses').select(
        'deal_id, analyzed_at, '
        'champion_score, economic_buyer_score, metrics_score, '
        'decision_criteria_score, decision_process_score, '
        'pain_score, competition_score, overall_score'
    ).eq('deal_id', deal_id).order('analyzed_at', desc=True).limit(1).execute()

    if response.data:
        return response.data[0]
    return None

print("=" * 80)
print("MEDDICC SCORE AVAILABILITY CHECK")
print("=" * 80)

print("\nChecking MEDDICC scores for 16 validation deals...\n")

now = datetime.now(timezone.utc)
staleness_threshold = timedelta(days=30)  # Consider scores >30 days old as stale

scores_available = []
scores_missing = []
scores_stale = []

for company in validation_deals:
    deal_id = get_deal_id(company)

    if not deal_id:
        scores_missing.append({'company': company, 'reason': 'deal_not_found'})
        continue

    meddicc = get_meddicc_scores(deal_id)

    if not meddicc:
        scores_missing.append({'company': company, 'reason': 'no_analysis'})
        continue

    # Check staleness
    analyzed_at = datetime.fromisoformat(meddicc['analyzed_at'].replace('Z', '+00:00'))
    age = (now - analyzed_at).days

    if age > 30:
        scores_stale.append({
            'company': company,
            'deal_id': deal_id,
            'analyzed_at': meddicc['analyzed_at'],
            'age_days': age,
            'scores': meddicc
        })
    else:
        scores_available.append({
            'company': company,
            'deal_id': deal_id,
            'analyzed_at': meddicc['analyzed_at'],
            'age_days': age,
            'scores': meddicc
        })

# Report results
print("=" * 80)
print("AVAILABILITY SUMMARY")
print("=" * 80)

print(f"\nTotal validation deals: {len(validation_deals)}")
print(f"  Recent scores (<30 days): {len(scores_available)}")
print(f"  Stale scores (>30 days): {len(scores_stale)}")
print(f"  No scores available: {len(scores_missing)}")

coverage_rate = (len(scores_available) / len(validation_deals)) * 100
print(f"\nCoverage rate (recent): {coverage_rate:.1f}%")

# Show deals with recent scores
if scores_available:
    print("\n" + "=" * 80)
    print("DEALS WITH RECENT MEDDICC SCORES")
    print("=" * 80)

    for deal in sorted(scores_available, key=lambda x: x['company']):
        s = deal['scores']
        print(f"\n{deal['company']} (analyzed {deal['age_days']}d ago):")
        print(f"  Overall: {s.get('overall_score', 'N/A')}/70")
        print(f"  Champion: {s.get('champion_score', 'N/A')}/10")
        print(f"  Economic Buyer: {s.get('economic_buyer_score', 'N/A')}/10")
        print(f"  Metrics: {s.get('metrics_score', 'N/A')}/10")
        print(f"  Decision Criteria: {s.get('decision_criteria_score', 'N/A')}/10")
        print(f"  Decision Process: {s.get('decision_process_score', 'N/A')}/10")
        print(f"  Pain: {s.get('pain_score', 'N/A')}/10")
        print(f"  Competition: {s.get('competition_score', 'N/A')}/10")

# Show stale scores
if scores_stale:
    print("\n" + "=" * 80)
    print("DEALS WITH STALE SCORES (>30 days)")
    print("=" * 80)

    for deal in sorted(scores_stale, key=lambda x: -x['age_days']):
        s = deal['scores']
        print(f"\n{deal['company']} (analyzed {deal['age_days']}d ago):")
        print(f"  Overall: {s.get('overall_score', 'N/A')}/70")
        print(f"  ⚠️  Score is {deal['age_days']} days old - may not reflect current state")

# Show missing scores
if scores_missing:
    print("\n" + "=" * 80)
    print("DEALS WITHOUT SCORES")
    print("=" * 80)

    for deal in scores_missing:
        print(f"  - {deal['company']}: {deal['reason']}")

# Recommendation
print("\n" + "=" * 80)
print("RECOMMENDATION")
print("=" * 80)

if coverage_rate >= 75:
    print(f"\n✅ SUFFICIENT COVERAGE ({coverage_rate:.1f}%)")
    print("   MEDDICC scores available for most validation deals.")
    print("   Can use as third data point alongside system classification and rep answers.")
    print("\n   Approach:")
    print("   1. Pull MEDDICC scores for available deals BEFORE sending rep questions")
    print("   2. Do NOT show scores to reps (anchoring risk)")
    print("   3. After collecting rep answers, build three-way comparison:")
    print("      - System classification (Signal 2 + Signal 3)")
    print("      - Rep's unprompted answer")
    print("      - MEDDICC score pattern")
    print("\n   Most interesting: Cases where MEDDICC and rep DISAGREE")
    print("   - Rep 'moving' + MEDDICC weak → rep may be overly optimistic")
    print("   - Rep 'stalled' + MEDDICC strong → rep has context not captured in scoring")

elif coverage_rate >= 50:
    print(f"\n⚠️  MODERATE COVERAGE ({coverage_rate:.1f}%)")
    print("   MEDDICC scores available for about half of validation deals.")
    print("   Can use as complementary data point, but not comprehensive.")
    print("\n   Recommendation: Proceed with rep validation as primary signal.")
    print("   Use MEDDICC where available as additional context.")

else:
    print(f"\n❌ INSUFFICIENT COVERAGE ({coverage_rate:.1f}%)")
    print("   MEDDICC scores unavailable for most validation deals.")
    print("   Do NOT incorporate into validation approach.")
    print("\n   Recommendation: Proceed with rep validation only (system + rep two-way comparison).")
    print("   MEDDICC availability should not block or shortcut rep validation.")

print("\n" + "=" * 80)
print("KEY PRINCIPLE")
print("=" * 80)

print("""
MEDDICC is a complement to rep validation, NOT a substitute.

The whole point of asking reps was to get ground truth from someone with
context the data can't capture. MEDDICC is still just another data-derived
signal, even if it's a richer one.

If MEDDICC unavailable or stale:
→ Proceed with rep validation anyway (system classification vs rep answer)

If MEDDICC available:
→ Use as third independent data point
→ Most diagnostic: cases where MEDDICC and rep DISAGREE
→ Still don't show MEDDICC to reps (anchoring risk)
""")
