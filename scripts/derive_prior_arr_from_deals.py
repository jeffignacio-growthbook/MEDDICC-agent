#!/usr/bin/env python3
"""
Check if prior_arr can be DERIVED from sequential renewal deals per customer.

Concept: This period's starting ARR = last period's ending ARR for same customer.
If deals are sequentially chained per customer, we can sidestep the unreliable
manual prior_arr field entirely.
"""

import os
import sys
from pathlib import Path
from datetime import datetime, timedelta
from collections import defaultdict
from dotenv import load_dotenv

sys.path.insert(0, str(Path(__file__).parent.parent))
load_dotenv()

from scripts.hubspot_deals import HubSpotDealsClient

print("=" * 80)
print("DERIVE PRIOR_ARR FROM SEQUENTIAL DEAL RECORDS")
print("=" * 80)
print()

hs = HubSpotDealsClient()

# Fetch ALL closed won renewal deals with company associations
print("Fetching all closed won renewal deals with company associations...")

properties = [
    'dealname',
    'closedate',
    'hs_object_id',
    'prior_arr',
    'gb_arr',
    'amount',
    'renewal_revenue',
    'associations.company'
]

RENEWAL_PIPELINE_ID = "866608541"
CLOSED_WON_STAGE_ID = "1297321623"

# Need to use the associations API to get company IDs
body = {
    "filterGroups": [
        {
            "filters": [
                {
                    "propertyName": "pipeline",
                    "operator": "EQ",
                    "value": RENEWAL_PIPELINE_ID
                },
                {
                    "propertyName": "dealstage",
                    "operator": "EQ",
                    "value": CLOSED_WON_STAGE_ID
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
        print(f"Error: {response.status_code}")
        sys.exit(1)

    data = response.json()
    results = data.get('results', [])

    # Get company associations for each deal
    for deal in results:
        deal_id = deal.get('id')

        # Fetch associations
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

print(f"✓ Fetched {len(all_deals)} closed won renewal deals")
print()

# Parse deals
parsed_deals = []

for deal in all_deals:
    props = deal.get('properties', {})
    closedate_str = props.get('closedate')

    if not closedate_str:
        continue

    try:
        closedate = datetime.fromisoformat(closedate_str.replace('Z', '+00:00'))
    except:
        continue

    company_ids = deal.get('company_ids', [])

    parsed_deals.append({
        'id': deal.get('id'),
        'name': props.get('dealname', 'Unknown'),
        'closedate': closedate,
        'prior_arr': float(props.get('prior_arr') or 0),
        'gb_arr': float(props.get('gb_arr') or 0),
        'amount': float(props.get('amount') or 0),
        'renewal_revenue': float(props.get('renewal_revenue') or 0),
        'company_ids': company_ids,
        'has_company': len(company_ids) > 0
    })

# Sort by close date
parsed_deals.sort(key=lambda x: x['closedate'])

print(f"Deals with company associations: {sum(1 for d in parsed_deals if d['has_company'])}/{len(parsed_deals)}")
print()

# ============================================================================
# CHECK 1: Do customers have sequential renewal deals?
# ============================================================================
print("=" * 80)
print("CHECK 1: SEQUENTIAL RENEWAL DEALS PER CUSTOMER")
print("=" * 80)
print()

# Group deals by company
by_company = defaultdict(list)

for deal in parsed_deals:
    for company_id in deal['company_ids']:
        by_company[company_id].append(deal)

# Find companies with multiple renewals
multi_renewal_companies = {
    company_id: deals
    for company_id, deals in by_company.items()
    if len(deals) >= 2
}

print(f"Companies with multiple renewal deals: {len(multi_renewal_companies)}")
print()

if len(multi_renewal_companies) == 0:
    print("⚠️ NO SEQUENTIAL RENEWALS FOUND")
    print()
    print("Finding: Each company appears to have only one renewal deal in system.")
    print("This means prior_arr CANNOT be derived from previous deal records")
    print("because there are no previous renewal records to chain from.")
    print()
    print("CONCLUSION: GRR is NOT YET COMPUTABLE")
    print("  - Starting ARR is manual, unreliable input")
    print("  - No derivation path available")
    print("  - Contraction formula proven correct (keep this finding)")
    print("  - Recommend: Automate prior_arr/gb_arr capture")
    sys.exit(0)

# Analyze sequential renewals
print("Sample companies with sequential renewals:")
print()

derivation_tests = []

for company_id, deals in list(multi_renewal_companies.items())[:10]:
    # Sort by date
    deals_sorted = sorted(deals, key=lambda x: x['closedate'])

    print(f"Company ID: {company_id}")
    print(f"  Renewal count: {len(deals_sorted)}")

    for i, deal in enumerate(deals_sorted):
        print(f"  [{i+1}] {deal['name']}")
        print(f"      Close: {deal['closedate'].strftime('%Y-%m-%d')}")
        print(f"      Prior ARR: ${deal['prior_arr']:,.2f}")
        print(f"      GB ARR: ${deal['gb_arr']:,.2f}")

    # Check if we can derive deal 2's prior_arr from deal 1's gb_arr
    if len(deals_sorted) >= 2:
        deal1 = deals_sorted[-2]  # Second to last
        deal2 = deals_sorted[-1]  # Most recent

        # Expected: deal2's prior_arr should = deal1's gb_arr
        expected_prior = deal1['gb_arr']
        actual_prior = deal2['prior_arr']

        match = abs(expected_prior - actual_prior) < 0.01

        print(f"  Derivation test:")
        print(f"    Deal 1 ending ARR: ${expected_prior:,.2f}")
        print(f"    Deal 2 prior ARR: ${actual_prior:,.2f}")
        print(f"    Match: {match}")

        if not match:
            diff = abs(expected_prior - actual_prior)
            diff_pct = (diff / expected_prior * 100) if expected_prior > 0 else 0
            print(f"    Difference: ${diff:,.2f} ({diff_pct:.1f}%)")

        derivation_tests.append({
            'company_id': company_id,
            'deal1_name': deal1['name'],
            'deal2_name': deal2['name'],
            'expected': expected_prior,
            'actual': actual_prior,
            'match': match,
            'diff': abs(expected_prior - actual_prior)
        })

    print()

# ============================================================================
# CHECK 2: Derivation reliability
# ============================================================================
print("=" * 80)
print("CHECK 2: DERIVATION RELIABILITY")
print("=" * 80)
print()

if len(derivation_tests) == 0:
    print("⚠️ Not enough sequential deals to test derivation")
    sys.exit(0)

matches = sum(1 for t in derivation_tests if t['match'])
total = len(derivation_tests)
match_rate = (matches / total * 100) if total > 0 else 0

print(f"Derivation tests: {total}")
print(f"Exact matches: {matches} ({match_rate:.1f}%)")
print()

if match_rate >= 90:
    print("✓ DERIVATION IS RELIABLE")
    print()
    print("Finding: This period's prior_arr CAN be derived from last period's gb_arr")
    print("         with >90% accuracy across sequential renewal records.")
    print()
    print("RECOMMENDATION:")
    print("  1. Create hygiene rule: derive_prior_arr_from_sequential_deals")
    print("  2. For each renewal, look up customer's previous renewal deal")
    print("  3. Use previous deal's gb_arr as this deal's starting ARR")
    print("  4. This sidesteps unreliable manual prior_arr field entirely")
    print()
    print("  → Re-run GRR dogfood test with derived starting ARR")
    print("  → Contraction handling already proven correct")

elif match_rate >= 50:
    print("⚠️ DERIVATION IS APPROXIMATE")
    print()
    print(f"Finding: Derivation works for {match_rate:.1f}% of cases")
    print("         Remaining cases have discrepancies")
    print()
    print("Investigate mismatches:")
    mismatches = [t for t in derivation_tests if not t['match']]
    for t in mismatches[:5]:
        print(f"  Company {t['company_id']}")
        print(f"    {t['deal1_name']} → {t['deal2_name']}")
        print(f"    Expected: ${t['expected']:,.2f}, Actual: ${t['actual']:,.2f}")
        print(f"    Diff: ${t['diff']:,.2f}")
        print()

    print("Need to understand why these don't match before using derivation")

else:
    print("✗ DERIVATION IS UNRELIABLE")
    print()
    print(f"Finding: Only {match_rate:.1f}% of sequential renewals have matching ARR")
    print("         This suggests gb_arr is also unreliable or inconsistently defined")
    print()
    print("CONCLUSION: GRR is NOT YET COMPUTABLE")
    print("  - Both prior_arr AND gb_arr are unreliable")
    print("  - No reliable derivation path")
    print("  - Contraction formula proven correct (preserve this finding)")
    print("  - Recommend: Automate ARR capture at source")

print()
print("=" * 80)
print(f"Sequential renewal companies: {len(multi_renewal_companies)}")
print(f"Derivation match rate: {match_rate:.1f}%")
print("=" * 80)
