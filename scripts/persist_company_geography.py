#!/usr/bin/env python3
"""
Persist Company geography data to Supabase.

Adds company_country column to deals table and populates from HubSpot.
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
print("PERSIST COMPANY GEOGRAPHY TO SUPABASE")
print("=" * 80)
print()

sb = get_supabase()
hs = HubSpotDealsClient()

# Step 1: Check if company_country column exists
print("Step 1: Checking if company_country column exists...")
print()

# Try to select company_country
try:
    test = sb.table('deals').select('company_country').limit(1).execute()
    print("✓ company_country column already exists")
    column_exists = True
except Exception as e:
    if 'column deals.company_country does not exist' in str(e):
        print("❌ company_country column does not exist")
        print()
        print("MANUAL STEP REQUIRED:")
        print("Run this SQL in Supabase:")
        print()
        print("  ALTER TABLE deals ADD COLUMN company_country TEXT;")
        print()
        print("Then re-run this script.")
        sys.exit(1)
    else:
        raise

print()

# Step 2: Fetch all deals
print("Step 2: Fetching all deals...")
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

# Get unique company IDs
unique_company_ids = set()
for deal in all_deals:
    company_id = deal.get('company_id')
    if company_id:
        unique_company_ids.add(str(company_id))

print(f"Unique companies: {len(unique_company_ids)}")
print()

# Step 3: Fetch geography from HubSpot
print("=" * 80)
print("Step 3: Fetching geography from HubSpot...")
print("=" * 80)
print()

company_geography = {}
batch_size = 100
company_id_list = list(unique_company_ids)

print(f"Fetching {len(company_id_list)} companies in batches of {batch_size}...")

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

            if country:
                company_geography[company_id] = country

    time.sleep(0.1)

    if (i + batch_size) % 1000 == 0:
        print(f"  Processed {i + batch_size}/{len(company_id_list)} companies...")

print()
print(f"✓ Fetched geography for {len(company_geography)} companies")
print()

# Step 4: Update deals table
print("=" * 80)
print("Step 4: Updating deals table...")
print("=" * 80)
print()

updated = 0
skipped = 0

for deal in all_deals:
    deal_id = deal.get('deal_id')
    company_id = str(deal.get('company_id', ''))

    if company_id in company_geography:
        country = company_geography[company_id]

        # Update deal
        sb.table('deals').update({
            'company_country': country
        }).eq('deal_id', deal_id).execute()

        updated += 1

        if updated % 100 == 0:
            print(f"  Updated {updated}/{len(all_deals)} deals...")
    else:
        skipped += 1

print()
print(f"✓ Updated {updated} deals with company_country")
print(f"  Skipped {skipped} deals (no geography data)")
print()

# Step 5: Verify
print("=" * 80)
print("Step 5: Verifying...")
print("=" * 80)
print()

verification = sb.table('deals').select('company_country').execute()
with_country = sum(1 for d in verification.data if d.get('company_country'))
coverage_pct = (with_country / len(verification.data) * 100) if verification.data else 0

print(f"Deals with company_country: {with_country} ({coverage_pct:.1f}%)")
print()

# Show country distribution
country_counts = defaultdict(int)
for deal in verification.data:
    country = deal.get('company_country')
    if country:
        country_counts[country] += 1

print("Top 10 countries by deal count:")
for country, count in sorted(country_counts.items(), key=lambda x: -x[1])[:10]:
    print(f"  {country}: {count} deals")

print()
print("=" * 80)
print("✅ COMPLETE")
print("=" * 80)
