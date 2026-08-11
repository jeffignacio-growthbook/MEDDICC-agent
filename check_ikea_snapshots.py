#!/usr/bin/env python3
"""
Check IKEA deal in snapshots
"""

import os
from supabase import create_client

SUPABASE_URL = os.getenv('SUPABASE_URL')
SUPABASE_KEY = os.getenv('SUPABASE_SERVICE_KEY')

if not SUPABASE_URL or not SUPABASE_KEY:
    print("⚠️  SUPABASE_URL or SUPABASE_SERVICE_KEY not set")
    exit(1)

sb = create_client(SUPABASE_URL, SUPABASE_KEY)

# Check deal 50347229229 across snapshots
deal_id = '50347229229'

print(f"=== Snapshots for deal {deal_id} ===\n")

result = sb.table('deals_snapshot').select('*').eq('deal_id', deal_id).order('snapshot_date').execute()

if result.data:
    print(f"{'Date':<15} {'Stage ID':<25} {'Order':<8} {'Value':<12} {'Status':<10}")
    print("-" * 75)
    for row in result.data:
        print(f"{row.get('snapshot_date', ''):<15} {str(row.get('stage_id', '')):<25} {str(row.get('stage_order', '')):<8} {str(row.get('deal_value', '')):<12} {row.get('deal_status', ''):<10}")
else:
    print("No snapshots found for this deal")

# Also check current deals table
print(f"\n=== Current deals table ===\n")
result = sb.table('deals').select('*').eq('deal_id', deal_id).execute()
if result.data:
    deal = result.data[0]
    print(f"Stage: {deal.get('stage')}")
    print(f"Company: {deal.get('company_name')}")
    print(f"Value: {deal.get('deal_value')}")
    print(f"Pipeline: {deal.get('pipeline')}")
