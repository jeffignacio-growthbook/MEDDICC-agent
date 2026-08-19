#!/usr/bin/env python3
"""Check if specific deals exist in Supabase."""

import sys
import os
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))

# Set env vars
os.environ.setdefault('SUPABASE_URL', 'https://nrtapzrcwuksbupwxjbq.supabase.co')
os.environ.setdefault('SUPABASE_SERVICE_KEY', 'eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9.eyJpc3MiOiJzdXBhYmFzZSIsInJlZiI6Im5ydGFwenJjd3Vrc2J1cHd4amJxIiwicm9sZSI6InNlcnZpY2Vfcm9sZSIsImlhdCI6MTczMjY3MTgzMCwiZXhwIjoyMDQ4MjQ3ODMwfQ.lj_9PKhzRe3F9wbDdj-xk0pucBzHivxc7ARVVQnwKDg')

from supabase_client import SupabaseWriter

def main():
    writer = SupabaseWriter()
    supabase = writer.client

    deal_ids = ['57207848177', '55853063629']

    result = supabase.table('meddicc_analyses').select('*').in_('deal_id', deal_ids).execute()

    if result.data:
        print(f"Found {len(result.data)} records:")
        for row in result.data:
            print(f"\nDeal: {row.get('deal_name')} ({row.get('deal_id')})")
            print(f"  Company: {row.get('company_name')}")
            print(f"  ARR: ${row.get('arr')}")
            print(f"  Status: {row.get('status')}")
            print(f"  Root cause: {row.get('root_cause')}")
    else:
        print('No results found in Supabase')
        print('\nThese deals may not have been analyzed yet or may have different IDs.')

if __name__ == '__main__':
    main()
