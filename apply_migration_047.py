#!/usr/bin/env python3
"""
Apply migration 047 to add historical_conversion columns to forecast_weekly.
"""
import os
import sys
from pathlib import Path

# Add scripts to path for imports
REPO_ROOT = Path(__file__).parent
sys.path.insert(0, str(REPO_ROOT / 'scripts'))

try:
    import psycopg2
    HAS_PSYCOPG2 = True
except ImportError:
    HAS_PSYCOPG2 = False
    print("⚠️  psycopg2 not available, trying Supabase client")

def main():
    migration_sql = """
ALTER TABLE forecast_weekly
  ADD COLUMN IF NOT EXISTS historical_conversion_low  NUMERIC DEFAULT 0,
  ADD COLUMN IF NOT EXISTS historical_conversion_mid  NUMERIC DEFAULT 0,
  ADD COLUMN IF NOT EXISTS historical_conversion_high NUMERIC DEFAULT 0;
"""

    # Try psycopg2 first (preferred for DDL)
    SUPABASE_DB_URL = os.getenv('SUPABASE_DB_URL')
    if HAS_PSYCOPG2 and SUPABASE_DB_URL:
        print("Using psycopg2 connection...")
        try:
            conn = psycopg2.connect(SUPABASE_DB_URL)
            cur = conn.cursor()
            cur.execute(migration_sql)
            conn.commit()
            cur.close()
            conn.close()
            print("✓ Migration 047 applied successfully via psycopg2")
            return
        except Exception as e:
            print(f"⚠️  psycopg2 failed: {e}")

    # Fallback: print SQL for manual application
    print("\n" + "="*70)
    print("MANUAL APPLICATION REQUIRED")
    print("="*70)
    print("\nPaste this SQL into Supabase SQL Editor:\n")
    print(migration_sql)
    print("\n" + "="*70)

if __name__ == '__main__':
    main()
