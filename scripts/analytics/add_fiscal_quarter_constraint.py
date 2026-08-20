#!/usr/bin/env python3
"""
Add NOT NULL constraint to fiscal_quarter column.

MUST run backfill_null_fiscal_quarters.py first to ensure no NULL values exist.
This prevents future code regressions from creating orphan rows that escape
fiscal_quarter-based cleanup filters.
"""
import os
import sys
from dotenv import load_dotenv

load_dotenv()

sys.path.insert(0, 'scripts')
from supabase import create_client

def main():
    sb = create_client(os.getenv('SUPABASE_URL'), os.getenv('SUPABASE_SERVICE_KEY'))

    print("=" * 80)
    print("ADD NOT NULL CONSTRAINT TO fiscal_quarter")
    print("=" * 80)

    # Verify no NULL values exist
    result = sb.table('deals_snapshot').select('deal_id', count='exact').is_('fiscal_quarter', 'null').execute()

    null_count = result.count

    if null_count > 0:
        print(f"\n✗ Cannot add NOT NULL constraint")
        print(f"  {null_count} rows have fiscal_quarter=NULL")
        print(f"\nRun backfill first:")
        print(f"  python3 scripts/analytics/backfill_null_fiscal_quarters.py")
        sys.exit(1)

    print(f"\n✓ Verified: 0 rows with fiscal_quarter=NULL")

    # Add NOT NULL constraint via SQL
    print(f"\nAdding NOT NULL constraint to fiscal_quarter column...")

    try:
        # Supabase uses PostgREST, which doesn't support ALTER TABLE directly
        # We need to use the SQL editor or migration system
        print(f"\n⚠️  NOT NULL constraint must be added via Supabase SQL editor:")
        print(f"\n  ALTER TABLE deals_snapshot")
        print(f"  ALTER COLUMN fiscal_quarter SET NOT NULL;")
        print(f"\nOR add as migration:")
        print(f"  File: scripts/migrations/038_add_fiscal_quarter_constraint.sql")
        print(f"\nAfter adding constraint, Monday's run will fail loudly if fiscal_quarter")
        print(f"is ever NULL instead of creating orphan rows.")

    except Exception as e:
        print(f"\n✗ Error: {e}")
        sys.exit(1)

if __name__ == '__main__':
    main()
