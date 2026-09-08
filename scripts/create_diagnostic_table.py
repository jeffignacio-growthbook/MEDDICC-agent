#!/usr/bin/env python3
"""Create diagnostic_escalations table using direct PostgreSQL connection."""

import os
import sys
from pathlib import Path
from dotenv import load_dotenv

load_dotenv()

# Try psycopg2 first
try:
    import psycopg2
    from psycopg2 import sql
except ImportError:
    print("psycopg2 not installed. Installing...")
    import subprocess
    subprocess.check_call([sys.executable, "-m", "pip", "install", "psycopg2-binary"])
    import psycopg2
    from psycopg2 import sql

# Construct PostgreSQL connection string from Supabase URL
supabase_url = os.environ.get('SUPABASE_URL')
supabase_key = os.environ.get('SUPABASE_SERVICE_KEY')

if not supabase_url:
    print("ERROR: SUPABASE_URL not set")
    sys.exit(1)

# Supabase URL format: https://PROJECT_ID.supabase.co
# PostgreSQL connection: postgresql://postgres:[PASSWORD]@db.PROJECT_ID.supabase.co:5432/postgres
project_id = supabase_url.replace('https://', '').replace('.supabase.co', '')

# For direct connection, we need the database password
db_password = os.environ.get('SUPABASE_DB_PASSWORD') or supabase_key

postgres_url = f"postgresql://postgres.{project_id}:{db_password}@aws-0-us-west-1.pooler.supabase.com:6543/postgres"

print("="*80)
print("Creating diagnostic_escalations table")
print("="*80)
print()

# Read migration SQL
migration_file = Path(__file__).parent / "migrations" / "014_add_diagnostic_escalations.sql"
with open(migration_file, 'r') as f:
    sql_content = f.read()

print("Connecting to Supabase PostgreSQL...")

try:
    # Connect to PostgreSQL
    conn = psycopg2.connect(postgres_url)
    conn.autocommit = True
    cur = conn.cursor()

    print("✓ Connected")
    print()

    # Execute the SQL
    print("Running migration...")
    cur.execute(sql_content)

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
    print("="*80)
    print("SUCCESS: Table ready for use")
    print("="*80)

except Exception as e:
    print(f"✗ Error: {e}")
    print()
    print("This might be due to connection string format.")
    print("Alternative: Run the SQL manually in Supabase SQL Editor")
    print()
    print("SQL to run:")
    print("─"*80)
    print(sql_content)
    print("─"*80)
    sys.exit(1)
