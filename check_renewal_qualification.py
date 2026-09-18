#!/usr/bin/env python3
"""Check if renewal deals have qualified_date set."""
from dotenv import load_dotenv
load_dotenv()

import os
from supabase import create_client
from collections import Counter

supabase_url = os.getenv("SUPABASE_URL")
supabase_key = os.getenv("SUPABASE_SERVICE_KEY")

supabase = create_client(supabase_url, supabase_key)

# Query renewal pipeline deals
response = supabase.table("deals") \
    .select("deal_id,company_name,stage,qualified_date,highest_stage_order_reached,stage_source") \
    .eq("pipeline_id", "866608541") \
    .execute()

deals = response.data

print(f"Renewal pipeline deals: {len(deals)}")
print("=" * 70)

# Count by qualified_date presence
qualified = [d for d in deals if d.get('qualified_date')]
unqualified = [d for d in deals if not d.get('qualified_date')]

print(f"With qualified_date: {len(qualified)}")
print(f"Without qualified_date: {len(unqualified)}")

# Check stage_order for unqualified
stage_order_counts = Counter()
for d in unqualified:
    order = d.get('highest_stage_order_reached', 0)
    stage_order_counts[order] += 1

print(f"\nStage order distribution for deals WITHOUT qualified_date:")
for order in sorted(stage_order_counts.keys()):
    count = stage_order_counts[order]
    print(f"  stage_order {order}: {count} deals")

# Show sample of deals with qualified_date
print(f"\nSample of deals WITH qualified_date (first 10):")
for i, deal in enumerate(qualified[:10]):
    name = deal['company_name'] or 'N/A'
    qdate = deal.get('qualified_date', 'N/A')
    order = deal.get('highest_stage_order_reached', 0)
    print(f"  [{i+1}] {name[:30]:30} | {qdate} | order={order}")

# Show sample of deals without qualified_date
print(f"\nSample of deals WITHOUT qualified_date (first 10):")
for i, deal in enumerate(unqualified[:10]):
    name = deal['company_name'] or 'N/A'
    stage = deal.get('stage', 'N/A')
    order = deal.get('highest_stage_order_reached', 0)
    source = deal.get('stage_source', 'N/A')
    print(f"  [{i+1}] {name[:30]:30} | stage={stage[:15]:15} | order={order} | source={source}")
