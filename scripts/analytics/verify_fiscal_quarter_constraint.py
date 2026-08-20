#!/usr/bin/env python3
"""
Verify NOT NULL constraint is active on fiscal_quarter column.

Run this AFTER applying the constraint via Supabase SQL editor.
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
    print("VERIFY NOT NULL CONSTRAINT ON fiscal_quarter")
    print("=" * 80)
    print()

    # Step 1: Verify no NULL values exist
    print("Step 1: Verify no NULL values exist...")
    result = sb.table('deals_snapshot').select('deal_id', count='exact').is_('fiscal_quarter', 'null').execute()

    if result.count > 0:
        print(f"✗ FAIL: {result.count} rows have fiscal_quarter=NULL")
        print("  Cannot verify constraint until NULLs are removed")
        return False

    print(f"✓ PASS: 0 rows with fiscal_quarter=NULL")
    print()

    # Step 2: Test that NULL values are rejected
    print("Step 2: Test that NULL insert is rejected...")

    test_row = {
        'deal_id': 'test_null_constraint_verification',
        'snapshot_date': '2099-12-31',
        'pipeline_id': 'test',
        'fiscal_quarter': None,  # This should be rejected
        'week_of_quarter': 1,
        'snapshot_source': 'test'
    }

    try:
        # Attempt to insert NULL fiscal_quarter
        result = sb.table('deals_snapshot').insert(test_row).execute()

        # If we get here, the insert succeeded (BAD)
        print("✗ FAIL: NULL fiscal_quarter was accepted")
        print("  Constraint is NOT active")

        # Clean up the test row
        sb.table('deals_snapshot').delete().eq('deal_id', 'test_null_constraint_verification').execute()

        return False

    except Exception as e:
        error_msg = str(e)

        # Check if it's a not-null violation
        if 'null value in column "fiscal_quarter"' in error_msg.lower() or \
           'violates not-null constraint' in error_msg.lower() or \
           'not null constraint' in error_msg.lower():
            print("✓ PASS: NULL fiscal_quarter was rejected")
            print(f"  Error: {error_msg[:100]}...")
            print()
            print("=" * 80)
            print("✓ NOT NULL CONSTRAINT IS ACTIVE")
            print("=" * 80)
            print()
            print("Monday's run will fail loudly if fiscal_quarter is NULL")
            print("instead of silently creating orphan rows.")
            return True
        else:
            print(f"⚠️  UNEXPECTED ERROR: {error_msg}")
            print("  Cannot confirm if constraint is active")
            return False

if __name__ == '__main__':
    success = main()
    sys.exit(0 if success else 1)
