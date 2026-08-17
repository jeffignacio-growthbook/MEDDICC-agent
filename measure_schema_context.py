#!/usr/bin/env python3
"""Measure schema context size before vs after backfill."""

import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
os.environ['SUPABASE_URL'] = 'https://htgvkqycrwesdysustxd.supabase.co'
os.environ['SUPABASE_SERVICE_KEY'] = 'eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9.eyJpc3MiOiJzdXBhYmFzZSIsInJlZiI6Imh0Z3ZrcXljcndlc2R5c3VzdHhkIiwicm9sZSI6InNlcnZpY2Vfcm9sZSIsImlhdCI6MTc4NTg4NTI5MiwiZXhwIjoyMTAxNDYxMjkyfQ.aeJFp6OwucNplQClgNGcC6pFZu_zfVK7ATim_MC_Wn4'

from api.db import get_supabase
from api.schema_context import get_schema_context, invalidate_cache

# Rough token estimator (1 token ≈ 4 chars for English text)
def estimate_tokens(text):
    return len(text) // 4

sb = get_supabase()

# Get current row count
result = sb.table('data_dictionary')\
    .select('*', count='exact')\
    .eq('is_queryable', True)\
    .execute()

current_rows = result.count
print(f"{'='*80}")
print(f"SCHEMA CONTEXT SIZE ANALYSIS")
print(f"{'='*80}\n")
print(f"Current data_dictionary rows (is_queryable=true): {current_rows}")

# Get current schema context
invalidate_cache()
current_context = get_schema_context(sb)
current_chars = len(current_context)
current_tokens = estimate_tokens(current_context)

print(f"\nCURRENT SCHEMA CONTEXT ({current_rows} rows):")
print(f"  Characters: {current_chars:,}")
print(f"  Estimated tokens: {current_tokens:,}")

# Estimate pre-backfill size (47 rows)
# The backfill added 152 rows, so before was 202 - 152 = 50 rows (close to 47)
# Each row contributes approximately: column line + description
# Average line length from current context

lines = current_context.split('\n')
# Column lines look like: "  column_name (type): description"
column_lines = [l for l in lines if l.startswith('  ') and not l.startswith('    ') and '(' in l and ':' in l]
avg_column_line_len = sum(len(l) for l in column_lines) / len(column_lines) if column_lines else 100

print(f"\nColumn line stats:")
print(f"  Total column lines: {len(column_lines)}")
print(f"  Avg chars per column: {avg_column_line_len:.1f}")

# Estimate pre-backfill context
# 47 rows vs 202 rows = 23% of current size
pre_backfill_ratio = 47 / current_rows
pre_backfill_chars = int(current_chars * pre_backfill_ratio)
pre_backfill_tokens = pre_backfill_chars // 4  # Direct calculation instead of calling estimate_tokens

print(f"\nESTIMATED PRE-BACKFILL ({47} rows):")
print(f"  Characters: {pre_backfill_chars:,}")
print(f"  Estimated tokens: {pre_backfill_tokens:,}")

# Calculate increase
char_increase = current_chars - pre_backfill_chars
token_increase = current_tokens - pre_backfill_tokens

print(f"\nINCREASE FROM BACKFILL:")
print(f"  Characters: +{char_increase:,} ({char_increase/pre_backfill_chars*100:.1f}% increase)")
print(f"  Estimated tokens: +{token_increase:,} ({token_increase/pre_backfill_tokens*100:.1f}% increase)")

# Impact on dynamic_query_loop (repeated on every iteration)
print(f"\n{'='*80}")
print(f"IMPACT ON DYNAMIC_QUERY_LOOP")
print(f"{'='*80}")
print(f"\nSchema context is sent on EVERY iteration of the loop.")
print(f"\nPer-iteration overhead:")
print(f"  Before: ~{pre_backfill_tokens:,} tokens")
print(f"  After:  ~{current_tokens:,} tokens")
print(f"  Delta:  +{token_increase:,} tokens per iteration")

print(f"\nOver 3 iterations:")
print(f"  Before: ~{pre_backfill_tokens * 3:,} tokens")
print(f"  After:  ~{current_tokens * 3:,} tokens")
print(f"  Delta:  +{token_increase * 3:,} tokens")

# Sample of context to show density
print(f"\n{'='*80}")
print(f"SCHEMA CONTEXT SAMPLE (first 800 chars)")
print(f"{'='*80}")
print(current_context[:800])
print("...")

# Breakdown by table
print(f"\n{'='*80}")
print(f"BREAKDOWN BY TABLE")
print(f"{'='*80}\n")

# Count columns per table
result_all = sb.table('data_dictionary')\
    .select('supabase_table, supabase_column')\
    .eq('is_queryable', True)\
    .execute()

by_table = {}
for row in result_all.data:
    table = row['supabase_table']
    by_table.setdefault(table, 0)
    by_table[table] += 1

for table in sorted(by_table.keys()):
    count = by_table[table]
    # Estimate chars per table: header + columns
    est_chars = 50 + (count * avg_column_line_len)  # rough
    est_tokens = int(est_chars) // 4
    print(f"  {table:30s} {count:3d} columns  ~{int(est_chars):5,} chars  ~{int(est_tokens):4,} tokens")

print(f"\n{'='*80}\n")
