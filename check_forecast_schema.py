#!/usr/bin/env python3
"""
Check forecast_weekly table schema to verify historical_conversion columns exist.
"""
import os
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).parent
sys.path.insert(0, str(REPO_ROOT / 'scripts'))

def main():
    SUPABASE_URL = os.getenv('SUPABASE_URL')
    SUPABASE_KEY = os.getenv('SUPABASE_SERVICE_KEY')

    if not SUPABASE_URL or not SUPABASE_KEY:
        print("⚠️  SUPABASE_URL or SUPABASE_SERVICE_KEY not set")
        return

    from supabase import create_client
    sb = create_client(SUPABASE_URL, SUPABASE_KEY)

    print("Checking forecast_weekly schema...")
    print()

    # Try to select all columns to see what exists
    try:
        result = sb.table('forecast_weekly').select('*').limit(1).execute()
        if result.data:
            print("Current columns in forecast_weekly:")
            for col in sorted(result.data[0].keys()):
                print(f"  ✓ {col}")

            # Check specifically for historical_conversion columns
            has_low = 'historical_conversion_low' in result.data[0]
            has_mid = 'historical_conversion_mid' in result.data[0]
            has_high = 'historical_conversion_high' in result.data[0]

            print()
            if all([has_low, has_mid, has_high]):
                print("✓ All historical_conversion columns exist")
            else:
                print("⚠️  Missing historical_conversion columns:")
                if not has_low:
                    print("  - historical_conversion_low")
                if not has_mid:
                    print("  - historical_conversion_mid")
                if not has_high:
                    print("  - historical_conversion_high")
                print()
                print("Migration 047 needs to be applied.")
        else:
            print("⚠️  forecast_weekly table is empty, cannot determine schema")
            print("Trying a describe approach instead...")

            # Try to insert with all columns to test
            test_row = {
                'week_ending': '2026-09-01',
                'pipeline_id': 'test',
                'fiscal_quarter': 'FY2027 Q1',
                'historical_conversion_low': 0,
                'historical_conversion_mid': 0,
                'historical_conversion_high': 0,
            }
            result = sb.table('forecast_weekly').insert(test_row).execute()
            print("✓ All historical_conversion columns exist (test insert succeeded)")

            # Clean up test row
            sb.table('forecast_weekly').delete().eq('pipeline_id', 'test').execute()

    except Exception as e:
        error_msg = str(e)
        if 'historical_conversion' in error_msg.lower():
            print(f"⚠️  Migration 047 NOT applied: {e}")
            print()
            print("="*70)
            print("ACTION REQUIRED: Apply migration in Supabase SQL Editor")
            print("="*70)
            print("""
ALTER TABLE forecast_weekly
  ADD COLUMN IF NOT EXISTS historical_conversion_low  NUMERIC DEFAULT 0,
  ADD COLUMN IF NOT EXISTS historical_conversion_mid  NUMERIC DEFAULT 0,
  ADD COLUMN IF NOT EXISTS historical_conversion_high NUMERIC DEFAULT 0;
""")
        else:
            print(f"Error checking schema: {e}")

if __name__ == '__main__':
    main()
