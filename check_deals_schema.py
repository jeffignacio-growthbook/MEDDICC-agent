#!/usr/bin/env python3
"""
Check deals and deals_snapshot table schemas
"""

import os
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).parent
sys.path.insert(0, str(REPO_ROOT / 'scripts'))

from supabase import create_client

SUPABASE_URL = os.getenv('SUPABASE_URL')
SUPABASE_KEY = os.getenv('SUPABASE_SERVICE_KEY')

if not SUPABASE_URL or not SUPABASE_KEY:
    print("⚠️  SUPABASE_URL or SUPABASE_SERVICE_KEY not set")
    exit(1)

sb = create_client(SUPABASE_URL, SUPABASE_KEY)

# Get deals table columns
print("=== DEALS Table Columns ===")
result = sb.table('deals').select('*').limit(1).execute()
if result.data:
    cols = sorted(result.data[0].keys())
    for col in cols:
        print(f"  {col}")

print("\n=== DEALS_SNAPSHOT Table Columns ===")
result = sb.table('deals_snapshot').select('*').limit(1).execute()
if result.data:
    cols = sorted(result.data[0].keys())
    for col in cols:
        print(f"  {col}")

# Check a sample deal to see stage_order vs deal_stage_name
print("\n=== Sample Deal Stage Data ===")
result = sb.table('deals').select('deal_id, deal_stage_name, stage_order, pipeline_id').limit(5).execute()
if result.data:
    print(f"{'Deal ID':<20} {'Stage Name':<30} {'Order':<8} {'Pipeline':<15}")
    print("-" * 75)
    for row in result.data:
        print(f"{str(row.get('deal_id', '')):<20} {str(row.get('deal_stage_name', '')):<30} {str(row.get('stage_order', '')):<8} {str(row.get('pipeline_id', '')):<15}")

# Check snapshot stage data
print("\n=== Sample Snapshot Stage Data (2026-08-11) ===")
result = sb.table('deals_snapshot').select('deal_id, deal_stage_name, stage_order, pipeline_id').eq('snapshot_date', '2026-08-11').limit(5).execute()
if result.data:
    print(f"{'Deal ID':<20} {'Stage Name':<30} {'Order':<8} {'Pipeline':<15}")
    print("-" * 75)
    for row in result.data:
        print(f"{str(row.get('deal_id', '')):<20} {str(row.get('deal_stage_name', '')):<30} {str(row.get('stage_order', '')):<8} {str(row.get('pipeline_id', '')):<15}")
