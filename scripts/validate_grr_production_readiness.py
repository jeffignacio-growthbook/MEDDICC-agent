#!/usr/bin/env python3
"""
Production readiness validation for GRR cohort formula.

Checks:
1. What are the 3 "other stage" deals? Open or terminal state?
2. Expansion scope: renewal pipeline only or all deals for cohort companies?
3. Multi-period sanity check: Q1, Q2, Q3 results
"""

import os
import sys
from pathlib import Path
from datetime import datetime, timezone as tz
from collections import defaultdict
from dotenv import load_dotenv

sys.path.insert(0, str(Path(__file__).parent.parent))
load_dotenv()

from scripts.hubspot_deals import HubSpotDealsClient

print("=" * 80)
print("GRR PRODUCTION READINESS VALIDATION")
print("=" * 80)
print()

hs = HubSpotDealsClient()

RENEWAL_PIPELINE_ID = "866608541"
CLOSED_WON_STAGE_ID = "1297321623"
CLOSED_LOST_STAGE_ID = "1297321624"

# Stage name mapping
STAGE_NAMES = {
    '1297321618': 'Upcoming Renewal',
    '1297321619': 'Renewal Engaged',
    '1297321620': 'Pricing Presented',
    '1297321622': 'Contract Sent',
    '1297321623': 'Closed Won',
    '1297321624': 'Closed Lost'
}

def fetch_renewal_cohort(period_start, period_end):
    """Fetch all renewal deals in a period."""
    properties = [
        'dealname',
        'closedate',
        'dealstage',
        'renewal_revenue',
        'contraction_revenue',
        'expansion_revenue',
        'associations.company'
    ]

    body = {
        "filterGroups": [
            {
                "filters": [
                    {
                        "propertyName": "pipeline",
                        "operator": "EQ",
                        "value": RENEWAL_PIPELINE_ID
                    }
                ]
            }
        ],
        "properties": properties,
        "limit": 100
    }

    all_deals = []
    after = None

    while True:
        if after:
            body["after"] = after

        response = hs.session.post(
            f"{hs.BASE_URL}/crm/v3/objects/deals/search",
            json=body
        )

        if response.status_code != 200:
            return []

        data = response.json()
        results = data.get('results', [])

        # Get company associations
        for deal in results:
            deal_id = deal.get('id')
            assoc_response = hs.session.get(
                f"{hs.BASE_URL}/crm/v4/objects/deals/{deal_id}/associations/companies"
            )

            if assoc_response.status_code == 200:
                assoc_data = assoc_response.json()
                companies = [r.get('toObjectId') for r in assoc_data.get('results', [])]
                deal['company_ids'] = companies
            else:
                deal['company_ids'] = []

            all_deals.append(deal)

        paging = data.get('paging', {})
        after = paging.get('next', {}).get('after')

        if not after:
            break

    # Filter to period
    cohort = []
    for deal in all_deals:
        props = deal.get('properties', {})
        closedate_str = props.get('closedate')

        if not closedate_str:
            continue

        try:
            closedate = datetime.fromisoformat(closedate_str.replace('Z', '+00:00'))
        except:
            continue

        if not (period_start <= closedate <= period_end):
            continue

        stage = props.get('dealstage', '')

        cohort.append({
            'id': deal.get('id'),
            'name': props.get('dealname', 'Unknown'),
            'closedate': closedate,
            'stage': stage,
            'stage_name': STAGE_NAMES.get(stage, f'Unknown ({stage})'),
            'is_won': stage == CLOSED_WON_STAGE_ID,
            'is_lost': stage == CLOSED_LOST_STAGE_ID,
            'is_open': stage not in [CLOSED_WON_STAGE_ID, CLOSED_LOST_STAGE_ID],
            'renewal_revenue': float(props.get('renewal_revenue') or 0),
            'contraction_revenue': float(props.get('contraction_revenue') or 0),
            'expansion_revenue': float(props.get('expansion_revenue') or 0),
            'company_ids': deal.get('company_ids', [])
        })

    return cohort

def calculate_grr(cohort):
    """Calculate GRR for a cohort."""
    won_deals = [d for d in cohort if d['is_won']]

    denominator = sum(d['renewal_revenue'] for d in cohort)
    won_renewal = sum(d['renewal_revenue'] for d in won_deals)
    total_contraction = sum(d['contraction_revenue'] for d in won_deals)

    numerator = won_renewal - total_contraction
    grr = (numerator / denominator * 100) if denominator > 0 else 0

    return {
        'cohort_size': len(cohort),
        'won': len(won_deals),
        'lost': sum(1 for d in cohort if d['is_lost']),
        'open': sum(1 for d in cohort if d['is_open']),
        'denominator': denominator,
        'won_renewal': won_renewal,
        'contraction': total_contraction,
        'numerator': numerator,
        'grr': grr
    }

