#!/usr/bin/env python3
"""Check actual SDR table schema in Supabase."""

import os
import sys
from pathlib import Path
from dotenv import load_dotenv

# Load environment variables
env_path = Path(__file__).parent / '.env'
load_dotenv(env_path)

sys.path.insert(0, str(Path(__file__).parent))
from api.db import get_supabase

sb = get_supabase()

# Query information_schema for SDR tables
query = """
SELECT table_name, column_name, data_type
FROM information_schema.columns
WHERE table_name IN ('sdr_metrics', 'sdr_daily_summary', 'sdr_users')
ORDER BY table_name, ordinal_position;
"""

try:
    result = sb.rpc('execute_sql', {'query': query}).execute()

    current_table = None
    for row in result.data:
        table = row['table_name']
        if table != current_table:
            print(f"\n{table}:")
            current_table = table
        print(f"  {row['column_name']:30} {row['data_type']}")

except Exception as e:
    print(f"Error: {e}")
    print("\nFalling back to direct table inspection...")

    # Try direct queries instead
    for table in ['sdr_metrics', 'sdr_users']:
        try:
            result = sb.table(table).select('*').limit(1).execute()
            print(f"\n{table}:")
            if result.data:
                for col in result.data[0].keys():
                    print(f"  {col}")
            else:
                print("  (empty table)")
        except Exception as e2:
            print(f"  Error querying {table}: {e2}")
