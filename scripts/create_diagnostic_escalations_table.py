#!/usr/bin/env python3
"""Create diagnostic_escalations table using psycopg2."""

import os
import sys
from pathlib import Path
from dotenv import load_dotenv

# Load environment variables
load_dotenv()

# Try to import psycopg2
try:
    import psycopg2
except ImportError:
    print("Installing psycopg2-binary...")
    import subprocess
    subprocess.check_call([sys.executable, "-m", "pip", "install", "psycopg2-binary"])
    import psycopg2

# Get database URL
db_url = os.getenv('SUPABASE_DB_URL')
if not db_url:
    print("ERROR: SUPABASE_DB_URL not set in .env")
    sys.exit(1)

print("=" * 80)
print("Creating diagnostic_escalations table")
print("=" * 80)
print()

# Read migration SQL
migration_file = Path(__file__).parent / "migrations" / "014_add_diagnostic_escalations.sql"
sql = migration_file.read_text()

print("Connecting to Supabase PostgreSQL...")

try:
    # Connect
    conn = psycopg2.connect(db_url)
    conn.autocommit = True
    cur = conn.cursor()

    print("✓ Connected")
    print()

    # Execute migration
    print("Running migration...")
    cur.execute(sql)
    print("✓ Migration executed")
    print()

    # Verify table exists
    cur.execute("""
        SELECT COUNT(*)
        FROM information_schema.tables
        WHERE table_name = 'diagnostic_escalations'
    """)

    count = cur.fetchone()[0]

    if count > 0:
        print("✓ Table diagnostic_escalations created successfully")

        # Get column count
        cur.execute("""
            SELECT COUNT(*)
            FROM information_schema.columns
            WHERE table_name = 'diagnostic_escalations'
        """)
        col_count = cur.fetchone()[0]
        print(f"  Columns: {col_count}")

        # Get index count
        cur.execute("""
            SELECT COUNT(*)
            FROM pg_indexes
            WHERE tablename = 'diagnostic_escalations'
        """)
        idx_count = cur.fetchone()[0]
        print(f"  Indexes: {idx_count}")

    else:
        print("✗ Table not found after migration")
        sys.exit(1)

    cur.close()
    conn.close()

    print()
    print("=" * 80)
    print("SUCCESS: Table ready for use")
    print("=" * 80)

except Exception as e:
    print(f"✗ Error: {e}")
    sys.exit(1)
