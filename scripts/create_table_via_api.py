#!/usr/bin/env python3
"""Create diagnostic_escalations table via Supabase REST API."""

import os
import sys
import requests
from pathlib import Path
from dotenv import load_dotenv

load_dotenv()

SUPABASE_URL = os.environ.get('SUPABASE_URL')
SUPABASE_KEY = os.environ.get('SUPABASE_SERVICE_KEY')

if not SUPABASE_URL or not SUPABASE_KEY:
    print("ERROR: SUPABASE_URL and SUPABASE_SERVICE_KEY must be set")
    sys.exit(1)

# Read migration SQL
migration_file = Path(__file__).parent / "migrations" / "014_add_diagnostic_escalations.sql"
with open(migration_file, 'r') as f:
    sql_content = f.read()

print("="*80)
print("Creating diagnostic_escalations table via Supabase API")
print("="*80)
print()

# Supabase has a query endpoint we can use
# https://supabase.com/docs/guides/database/api/using-custom-schemas

# Try using the /rest/v1/rpc endpoint
url = f"{SUPABASE_URL}/rest/v1/rpc/exec_sql"

headers = {
    "apikey": SUPABASE_KEY,
    "Authorization": f"Bearer {SUPABASE_KEY}",
    "Content-Type": "application/json"
}

# Try to call a custom SQL function (if it exists)
response = requests.post(
    url,
    headers=headers,
    json={"sql": sql_content}
)

if response.status_code == 200:
    print("✓ Table created successfully via RPC")
    sys.exit(0)
elif "does not exist" in response.text:
    print("RPC function not available - trying alternative method")
else:
    print(f"API call failed: {response.status_code}")
    print(f"Response: {response.text[:200]}")

print()
print("Alternative: Using HTTP POST to create table metadata")
print()

# Try creating via the table metadata endpoint
# Actually, let's just insert a dummy row to create the table structure
# No, that won't work either.

# The real solution: Use psql directly if available
print("Checking for psql...")
import subprocess

try:
    # Check if psql is available
    result = subprocess.run(["which", "psql"], capture_output=True, text=True)

    if result.returncode == 0:
        print(f"✓ Found psql at: {result.stdout.strip()}")
        print()

        # Construct connection string
        # Supabase connection format
        project_ref = SUPABASE_URL.replace("https://", "").replace(".supabase.co", "")

        # Try to get DB password from environment or use service key
        db_password = os.environ.get('SUPABASE_DB_PASSWORD', SUPABASE_KEY)

        # Supabase direct connection
        conn_string = f"postgresql://postgres:{db_password}@db.{project_ref}.supabase.co:5432/postgres"

        print("Executing SQL via psql...")

        # Run migration
        with open(migration_file, 'r') as f:
            result = subprocess.run(
                ["psql", conn_string],
                stdin=f,
                capture_output=True,
                text=True
            )

        if result.returncode == 0:
            print("✓ Table created successfully")
            print()
            if result.stdout:
                print("Output:")
                print(result.stdout)
        else:
            print(f"✗ psql failed: {result.stderr}")
            sys.exit(1)
    else:
        print("✗ psql not found")
        print()
        print("Please install PostgreSQL client:")
        print("  brew install postgresql  # macOS")
        print("  apt-get install postgresql-client  # Linux")
        sys.exit(1)

except Exception as e:
    print(f"✗ Error: {e}")
    sys.exit(1)
