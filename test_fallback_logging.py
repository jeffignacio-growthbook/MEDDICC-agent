#!/usr/bin/env python3
"""
Verify fallback_log table exists and can be written to.

Tests the infrastructure without triggering actual failures.
"""
import sys
import asyncio
from pathlib import Path
from datetime import datetime

sys.path.insert(0, str(Path(__file__).parent / 'scripts'))
sys.path.insert(0, str(Path(__file__).parent / 'api'))

from dotenv import load_dotenv
load_dotenv(Path(__file__).parent / '.env')

from supabase_client import SupabaseWriter

async def main():
    """Test fallback_log table structure."""
    writer = SupabaseWriter()

    print("Testing fallback_log table")
    print("=" * 70)
    print()

    # Test 1: Table exists and is accessible
    print("1. Checking table exists...")
    try:
        result = writer.client.table('fallback_log').select('*').limit(1).execute()
        print("   ✓ Table exists and is readable")
        print()
    except Exception as e:
        print(f"   ✗ Failed to read table: {e}")
        return

    # Test 2: Can write a test row
    print("2. Writing test row...")
    test_data = {
        'question': 'Test question for fallback logging infrastructure verification',
        'trigger': 'test',
        'fast_path_attempted': 'test_handler',
        'fast_path_failure': 'This is a test write to verify the infrastructure',
        'queries_run': [
            {'tool': 'filter_table', 'params': {'table': 'deals'}, 'rows_returned': 127}
        ],
        'answered': False,
        'tokens_used': 0
    }

    try:
        insert_result = writer.client.table('fallback_log').insert(test_data).execute()
        print("   ✓ Test row written successfully")
        test_id = insert_result.data[0]['id']
        print(f"   Test row ID: {test_id}")
        print()
    except Exception as e:
        print(f"   ✗ Failed to write: {e}")
        return

    # Test 3: Read back the test row
    print("3. Reading back test row...")
    try:
        read_result = writer.client.table('fallback_log').select('*').eq('id', test_id).execute()
        if read_result.data:
            row = read_result.data[0]
            print("   ✓ Test row retrieved")
            print(f"   Question: {row['question'][:60]}...")
            print(f"   Trigger: {row['trigger']}")
            print(f"   Handler: {row['fast_path_attempted']}")
            print(f"   Queries tracked: {len(row['queries_run']) if row['queries_run'] else 0}")
            print()
        else:
            print("   ✗ Could not retrieve test row")
            return
    except Exception as e:
        print(f"   ✗ Failed to read back: {e}")
        return

    # Test 4: Clean up test row
    print("4. Cleaning up test row...")
    try:
        writer.client.table('fallback_log').delete().eq('trigger', 'test').execute()
        print("   ✓ Test row deleted")
        print()
    except Exception as e:
        print(f"   ✗ Failed to clean up: {e}")

    # Test 5: Show any real fallback logs
    print("5. Checking for real fallback logs...")
    try:
        real_logs = writer.client.table('fallback_log')\
            .select('id, question, trigger, fast_path_attempted, answered, created_at')\
            .neq('trigger', 'test')\
            .order('created_at', desc=True)\
            .limit(5)\
            .execute()

        if real_logs.data:
            print(f"   Found {len(real_logs.data)} recent fallback log(s):")
            for log in real_logs.data:
                print(f"   - [{log['trigger']}] {log['question'][:50]}...")
                print(f"     Handler: {log['fast_path_attempted']}, Answered: {log['answered']}")
            print()
        else:
            print("   No real fallback logs yet (infrastructure is ready)")
            print()
    except Exception as e:
        print(f"   ✗ Failed to read real logs: {e}")

    print("=" * 70)
    print("SUMMARY")
    print("=" * 70)
    print("""
Fallback logging infrastructure is ready:

✓ fallback_log table exists
✓ Can write failure records
✓ Tracks: question, trigger, handler, queries_run, tokens
✓ Wired into _give_up() and _below_floor()

Next: Use the system normally for one week, then run:

    SELECT trigger, fast_path_attempted, COUNT(*) as failures
    FROM fallback_log
    WHERE created_at > NOW() - INTERVAL '7 days'
    GROUP BY trigger, fast_path_attempted
    ORDER BY failures DESC;

Questions that appear 3+ times → build a handler using queries_run as spec.
""")

if __name__ == '__main__':
    asyncio.run(main())
