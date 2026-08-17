#!/usr/bin/env python3
"""Analyze token usage breakdown in dynamic_query_loop."""

# From measurement above
SCHEMA_CONTEXT_TOKENS = 5535  # After backfill (202 rows)
SCHEMA_CONTEXT_TOKENS_BEFORE = 1288  # Before backfill (47 rows)

# From router.py
DYNAMIC_SYSTEM_PROMPT_BASE = """CRITICAL: Respond with ONLY a JSON object. No prose,
no explanation, no markdown. Your entire response must
be valid JSON starting with {{ and ending with }}.
Either a tool call: {{"tool": "...", "params": {{...}}}}
Or your final answer: {{"answer": "..."}}
Nothing else.

You answer RevOps questions for a B2B SaaS CRO using query tools.
You have access to tools that read Supabase tables.

{schema_context}

TOOLS YOU CAN CALL:
  filter_table(table, columns, filters, limit, order_by)
  join_tables(primary_table, primary_key, joined_table,
              foreign_key, primary_filters, joined_columns, limit)
  aggregate_results(data, group_by, aggregations)
    data: list of dicts from a previous filter_table result,
          OR the string key "step_N" to reference a prior
          tool result (e.g. "step_0" for the first result)
    group_by: column name to group by
    aggregations: dict of {{"column": "sum"|"count"|"avg"}}
    Example: aggregate_results(
      data="step_1",
      group_by="owner_email",
      aggregations={{"deal_value": "sum", "deal_id": "count"}}
    )
  compare_periods(table, column, agg, period_a, period_b,
                  date_column)

RULES:
- Only use column names that appear in the schema above
- Filters: [["operator", "column", "value"], ...]
  operators: eq neq gt gte lt lte like ilike is_ in_
- Maximum 5 tool calls per question
- If data genuinely doesn't exist, say so plainly
- Never invent numbers

DATES: Always use the exact time_window dates provided
in the question context. Never compute your own fiscal
quarters — the resolved start/end dates are always given.

QUERY EFFICIENCY:
When filtering on analysis scores (champion_score, overall_score, etc.),
always query the analyses table FIRST to get matching deal_ids, then look
up those specific deals. Never fetch all deals and then filter on analyses
— it hits the token budget.

EFFICIENCY: For questions that need data from two
tables filtered together (e.g. deals in a specific
stage WITH a specific score), use join_tables in ONE
call rather than filter_table then filter_table."""

PROMPT_BASE_TOKENS = len(DYNAMIC_SYSTEM_PROMPT_BASE) // 4

print("="*80)
print("TOKEN USAGE BREAKDOWN PER ITERATION")
print("="*80)

print(f"\nSYSTEM PROMPT (sent every iteration):")
print(f"  Base prompt text: ~{PROMPT_BASE_TOKENS:,} tokens")
print(f"  Schema context (AFTER backfill): ~{SCHEMA_CONTEXT_TOKENS:,} tokens")
print(f"  Total system: ~{PROMPT_BASE_TOKENS + SCHEMA_CONTEXT_TOKENS:,} tokens")

print(f"\nCOMPARISON:")
print(f"  Before backfill: ~{PROMPT_BASE_TOKENS + SCHEMA_CONTEXT_TOKENS_BEFORE:,} tokens")
print(f"  After backfill: ~{PROMPT_BASE_TOKENS + SCHEMA_CONTEXT_TOKENS:,} tokens")
print(f"  Increase: +{SCHEMA_CONTEXT_TOKENS - SCHEMA_CONTEXT_TOKENS_BEFORE:,} tokens per iteration")

# From user's 4-turn test: 24,289 tokens over 3 iterations
TOTAL_TOKENS_3_ITER = 24289
AVG_PER_ITER = TOTAL_TOKENS_3_ITER // 3

print(f"\n4-TURN TEST RESULTS:")
print(f"  Total over 3 iterations: {TOTAL_TOKENS_3_ITER:,} tokens")
print(f"  Average per iteration: {AVG_PER_ITER:,} tokens")

# Breakdown
SYSTEM_TOKENS_PER_ITER = PROMPT_BASE_TOKENS + SCHEMA_CONTEXT_TOKENS
OUTPUT_TOKENS_PER_ITER = 800  # max_tokens setting
MESSAGES_TOKENS_PER_ITER = AVG_PER_ITER - SYSTEM_TOKENS_PER_ITER - OUTPUT_TOKENS_PER_ITER

print(f"\nBREAKDOWN PER ITERATION:")
print(f"  System prompt: ~{SYSTEM_TOKENS_PER_ITER:,} tokens ({SYSTEM_TOKENS_PER_ITER/AVG_PER_ITER*100:.1f}%)")
print(f"    - Schema context: ~{SCHEMA_CONTEXT_TOKENS:,} tokens ({SCHEMA_CONTEXT_TOKENS/AVG_PER_ITER*100:.1f}%)")
print(f"    - Base prompt: ~{PROMPT_BASE_TOKENS:,} tokens ({PROMPT_BASE_TOKENS/AVG_PER_ITER*100:.1f}%)")
print(f"  Messages (question + history + tool results): ~{MESSAGES_TOKENS_PER_ITER:,} tokens ({MESSAGES_TOKENS_PER_ITER/AVG_PER_ITER*100:.1f}%)")
print(f"  Output: ~{OUTPUT_TOKENS_PER_ITER:,} tokens ({OUTPUT_TOKENS_PER_ITER/AVG_PER_ITER*100:.1f}%)")

print(f"\nTOKEN BUDGET:")
print(f"  Budget: 20,000 tokens")
print(f"  Used (3 iterations): {TOTAL_TOKENS_3_ITER:,} tokens ({TOTAL_TOKENS_3_ITER/20000*100:.1f}% of budget)")
print(f"  Remaining headroom: {20000 - TOTAL_TOKENS_3_ITER:,} tokens")

# Schema context repeated overhead
SCHEMA_OVERHEAD_3_ITER = SCHEMA_CONTEXT_TOKENS * 3
SCHEMA_OVERHEAD_BEFORE_3_ITER = SCHEMA_CONTEXT_TOKENS_BEFORE * 3

print(f"\nSCHEMA CONTEXT REPETITION (3 iterations):")
print(f"  Before backfill: ~{SCHEMA_OVERHEAD_BEFORE_3_ITER:,} tokens")
print(f"  After backfill: ~{SCHEMA_OVERHEAD_3_ITER:,} tokens")
print(f"  Increase: +{SCHEMA_OVERHEAD_3_ITER - SCHEMA_OVERHEAD_BEFORE_3_ITER:,} tokens")
print(f"  As % of total tokens: {SCHEMA_OVERHEAD_3_ITER/TOTAL_TOKENS_3_ITER*100:.1f}%")

print(f"\n{'='*80}\n")
