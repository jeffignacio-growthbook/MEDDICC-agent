#!/usr/bin/env python3
"""Verify contraction is load-bearing in potential test periods."""

import os
import sys
from pathlib import Path
from datetime import datetime
from collections import defaultdict
from dotenv import load_dotenv

sys.path.insert(0, str(Path(__file__).parent.parent))
load_dotenv()

from scripts.hubspot_deals import HubSpotDealsClient

print("=" * 80)
print("CONTRACTION LOAD-BEARING TEST - GRR Dogfood Prerequisites")
print("=" * 80)
print()

hs = HubSpotDealsClient()

# Fetch all renewal deals with relevant fields
properties = [
    'dealname',
    'closedate',
    'dealstage',
    'contraction_revenue',
    'expansion_revenue',
    'renewal_revenue',
    'prior_arr',
    'gb_arr',
    'hubspot_owner_id'
]

RENEWAL_PIPELINE_ID = "866608541"

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

renewal_deals = []
after = None

while True:
    if after:
        body["after"] = after

    response = hs.session.post(
        f"{hs.BASE_URL}/crm/v3/objects/deals/search",
        json=body
    )

    if response.status_code != 200:
        print(f"Error: {response.status_code}")
        break

    data = response.json()
    results = data.get('results', [])
    renewal_deals.extend(results)

    paging = data.get('paging', {})
    after = paging.get('next', {}).get('after')

    if not after:
        break

print(f"✓ Fetched {len(renewal_deals)} renewal deals")
print()

# Parse and categorize deals
closed_won_deals = []
non_zero_contraction_deals = []
null_contraction_deals = []

for deal in renewal_deals:
    props = deal.get('properties', {})

    # Only look at closed won
    stage = props.get('dealstage', '')
    if '1297321623' not in stage:  # Closed Won stage ID
        continue

    closedate_str = props.get('closedate')
    if not closedate_str:
        continue

    try:
        closedate = datetime.fromisoformat(closedate_str.replace('Z', '+00:00'))
    except:
        continue

    contraction = props.get('contraction_revenue')

    deal_data = {
        'name': props.get('dealname', 'Unknown'),
        'closedate': closedate,
        'closedate_str': closedate_str,
        'contraction': contraction,
        'expansion': props.get('expansion_revenue'),
        'renewal': props.get('renewal_revenue'),
        'prior_arr': props.get('prior_arr'),
        'gb_arr': props.get('gb_arr'),
        'owner_id': props.get('hubspot_owner_id')
    }

    closed_won_deals.append(deal_data)

    # Track non-zero contraction
    if contraction and float(contraction) != 0:
        non_zero_contraction_deals.append(deal_data)

    # Track null/empty
    if contraction is None or contraction == '':
        null_contraction_deals.append(deal_data)

print(f"Closed Won renewal deals: {len(closed_won_deals)}")
print(f"Non-zero contraction: {len(non_zero_contraction_deals)}")
print(f"Null/empty contraction: {len(null_contraction_deals)}")
print()

# ============================================================================
# CHECK 1: Are non-zero contraction deals in natural test periods?
# ============================================================================
print("=" * 80)
print("CHECK 1: CONTRACTION LOAD-BEARING IN TEST PERIODS")
print("=" * 80)
print()

if non_zero_contraction_deals:
    print(f"Found {len(non_zero_contraction_deals)} non-zero contraction deals:")
    print()

    for deal in non_zero_contraction_deals:
        print(f"Deal: {deal['name']}")
        print(f"  Close date: {deal['closedate'].strftime('%Y-%m-%d')}")
        print(f"  Quarter: {deal['closedate'].year} Q{(deal['closedate'].month-1)//3 + 1}")
        print(f"  Contraction: ${float(deal['contraction']):,.2f}")
        print(f"  Prior ARR: {deal['prior_arr']}")
        print(f"  GB ARR: {deal['gb_arr']}")
        print()

    # Suggest test periods that include these deals
    print("Natural quarterly test periods that include non-zero contraction:")
    print()

    for deal in non_zero_contraction_deals:
        quarter = (deal['closedate'].month-1)//3 + 1
        year = deal['closedate'].year
        print(f"  - {year} Q{quarter} (includes {deal['name']})")

    print()
    print("✓ RECOMMENDATION: Choose one of these quarters for GRR dogfood test")
    print("  to ensure contraction term is PROVABLY load-bearing.")
    print()

else:
    print("⚠️  WARNING: No non-zero contraction deals found in closed won renewals")
    print()
    print("This suggests the 2 non-zero cases from the full audit may not be")
    print("closed won, or may be in different pipelines.")
    print()

