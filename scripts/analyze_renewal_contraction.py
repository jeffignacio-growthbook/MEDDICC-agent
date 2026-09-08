#!/usr/bin/env python3
"""Analyze contraction_revenue specifically on renewal deals."""

import os
import sys
from pathlib import Path
from dotenv import load_dotenv

sys.path.insert(0, str(Path(__file__).parent.parent))
load_dotenv()

from scripts.hubspot_deals import HubSpotDealsClient

print("=" * 80)
print("CONTRACTION ANALYSIS - RENEWAL DEALS ONLY")
print("=" * 80)
print()

hs = HubSpotDealsClient()

# Fetch all deals in renewal pipeline
print("Fetching all deals in renewal pipeline...")

properties = [
    'dealname',
    'amount',
    'gb_arr',
    'closedate',
    'dealstage',
    'pipeline',
    'contraction_revenue',
    'expansion_revenue',
    'renewal_revenue',
    'prior_arr',
    'incremental_arr'
]

# Filter to renewal pipeline (ID from earlier output)
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
        print(response.text)
        break

    data = response.json()
    results = data.get('results', [])
    renewal_deals.extend(results)

    paging = data.get('paging', {})
    after = paging.get('next', {}).get('after')

    if not after:
        break

print(f"✓ Fetched {len(renewal_deals)} renewal pipeline deals")
print()

# Analyze contraction field on renewals
print("=" * 80)
print("CONTRACTION FIELD POPULATION - RENEWAL DEALS")
print("=" * 80)
print()

populated = 0
null_or_empty = 0
zero_values = 0
non_zero_values = 0
negative_values = 0

non_zero_examples = []
null_or_empty_examples = []

for deal in renewal_deals:
    props = deal.get('properties', {})
    contraction = props.get('contraction_revenue')

    if contraction is None or contraction == '':
        null_or_empty += 1
        if len(null_or_empty_examples) < 5:
            null_or_empty_examples.append({
                'name': props.get('dealname', 'Unknown'),
                'closedate': props.get('closedate', 'N/A'),
                'gb_arr': props.get('gb_arr', 'N/A'),
                'prior_arr': props.get('prior_arr', 'N/A')
            })
    else:
        populated += 1
        try:
            value = float(contraction)
            if value == 0:
                zero_values += 1
            else:
                non_zero_values += 1
                if value < 0:
                    negative_values += 1
                if len(non_zero_examples) < 10:
                    non_zero_examples.append({
                        'name': props.get('dealname', 'Unknown'),
                        'contraction': value,
                        'expansion': props.get('expansion_revenue', 'N/A'),
                        'renewal': props.get('renewal_revenue', 'N/A'),
                        'prior_arr': props.get('prior_arr', 'N/A'),
                        'gb_arr': props.get('gb_arr', 'N/A'),
                        'closedate': props.get('closedate', 'N/A')
                    })
        except (ValueError, TypeError):
            pass

print(f"Total renewal deals: {len(renewal_deals)}")
print()
print(f"Contraction field status:")
print(f"  Populated (not null/empty): {populated} ({populated/len(renewal_deals)*100:.1f}%)")
print(f"  Null or empty: {null_or_empty} ({null_or_empty/len(renewal_deals)*100:.1f}%)")
print()
print(f"Among populated values:")
print(f"  Zero values: {zero_values} ({zero_values/populated*100:.1f}% of populated)")
print(f"  Non-zero values: {non_zero_values} ({non_zero_values/populated*100:.1f}% of populated)")
print(f"  Negative values: {negative_values}")
print()

if non_zero_examples:
    print("=" * 80)
    print("NON-ZERO CONTRACTION EXAMPLES")
    print("=" * 80)
    print()
    for ex in non_zero_examples:
        print(f"Deal: {ex['name']}")
        print(f"  Contraction: ${ex['contraction']:,.2f}")
        print(f"  Expansion: {ex['expansion']}")
        print(f"  Renewal: {ex['renewal']}")
        print(f"  Prior ARR: {ex['prior_arr']}")
        print(f"  GB ARR: {ex['gb_arr']}")
        print(f"  Close date: {ex['closedate']}")
        print()

if null_or_empty_examples:
    print("=" * 80)
    print("NULL/EMPTY CONTRACTION EXAMPLES")
    print("=" * 80)
    print()
    for ex in null_or_empty_examples:
        print(f"Deal: {ex['name']}")
        print(f"  GB ARR: {ex['gb_arr']}")
        print(f"  Prior ARR: {ex['prior_arr']}")
        print(f"  Close date: {ex['closedate']}")
        print()

print("=" * 80)
print("VERDICT ON CONTRACTION DATA")
print("=" * 80)
print()

if null_or_empty / len(renewal_deals) > 0.5:
    print("⚠️  MAJORITY OF RENEWAL DEALS MISSING CONTRACTION DATA")
    print()
    print(f"Finding: {null_or_empty/len(renewal_deals)*100:.1f}% of renewal deals have null/empty")
    print("         contraction_revenue, suggesting data entry gap.")
    print()
    print("This is a DATA QUALITY issue, not a business reality.")
elif non_zero_values < 5:
    print("ℹ️  CONTRACTION FIELD TRACKED, BUT RARELY NON-ZERO")
    print()
    print(f"Finding: {populated/len(renewal_deals)*100:.1f}% of renewal deals have populated")
    print(f"         contraction_revenue, but only {non_zero_values} deals have non-zero values.")
    print()
    print("This could mean:")
    print("  1. Business genuinely has very low contraction (likely)")
    print("  2. Field is populated but not actively maintained (check workflow)")
    print()
    print("For GRR calculation:")
    print("  - Field EXISTS and is populated → can compute GRR")
    print("  - Zeros appear to be REAL zeros (not missing data)")
    print("  - GRR will reflect business reality: very low contraction")
else:
    print("✓ CONTRACTION DATA APPEARS HEALTHY")
    print()
    print(f"Finding: {populated/len(renewal_deals)*100:.1f}% populated, {non_zero_values}")
    print("         deals with non-zero contraction values.")
