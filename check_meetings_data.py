#!/usr/bin/env python3
"""Check if meetings data exists in Supabase."""

import os
import sys
from pathlib import Path
from dotenv import load_dotenv

# Load environment variables
env_path = Path(__file__).parent / '.env'
load_dotenv(env_path)

sys.path.insert(0, str(Path(__file__).parent))
from api.db import get_supabase

sb = get_supabase()

print("\n" + "="*80)
print("MEETINGS DATA INVESTIGATION")
print("="*80)

# 1. Check for meetings-related tables
print("\n1. Looking for meetings-related tables:")

# Try to query for meetings table directly
tables_to_check = ['meetings', 'engagements', 'activities', 'calls', 'emails']
found_tables = []

for table in tables_to_check:
    try:
        result = sb.table(table).select('*').limit(1).execute()
        found_tables.append(table)
        print(f"   ✓ {table} table exists ({len(result.data)} sample rows)")
    except Exception as e:
        if 'does not exist' in str(e) or 'could not find' in str(e).lower():
            print(f"   ✗ {table} table does not exist")
        else:
            print(f"   ? {table} - error: {e}")

# 2. Check deals table for Jake's deals and their stages
print("\n2. Checking deals table for Jake Stangl's pipeline:")
jake_deals = sb.table('deals').select(
    'deal_id,company_name,stage,deal_status,create_date,owner_email'
).eq('owner_email', 'jake.stangl@growthbook.io').execute()

print(f"   Total deals owned by Jake: {len(jake_deals.data)}")

if jake_deals.data:
    # Show stage distribution
    from collections import Counter
    stages = Counter(d.get('stage') for d in jake_deals.data)
    print("\n   Stage distribution:")
    for stage, count in stages.most_common():
        print(f"     {stage}: {count}")

    # Show recent deals
    print("\n   Recent deals (sample):")
    sorted_deals = sorted(jake_deals.data,
                          key=lambda x: x.get('create_date', '') or '',
                          reverse=True)
    for deal in sorted_deals[:5]:
        print(f"     - {deal.get('company_name')}: {deal.get('stage')} "
              f"(created: {deal.get('create_date', 'unknown')[:10]})")

# 3. Check if meetings are tracked as HubSpot engagements
print("\n3. Checking for meeting metadata in deals table:")
sample_deals = sb.table('deals').select('*').limit(1).execute()
if sample_deals.data:
    print("   Sample deal columns:")
    for col in sorted(sample_deals.data[0].keys()):
        if 'meet' in col.lower() or 'engagement' in col.lower():
            print(f"     ✓ {col}: {sample_deals.data[0].get(col)}")

# 4. Check analyses table for SDR attribution
print("\n4. Checking analyses table for SDR attribution:")
try:
    analyses_sample = sb.table('analyses').select('*').limit(1).execute()
    if analyses_sample.data:
        print("   Sample analyses columns with 'sdr' or 'source':")
        for col in sorted(analyses_sample.data[0].keys()):
            if 'sdr' in col.lower() or 'source' in col.lower() or 'origin' in col.lower():
                print(f"     {col}: {analyses_sample.data[0].get(col)}")
except Exception as e:
    print(f"   Error querying analyses: {e}")

print("\n" + "="*80)
print("CONCLUSION:")
print("="*80)
if 'meetings' in found_tables:
    print("✓ Meetings table exists - check if it has Jake's data")
else:
    print("✗ No meetings table found - need migration 016 + HubSpot meetings ETL")
print("\nNext: Check HubSpot for meeting engagement objects")
print("="*80 + "\n")