# ============================================================================
# CHECK 2: Null contraction distribution pattern
# ============================================================================
print("=" * 80)
print("CHECK 2: NULL CONTRACTION DISTRIBUTION PATTERN")
print("=" * 80)
print()

if null_contraction_deals:
    print(f"Analyzing {len(null_contraction_deals)} deals with null/empty contraction:")
    print()

    # By owner
    by_owner = defaultdict(int)
    for deal in null_contraction_deals:
        owner = deal['owner_id'] or 'No owner'
        by_owner[owner] += 1

    print("Distribution by owner:")
    for owner, count in sorted(by_owner.items(), key=lambda x: -x[1])[:10]:
        pct = count / len(null_contraction_deals) * 100
        print(f"  {owner}: {count} deals ({pct:.1f}%)")
    print()

    # By year
    by_year = defaultdict(int)
    for deal in null_contraction_deals:
        year = deal['closedate'].year
        by_year[year] += 1

    print("Distribution by year:")
    for year in sorted(by_year.keys()):
        count = by_year[year]
        pct = count / len(null_contraction_deals) * 100
        print(f"  {year}: {count} deals ({pct:.1f}%)")
    print()

    # By quarter
    by_quarter = defaultdict(int)
    for deal in null_contraction_deals:
        year = deal['closedate'].year
        quarter = (deal['closedate'].month-1)//3 + 1
        by_quarter[f"{year} Q{quarter}"] += 1

    print("Distribution by quarter:")
    for qtr in sorted(by_quarter.keys()):
        count = by_quarter[qtr]
        pct = count / len(null_contraction_deals) * 100
        print(f"  {qtr}: {count} deals ({pct:.1f}%)")
    print()

    # Check for concentration
    max_owner_pct = max(by_owner.values()) / len(null_contraction_deals) * 100
    max_year_pct = max(by_year.values()) / len(null_contraction_deals) * 100

    print("=" * 80)
    print("CONCENTRATION ANALYSIS")
    print("=" * 80)
    print()

    if max_owner_pct > 50:
        print(f"⚠️  CONCENTRATED BY OWNER: {max_owner_pct:.1f}% from single owner")
        print("   This suggests one rep doesn't fill the field.")
        print("   → Should surface in clarifying-questions")
        print()
    elif max_year_pct > 70:
        print(f"⚠️  CONCENTRATED BY TIME: {max_year_pct:.1f}% from single year")
        print("   This suggests field was introduced mid-history.")
        print("   → Should surface in clarifying-questions")
        print()
    else:
        print("✓ RANDOMLY DISTRIBUTED")
        print("   No strong concentration by owner or time period.")
        print("   → Option A (treat null as zero) is reasonable default")
        print()

    # Sample a few nulls
    print("Sample null/empty deals:")
    for deal in null_contraction_deals[:5]:
        print(f"  - {deal['name']} (closed {deal['closedate'].strftime('%Y-%m-%d')})")
        print(f"    GB ARR: {deal['gb_arr']}, Prior ARR: {deal['prior_arr']}")
    print()

# ============================================================================
# FINAL RECOMMENDATIONS
# ============================================================================
print("=" * 80)
print("RECOMMENDATIONS FOR GRR DOGFOOD TEST")
print("=" * 80)
print()

if len(non_zero_contraction_deals) == 0:
    print("⚠️  ISSUE: No non-zero contraction deals found in closed won renewals")
    print()
    print("Options:")
    print("  A) Search broader (all pipelines, all stages) for the 2 known cases")
    print("  B) Accept this test proves mechanism only, add separate unit test")
    print("     for contraction arithmetic (verify $36,250 is correctly subtracted)")
    print()
elif len(non_zero_contraction_deals) > 0:
    print("✓ Can construct load-bearing test")
    print()
    print("Recommended approach:")
    quarters = set()
    for deal in non_zero_contraction_deals:
        quarter = (deal['closedate'].month-1)//3 + 1
        year = deal['closedate'].year
        quarters.add(f"{year} Q{quarter}")

    print(f"  1. Pick test period from: {', '.join(sorted(quarters))}")
    print(f"  2. This ensures contraction term is provably load-bearing")
    print(f"  3. Backtest can distinguish 'includes contraction' vs 'ignores it'")
    print()

if len(null_contraction_deals) > 0:
    if max_owner_pct > 50 or max_year_pct > 70:
        print("⚠️  Null contraction deals show concentration pattern")
        print("   → Surface in clarifying-questions:")
        print('     "14% of renewals missing contraction data, concentrated in [X]"')
    else:
        print("✓ Null contraction deals randomly distributed")
        print("   → Safe to default to Option A (treat null as zero)")
        print("   → State this as a checked conclusion in documentation")