# ============================================================================
# CHECK 1: What are the 3 "other stage" deals in Q2?
# ============================================================================
print("=" * 80)
print("CHECK 1: OTHER STAGE DEALS IN Q2 2026")
print("=" * 80)
print()

q2_start = datetime(2026, 4, 1, tzinfo=tz.utc)
q2_end = datetime(2026, 6, 30, 23, 59, 59, tzinfo=tz.utc)

q2_cohort = fetch_renewal_cohort(q2_start, q2_end)

print(f"Q2 2026 cohort: {len(q2_cohort)} deals")
print(f"  Won: {sum(1 for d in q2_cohort if d['is_won'])}")
print(f"  Lost: {sum(1 for d in q2_cohort if d['is_lost'])}")
print(f"  Other: {sum(1 for d in q2_cohort if d['is_open'])}")
print()

other_stage_deals = [d for d in q2_cohort if d['is_open']]

if other_stage_deals:
    print(f"Details of {len(other_stage_deals)} 'other stage' deals:")
    print()

    for deal in other_stage_deals:
        print(f"Deal: {deal['name']}")
        print(f"  Close date: {deal['closedate'].strftime('%Y-%m-%d')}")
        print(f"  Current stage: {deal['stage_name']}")
        print(f"  Renewal revenue: ${deal['renewal_revenue']:,.2f}")
        print(f"  Is terminal state: {not deal['is_open']}")
        print()

    print("DECISION REQUIRED:")
    print("  - If these are truly 'open' (not yet resolved): Historical GRR is PROVISIONAL")
    print("  - If these are terminal states (but not won/lost): Need to understand status")
    print()
    print("Recommendation:")
    print("  For closed historical periods (Q2 2026 is past), GRR should be treated as")
    print("  FINAL once computed, with any still-open deals excluded from numerator")
    print("  (conservative: assume lost until proven won).")
    print()
    print("  Same discipline as qualification-week cohort: deals that haven't resolved")
    print("  don't count as wins.")
    print()

else:
    print("✓ No 'other stage' deals - entire cohort is terminal (won/lost)")
    print("  GRR for Q2 2026 is FINAL, not provisional")
    print()

# ============================================================================
# CHECK 2: Expansion scope for NRR
# ============================================================================
print("=" * 80)
print("CHECK 2: EXPANSION SCOPE FOR NRR")
print("=" * 80)
print()

print("Question: Does NRR expansion include deals from DEFAULT pipeline?")
print()

# Get companies in Q2 renewal cohort
q2_company_ids = set()
for deal in q2_cohort:
    q2_company_ids.update(deal['company_ids'])

print(f"Companies in Q2 renewal cohort: {len(q2_company_ids)}")
print()

# Check if there are any DEFAULT pipeline deals for these companies in Q2
print("Checking for DEFAULT pipeline deals for cohort companies in Q2...")

DEFAULT_PIPELINE = "default"

body = {
    "filterGroups": [
        {
            "filters": [
                {
                    "propertyName": "pipeline",
                    "operator": "EQ",
                    "value": DEFAULT_PIPELINE
                }
            ]
        }
    ],
    "properties": ['dealname', 'closedate', 'dealstage', 'expansion_revenue', 'amount'],
    "limit": 100
}

default_deals = []
after = None

while True:
    if after:
        body["after"] = after

    response = hs.session.post(
        f"{hs.BASE_URL}/crm/v3/objects/deals/search",
        json=body
    )

    if response.status_code != 200:
        break

    data = response.json()
    results = data.get('results', [])

    for deal in results:
        deal_id = deal.get('id')
        assoc_response = hs.session.get(
            f"{hs.BASE_URL}/crm/v4/objects/deals/{deal_id}/associations/companies"
        )

        if assoc_response.status_code == 200:
            assoc_data = assoc_response.json()
            companies = [r.get('toObjectId') for r in assoc_data.get('results', [])]

            # Check if any company is in Q2 renewal cohort
            if any(c in q2_company_ids for c in companies):
                props = deal.get('properties', {})
                closedate_str = props.get('closedate')

                if closedate_str:
                    try:
                        closedate = datetime.fromisoformat(closedate_str.replace('Z', '+00:00'))
                        if q2_start <= closedate <= q2_end:
                            default_deals.append({
                                'name': props.get('dealname', 'Unknown'),
                                'closedate': closedate,
                                'expansion': float(props.get('expansion_revenue') or 0),
                                'amount': float(props.get('amount') or 0),
                                'company_ids': companies
                            })
                    except:
                        pass

    paging = data.get('paging', {})
    after = paging.get('next', {}).get('after')

    if not after:
        break

