#!/usr/bin/env python3
"""
Check IKEA deal across snapshots
"""

import os
from supabase import create_client

SUPABASE_URL = os.getenv('SUPABASE_URL')
SUPABASE_KEY = os.getenv('SUPABASE_SERVICE_KEY')

if not SUPABASE_URL or not SUPABASE_KEY:
    print("⚠️  SUPABASE_URL or SUPABASE_SERVICE_KEY not set")
    exit(1)

sb = create_client(SUPABASE_URL, SUPABASE_KEY)

# Check current deals table for IKEA
print("=== Current DEALS table (IKEA) ===")
result = sb.table('deals').select('deal_id, company_name, stage, pipeline, highest_stage_order_reached').ilike('company_name', '%IKEA%Optimizely%').execute()
if result.data:
    for row in result.data:
        print(f"Deal ID: {row.get('deal_id')}")
        print(f"Company: {row.get('company_name')}")
        print(f"Stage: {row.get('stage')}")
        print(f"Pipeline: {row.get('pipeline')}")
        print(f"Highest Order Reached: {row.get('highest_stage_order_reached')}")
        print()

# Check snapshots
print("=== DEALS_SNAPSHOT for IKEA deal ===")
# Assuming deal_id from screenshot is visible
result = sb.table('deals_snapshot').select('*').in_('snapshot_date', ['2026-08-09', '2026-08-11']).ilike('owner_email', '%liebenow%').execute()

if result.data:
    print(f"{'Snapshot Date':<15} {'Deal ID':<20} {'Stage ID':<15} {'Order':<8} {'Value':<12} {'Status':<10}")
    print("-" * 90)
    for row in sorted(result.data, key=lambda x: (x.get('deal_id', ''), x.get('snapshot_date', ''))):
        print(f"{row.get('snapshot_date', ''):<15} {str(row.get('deal_id', '')):<20} {str(row.get('stage_id', '')):<15} {str(row.get('stage_order', '')):<8} {str(row.get('deal_value', '')):<12} {row.get('deal_status', ''):<10}")
