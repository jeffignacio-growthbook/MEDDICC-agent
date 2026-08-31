#!/usr/bin/env python3
"""
Backfill incremental_arr from HubSpot to Supabase.
HubSpot has this as a calculated field; the regular ETL doesn't pull it.
Run once after migration 046.
"""
import os
import sys
from pathlib import Path
from dotenv import load_dotenv

REPO_ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(REPO_ROOT / 'scripts'))

load_dotenv()

from supabase_client import SupabaseWriter
from hubspot_deals import HubSpotDealsClient

def backfill_incremental_arr():
    """Fetch incremental_arr from HubSpot and write to Supabase."""

    hubspot = HubSpotDealsClient()
    supabase = SupabaseWriter()

    print("Fetching renewal pipeline deals from Supabase...")

    # Get all renewal pipeline deals (866608541 from config)
    result = supabase.client.table('deals')\
        .select('deal_id,company_name')\
        .eq('pipeline_id', '866608541')\
        .execute()

    deals = result.data
    print(f"Found {len(deals)} renewal pipeline deals")
    print()

    # Batch fetch from HubSpot
    print("Fetching incremental_arr values from HubSpot...")
    deal_ids = [d['deal_id'] for d in deals]

    updated = 0
    null_count = 0
    errors = 0

    # Process in batches of 100
    BATCH_SIZE = 100
    for i in range(0, len(deal_ids), BATCH_SIZE):
        batch = deal_ids[i:i + BATCH_SIZE]

        try:
            # Use HubSpot batch API
            response = hubspot._post("/crm/v3/objects/deals/batch/read", {
                "properties": ["incremental_arr"],
                "inputs": [{"id": deal_id} for deal_id in batch]
            })

            # Update each deal in Supabase
            for result_item in response.get('results', []):
                deal_id = result_item['id']
                incremental_arr = result_item.get('properties', {}).get('incremental_arr')

                if incremental_arr is not None and incremental_arr != '':
                    # Update Supabase
                    supabase.client.table('deals')\
                        .update({'incremental_arr': float(incremental_arr)})\
                        .eq('deal_id', str(deal_id))\
                        .execute()
                    updated += 1
                else:
                    null_count += 1

            if (i + BATCH_SIZE) % 500 == 0:
                print(f"  Processed {min(i + BATCH_SIZE, len(deal_ids))}/{len(deal_ids)} deals...")

        except Exception as e:
            print(f"  Error processing batch {i}: {e}")
            errors += 1

    print()
    print(f"✓ Backfill complete")
    print(f"  Updated: {updated} deals")
    print(f"  NULL values: {null_count}")
    print(f"  Errors: {errors}")

if __name__ == "__main__":
    backfill_incremental_arr()
