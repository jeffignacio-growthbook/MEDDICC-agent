#!/usr/bin/env python3
"""Run migration 014: Create diagnostic_escalations table."""

import os
import sys
from pathlib import Path
from dotenv import load_dotenv
from supabase import create_client

load_dotenv()

SUPABASE_URL = os.environ.get('SUPABASE_URL')
SUPABASE_KEY = os.environ.get('SUPABASE_SERVICE_KEY')

if not SUPABASE_URL or not SUPABASE_KEY:
    print("ERROR: SUPABASE_URL and SUPABASE_SERVICE_KEY must be set")
    sys.exit(1)

sb = create_client(SUPABASE_URL, SUPABASE_KEY)

print("="*80)
print("MIGRATION 014: Create diagnostic_escalations table")
print("="*80)
print()

# Read migration SQL
migration_file = Path(__file__).parent / "migrations" / "014_add_diagnostic_escalations.sql"
with open(migration_file, 'r') as f:
    sql = f.read()

# For Supabase, we need to use the SQL editor or direct psql
# Since we can't execute arbitrary SQL via the Python client easily,
# let's use the table creation approach

print("Creating diagnostic_escalations table via Supabase client...")
print()

# Try to query the table first to see if it exists
try:
    result = sb.table('diagnostic_escalations').select('id', count='exact').limit(1).execute()
    print(f"ℹ️  Table already exists (count: {result.count or 0})")
    print()
    print("Skipping creation - table is already live.")
    sys.exit(0)
except Exception as e:
    if "does not exist" in str(e).lower() or "could not find" in str(e).lower():
        print("Table does not exist - need to create it")
        print()
        print("="*80)
        print("MANUAL STEP REQUIRED")
        print("="*80)
        print()
        print("Supabase Python client cannot execute DDL directly.")
        print("Please run this SQL in the Supabase SQL Editor:")
        print()
        print("─"*80)
        print(sql)
        print("─"*80)
        print()
        print("After running the SQL, re-run this script to verify.")
        sys.exit(1)
    else:
        print(f"Unexpected error: {e}")
        sys.exit(1)
