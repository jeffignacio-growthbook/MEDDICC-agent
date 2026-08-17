#!/usr/bin/env python3
"""Measure token savings from hybrid schema approach."""

import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
os.environ['SUPABASE_URL'] = 'https://htgvkqycrwesdysustxd.supabase.co'
os.environ['SUPABASE_SERVICE_KEY'] = 'eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9.eyJpc3MiOiJzdXBhYmFzZSIsInJlZiI6Imh0Z3ZrcXljcndlc2R5c3VzdHhkIiwicm9sZSI6InNlcnZpY2Vfcm9sZSIsImlhdCI6MTc4NTg4NTI5MiwiZXhwIjoyMTAxNDYxMjkyfQ.aeJFp6OwucNplQClgNGcC6pFZu_zfVK7ATim_MC_Wn4'
os.environ['ANTHROPIC_API_KEY'] = os.getenv('ANTHROPIC_API_KEY', 'dummy')

from api.db import get_supabase
from api.schema_context import get_schema_context

def estimate_tokens(text):
    return len(text) // 4

sb = get_supabase()

print(f"{'='*80}")
print(f"HYBRID SCHEMA APPROACH - TOKEN SAVINGS")
print(f"{'='*80}\n")

# Full schema (legacy behavior - all tables with descriptions)
full_schema = get_schema_context(sb, tables_with_descriptions=None)
full_tokens = estimate_tokens(full_schema)

print(f"FULL SCHEMA (all 14 tables with descriptions):")
print(f"  Characters: {len(full_schema):,}")
print(f"  Estimated tokens: {full_tokens:,}")

# Hybrid schema - typical case: 3 relevant tables
typical_relevant_tables = ["deals", "analyses", "objections"]
hybrid_schema_3 = get_schema_context(sb, tables_with_descriptions=typical_relevant_tables)
hybrid_tokens_3 = estimate_tokens(hybrid_schema_3)

print(f"\nHYBRID SCHEMA (3 relevant tables with descriptions):")
print(f"  Tables with full descriptions: {typical_relevant_tables}")
print(f"  Characters: {len(hybrid_schema_3):,}")
print(f"  Estimated tokens: {hybrid_tokens_3:,}")
print(f"  Savings: {full_tokens - hybrid_tokens_3:,} tokens ({(full_tokens - hybrid_tokens_3)/full_tokens*100:.1f}%)")

# Hybrid schema - complex case: 5 relevant tables
complex_relevant_tables = ["deals", "analyses", "waterfall_weekly", "forecast_weekly", "rep_performance"]
hybrid_schema_5 = get_schema_context(sb, tables_with_descriptions=complex_relevant_tables)
hybrid_tokens_5 = estimate_tokens(hybrid_schema_5)

print(f"\nHYBRID SCHEMA (5 relevant tables with descriptions):")
print(f"  Tables with full descriptions: {complex_relevant_tables}")
print(f"  Characters: {len(hybrid_schema_5):,}")
print(f"  Estimated tokens: {hybrid_tokens_5:,}")
print(f"  Savings: {full_tokens - hybrid_tokens_5:,} tokens ({(full_tokens - hybrid_tokens_5)/full_tokens*100:.1f}%)")

# Minimal case: 1 table
minimal_relevant_tables = ["deals"]
hybrid_schema_1 = get_schema_context(sb, tables_with_descriptions=minimal_relevant_tables)
hybrid_tokens_1 = estimate_tokens(hybrid_schema_1)

print(f"\nHYBRID SCHEMA (1 relevant table with descriptions):")
print(f"  Tables with full descriptions: {minimal_relevant_tables}")
print(f"  Characters: {len(hybrid_schema_1):,}")
print(f"  Estimated tokens: {hybrid_tokens_1:,}")
print(f"  Savings: {full_tokens - hybrid_tokens_1:,} tokens ({(full_tokens - hybrid_tokens_1)/full_tokens*100:.1f}%)")

print(f"\n{'='*80}")
print(f"IMPACT ON 3-ITERATION QUERY")
print(f"{'='*80}\n")

# Calculate savings over 3 iterations
print(f"Full schema repeated 3x: {full_tokens * 3:,} tokens")
print(f"Hybrid (3 tables) repeated 3x: {hybrid_tokens_3 * 3:,} tokens")
print(f"Savings: {(full_tokens - hybrid_tokens_3) * 3:,} tokens")

# Previous 4-turn test: 24,289 tokens total
prev_total = 24289
prev_schema_overhead = full_tokens * 3
prev_non_schema = prev_total - prev_schema_overhead

projected_total_3_tables = prev_non_schema + (hybrid_tokens_3 * 3)
projected_total_5_tables = prev_non_schema + (hybrid_tokens_5 * 3)

print(f"\nProjected total for previous 4-turn test:")
print(f"  Before optimization: {prev_total:,} tokens (exceeded 20K budget)")
print(f"  With hybrid (3 tables): ~{projected_total_3_tables:,} tokens")
print(f"  With hybrid (5 tables): ~{projected_total_5_tables:,} tokens")
print(f"  Budget: 20,000 tokens")

if projected_total_3_tables <= 20000:
    print(f"\n✅ Hybrid (3 tables) fits within budget!")
    print(f"   Headroom: {20000 - projected_total_3_tables:,} tokens")
else:
    print(f"\n⚠️  Hybrid (3 tables) still exceeds budget by {projected_total_3_tables - 20000:,} tokens")

if projected_total_5_tables <= 20000:
    print(f"✅ Hybrid (5 tables) fits within budget!")
    print(f"   Headroom: {20000 - projected_total_5_tables:,} tokens")
else:
    print(f"⚠️  Hybrid (5 tables) still exceeds budget by {projected_total_5_tables - 20000:,} tokens")

print(f"\n{'='*80}")
print(f"SCHEMA SAMPLE - HYBRID (3 tables)")
print(f"{'='*80}")
print(hybrid_schema_3[:1000])
print("...")

print(f"\n{'='*80}\n")
