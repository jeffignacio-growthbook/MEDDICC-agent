#!/usr/bin/env python3
"""
GRR with clean cohorts - exclude $0 renewal_revenue deals.

Compare variance on CLEAN, RESOLVED cohorts.
"""

import os
import sys
from pathlib import Path
from datetime import datetime, timezone as tz
from dotenv import load_dotenv

sys.path.insert(0, str(Path(__file__).parent.parent))
load_dotenv()

from scripts.hubspot_deals import HubSpotDealsClient

print("=" * 80)
print("GRR WITH CLEAN COHORTS (EXCLUDE $0 RENEWAL REVENUE)")
print("=" * 80)
print()

hs = HubSpotDealsClient()

RENEWAL_PIPELINE_ID = "866608541"
CLOSED_WON_STAGE_ID = "1297321623"
CLOSED_LOST_STAGE_ID = "1297321624"

def fetch_renewal_cohort(period_start, period_end):
    """Fetch all renewal deals in a period."""
    properties = [
        'dealname',
        'closedate',
        'dealstage',
        'renewal_revenue',
        'contraction_revenue',
        'expansion_revenue'
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
        all_deals.extend(results)

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
        renewal_revenue = float(props.get('renewal_revenue') or 0)

        cohort.append({
            'name': props.get('dealname', 'Unknown'),
            'closedate': closedate,
            'stage': stage,
            'is_won': stage == CLOSED_WON_STAGE_ID,
            'is_lost': stage == CLOSED_LOST_STAGE_ID,
            'is_open': stage not in [CLOSED_WON_STAGE_ID, CLOSED_LOST_STAGE_ID],
            'renewal_revenue': renewal_revenue,
            'contraction_revenue': float(props.get('contraction_revenue') or 0),
            'expansion_revenue': float(props.get('expansion_revenue') or 0)
        })

    return cohort

def calculate_grr_clean_resolved(cohort):
    """Calculate GRR on clean (no $0 revenue), resolved (no open) cohort."""
    # Filter out $0 renewal_revenue
    clean_cohort = [d for d in cohort if d['renewal_revenue'] > 0]

    # Filter to resolved only
    resolved_cohort = [d for d in clean_cohort if not d['is_open']]

    won_deals = [d for d in resolved_cohort if d['is_won']]

    denominator = sum(d['renewal_revenue'] for d in resolved_cohort)
    won_renewal = sum(d['renewal_revenue'] for d in won_deals)
    total_contraction = sum(d['contraction_revenue'] for d in won_deals)
    total_expansion = sum(d['expansion_revenue'] for d in won_deals)

    numerator_grr = won_renewal - total_contraction
    grr = (numerator_grr / denominator * 100) if denominator > 0 else 0

    numerator_nrr = numerator_grr + total_expansion
    nrr = (numerator_nrr / denominator * 100) if denominator > 0 else 0

    # Count excluded deals
    zero_revenue_deals = [d for d in cohort if d['renewal_revenue'] == 0]
    open_with_revenue = [d for d in clean_cohort if d['is_open']]

    return {
        'total_cohort': len(cohort),
        'zero_revenue_excluded': len(zero_revenue_deals),
        'open_excluded': len(open_with_revenue),
        'clean_resolved_cohort': len(resolved_cohort),
        'won': len(won_deals),
        'lost': len(resolved_cohort) - len(won_deals),
        'denominator': denominator,
        'won_renewal': won_renewal,
        'contraction': total_contraction,
        'expansion': total_expansion,
        'grr': grr,
        'nrr': nrr,
        'zero_revenue_deals': zero_revenue_deals,
        'open_with_revenue': open_with_revenue
    }

# Fetch all three periods
periods = [
    ("2026 Q1", datetime(2026, 1, 1, tzinfo=tz.utc), datetime(2026, 3, 31, 23, 59, 59, tzinfo=tz.utc)),
    ("2026 Q2", datetime(2026, 4, 1, tzinfo=tz.utc), datetime(2026, 6, 30, 23, 59, 59, tzinfo=tz.utc)),
    ("2026 Q3", datetime(2026, 7, 1, tzinfo=tz.utc), datetime(2026, 9, 30, 23, 59, 59, tzinfo=tz.utc))
]

results = []

for period_name, start, end in periods:
    print(f"Calculating {period_name}...")
    cohort = fetch_renewal_cohort(start, end)
    metrics = calculate_grr_clean_resolved(cohort)
    results.append({
        'period': period_name,
        **metrics
    })

print()
print("=" * 80)
print("CLEAN, RESOLVED COHORTS COMPARISON")
print("=" * 80)
print()

print("Exclusions applied:")
print("  1. $0 renewal_revenue deals (not real renewals)")
print("  2. Open deals (not yet resolved)")
print()

print(f"{'Period':<12} {'Original':<9} {'Excluded':<10} {'Clean+Res':<10} {'Won':<6} {'Lost':<6} {'GRR':<10} {'NRR':<10}")
print("-" * 85)

for r in results:
    excluded = r['zero_revenue_excluded'] + r['open_excluded']
    print(f"{r['period']:<12} {r['total_cohort']:<9} {excluded:<10} {r['clean_resolved_cohort']:<10} {r['won']:<6} {r['lost']:<6} {r['grr']:>8.2f}% {r['nrr']:>8.2f}%")

print()

# Variance analysis (Q1 vs Q2 only, Q3 is too incomplete)
q1_grr = results[0]['grr']
q2_grr = results[1]['grr']
variance_q1_q2 = abs(q1_grr - q2_grr)

print("VARIANCE ANALYSIS:")
print(f"  Q1 GRR: {q1_grr:.2f}%")
print(f"  Q2 GRR: {q2_grr:.2f}%")
print(f"  Variance: {variance_q1_q2:.2f} percentage points")
print()

if variance_q1_q2 < 10:
    print("  ✓ STABLE: Less than 10 percentage points")
elif variance_q1_q2 < 15:
    print(f"  ⚠️ MODERATE: {variance_q1_q2:.1f} percentage points")
    print("  May reflect real business seasonality")
elif variance_q1_q2 < 20:
    print(f"  ⚠️ NOTABLE: {variance_q1_q2:.1f} percentage points")
    print("  Warrants investigation of business factors")
else:
    print(f"  ⚠️ HIGH: {variance_q1_q2:.1f} percentage points")
    print("  Significant difference - investigate cause")

print()

# Detailed breakdown
for r in results[:2]:  # Only Q1 and Q2 (Q3 is incomplete)
    print(f"{r['period']} details:")
    print(f"  Original cohort: {r['total_cohort']} deals")

    if r['zero_revenue_excluded'] > 0:
        print(f"    Excluded {r['zero_revenue_excluded']} $0 revenue deals:")
        for deal in r['zero_revenue_deals']:
            print(f"      - {deal['name']}")

    if r['open_excluded'] > 0:
        print(f"    Excluded {r['open_excluded']} open deals (not resolved):")
        for deal in r['open_with_revenue']:
            print(f"      - {deal['name']} (${deal['renewal_revenue']:,.0f})")

    print(f"  Clean, resolved cohort: {r['clean_resolved_cohort']} deals")
    print(f"    {r['won']} won, {r['lost']} lost")
    print(f"  Denominator: ${r['denominator']:,.2f}")
    print(f"  Contraction: ${r['contraction']:,.2f}")
    print(f"  Expansion: ${r['expansion']:,.2f}")
    print(f"  GRR: {r['grr']:.2f}%")
    print(f"  NRR: {r['nrr']:.2f}%")
    print()

print("=" * 80)
print("SUMMARY")
print("=" * 80)
print()

print("Clean cohort definition:")
print("  - Exclude deals with $0 renewal_revenue (not real renewals)")
print("  - Exclude open deals from resolved cohort (only compare won/lost)")
print()

print(f"Q1 vs Q2 variance: {variance_q1_q2:.2f} percentage points")
print()

if variance_q1_q2 < 15:
    print("ASSESSMENT: Variance is within reasonable range for normal business volatility.")
    print("This could reflect:")
    print("  - Seasonal patterns in renewal performance")
    print("  - Different cohort composition (company sizes, segments)")
    print("  - Normal fluctuation in customer retention")
else:
    print("ASSESSMENT: Variance warrants investigation.")
    print("Check for:")
    print("  - Seasonal patterns")
    print("  - Cohort composition differences")
    print("  - Business factors (pricing changes, product issues, etc.)")

print()
print("Q3 not included in variance analysis (only 36% resolved).")
