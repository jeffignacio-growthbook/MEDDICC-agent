#!/usr/bin/env python3
"""Execute migration 061 to add newly_arr_bearing columns."""
import os
import psycopg2
from dotenv import load_dotenv

load_dotenv()

SUPABASE_DB_URL = os.getenv('SUPABASE_DB_URL')

if not SUPABASE_DB_URL:
    raise ValueError('SUPABASE_DB_URL must be set in .env')

# Migration SQL
migration_sql = """
-- Add newly_arr_bearing columns to waterfall_weekly
-- These track deals that crossed the ARR-bearing threshold ($0→value with stage progression)

ALTER TABLE waterfall_weekly
ADD COLUMN IF NOT EXISTS newly_arr_bearing_value NUMERIC DEFAULT 0,
ADD COLUMN IF NOT EXISTS newly_arr_bearing_count INTEGER DEFAULT 0;

COMMENT ON COLUMN waterfall_weekly.newly_arr_bearing_value IS 'Value of deals that crossed ARR-bearing threshold this week ($0→value with stage_order progression)';
COMMENT ON COLUMN waterfall_weekly.newly_arr_bearing_count IS 'Count of deals that crossed ARR-bearing threshold this week';
"""

print("=" * 70)
print("Executing migration 061: add_newly_arr_bearing")
print("=" * 70)
print()
print("SQL to execute:")
print(migration_sql)
print()

try:
    # Connect to database
    print("Connecting to database...")
    conn = psycopg2.connect(SUPABASE_DB_URL)
    conn.autocommit = True
    cursor = conn.cursor()

    # Execute migration
    print("Executing migration...")
    cursor.execute(migration_sql)

    # Verify columns were added
    cursor.execute("""
        SELECT column_name, data_type, column_default
        FROM information_schema.columns
        WHERE table_name = 'waterfall_weekly'
        AND column_name IN ('newly_arr_bearing_value', 'newly_arr_bearing_count')
        ORDER BY column_name;
    """)

    columns = cursor.fetchall()

    print()
    print("✓ Migration executed successfully!")
    print()
    print("Columns added:")
    for col in columns:
        print(f"  - {col[0]} ({col[1]}, default: {col[2]})")

    cursor.close()
    conn.close()

    print()
    print("=" * 70)
    print("Next step: Run the full backfill")
    print("=" * 70)
    print()
    print("  python scripts/analytics/compute_waterfall_segmented.py --backfill")
    print()

except Exception as e:
    print(f"✗ Migration failed: {e}")
    print()
    print("If psycopg2 is not installed, install it:")
    print("  pip install psycopg2-binary")
    exit(1)
