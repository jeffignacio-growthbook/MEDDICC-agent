#!/usr/bin/env python3
"""
Populate region column in deals table from company_country.

Uses batch updates for efficiency.
"""

from dotenv import load_dotenv
from pathlib import Path
load_dotenv(Path(__file__).parent.parent / '.env')

import sys
sys.path.insert(0, str(Path(__file__).parent.parent))

from api.db import get_supabase
from api.field_semantics import get_region

sb = get_supabase()

print('=' * 80)
print('POPULATE REGION COLUMN')
print('=' * 80)
print()

# Fetch all deals
print('Fetching all deals...')
all_deals = []
offset = 0
page_size = 1000

while True:
    result = sb.table('deals').select('deal_id, company_country').range(offset, offset + page_size - 1).execute()
    batch = result.data
    if not batch:
        break
    all_deals.extend(batch)
    offset += page_size
    if len(batch) < page_size:
        break

print(f'Total deals: {len(all_deals)}')
print()

# Compute regions and batch update
print('Computing regions and updating...')
batch_size = 100
updated = 0

for i in range(0, len(all_deals), batch_size):
    batch = all_deals[i:i + batch_size]

    # Update each deal in the batch
    for deal in batch:
        region = get_region(deal)
        sb.table('deals').update({'region': region}).eq('deal_id', deal['deal_id']).execute()
        updated += 1

    if updated % 200 == 0:
        print(f'  Updated {updated}/{len(all_deals)}...')

print()
print(f'✓ Updated {updated} deals with region')
print()

# Verify distribution
print('Verifying distribution...')
result = sb.table('deals').select('region').execute()

from collections import defaultdict
counts = defaultdict(int)
for deal in result.data:
    counts[deal.get('region', 'NULL')] += 1

print()
print('Region distribution:')
for region in ['NAM', 'EMEA', 'APAC', 'LATAM', 'ROW', 'UNKNOWN']:
    print(f'  {region}: {counts[region]} deals')

print()
print('=' * 80)
print('COMPLETE')
print('=' * 80)
