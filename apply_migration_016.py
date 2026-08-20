#!/usr/bin/env python3
"""Apply migration 016 using direct PostgreSQL connection."""

import os
import psycopg2
from pathlib import Path

# Connection string comes from the environment — never hardcode a DB password
# in source; a committed credential stays live until rotated. Set
# SUPABASE_DB_URL (a postgresql:// connection string).
conn_string = os.environ["SUPABASE_DB_URL"]

# Read migration
migration_sql = Path('scripts/migrations/016_create_meetings_table.sql').read_text()

print("\n" + "="*80)
print("APPLYING MIGRATION 016: meetings table")
print("="*80)

try:
    # Connect to database
    conn = psycopg2.connect(conn_string)
    cur = conn.cursor()

    # Execute migration
    cur.execute(migration_sql)
    conn.commit()

    print("\n✓ Migration 016 applied successfully")

    # Verify table exists
    cur.execute("""
        SELECT column_name, data_type
        FROM information_schema.columns
        WHERE table_name = 'meetings'
        ORDER BY ordinal_position;
    """)

    columns = cur.fetchall()
    print(f"\n✓ meetings table created with {len(columns)} columns:")
    for col_name, col_type in columns:
        print(f"  - {col_name}: {col_type}")

    cur.close()
    conn.close()

except Exception as e:
    print(f"\n✗ Error: {e}")
    import traceback
    traceback.print_exc()

print("\n" + "="*80 + "\n")
