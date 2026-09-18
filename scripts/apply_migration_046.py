#!/usr/bin/env python3
"""
One-time migration applier for 046_add_incremental_arr.sql
Uses psycopg2 with proper password handling
"""
import os
import sys
from dotenv import load_dotenv

load_dotenv()

# Try importing psycopg2
try:
    import psycopg2
except ImportError:
    print("Installing psycopg2-binary...")
    os.system("pip install psycopg2-binary -q")
    import psycopg2

# Get database URL
db_url = os.getenv('SUPABASE_DB_URL')
if not db_url:
    print("ERROR: SUPABASE_DB_URL not set in .env")
    sys.exit(1)

# The URL has the password with a literal ! character, but psycopg2 needs it unescaped
# The format is: postgresql://user:pass@host:port/db
# Extract and parse manually
import re
pattern = r'postgresql://([^:]+):([^@]+)@([^:]+):(\d+)/(.+)'
match = re.match(pattern, db_url)

if not match:
    print(f"ERROR: Could not parse SUPABASE_DB_URL: {db_url}")
    sys.exit(1)

user, password, host, port, database = match.groups()

# The password might have escaped characters - handle the \! case
password = password.replace(r'\!', '!')

print(f"Connecting to {host}:{port}/{database} as {user}...")

try:
    conn = psycopg2.connect(
        host=host,
        port=int(port),
        database=database,
        user=user,
        password=password
    )

    cur = conn.cursor()

    # Execute migration
    print("Applying migration 046_add_incremental_arr.sql...")
    cur.execute('ALTER TABLE deals ADD COLUMN IF NOT EXISTS incremental_arr NUMERIC;')
    conn.commit()

    print('✓ Column added successfully')

    # Verify column exists
    cur.execute("""
        SELECT column_name
        FROM information_schema.columns
        WHERE table_name = 'deals'
        AND column_name = 'incremental_arr';
    """)
    result = cur.fetchone()

    if result:
        print(f'✓ Verified column exists: {result[0]}')
    else:
        print('WARNING: Column not found after creation')

    cur.close()
    conn.close()

    print('\n✓ Migration 046 applied successfully')

except psycopg2.OperationalError as e:
    print(f"ERROR: Database connection failed: {e}")
    print("\nPlease apply the migration manually via Supabase SQL Editor:")
    print("\n  ALTER TABLE deals ADD COLUMN IF NOT EXISTS incremental_arr NUMERIC;")
    print("\n  COMMENT ON COLUMN deals.incremental_arr IS")
    print("  'HubSpot calculated incremental ARR (calculation_equation field type).")
    print("  Used in NRR formula: (incremental_arr + renewal_revenue) for not-lost deals.")
    print("  NOT the same as new_arr + expansion_arr - this is HubSpot''s own calculation.';")
    sys.exit(1)
