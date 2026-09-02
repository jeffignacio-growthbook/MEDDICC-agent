#!/usr/bin/env python3
"""Apply migration 048 using Python Supabase client."""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent / 'scripts'))
sys.path.insert(0, str(Path(__file__).parent / 'api'))

from dotenv import load_dotenv
load_dotenv(Path(__file__).parent / '.env')

from supabase_client import SupabaseWriter

def main():
    """Apply migration 048 to create fallback_log table."""
    writer = SupabaseWriter()

    # Read the migration SQL
    migration_path = Path(__file__).parent / 'scripts' / 'migrations' / '048_add_fallback_log.sql'
    migration_sql = migration_path.read_text()

    print("Applying migration 048: fallback_log table")
    print("=" * 70)

    try:
        # Execute the SQL using rpc or direct query
        # Supabase Python client doesn't expose raw SQL directly,
        # but we can use the PostgREST client's raw query capability
        result = writer.client.rpc('exec_sql', {'query': migration_sql}).execute()
        print("✓ Migration applied successfully")
        print(result)
    except Exception as e:
        # If RPC doesn't work, try creating the table directly via table operations
        print(f"RPC approach failed: {e}")
        print("\nTrying direct SQL execution via postgrest...")

        # Alternative: use the underlying postgrest client
        from supabase import Client
        import os

        url = os.getenv('SUPABASE_URL')
        key = os.getenv('SUPABASE_KEY')

        # Execute raw SQL using the REST API
        import requests
        headers = {
            'apikey': key,
            'Authorization': f'Bearer {key}',
            'Content-Type': 'application/json'
        }

        # Supabase doesn't expose raw SQL via REST API, so we need to use the connection string
        print("\nFallback: Using psycopg2 direct connection...")
        import psycopg2

        conn_string = os.getenv('SUPABASE_DB_URL') or os.getenv('DATABASE_URL')
        if not conn_string:
            print("ERROR: SUPABASE_DB_URL or DATABASE_URL not found in .env")
            print("Need connection string for direct SQL execution")
            sys.exit(1)

        # Remove quotes if present and unescape the password
        conn_string = conn_string.strip('"').replace('\\!', '!')

        conn = psycopg2.connect(conn_string)
        cur = conn.cursor()
        cur.execute(migration_sql)
        conn.commit()
        cur.close()
        conn.close()

        print("✓ Migration applied via direct connection")

if __name__ == '__main__':
    main()
