#!/usr/bin/env python3
"""
Verify region classification accuracy.

1. Count actual deals by region using config/regions.yaml
2. Show top EMEA deals by owner to spot-check
3. Verify unknown/unclassified handling
"""

import os
import sys
from pathlib import Path
from dotenv import load_dotenv
from collections import defaultdict
import yaml

env_path = Path(__file__).parent.parent / '.env'
load_dotenv(env_path)
sys.path.insert(0, str(Path(__file__).parent.parent))

from api.db import get_supabase

print("=" * 80)
print("REGION CLASSIFICATION VERIFICATION")
print("=" * 80)
print()

sb = get_supabase()

# Load region definitions
regions_yaml = Path(__file__).parent.parent / 'config' / 'regions.yaml'
with open(regions_yaml) as f:
    regions_config = yaml.safe_load(f)

region_defs = regions_config['region_definitions']

# Build country -> region mapping
country_to_region = {}
for region, config in region_defs.items():
    if region == 'ROW':
        continue
    countries = config.get('countries', [])
    for country in countries:
        country_to_region[country] = region

print(f"Loaded {len(country_to_region)} country mappings")
print()

# Fetch all deals with pagination
print("Fetching all deals...")
all_deals = []
page_size = 1000
offset = 0

while True:
    result = sb.table('deals').select(
        'deal_id, company_id, company_name, owner_email, deal_value, incremental_arr, '
        'deal_status, pipeline_id'
    ).range(offset, offset + page_size - 1).execute()
    batch = result.data

    if not batch:
        break

    all_deals.extend(batch)
    offset += page_size

    if len(batch) < page_size:
        break

print(f"Total deals: {len(all_deals)}")
print()

# Get company geography from HubSpot (using cached data from earlier script)
# For now, we'll use company_id to fetch from HubSpot again
from scripts.hubspot_deals import HubSpotDealsClient
import time

hs = HubSpotDealsClient()

# Get unique company IDs
unique_company_ids = set()
for deal in all_deals:
    company_id = deal.get('company_id')
    if company_id:
        unique_company_ids.add(str(company_id))

print(f"Fetching geography for {len(unique_company_ids)} companies from HubSpot...")

company_geography = {}
batch_size = 100
company_id_list = list(unique_company_ids)

for i in range(0, len(company_id_list), batch_size):
    batch = company_id_list[i:i + batch_size]

    batch_read_body = {
        "properties": ["country", "name"],
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
            country = props.get('country')
            name = props.get('name')

            if country:
                company_geography[company_id] = {
                    'country': country,
                    'name': name
                }

    time.sleep(0.1)

    if (i + batch_size) % 1000 == 0:
        print(f"  Processed {i + batch_size}/{len(company_id_list)}...")

print(f"✓ Got geography for {len(company_geography)} companies")
print()

# Classify deals by region
region_counts = defaultdict(int)
owner_region_counts = defaultdict(lambda: defaultdict(int))
deals_by_region = defaultdict(list)

for deal in all_deals:
    company_id = str(deal.get('company_id', ''))
    owner = deal.get('owner_email', 'unknown')

    if company_id in company_geography:
        country = company_geography[company_id]['country']
        region = country_to_region.get(country, 'ROW')
    else:
        region = 'UNKNOWN'

    region_counts[region] += 1
    owner_region_counts[owner][region] += 1
    deals_by_region[region].append({
        'deal_id': deal.get('deal_id'),
        'company_name': deal.get('company_name'),
        'owner': owner,
        'country': company_geography.get(company_id, {}).get('country'),
        'deal_value': deal.get('deal_value', 0) or deal.get('incremental_arr', 0) or 0,
        'deal_status': deal.get('deal_status')
    })

# Print results
print("=" * 80)
print("DEAL COUNTS BY REGION")
print("=" * 80)
print()

for region in ['NAM', 'EMEA', 'APAC', 'LATAM', 'ROW', 'UNKNOWN']:
    count = region_counts[region]
    pct = (count / len(all_deals) * 100) if all_deals else 0
    print(f"{region:8} {count:4} deals ({pct:5.1f}%)")

print()
print(f"Total: {len(all_deals)} deals")
print()

# Owner breakdown for top owners
print("=" * 80)
print("EMEA DEALS BY OWNER (Top 10)")
print("=" * 80)
print()

owner_emea = [(owner, counts['EMEA']) for owner, counts in owner_region_counts.items()]
owner_emea.sort(key=lambda x: -x[1])

for owner, count in owner_emea[:10]:
    if count > 0:
        print(f"{owner:35} {count:3} EMEA deals")

print()

# Check 2: Christian's top 10 EMEA deals
print("=" * 80)
print("CHRISTIAN'S TOP 10 EMEA DEALS (By Value)")
print("=" * 80)
print()

christian_emea = [d for d in deals_by_region['EMEA'] if d['owner'] == 'christian@growthbook.io']
christian_emea.sort(key=lambda x: -float(x['deal_value']))

print(f"Christian's EMEA book: {len(christian_emea)} deals")
print()
print(f"{'Company':<40} {'Country':<25} {'Value':>12} {'Status'}")
print("-" * 100)

for deal in christian_emea[:10]:
    company = deal['company_name'] or '(no name)'
    country = deal['country'] or 'unknown'
    value = deal['deal_value']
    status = deal['deal_status']

    print(f"{company:<40} {country:<25} ${value:>11,.0f} {status}")

print()

# Check 3: Unknown handling
print("=" * 80)
print("UNKNOWN/UNCLASSIFIED DEALS")
print("=" * 80)
print()

unknown_deals = deals_by_region['UNKNOWN']
print(f"Total UNKNOWN: {len(unknown_deals)} deals ({len(unknown_deals)/len(all_deals)*100:.1f}%)")
print()

# Sample unknown deals
print("Sample UNKNOWN deals (no Company.country):")
for deal in unknown_deals[:10]:
    company = deal['company_name'] or '(no name)'
    owner = deal['owner']
    print(f"  {company:<40} owner: {owner}")

print()
print("=" * 80)
print("SUMMARY")
print("=" * 80)
print()

print(f"EMEA deals (actual): {region_counts['EMEA']}")
print(f"UNKNOWN deals: {region_counts['UNKNOWN']} - MUST be surfaced explicitly")
print()
print(f"Marcel + James EMEA deals: {owner_region_counts['marcel@growthbook.io']['EMEA'] + owner_region_counts['james.shannon@growthbook.io']['EMEA']}")
print(f"All other owners EMEA deals: {region_counts['EMEA'] - owner_region_counts['marcel@growthbook.io']['EMEA'] - owner_region_counts['james.shannon@growthbook.io']['EMEA']}")