print(f"Found {len(default_deals)} DEFAULT pipeline deals for cohort companies in Q2")
print()

if default_deals:
    print("Sample DEFAULT pipeline deals that might contribute to NRR:")
    for deal in default_deals[:5]:
        print(f"  - {deal['name']}")
        print(f"    Expansion: ${deal['expansion']:,.2f}")
        print(f"    Amount: ${deal['amount']:,.2f}")
    print()

    total_default_expansion = sum(d['expansion'] for d in default_deals)
    print(f"Total expansion from DEFAULT pipeline: ${total_default_expansion:,.2f}")
    print()

    # Check current NRR calculation (renewal pipeline only)
    renewal_expansion = sum(d['expansion_revenue'] for d in q2_cohort if d['is_won'])
    print(f"Current NRR expansion (renewal pipeline only): ${renewal_expansion:,.2f}")
    print()

    if total_default_expansion > 0:
        print("⚠️ SCOPE DECISION REQUIRED:")
        print("  Should NRR include DEFAULT pipeline expansion?")
        print()
        print("  If YES:")
        print(f"    NRR expansion = ${renewal_expansion:,.2f} + ${total_default_expansion:,.2f}")
        print(f"                  = ${renewal_expansion + total_default_expansion:,.2f}")
        print()
        print("  If NO (current implementation):")
        print(f"    NRR expansion = ${renewal_expansion:,.2f} (renewal deals only)")
        print()
        print("  Recommendation: Start with renewal pipeline only (conservative),")
        print("  expand to all pipelines only if user explicitly requests it")
        print()
else:
    print("✓ No DEFAULT pipeline deals found for cohort companies")
    print("  NRR expansion = renewal pipeline expansion only")
    print()

# ============================================================================
# CHECK 3: Multi-period sanity check
# ============================================================================
print("=" * 80)
print("CHECK 3: MULTI-PERIOD SANITY CHECK")
print("=" * 80)
print()

periods = [
    ("2026 Q1", datetime(2026, 1, 1, tzinfo=tz.utc), datetime(2026, 3, 31, 23, 59, 59, tzinfo=tz.utc)),
    ("2026 Q2", datetime(2026, 4, 1, tzinfo=tz.utc), datetime(2026, 6, 30, 23, 59, 59, tzinfo=tz.utc)),
    ("2026 Q3", datetime(2026, 7, 1, tzinfo=tz.utc), datetime(2026, 9, 30, 23, 59, 59, tzinfo=tz.utc))
]

results = []

for period_name, start, end in periods:
    print(f"Calculating {period_name}...")
    cohort = fetch_renewal_cohort(start, end)
    metrics = calculate_grr(cohort)

    results.append({
        'period': period_name,
        **metrics
    })

print()
print("=" * 80)
print("MULTI-PERIOD COMPARISON")
print("=" * 80)
print()

print(f"{'Period':<12} {'Cohort':<8} {'Won':<6} {'Lost':<6} {'Open':<6} {'GRR':<10}")
print("-" * 60)

for r in results:
    print(f"{r['period']:<12} {r['cohort_size']:<8} {r['won']:<6} {r['lost']:<6} {r['open']:<6} {r['grr']:>8.2f}%")

print()

# Check for erratic behavior
grr_values = [r['grr'] for r in results if r['grr'] > 0]

if len(grr_values) >= 2:
    min_grr = min(grr_values)
    max_grr = max(grr_values)
    range_grr = max_grr - min_grr

    print("GRR stability:")
    print(f"  Min: {min_grr:.2f}%")
    print(f"  Max: {max_grr:.2f}%")
    print(f"  Range: {range_grr:.2f} percentage points")
    print()

    if range_grr < 10:
        print("✓ STABLE: GRR values are within 10 percentage points")
        print("  Formula produces consistent results across periods")
    elif range_grr < 20:
        print("⚠️ MODERATE VARIANCE: GRR ranges {range_grr:.1f} percentage points")
        print("  This may reflect real business seasonality or data quality issues")
    else:
        print("⚠️ HIGH VARIANCE: GRR ranges {range_grr:.1f} percentage points")
        print("  Investigate: Is this real business volatility or formula issue?")

print()
print("=" * 80)
print("PRODUCTION READINESS SUMMARY")
print("=" * 80)
print()

print("1. Other stage deals: See findings above")
print("2. Expansion scope: Recommend starting with renewal pipeline only")
print("3. Multi-period check: See stability analysis above")
