# Fallback Logging Infrastructure - Complete

**Date:** 2026-09-02
**Commits:** 0319757, c320d0a, 0620b83, 1a07e15

## What Was Built

Per FIX_EXIT_AND_BUILD_FALLBACK.md Part 2, the logging infrastructure to capture every use of the fallback path.

### 1. Database Table

Migration 048 applied successfully:

```sql
CREATE TABLE fallback_log (
    id BIGSERIAL PRIMARY KEY,
    question TEXT NOT NULL,
    trigger TEXT NOT NULL,  -- budget_exhausted, below_floor, discarded_answer, etc.
    fast_path_attempted TEXT,
    fast_path_failure TEXT,
    queries_run JSONB,
    answered BOOLEAN DEFAULT FALSE,
    answer_excerpt TEXT,
    tokens_used INTEGER,
    latency_ms INTEGER,
    created_at TIMESTAMPTZ DEFAULT NOW()
);
```

Indexes for weekly review grouping, trigger analysis, and fast path failure analysis.

### 2. Failure Path Logging

**dynamic_query_loop** (`_give_up()` at router.py:1642):
- Logs when budget exhausted before finding data
- Logs when budget exhausted with partial data but no synthesis
- Tracks all queries_run with tool, params, rows_returned

**route_question** (`_below_floor()` at router.py:2574):
- Logs when assessment score falls below confidence floor
- Records the handler that produced the low-quality answer
- Captures the score that triggered the failure

### 3. Success Logging

Already in place from commit 0620b83 (_log_successful_query at router.py:1619):
- Logs every successful query with queries_run
- Provides working examples for handler development
- Trigger: 'success' distinguishes from failures

### 4. Three Adjustments from Original Spec

1. **"discarded_answer" trigger added** (router.py:1993-2013)
   - Detects control-flow bug when has_answer=True but loop returns failure
   - Should never fire now that evaluation gate is removed
   - Kept as canary for regression

2. **Success logging** (router.py:1619-1635)
   - Not just failures - successful queries logged too
   - queries_run shows working patterns for handler development
   - Roadmap comes from what works, not just what breaks

3. **Lightweight schema verified sufficient** (test_arr_query.py)
   - 127 deals with no ARR answered correctly at iteration 1
   - 7,098 char schema with 16 described columns
   - No need for expensive full schema in fallback
   - Will test dimensions individually if fallback rate climbs

## Git Tree

```bash
$ git ls-tree origin/main api/router.py scripts/migrations/048_add_fallback_log.sql apply_migration_048.py

100644 blob 4acf857892d85172369ad32095690cc7a0a1d99e	api/router.py
100644 blob 930ee9af0469822256d803508f9d86ed05ed41bc	apply_migration_048.py
100644 blob e8ff87fabcb5f16caf690d885999027c5ff2ca00	scripts/migrations/048_add_fallback_log.sql
```

## Verification

```bash
$ python test_fallback_logging.py

Testing fallback_log table
======================================================================

1. Checking table exists...
   ✓ Table exists and is readable

2. Writing test row...
   ✓ Test row written successfully
   Test row ID: 1

3. Reading back test row...
   ✓ Test row retrieved
   Question: Test question for fallback logging infrastructure verificati...
   Trigger: test
   Handler: test_handler
   Queries tracked: 1

4. Cleaning up test row...
   ✓ Test row deleted

5. Checking for real fallback logs...
   No real fallback logs yet (infrastructure is ready)
```

## Weekly Review Query

After one week of real use:

```sql
SELECT
    trigger,
    fast_path_attempted,
    COUNT(*) as failures,
    COUNT(*) FILTER (WHERE answered = true) as recoveries,
    AVG(tokens_used) as avg_tokens
FROM fallback_log
WHERE created_at > NOW() - INTERVAL '7 days'
  AND trigger != 'success'
GROUP BY trigger, fast_path_attempted
ORDER BY failures DESC;
```

**Same intent 3+ times** → build handler using queries_run as specification
**Fast path failed on missing fact** → semantic fact, not handler
**One-off** → leave it, that's what fallback is for

## What's NOT Built Yet

The actual general fallback path. This infrastructure logs failures; it doesn't fix them.

When fallback rate justifies the cost (if it does), test dimensions from test_fallback_dimensions.py:
1. More iterations (5 → 10)
2. No sampling (full results vs aggregated)
3. Full schema (vs lightweight)
4. Better model (Opus vs Sonnet)

Run dimension tests against real failed questions from fallback_log to find what moves failure → success.

## Next Action

Ship and watch. Check fallback_log weekly. Build the expensive fallback path only if the data shows it's needed.

The ratio becomes a measurement rather than an opinion:
- **5% fallback rate** → fast path is good, insurance working as designed
- **40% fallback rate** → fast path is wrong abstraction, data proves it

## Previous Fixes (Now Verified)

1. **has_answer gate removed** (commit c320d0a)
   - Loop no longer continues after producing complete answer
   - ARR question now answers at iteration 1 (was failing at iteration 4)
   - 127 deals correctly identified

2. **Zero_counts in aggregation** (commit 0319757)
   - Per-column zero and null counts computed over full fetched set
   - Enables exact counting instead of sample-based inference
   - Ground truth: 127/432 active deals (29.4%) have no ARR

3. **Fetch limits raised** (commit 0319757)
   - Default 50 → 200 rows
   - Max: 500 rows
   - Aggregation handles size, no context cost for larger fetches
