#!/usr/bin/env python3
"""
GRR comparison on RESOLVED cohorts only (apples-to-apples).

Computes GRR two ways:
1. Current: Open deals in denominator, not numerator (treats open as failures)
2. Resolved-only: Open deals excluded from BOTH numerator and denominator

Only the resolved-only version is comparable across periods.
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
print("GRR RESOLVED COHORTS COMPARISON")
print("=" * 80)
print()

hs = HubSpotDealsClient()

RENEWAL_PIPELINE_ID = "866608541"
CLOSED_WON_STAGE_ID = "1297321623"
CLOSED_LOST_STAGE_ID = "1297321624"

STAGE_NAMES = {
    '1297321618': 'Upcoming Renewal',
    '1297321619': 'Renewal Engaged',
    '1297321620': 'Pricing Presented',
    '1297321622': 'Contract Sent',
    '1297321623': 'Closed Won',
    '1297321624': 'Closed Lost'
}

def fetch_renewal_cohort(period_start, period_end):
    """Fetch all renewal deals in a period with activity tracking."""
    properties = [
        'dealname',
        'closedate',
        'dealstage',
        'renewal_revenue',
        'contraction_revenue',
        'expansion_revenue',
        'notes_last_updated',
        'notes_last_contacted',
        'hs_lastmodifieddate'
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

        # Get last activity
        last_modified_str = props.get('hs_lastmodifieddate')
        last_modified = None
        if last_modified_str:
            try:
                last_modified = datetime.fromisoformat(last_modified_str.replace('Z', '+00:00'))
            except:
                pass

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
            'last_modified': last_modified
        })

    return cohort

def calculate_grr_both_ways(cohort, period_name):
    """Calculate GRR two ways: all deals vs. resolved only."""
    won_deals = [d for d in cohort if d['is_won']]
    lost_deals = [d for d in cohort if d['is_lost']]
    open_deals = [d for d in cohort if d['is_open']]
    resolved_deals = won_deals + lost_deals

    # METHOD 1: Current (open in denominator, not numerator)
    denominator_all = sum(d['renewal_revenue'] for d in cohort)
    won_renewal = sum(d['renewal_revenue'] for d in won_deals)
    total_contraction = sum(d['contraction_revenue'] for d in won_deals)
    total_expansion = sum(d['expansion_revenue'] for d in won_deals)

    numerator_grr_all = won_renewal - total_contraction
    grr_all = (numerator_grr_all / denominator_all * 100) if denominator_all > 0 else 0

    numerator_nrr_all = numerator_grr_all + total_expansion
    nrr_all = (numerator_nrr_all / denominator_all * 100) if denominator_all > 0 else 0

    # METHOD 2: Resolved only (open excluded from both)
    denominator_resolved = sum(d['renewal_revenue'] for d in resolved_deals)
    numerator_grr_resolved = numerator_grr_all  # Same numerator (only won deals)
    grr_resolved = (numerator_grr_resolved / denominator_resolved * 100) if denominator_resolved > 0 else 0

    numerator_nrr_resolved = numerator_nrr_all  # Same numerator
    nrr_resolved = (numerator_nrr_resolved / denominator_resolved * 100) if denominator_resolved > 0 else 0

    return {
        'period': period_name,
        'cohort_size': len(cohort),
        'won': len(won_deals),
        'lost': len(lost_deals),
        'open': len(open_deals),
        'resolved': len(resolved_deals),
        'pct_resolved': (len(resolved_deals) / len(cohort) * 100) if len(cohort) > 0 else 0,

        # All deals (current method)
        'denominator_all': denominator_all,
        'grr_all': grr_all,
        'nrr_all': nrr_all,

        # Resolved only
        'denominator_resolved': denominator_resolved,
        'grr_resolved': grr_resolved,
        'nrr_resolved': nrr_resolved,

        'contraction': total_contraction,
        'expansion': total_expansion,
        'open_deals': open_deals
    }

# Fetch and compute for all three periods
periods = [
    ("2026 Q1", datetime(2026, 1, 1, tzinfo=tz.utc), datetime(2026, 3, 31, 23, 59, 59, tzinfo=tz.utc)),
    ("2026 Q2", datetime(2026, 4, 1, tzinfo=tz.utc), datetime(2026, 6, 30, 23, 59, 59, tzinfo=tz.utc)),
    ("2026 Q3", datetime(2026, 7, 1, tzinfo=tz.utc), datetime(2026, 9, 30, 23, 59, 59, tzinfo=tz.utc))
]

results = []
cohorts = {}

for period_name, start, end in periods:
    print(f"Fetching {period_name}...")
    cohort = fetch_renewal_cohort(start, end)
    metrics = calculate_grr_both_ways(cohort, period_name)
    results.append(metrics)
    cohorts[period_name] = cohort

print()
print("=" * 80)
print("GRR COMPARISON: TWO METHODS")
print("=" * 80)
print()

print("METHOD 1: Current (open deals in denominator, not numerator)")
print("  → Treats open deals as 'failures' in the denominator")
print()

print(f"{'Period':<12} {'Total':<7} {'Won':<6} {'Lost':<6} {'Open':<6} {'%Res':<8} {'GRR':<10} {'NRR':<10}")
print("-" * 75)

for r in results:
    print(f"{r['period']:<12} {r['cohort_size']:<7} {r['won']:<6} {r['lost']:<6} {r['open']:<6} {r['pct_resolved']:>6.1f}% {r['grr_all']:>8.2f}% {r['nrr_all']:>8.2f}%")

print()

grr_all_values = [r['grr_all'] for r in results if r['grr_all'] > 0]
if len(grr_all_values) >= 2:
    range_all = max(grr_all_values) - min(grr_all_values)
    print(f"GRR variance (Method 1): {range_all:.2f} percentage points")
    print("  ⚠️ NOT COMPARABLE - periods have different cohort maturity levels")
    print()

print("-" * 80)
print()

print("METHOD 2: Resolved only (open deals excluded from BOTH numerator and denominator)")
print("  → Only counts deals that have actually resolved (won or lost)")
print("  → This is the FAIR comparison across periods")
print()

print(f"{'Period':<12} {'Resolved':<9} {'Won':<6} {'Lost':<6} {'%Res':<8} {'GRR':<10} {'NRR':<10}")
print("-" * 75)

for r in results:
    print(f"{r['period']:<12} {r['resolved']:<9} {r['won']:<6} {r['lost']:<6} {r['pct_resolved']:>6.1f}% {r['grr_resolved']:>8.2f}% {r['nrr_resolved']:>8.2f}%")

print()

grr_resolved_values = [r['grr_resolved'] for r in results if r['grr_resolved'] > 0]
if len(grr_resolved_values) >= 2:
    min_grr = min(grr_resolved_values)
    max_grr = max(grr_resolved_values)
    range_resolved = max_grr - min_grr
    print(f"GRR variance (Method 2, resolved only): {range_resolved:.2f} percentage points")
    print(f"  Range: {min_grr:.2f}% to {max_grr:.2f}%")
    print()

    if range_resolved < 10:
        print("  ✓ STABLE: Less than 10 percentage points")
    elif range_resolved < 20:
        print(f"  ⚠️ MODERATE: {range_resolved:.1f} percentage points")
    else:
        print(f"  ⚠️ HIGH: {range_resolved:.1f} percentage points")
    print()

# Detailed breakdown
for r in results:
    print(f"{r['period']} details:")
    print(f"  Cohort: {r['cohort_size']} deals ({r['resolved']} resolved, {r['open']} open)")
    print(f"  Resolved: {r['won']} won, {r['lost']} lost ({r['pct_resolved']:.1f}% of cohort)")
    print()
    print(f"  METHOD 1 (all deals):")
    print(f"    Denominator: ${r['denominator_all']:,.2f}")
    print(f"    GRR: {r['grr_all']:.2f}%")
    print(f"    NRR: {r['nrr_all']:.2f}%")
    print()
    print(f"  METHOD 2 (resolved only):")
    print(f"    Denominator: ${r['denominator_resolved']:,.2f}")
    print(f"    GRR: {r['grr_resolved']:.2f}%")
    print(f"    NRR: {r['nrr_resolved']:.2f}%")
    print()

# ============================================================================
# INVESTIGATE OPEN DEALS IN CLOSED PERIODS
# ============================================================================
print("=" * 80)
print("OPEN DEALS IN CLOSED PERIODS (DATA QUALITY CHECK)")
print("=" * 80)
print()

now = datetime.now(tz.utc)

for period_name in ["2026 Q1", "2026 Q2"]:
    r = next(r for r in results if r['period'] == period_name)

    if r['open'] == 0:
        print(f"{period_name}: No open deals ✓")
        print()
        continue

    print(f"{period_name}: {r['open']} open deals")

    period_end = periods[[p[0] for p in periods].index(period_name)][2]
    days_past_close = (now - period_end).days

    print(f"  Period ended: {period_end.strftime('%Y-%m-%d')} ({days_past_close} days ago)")
    print()

    for deal in r['open_deals']:
        print(f"  Deal: {deal['name']}")
        print(f"    Stage: {deal['stage_name']}")
        print(f"    Close date: {deal['closedate'].strftime('%Y-%m-%d')}")
        print(f"    Renewal revenue: ${deal['renewal_revenue']:,.2f}")

        if deal['last_modified']:
            days_since_modified = (now - deal['last_modified']).days
            print(f"    Last modified: {deal['last_modified'].strftime('%Y-%m-%d')} ({days_since_modified} days ago)")

            if days_since_modified > 90:
                print(f"    ⚠️ STALE: No activity in {days_since_modified} days")
            elif days_since_modified > 30:
                print(f"    ⚠️ INACTIVE: No activity in {days_since_modified} days")
        else:
            print(f"    Last modified: Unknown")

        print()

    print(f"  ASSESSMENT:")
    if period_name == "2026 Q1":
        print(f"    These deals are 5+ months past their close date.")
        print(f"    If stale/abandoned (like 'Chaos', 'Hey Harper' stale pipeline finding),")
        print(f"    they should be excluded from denominator or treated as lost.")
    else:
        print(f"    These deals are 2+ months past their close date.")
        print(f"    Need to verify if genuinely active or stale records.")
    print()

print("=" * 80)
print("Q3 OPEN DEALS (CURRENT PERIOD)")
print("=" * 80)
print()

q3_result = next(r for r in results if r['period'] == "2026 Q3")

print(f"Q3 has {q3_result['open']} open deals out of {q3_result['cohort_size']} ({q3_result['pct_resolved']:.1f}% resolved)")
print(f"With 23 days left in quarter, this means:")
print(f"  - Q3 GRR (Method 1): {q3_result['grr_all']:.2f}% is NOT FINAL")
print(f"  - Q3 GRR (Method 2): {q3_result['grr_resolved']:.2f}% is 'so far' on {q3_result['resolved']} deals")
print()
print("Q3 should NOT be compared to Q1/Q2 until more deals resolve.")
print()

# ============================================================================
# SUMMARY
# ============================================================================
print("=" * 80)
print("SUMMARY")
print("=" * 80)
print()

print("KEY FINDING:")
print("  The 25.6 ppt variance reported earlier was comparing:")
print(f"    Q1 at {results[0]['pct_resolved']:.0f}% resolved → {results[0]['grr_all']:.2f}% GRR")
print(f"    Q2 at {results[1]['pct_resolved']:.0f}% resolved → {results[1]['grr_all']:.2f}% GRR")
print(f"    Q3 at {results[2]['pct_resolved']:.0f}% resolved → {results[2]['grr_all']:.2f}% GRR")
print()
print("  This is NOT a fair comparison (different cohort maturity levels).")
print()

if len(grr_resolved_values) >= 2:
    print("FAIR COMPARISON (resolved deals only):")
    print(f"  Q1 GRR: {results[0]['grr_resolved']:.2f}% ({results[0]['resolved']} deals)")
    print(f"  Q2 GRR: {results[1]['grr_resolved']:.2f}% ({results[1]['resolved']} deals)")
    print(f"  Q3 GRR: {results[2]['grr_resolved']:.2f}% ({results[2]['resolved']} deals, partial)")
    print()
    print(f"  Variance (Q1 vs Q2 only): {abs(results[0]['grr_resolved'] - results[1]['grr_resolved']):.2f} ppts")
    print()

print("NEXT STEPS:")
print("  1. Investigate Q1's 4 open deals (5+ months stale)")
print("  2. Investigate Q2's 3 open deals (2+ months stale)")
print("  3. If stale, exclude from denominator and recompute")
print("  4. Wait for Q3 to resolve more before including in variance analysis")
