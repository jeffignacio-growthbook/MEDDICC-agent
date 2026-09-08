#!/usr/bin/env python3
"""
One-time enrichment: Pull Company Country/Region from HubSpot.

Fetches real geography data from HubSpot Company objects and stores
in Supabase for region classification.
"""

import os
import sys
from pathlib import Path
from dotenv import load_dotenv
from collections import defaultdict
import time

env_path = Path(__file__).parent.parent / '.env'
load_dotenv(env_path)
sys.path.insert(0, str(Path(__file__).parent.parent))

from api.db import get_supabase
from scripts.hubspot_deals import HubSpotDealsClient

print("=" * 80)
print("COMPANY GEOGRAPHY ENRICHMENT FROM HUBSPOT")
print("=" * 80)
print()

sb = get_supabase()
hs = HubSpotDealsClient()

# Step 1: Get unique company IDs from deals
print("Step 1: Fetching unique company IDs from deals...")
print()

all_deals = []
page_size = 1000
offset = 0

while True:
    result = sb.table('deals').select('deal_id, company_id, company_name').range(offset, offset + page_size - 1).execute()
    batch = result.data

    if not batch:
        break

    all_deals.extend(batch)
    offset += page_size

    if len(batch) < page_size:
        break

print(f"Total deals: {len(all_deals)}")

# Get unique company IDs (excluding None)
unique_company_ids = set()
deals_without_company = 0

for deal in all_deals:
    company_id = deal.get('company_id')
    if company_id:
        unique_company_ids.add(str(company_id))
    else:
        deals_without_company += 1

print(f"Unique companies: {len(unique_company_ids)}")
print(f"Deals without company_id: {deals_without_company}")
print()

# Step 2: Check what country/region properties exist on Company object
print("=" * 80)
print("Step 2: Checking HubSpot Company properties...")
print("=" * 80)
print()

# Get Company properties schema
props_response = hs.session.get(f"{hs.BASE_URL}/crm/v3/properties/companies")

if props_response.status_code == 200:
    all_props = props_response.json()

    # Filter to geography-related properties
    geo_props = []
    for prop in all_props.get('results', []):
        name = prop.get('name', '').lower()
        label = prop.get('label', '').lower()

        if any(term in name or term in label for term in ['country', 'region', 'geo', 'location', 'territory']):
            geo_props.append({
                'name': prop.get('name'),
                'label': prop.get('label'),
                'type': prop.get('type'),
                'description': prop.get('description', '')
            })

    if geo_props:
        print(f"Found {len(geo_props)} geography-related properties:")
        print()
        for prop in geo_props:
            print(f"  Property: {prop['name']}")
            print(f"    Label: {prop['label']}")
            print(f"    Type: {prop['type']}")
            if prop['description']:
                print(f"    Description: {prop['description']}")
            print()
    else:
        print("❌ NO geography properties found on Company object")
        print()
        print("Available properties (first 20):")
        for prop in all_props.get('results', [])[:20]:
            print(f"  - {prop.get('name')} ({prop.get('label')})")
        sys.exit(1)
else:
    print(f"❌ Failed to fetch Company properties: {props_response.status_code}")
    print(props_response.text)
    sys.exit(1)

# Step 3: Fetch Company objects with country/region data
print("=" * 80)
print("Step 3: Fetching Company geography data from HubSpot...")
print("=" * 80)
print()

# Use the first geography property found (typically 'country')
geography_property = geo_props[0]['name']
print(f"Using property: {geography_property}")
print()

# Batch fetch companies (HubSpot allows batch reads)
company_geography = {}
batch_size = 100
company_id_list = list(unique_company_ids)

print(f"Fetching geography for {len(company_id_list)} companies in batches of {batch_size}...")

for i in range(0, len(company_id_list), batch_size):
    batch = company_id_list[i:i + batch_size]

    # Build batch read request
    batch_read_body = {
        "properties": [geography_property, "name"],
        "inputs": [{"id": cid} for cid in batch]
    }

    response = hs.session.post(
        f"{hs.BASE_URL}/crm/v3/objects/companies/batch/read",
        json=batch_read_body
    )

    if response.status_code == 200:
        data = response.json()
        for result in data.get('results', []):
            company_id = result.get('id')
            props = result.get('properties', {})
            country = props.get(geography_property)
            company_name = props.get('name')

            if country:
                company_geography[company_id] = {
                    'country': country,
                    'name': company_name
                }
    else:
        print(f"  Warning: Batch {i//batch_size + 1} failed: {response.status_code}")

    # Rate limiting
    if i + batch_size < len(company_id_list):
        time.sleep(0.1)

    if (i + batch_size) % 1000 == 0:
        print(f"  Processed {i + batch_size}/{len(company_id_list)} companies...")

print()
print(f"✓ Fetched geography for {len(company_geography)} companies")
print()

# Step 4: Analyze the raw values
print("=" * 80)
print("Step 4: Analyzing country values...")
print("=" * 80)
print()

country_counts = defaultdict(int)
for data in company_geography.values():
    country = data['country']
    country_counts[country] += 1

print(f"Unique countries found: {len(country_counts)}")
print()
print("Top 20 countries:")
for country, count in sorted(country_counts.items(), key=lambda x: -x[1])[:20]:
    print(f"  {country}: {count} companies")

print()

# Step 5: Check coverage
print("=" * 80)
print("Step 5: Coverage Analysis")
print("=" * 80)
print()

deals_with_geography = 0
deals_without_geography = 0

for deal in all_deals:
    company_id = str(deal.get('company_id', ''))
    if company_id in company_geography:
        deals_with_geography += 1
    else:
        deals_without_geography += 1

coverage_pct = (deals_with_geography / len(all_deals) * 100) if all_deals else 0

print(f"Deals with company geography: {deals_with_geography} ({coverage_pct:.1f}%)")
print(f"Deals without company geography: {deals_without_geography}")
print()

# Show sample of missing geography
print("Sample deals without geography:")
missing_samples = [d for d in all_deals if str(d.get('company_id', '')) not in company_geography][:5]
for deal in missing_samples:
    print(f"  {deal.get('company_name')} (company_id: {deal.get('company_id')})")

print()
print("=" * 80)
print("READY TO PERSIST")
print("=" * 80)
print()
print(f"Property name: {geography_property}")
print(f"Coverage: {coverage_pct:.1f}%")
print(f"Sample values: {list(country_counts.keys())[:10]}")
print()
print("Next step: Store this data in Supabase")
