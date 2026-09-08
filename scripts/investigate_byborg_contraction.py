#!/usr/bin/env python3
"""
Investigate Byborg's contraction_revenue discrepancy.

Questions:
1. Why -$2,000 when ARR delta is $2,625?
2. Is negative sign convention intentional or error?
3. Is contraction_revenue calculated vs manually entered?
"""

import os
import sys
from pathlib import Path
from dotenv import load_dotenv

sys.path.insert(0, str(Path(__file__).parent.parent))
load_dotenv()

from scripts.hubspot_deals import HubSpotDealsClient

print("=" * 80)
print("BYBORG CONTRACTION DISCREPANCY INVESTIGATION")
print("=" * 80)
print()

hs = HubSpotDealsClient()

# Fetch Byborg deal with ALL fields
print("Fetching Byborg Enterprises - 2026 renewal deal...")

# Search for Byborg
body = {
    "filterGroups": [
        {
            "filters": [
                {
                    "propertyName": "dealname",
                    "operator": "CONTAINS_TOKEN",
                    "value": "Byborg"
                }
            ]
        }
    ],
    "properties": [
        "dealname", "closedate", "pipeline", "dealstage",
        "prior_arr", "gb_arr", "amount",
        "contraction_revenue", "expansion_revenue", "renewal_revenue",
        "incremental_arr", "new_revenue",
        "revenue_split_total",
        "hs_createdate", "hs_lastmodifieddate"
    ],
    "limit": 10
}

response = hs.session.post(
    f"{hs.BASE_URL}/crm/v3/objects/deals/search",
    json=body
)

if response.status_code != 200:
    print(f"Error: {response.status_code}")
    sys.exit(1)

data = response.json()
deals = data.get('results', [])

print(f"Found {len(deals)} Byborg deals")
print()

# Find the 2026 renewal
byborg_2026 = None
for deal in deals:
    props = deal.get('properties', {})
    if '2026 renewal' in props.get('dealname', '').lower():
        byborg_2026 = deal
        break

if not byborg_2026:
    print("Could not find Byborg 2026 renewal deal")
    sys.exit(1)

props = byborg_2026.get('properties', {})

print("=" * 80)
print("BYBORG 2026 RENEWAL - COMPLETE FIELD DUMP")
print("=" * 80)
print()

print(f"Deal name: {props.get('dealname')}")
print(f"Close date: {props.get('closedate')}")
print(f"Pipeline: {props.get('pipeline')}")
print(f"Stage: {props.get('dealstage')}")
print()

print("ARR FIELDS:")
print(f"  Prior ARR: ${float(props.get('prior_arr') or 0):,.2f}")
print(f"  GB ARR (ending): ${float(props.get('gb_arr') or 0):,.2f}")
print(f"  Amount: ${float(props.get('amount') or 0):,.2f}")
print()

print("REVENUE BREAKDOWN FIELDS:")
print(f"  Renewal revenue: ${float(props.get('renewal_revenue') or 0):,.2f}")
print(f"  Expansion revenue: ${float(props.get('expansion_revenue') or 0):,.2f}")
print(f"  Contraction revenue: ${float(props.get('contraction_revenue') or 0):,.2f}")
print(f"  New revenue: ${float(props.get('new_revenue') or 0):,.2f}")
print(f"  Incremental ARR: ${float(props.get('incremental_arr') or 0):,.2f}")
print()

print("VALIDATION FIELD:")
print(f"  Revenue split total: ${float(props.get('revenue_split_total') or 0):,.2f}")
print()

# Calculate what we expect
prior_arr = float(props.get('prior_arr') or 0)
gb_arr = float(props.get('gb_arr') or 0)
renewal_rev = float(props.get('renewal_revenue') or 0)
expansion_rev = float(props.get('expansion_revenue') or 0)
contraction_rev = float(props.get('contraction_revenue') or 0)
new_rev = float(props.get('new_revenue') or 0)
incremental_arr = float(props.get('incremental_arr') or 0)

print("=" * 80)
print("ANALYSIS: WHAT DO THE NUMBERS TELL US?")
print("=" * 80)
print()

# Calculate ARR delta
arr_delta = gb_arr - prior_arr
print(f"1. ARR DELTA CALCULATION:")
print(f"   Ending ARR - Prior ARR = ${gb_arr:,.2f} - ${prior_arr:,.2f} = ${arr_delta:,.2f}")
print()

# Check revenue breakdown
print(f"2. REVENUE BREAKDOWN CHECK:")
print(f"   New: ${new_rev:,.2f}")
print(f"   Renewal: ${renewal_rev:,.2f}")
print(f"   Expansion: ${expansion_rev:,.2f}")
print(f"   Contraction: ${contraction_rev:,.2f}")
print()

# Check if breakdown sums to anything meaningful
breakdown_sum = new_rev + renewal_rev + expansion_rev + contraction_rev
print(f"   Sum: ${breakdown_sum:,.2f}")
print(f"   GB ARR: ${gb_arr:,.2f}")
print(f"   Match: {abs(breakdown_sum - gb_arr) < 0.01}")
print()

# Check if renewal_revenue = prior_arr
print(f"3. RENEWAL REVENUE VS PRIOR ARR:")
print(f"   Renewal revenue: ${renewal_rev:,.2f}")
print(f"   Prior ARR: ${prior_arr:,.2f}")
print(f"   Difference: ${abs(renewal_rev - prior_arr):,.2f}")
print()

