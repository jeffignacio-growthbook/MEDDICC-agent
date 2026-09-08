#!/usr/bin/env python3
"""Check if contraction_arr field exists and is populated in historical deals."""

import os
import sys
from pathlib import Path
from dotenv import load_dotenv

# Add parent directory to path
sys.path.insert(0, str(Path(__file__).parent.parent))

load_dotenv()

from scripts.hubspot_deals import HubSpotDealsClient

print("=" * 80)
print("CONTRACTION FIELD AUDIT - Historical Deals")
print("=" * 80)
print()

hs = HubSpotDealsClient()

print("Step 1: Finding contraction/ARR related properties...")
print()

# Get all deal properties
response = hs._get("/crm/v3/properties/deals")
all_props = response.get('results', [])

# Search for contraction, arr, expansion related fields
keywords = ['contraction', 'arr', 'expansion', 'renewal', 'churn', 'downsell', 'downgrade']
related_props = []

for prop in all_props:
    name_lower = prop['name'].lower()
    label_lower = prop.get('label', '').lower()

    if any(kw in name_lower or kw in label_lower for kw in keywords):
        related_props.append({
            'name': prop['name'],
            'label': prop.get('label', 'No label'),
            'type': prop['type'],
            'description': prop.get('description', '')
        })

print(f"Found {len(related_props)} related properties:")
for p in related_props:
    print(f"  - {p['name']}")
    print(f"    Label: {p['label']}")
    print(f"    Type: {p['type']}")
    if p['description']:
        print(f"    Description: {p['description']}")
    print()

if not related_props:
    print("⚠️  No contraction/ARR/expansion related properties found")
    print()

print("=" * 80)
print("Step 2: Checking historical deal data...")
print()

# Get ALL deals (not just active) with ARR/amount fields
properties_to_check = [
    'dealname',
    'amount',
    'closedate',
    'dealstage',
    'pipeline',
    'hs_arr',
    'hs_mrr',
]

# Add any contraction-related fields we found
properties_to_check.extend([p['name'] for p in related_props])

print(f"Fetching all deals with {len(properties_to_check)} properties...")
print()

# Fetch all deals using search API
all_deals = []
after = None

while True:
    body = {
        "properties": properties_to_check,
        "limit": 100
    }

    if after:
        body["after"] = after

    response = hs.session.post(
        f"{hs.BASE_URL}/crm/v3/objects/deals/search",
        json=body
    )

    if response.status_code != 200:
        print(f"Error fetching deals: {response.status_code}")
        print(response.text)
        break

    data = response.json()
    results = data.get('results', [])
    all_deals.extend(results)

    paging = data.get('paging', {})
    after = paging.get('next', {}).get('after')

    if not after:
        break

print(f"✓ Fetched {len(all_deals)} total deals")
print()

print("=" * 80)
print("Step 3: Analyzing contraction field population...")
print()

# Check each contraction-related field
for prop_info in related_props:
    field_name = prop_info['name']

    populated_count = 0
    non_zero_count = 0
    sample_values = []

    for deal in all_deals:
        props = deal.get('properties', {})
        value = props.get(field_name)

        if value is not None and value != '':
            populated_count += 1

            # Try to parse as number
            try:
                num_value = float(value)
                if num_value != 0:
                    non_zero_count += 1
                    if len(sample_values) < 5:
                        sample_values.append({
                            'deal': props.get('dealname', 'Unknown'),
                            'value': num_value,
                            'closedate': props.get('closedate', 'N/A')
                        })
            except (ValueError, TypeError):
                pass

    print(f"Field: {field_name}")
    print(f"  Label: {prop_info['label']}")
    print(f"  Populated: {populated_count} / {len(all_deals)} deals ({populated_count/len(all_deals)*100:.1f}%)")
    print(f"  Non-zero values: {non_zero_count}")

    if sample_values:
        print(f"  Sample non-zero values:")
        for sample in sample_values:
            print(f"    - {sample['deal']}: ${sample['value']:,.2f} (closed: {sample['closedate']})")

    print()

print("=" * 80)
print("VERDICT")
print("=" * 80)
print()

# Check if ANY contraction field has meaningful data
has_contraction_data = any(
    sum(1 for deal in all_deals if deal.get('properties', {}).get(p['name']) not in [None, '', '0', 0]) > 0
    for p in related_props
)

if not has_contraction_data:
    print("⚠️  CONTRACTION DATA GENUINELY ABSENT")
    print()
    print("Finding: No contraction/expansion/downsell fields found with populated data")
    print("         across ALL historical deals.")
    print()
    print("Implication: GRR as strictly defined (including contraction) is NOT")
    print("             computable from current data. This is a DATA GAP.")
    print()
    print("Required action for Phase 2d:")
    print("  1. System must detect missing field during clarifying-questions")
    print("  2. Surface explicit choice: proceed with churn-only approximation")
    print("     (labeled as such) or defer until contraction is tracked")
    print("  3. If proceeding: label as 'GRR (churn-only approximation)'")
else:
    print("✓ CONTRACTION DATA EXISTS")
    print()
    print("Finding: At least one contraction-related field has historical data.")
    print("         GRR calculation may be possible if field mapping is correct.")
