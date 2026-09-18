#!/usr/bin/env python3
"""Check renewal pipeline deals in database after sync."""
from dotenv import load_dotenv
load_dotenv()

import os
from supabase import create_client
from collections import Counter

supabase_url = os.getenv("SUPABASE_URL")
supabase_key = os.getenv("SUPABASE_SERVICE_KEY")

if not supabase_url or not supabase_key:
    print("ERROR: Supabase credentials not found")
    exit(1)

supabase = create_client(supabase_url, supabase_key)

# Query all renewal pipeline deals
response = supabase.table("deals") \
    .select("deal_id,company_name,pipeline_id,stage,stage_source") \
    .eq("pipeline_id", "866608541") \
    .execute()

deals = response.data

print(f"Renewal pipeline (866608541) deals in database: {len(deals)}")
print("=" * 70)

# Count by stage_source
stage_source_counts = Counter(d['stage_source'] for d in deals if d.get('stage_source'))

print("Stage source breakdown:")
for source, count in stage_source_counts.most_common():
    print(f"  {source:15}: {count:3} deals")

print("\n" + "=" * 70)

# Write deal IDs to file for comparison
with open("/tmp/db_renewal_deals.txt", "w") as f:
    for deal in deals:
        f.write(f"{deal['deal_id']}\n")

print(f"Wrote {len(deals)} renewal deal IDs to /tmp/db_renewal_deals.txt")

# Show first 10
print("\nFirst 10 renewal deals in database:")
for i, deal in enumerate(deals[:10]):
    name = deal['company_name'] or 'N/A'
    stage = deal.get('stage', 'N/A')
    print(f"  [{i+1}] {name[:30]:30} | {stage[:20]:20} | {deal['deal_id']}")
