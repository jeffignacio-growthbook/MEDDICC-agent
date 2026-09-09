#!/usr/bin/env python3
"""
Pull full details of Sept 6 "silent success" - query completed with
answered=True despite empty aggregation. What did the user receive?
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
print("SEPT 6 SILENT FAILURE INVESTIGATION")
print("=" * 70)
print()

# Get the Sept 6 query that succeeded despite empty aggregation
result = sb.table('fallback_log') \
    .select('*') \
    .eq('answered', True) \
    .gte('created_at', '2026-09-06T00:00:00') \
    .lte('created_at', '2026-09-06T23:59:59') \
    .order('created_at', desc=True) \
    .execute()

print(f"Found {len(result.data)} queries on Sept 6 with answered=True")
print()

# Find the one with aggregate_results returning 0 rows
target_query = None
for entry in result.data:
    queries = entry.get('queries_run', [])
    for q in queries:
        if q.get('tool') == 'aggregate_results' and q.get('rows_returned', 0) == 0:
            target_query = entry
            break
    if target_query:
        break

if not target_query:
    print("❌ Could not find Sept 6 query with 0-row aggregate_results and answered=True")
    print()
    print("Checking fallback_log for Sept 6 entries:")
    for entry in result.data:
        print(f"\n  Timestamp: {entry['created_at']}")
        print(f"  Question: {entry['question'][:80]}...")
        queries = entry.get('queries_run', [])
        if queries:
            agg_queries = [q for q in queries if q.get('tool') == 'aggregate_results']
            if agg_queries:
                print(f"  Has aggregate_results: {len(agg_queries)} calls")
                for aq in agg_queries:
                    print(f"    - Rows: {aq.get('rows_returned', 0)}")
    sys.exit(0)

print("FOUND: Sept 6 query with empty aggregation but answered=True")
print("=" * 70)
print()

print("TIMESTAMP:")
print(f"  {target_query['created_at']}")
print()

print("QUESTION:")
print(f"  {target_query['question']}")
print()

print("HANDLER:")
print(f"  Fast path attempted: {target_query.get('fast_path_attempted', 'N/A')}")
print(f"  Fast path failure: {target_query.get('fast_path_failure', 'N/A')}")
print()

print("QUERY EXECUTION:")
print("-" * 70)
queries = target_query.get('queries_run', [])
for i, q in enumerate(queries):
    print(f"{i}. {q['tool']}")
    print(f"   Rows returned: {q.get('rows_returned', 0)}")
    if q.get('params'):
        params = q['params']
        if 'table' in params:
            print(f"   Table: {params['table']}")
        if 'data' in params:
            data = params['data']
            if isinstance(data, list):
                print(f"   Data: {type(data).__name__} with {len(data)} items")
            else:
                print(f"   Data: {data}")
        if 'group_by' in params:
            print(f"   Group by: {params['group_by']}")
        if 'filters' in params and params['filters']:
            print(f"   Filters: {len(params['filters'])} filters")
            for f in params['filters'][:2]:  # Show first 2
                print(f"     - {f}")
    print()

print("ANSWER EXCERPT:")
print("-" * 70)
answer = target_query.get('answer_excerpt', 'N/A')
if answer and len(answer) > 0:
    print(answer)
else:
    print("(No answer excerpt stored)")
print()

print("TOKENS USED:")
print(f"  {target_query.get('tokens_used', 'N/A')}")
print()

print("=" * 70)
print("ANALYSIS")
print("=" * 70)
print()

# Analyze what happened
agg_call = None
for q in queries:
    if q.get('tool') == 'aggregate_results' and q.get('rows_returned', 0) == 0:
        agg_call = q
        break

if agg_call:
    print("Empty aggregation call found:")
    print(f"  Index: {queries.index(agg_call)}")
    print(f"  Parameters: {json.dumps(agg_call.get('params', {}), indent=4)}")
    print()

    # Check if there was a previous query with data
    prev_queries = queries[:queries.index(agg_call)]
    if prev_queries:
        print("Previous queries that had data:")
        for i, pq in enumerate(prev_queries):
            if pq.get('rows_returned', 0) > 0:
                print(f"  {i}. {pq['tool']}: {pq['rows_returned']} rows")
        print()
        print("⚠️  ISSUE: Data existed from previous query but aggregation got empty array")

    # Check if there were queries after the failed aggregation
    next_queries = queries[queries.index(agg_call)+1:]
    if next_queries:
        print()
        print("Queries after empty aggregation (recovery attempts):")
        for i, nq in enumerate(next_queries):
            print(f"  {i}. {nq['tool']}: {nq['rows_returned']} rows")
        print()
        print("✅ System recovered by running additional queries")
        print("❌ But answer may be incomplete or based on partial data")
    else:
        print()
        print("⚠️  No recovery queries after empty aggregation")
        print("Answer is based on data before aggregation (incomplete)")

print()
print("=" * 70)
print("USER IMPACT")
print("=" * 70)
print()

print("The user asked:")
print(f'  "{target_query["question"]}"')
print()
print("The system:")
print(f"  1. Retrieved {queries[0].get('rows_returned', 0)} rows from initial query")
print(f"  2. Tried to aggregate with empty data (0 rows)")
print(f"  3. {'Recovered with additional queries' if len(queries) > 2 else 'Returned answer with incomplete data'}")
print()

if answer and len(answer) > 0:
    print("The user received this answer:")
    print(f'  "{answer}"')
    print()
    print("⚠️  CONCERN: User had no indication that aggregation failed")
    print("    Answer may be incomplete or misleading")
else:
    print("⚠️  No answer excerpt available to verify what user received")

print()
print("RECOMMENDATION:")
print("  Review this specific answer for accuracy")
print("  If decision was made based on this answer, may need correction")