# Try to understand contraction sign
print(f"4. CONTRACTION VALUE INTERPRETATION:")
print(f"   Contraction revenue: ${contraction_rev:,.2f}")
print(f"   Is negative: {contraction_rev < 0}")
print()

if contraction_rev < 0:
    print("   Negative contraction could mean:")
    print("   a) Sign convention: negative = revenue lost (absolute value is amount)")
    print("   b) Data entry error: should be positive")
    print("   c) Special case: negative contraction = expansion (unlikely)")
print()

# Check if contraction explains the ARR delta
print(f"5. DOES CONTRACTION EXPLAIN ARR DELTA?")
print(f"   ARR delta: ${arr_delta:,.2f}")
print(f"   Contraction (absolute): ${abs(contraction_rev):,.2f}")
print(f"   Discrepancy: ${abs(arr_delta) - abs(contraction_rev):,.2f}")
print()

if abs(arr_delta) != abs(contraction_rev):
    print("   ⚠️ CONTRACTION DOESN'T FULLY EXPLAIN ARR DELTA")
    print(f"   Missing/extra: ${abs(abs(arr_delta) - abs(contraction_rev)):,.2f}")
    print()
    print("   Possible explanations:")
    print("   - Expansion revenue partially offset contraction")
    print("   - Contraction field excludes some component (e.g., one-time fees)")
    print("   - Rounding or data entry variance")
print()

# Check expansion
if expansion_rev != 0:
    print(f"6. EXPANSION FACTOR:")
    print(f"   Expansion revenue: ${expansion_rev:,.2f}")
    print()
    print("   If prior ARR $10,625 had:")
    print(f"   - Expansion: +${expansion_rev:,.2f}")
    print(f"   - Contraction: {contraction_rev:,.2f}")
    print(f"   Net change: ${expansion_rev + contraction_rev:,.2f}")
    print(f"   Expected ending: ${prior_arr + expansion_rev + contraction_rev:,.2f}")
    print(f"   Actual ending: ${gb_arr:,.2f}")
    print(f"   Match: {abs((prior_arr + expansion_rev + contraction_rev) - gb_arr) < 0.01}")
print()

# ============================================================================
# CHECK OTHER RENEWAL DEALS FOR SIGN CONVENTION
# ============================================================================
print("=" * 80)
print("SIGN CONVENTION CHECK: OTHER RENEWAL DEALS")
print("=" * 80)
print()

print("Fetching other renewal deals with non-zero contraction...")

RENEWAL_PIPELINE_ID = "866608541"
CLOSED_WON_STAGE_ID = "1297321623"

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
    "properties": [
        "dealname", "prior_arr", "gb_arr",
        "contraction_revenue", "expansion_revenue"
    ],
    "limit": 100
}

after = None
all_deals = []

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
    all_deals.extend(results)

    paging = data.get('paging', {})
    after = paging.get('next', {}).get('after')

    if not after:
        break

# Find deals with non-zero contraction
contraction_deals = []
for deal in all_deals:
    props = deal.get('properties', {})
    contraction = float(props.get('contraction_revenue') or 0)
    if contraction != 0:
        contraction_deals.append({
            'name': props.get('dealname', 'Unknown'),
            'prior_arr': float(props.get('prior_arr') or 0),
            'gb_arr': float(props.get('gb_arr') or 0),
            'contraction': contraction,
            'expansion': float(props.get('expansion_revenue') or 0)
        })

print(f"Found {len(contraction_deals)} deals with non-zero contraction")
print()

for deal in contraction_deals:
    arr_delta = deal['gb_arr'] - deal['prior_arr']

    print(f"Deal: {deal['name']}")
    print(f"  Prior ARR: ${deal['prior_arr']:,.2f}")
    print(f"  Ending ARR: ${deal['gb_arr']:,.2f}")
    print(f"  ARR delta: ${arr_delta:,.2f}")
    print(f"  Contraction: ${deal['contraction']:,.2f}")
    print(f"  Expansion: ${deal['expansion']:,.2f}")
    print(f"  Sign: {'NEGATIVE' if deal['contraction'] < 0 else 'POSITIVE'}")
    print()

# ============================================================================
# DETERMINATION
# ============================================================================
print("=" * 80)
print("DETERMINATION")
print("=" * 80)
print()

# Check sign pattern
negative_count = sum(1 for d in contraction_deals if d['contraction'] < 0)
positive_count = sum(1 for d in contraction_deals if d['contraction'] > 0)

print(f"Sign pattern across {len(contraction_deals)} deals:")
print(f"  Negative contraction: {negative_count}")
print(f"  Positive contraction: {positive_count}")
print()

if negative_count > 0 and positive_count == 0:
    print("✓ SIGN CONVENTION IS CONSISTENT")
    print("  All contraction values are negative")
    print("  This suggests: negative = revenue lost (by convention)")
    print()
    print("  In this system: contraction_revenue < 0 means contraction occurred")
    print("  Absolute value represents magnitude of loss")
elif positive_count > 0 and negative_count == 0:
    print("✓ SIGN CONVENTION IS CONSISTENT")
    print("  All contraction values are positive")
    print("  This suggests: positive = revenue lost (standard convention)")
else:
    print("⚠️ MIXED SIGN CONVENTION")
    print("  Both positive and negative values found")
    print("  This suggests inconsistent data entry or different meanings")

print()
print("Magnitude discrepancy ($2,000 vs $2,625):")
print("  Needs further investigation if not explained by expansion offset")
