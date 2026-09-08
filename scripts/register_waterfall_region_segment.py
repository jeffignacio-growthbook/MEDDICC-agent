#!/usr/bin/env python3
"""
Register waterfall_weekly region and segment columns in data_dictionary.

Prerequisites:
1. Migration add_region_segment_to_waterfall.sql has been run in Supabase
2. Columns region and segment exist in waterfall_weekly table

This script:
1. Verifies columns exist
2. Registers both in data_dictionary as queryable
3. Confirms registration succeeded
"""

import os
import sys
from pathlib import Path
from dotenv import load_dotenv

env_path = Path(__file__).parent.parent / '.env'
load_dotenv(env_path)
sys.path.insert(0, str(Path(__file__).parent.parent))

from api.db import get_supabase

print("=" * 80)
print("REGISTER WATERFALL_WEEKLY REGION + SEGMENT IN DATA_DICTIONARY")
print("=" * 80)
print()

sb = get_supabase()

# Step 1: Verify columns exist in waterfall_weekly
print("Step 1: Verifying region and segment columns exist...")
print()

try:
    test = sb.table('waterfall_weekly').select('region, segment').limit(1).execute()
    print("✓ Both columns exist in waterfall_weekly table")
except Exception as e:
    print(f"❌ ERROR: {e}")
    print()
    print("REQUIRED ACTION:")
    print("Run the migration SQL in Supabase SQL Editor:")
    print("  scripts/migrations/add_region_segment_to_waterfall.sql")
    print()
    sys.exit(1)

print()

# Step 2: Register region in data_dictionary
print("Step 2: Registering region in data_dictionary...")
print()

region_entry = {
    'supabase_table': 'waterfall_weekly',
    'supabase_column': 'region',
    'data_type': 'text',
    'description': 'Sales region for this waterfall row: NAM, EMEA, APAC, LATAM, ROW, or UNKNOWN. Enables region-specific pipeline movement analysis (beginning/ending/won/lost/net change by week and region). Derived from deals.region (company geography).',
    'is_queryable': True,
    'enum_values': ['NAM', 'EMEA', 'APAC', 'LATAM', 'ROW', 'UNKNOWN'],
    'source': 'computed'
}

# Check if already exists
existing = sb.table('data_dictionary').select('*').eq('supabase_table', 'waterfall_weekly').eq('supabase_column', 'region').execute()

if existing.data:
    print("  Region already registered, updating...")
    sb.table('data_dictionary').update(region_entry).eq('supabase_table', 'waterfall_weekly').eq('supabase_column', 'region').execute()
    print("  ✓ Updated")
else:
    print("  Inserting new entry...")
    sb.table('data_dictionary').insert(region_entry).execute()
    print("  ✓ Inserted")

print()

# Step 3: Register segment in data_dictionary
print("Step 3: Registering segment in data_dictionary...")
print()

segment_entry = {
    'supabase_table': 'waterfall_weekly',
    'supabase_column': 'segment',
    'data_type': 'text',
    'description': 'Company size segment for this waterfall row: SMB (<250 employees), Mid-Market (250-2000), Enterprise (>2000), or Unknown. Enables segment-specific pipeline movement analysis. Derived from deals.segment (employee count bands).',
    'is_queryable': True,
    'enum_values': ['SMB', 'Mid-Market', 'Enterprise', 'Unknown'],
    'source': 'computed'
}

# Check if already exists
existing = sb.table('data_dictionary').select('*').eq('supabase_table', 'waterfall_weekly').eq('supabase_column', 'segment').execute()

if existing.data:
    print("  Segment already registered, updating...")
    sb.table('data_dictionary').update(segment_entry).eq('supabase_table', 'waterfall_weekly').eq('supabase_column', 'segment').execute()
    print("  ✓ Updated")
else:
    print("  Inserting new entry...")
    sb.table('data_dictionary').insert(segment_entry).execute()
    print("  ✓ Inserted")

print()

# Step 4: Verification
print("=" * 80)
print("VERIFICATION")
print("=" * 80)
print()

print("Checking data_dictionary for waterfall_weekly region and segment...")
print()

dd_result = sb.table('data_dictionary').select('supabase_column, is_queryable, description').eq('supabase_table', 'waterfall_weekly').in_('supabase_column', ['region', 'segment']).execute()

if len(dd_result.data) == 2:
    print("✓ Both columns successfully registered:")
    print()
    for row in dd_result.data:
        queryable = '✓' if row['is_queryable'] else '✗'
        print(f"  [{queryable}] {row['supabase_column']}")
        print(f"      {row['description'][:80]}...")
        print()
    print("✓ Registration complete and verified")
else:
    print(f"❌ ERROR: Expected 2 entries, found {len(dd_result.data)}")
    sys.exit(1)

print()
print("=" * 80)
print("NEXT STEPS")
print("=" * 80)
print()
print("1. Update compute_waterfall.py to group by region and segment")
print("2. Run historical backfill to populate region/segment for all 84 existing rows")
print("3. Verify live Slack query: 'How has EMEA pipeline moved in the last 2 weeks'")
