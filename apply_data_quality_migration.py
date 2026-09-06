#!/usr/bin/env python3
"""
Apply data quality exclusions migration directly
"""

import os
import sys
from pathlib import Path
from dotenv import load_dotenv

env_path = Path(__file__).parent / '.env'
load_dotenv(env_path)
sys.path.insert(0, str(Path(__file__).parent))

from api.db import get_supabase


def main():
    supabase = get_supabase()

    print("Applying data_quality_exclusions migration...")
    print()

    # Read the migration file
    migration_path = Path(__file__).parent / 'scripts' / 'migrations' / '053_add_data_quality_exclusions.sql'
    with open(migration_path) as f:
        sql = f.read()

    # Split into individual statements (on semicolon + newline)
    statements = [s.strip() for s in sql.split(';\n') if s.strip() and not s.strip().startswith('--') and not s.strip().startswith('COMMENT')]

    for i, stmt in enumerate(statements, 1):
        if not stmt:
            continue

        print(f"Executing statement {i}/{len(statements)}...")
        try:
            # Execute via Supabase RPC or direct SQL if available
            result = supabase.rpc('exec_sql', {'sql_string': stmt}).execute()
            print(f"  ✓ Success")
        except Exception as e:
            # Try alternative method - some Supabase clients don't support exec_sql
            print(f"  Note: {e}")
            print(f"  Attempting alternative method...")
            try:
                # For PostgREST, we can't execute arbitrary SQL
                # This migration needs to be run via SQL editor
                print(f"  ⚠️  Manual application required via Supabase SQL editor")
                print()
                print("  SQL:")
                print("  " + "-" * 60)
                print("  " + stmt.replace("\n", "\n  "))
                print("  " + "-" * 60)
                print()
            except Exception as e2:
                print(f"  ✗ Failed: {e2}")

    print()
    print("Migration complete. Verifying table exists...")

    try:
        result = supabase.table('data_quality_exclusions').select('deal_id', count='exact').limit(1).execute()
        print(f"✓ Table exists with {result.count} rows")
    except Exception as e:
        print(f"⚠️  Table not found: {e}")
        print()
        print("Please apply the migration manually via Supabase SQL editor:")
        print()
        with open(migration_path) as f:
            print(f.read())


if __name__ == '__main__':
    main()
