#!/usr/bin/env python3
"""
Investigate why aggregate_results returned 0 rows in Sept 9 query.
Check if this is a systematic bug or a one-off LLM error.
"""
import os
import sys
from pathlib import Path
import json

REPO_ROOT = Path(__file__).parent
sys.path.insert(0, str(REPO_ROOT / 'scripts'))

from dotenv import load_dotenv
load_dotenv()

from supabase import create_client
SUPABASE_URL = os.getenv('SUPABASE_URL')
SUPABASE_KEY = os.getenv('SUPABASE_SERVICE_KEY')
sb = create_client(SUPABASE_URL, SUPABASE_KEY)

print("=" * 70)
print("AGGREGATE_RESULTS 0-ROW INVESTIGATION")
print("=" * 70)
print()

# Get all fallback_log entries with queries_run data
print("Searching all fallback_log entries (last 30 days)...")
print("-" * 70)

result = sb.table('fallback_log') \
    .select('*') \
    .gte('created_at', '2026-08-10') \
    .order('created_at', desc=True) \
    .execute()

print(f"Total entries: {len(result.data)}")
print()

# Find all queries that used aggregate_results
aggregate_queries = []
for entry in result.data:
    queries = entry.get('queries_run', [])
    for i, q in enumerate(queries):
        if q.get('tool') == 'aggregate_results':
            aggregate_queries.append({
                'timestamp': entry['created_at'],
                'question': entry['question'],
                'query_index': i,
                'rows_returned': q.get('rows_returned', 0),
                'params': q.get('params', {}),
                'answered': entry.get('answered', False),
                'all_queries': queries
            })

print(f"Found {len(aggregate_queries)} aggregate_results calls")
print()

# Separate by rows returned
zero_row_calls = [q for q in aggregate_queries if q['rows_returned'] == 0]
successful_calls = [q for q in aggregate_queries if q['rows_returned'] > 0]

print("=" * 70)
print("AGGREGATE_RESULTS CALLS SUMMARY")
print("=" * 70)
print(f"Total calls: {len(aggregate_queries)}")
print(f"  0 rows: {len(zero_row_calls)} ({100*len(zero_row_calls)/len(aggregate_queries) if aggregate_queries else 0:.1f}%)")
print(f"  >0 rows: {len(successful_calls)} ({100*len(successful_calls)/len(aggregate_queries) if aggregate_queries else 0:.1f}%)")
print()

if zero_row_calls:
    print("=" * 70)
    print("ZERO-ROW CALLS (POTENTIAL BUGS)")
    print("=" * 70)

    for i, call in enumerate(zero_row_calls, 1):
        print(f"\n{i}. Timestamp: {call['timestamp']}")
        print(f"   Question: {call['question'][:80]}...")
        print(f"   Answered: {call['answered']}")
        print(f"   Query index: {call['query_index']} (iteration in loop)")

        params = call['params']
        print(f"\n   Parameters passed:")
        print(f"     data: {params.get('data', 'N/A')}")
        print(f"     group_by: {params.get('group_by', 'N/A')}")
        print(f"     aggregations: {params.get('aggregations', 'N/A')}")

        # Check what the previous query returned
        print(f"\n   Previous queries in this loop:")
        for j, prev_q in enumerate(call['all_queries'][:call['query_index']]):
            print(f"     {j}. {prev_q['tool']}: {prev_q.get('rows_returned', 0)} rows")
            if prev_q.get('params', {}).get('table'):
                print(f"        table={prev_q['params']['table']}")

        print()
        print("-" * 70)
else:
    print("✅ NO ZERO-ROW AGGREGATE_RESULTS CALLS FOUND")
    print()
    print("This suggests the Sept 9 failure might have been:")
    print("  1. A transient state (empty accumulated_data)")
    print("  2. LLM passed wrong reference (e.g., 'step_1' when only step_0 existed)")
    print("  3. Not actually logged (error occurred before queries_run tracking)")

if successful_calls:
    print()
    print("=" * 70)
    print("SUCCESSFUL AGGREGATE_RESULTS CALLS (SAMPLE)")
    print("=" * 70)

    for i, call in enumerate(successful_calls[:3], 1):
        print(f"\n{i}. Timestamp: {call['timestamp']}")
        print(f"   Question: {call['question'][:80]}...")
        print(f"   Rows returned: {call['rows_returned']}")

        params = call['params']
        print(f"   Parameters:")
        print(f"     data: {params.get('data', 'N/A')}")
        print(f"     group_by: {params.get('group_by', 'N/A')}")
        print(f"     aggregations: {params.get('aggregations', 'N/A')}")
        print("-" * 70)

print()
print("=" * 70)
print("ANALYSIS")
print("=" * 70)

if zero_row_calls:
    print("\n⚠️  CASE 1 CONFIRMED: Real bug or systematic LLM error")
    print(f"    {len(zero_row_calls)} aggregate_results calls returned 0 rows")
    print()
    print("    Common patterns to check:")
    print("    - Wrong data reference (e.g., 'step_1' when only step_0 exists)")
    print("    - group_by column not in data")
    print("    - aggregations column not in data")
    print("    - Bug in aggregate_results logic")
    print()
    print("    ACTION REQUIRED:")
    print("    1. Review parameters of 0-row calls above")
    print("    2. Test aggregate_results with same parameters")
    print("    3. Fix bug or improve LLM parameter generation")
else:
    print("\n✅ CASE 2: Ambiguous or incorrect LLM request")
    print("    No other 0-row aggregate_results calls in last 30 days")
    print("    Sept 9 failure likely one-off LLM mistake")
    print()
    print("    ACTION: Document as transient, no code fix needed")

print()
print("=" * 70)
print("RECOMMENDATION")
print("=" * 70)

if zero_row_calls:
    print("""
URGENT: This is a silent failure pattern that could be affecting
other queries. Even queries that "succeed" might have incorrect
empty aggregations.

Next steps:
1. Review each 0-row call's parameters
2. Reproduce the issue with test data
3. Fix the root cause (likely data reference or column mismatch)
4. Add validation to aggregate_results to catch this early
   (e.g., log warning if data reference returns empty)
""")
else:
    print("""
LIKELY ONE-OFF: No pattern of 0-row aggregate_results calls.

The Sept 9 failure was likely:
- LLM passed wrong step reference
- Timing issue with accumulated_data
- Not a systematic bug

Mark as low priority, monitor for recurrence.
""")
