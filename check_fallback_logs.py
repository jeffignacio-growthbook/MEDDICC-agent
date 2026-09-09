#!/usr/bin/env python3
"""
Check fallback_log table for Sept 9 budget exhaustion.
Find the EMEA pipeline question and understand what happened.
"""
import os
import sys
from pathlib import Path
from datetime import datetime

REPO_ROOT = Path(__file__).parent
sys.path.insert(0, str(REPO_ROOT / 'scripts'))

from dotenv import load_dotenv
load_dotenv()

from supabase import create_client
SUPABASE_URL = os.getenv('SUPABASE_URL')
SUPABASE_KEY = os.getenv('SUPABASE_SERVICE_KEY')
sb = create_client(SUPABASE_URL, SUPABASE_KEY)

print("=" * 70)
print("FALLBACK LOG ANALYSIS - Sept 9 Budget Error")
print("=" * 70)
print()

# Get recent budget_exhausted entries
print("Budget exhausted entries (last 7 days):")
print("-" * 70)

result = sb.table('fallback_log') \
    .select('*') \
    .eq('trigger', 'budget_exhausted') \
    .gte('created_at', '2026-09-02') \
    .order('created_at', desc=True) \
    .execute()

if not result.data:
    print("No budget_exhausted entries found in last 7 days")
    print()
    print("Checking for ANY fallback entries on Sept 9...")

    result = sb.table('fallback_log') \
        .select('*') \
        .gte('created_at', '2026-09-09T00:00:00') \
        .lte('created_at', '2026-09-09T23:59:59') \
        .order('created_at', desc=True) \
        .execute()

    if not result.data:
        print("No fallback entries at all on Sept 9")
        print()
        print("Checking table structure...")
        sample = sb.table('fallback_log').select('*').limit(1).execute()
        if sample.data:
            print("Sample row columns:", list(sample.data[0].keys()))
    else:
        print(f"Found {len(result.data)} fallback entries on Sept 9:")
        for row in result.data:
            print(f"\n  Created: {row['created_at']}")
            print(f"  Question: {row['question']}")
            print(f"  Trigger: {row['trigger']}")
            print(f"  Handler: {row.get('fast_path_attempted', 'N/A')}")
            print(f"  Answered: {row.get('answered', 'N/A')}")
            if row.get('tokens_used'):
                print(f"  Tokens: {row['tokens_used']}")
else:
    for row in result.data:
        print(f"\nTimestamp: {row['created_at']}")
        print(f"Question: {row['question']}")
        print(f"Handler: {row.get('fast_path_attempted', 'N/A')}")
        print(f"Failure: {row.get('fast_path_failure', 'N/A')}")
        print(f"Tokens used: {row.get('tokens_used', 'N/A')}")
        print(f"Answered: {row.get('answered', False)}")

        queries = row.get('queries_run', [])
        if queries:
            print(f"Queries run: {len(queries)} operations")
            for i, q in enumerate(queries):
                print(f"  {i+1}. {q.get('tool', 'unknown')}: {q.get('rows_returned', 0)} rows")
                if q.get('params'):
                    params = q['params']
                    if 'table' in params:
                        print(f"     table={params['table']}")
                    if 'filters' in params and params['filters']:
                        print(f"     filters={params['filters'][:2]}...")  # Show first 2 filters
        else:
            print("Queries run: none (exhausted before any tool calls)")

        print("-" * 70)

print()
print("=" * 70)
print("ANALYSIS")
print("=" * 70)

# Look specifically for EMEA pipeline questions
emea_questions = [r for r in result.data if 'EMEA' in r.get('question', '').upper()]

if emea_questions:
    print(f"\nFound {len(emea_questions)} EMEA-related questions:")
    for row in emea_questions:
        print(f"\n  Question: {row['question']}")
        print(f"  Tokens: {row.get('tokens_used', 'N/A')}")
        queries = row.get('queries_run', [])
        print(f"  Iterations completed: {len(queries)}")
        if queries:
            total_rows = sum(q.get('rows_returned', 0) for q in queries)
            print(f"  Total rows retrieved: {total_rows}")
else:
    print("\nNo EMEA-related questions found in budget_exhausted logs")

print()
print("REPRODUCIBILITY TEST RECOMMENDATION:")
print("  Retry the exact question in Slack:")
print('  "How has EMEA pipeline moved in the last 2 weeks"')
print()
print("  If it succeeds now → ONE-OFF (transient state)")
print("  If it fails again → REPRODUCIBLE (needs optimization)")
