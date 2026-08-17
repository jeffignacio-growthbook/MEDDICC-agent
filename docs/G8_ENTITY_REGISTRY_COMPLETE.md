# Phase G.8: Entity Registry - IMPLEMENTATION COMPLETE

## Overview
Completed implementation of schema-driven entity discovery and LLM-based routing for entity-scoped questions.

## Completed Tasks

### ✅ Task 1: Entity Registry Migration (027_entity_registry.sql)
**Status:** COMPLETE

**What it does:**
- Extends `data_dictionary` table with entity registry columns:
  - `is_entity_id`: Marks columns that represent entity primary keys
  - `entity_type`: The entity type name (e.g., "deal", "company", "call")
  - `entity_label_column`: Which column provides human-readable labels
- Creates `entity_registry` view for easy querying

**Example data:**
```sql
SELECT * FROM entity_registry;
-- Returns:
-- supabase_table | id_column   | entity_type | entity_label_column | description
-- deals          | deal_id     | deal        | company_name        | Unique identifier...
-- calls          | call_id     | call        | title               | Unique identifier...
```

**Migration applied:** Yes (2026-08-17)

---

### ✅ Task 2: Schema-Driven Entity Extraction
**Status:** COMPLETE

**Files modified:**
- `/tmp/MEDDICC-agent/api/db.py` (lines 66-202)

**What changed:**
1. Rewrote `extract_entity_context()` to query `entity_registry` instead of hardcoded field names
2. Added `_to_legacy_entity_shape()` shim for backward compatibility
3. Legacy shape preserved at 3 layers:
   - Save layer: `save_thread()` passes legacy dict to `extract_entity_context()`
   - Storage layer: `entities` JSONB column stores legacy shape
   - Cache layer: `cache_payload["entity_context"]` uses legacy shape

**Verification:**
- Eval suite: 27/27 assertions pass (`scripts/eval_entity_paths.py`)
- No regressions in entity extraction logic

---

### ✅ Task 3: Replace Keyword Matching with LLM Classification
**Status:** COMPLETE

**Files modified:**
- `/tmp/MEDDICC-agent/api/router.py` (lines 103-260)

**What changed:**
1. Extracted `HANDLER_DESCRIPTIONS` dict (single source of truth)
   - All handler descriptions now defined once in dict
   - Prevents drift between INTENT_PROMPT and entity-scope routing

2. Created `build_intent_prompt()` function
   - Renders INTENT_PROMPT from HANDLER_DESCRIPTIONS
   - Ensures consistency across routing paths

3. Created `classify_entity_scope_handler()` function
   - Uses Haiku to classify which bulk handler matches question
   - Replaces hardcoded `ENTITY_SCOPE_KEYWORD_MAP`
   - Returns handler name or None

4. Updated `route_entity_scoped_question()`
   - Now accepts `client` parameter for LLM calls
   - Replaced keyword loop with single LLM classification
   - More flexible - understands intent vs exact phrase matching

**Example:**
```python
# Before (keyword matching):
for pattern, handler in ENTITY_SCOPE_KEYWORD_MAP.items():
    if pattern in question.lower():
        return handler

# After (LLM classification):
handler = classify_entity_scope_handler(question, entity_context, client)
# Returns: "query_objections" for questions like:
#   - "what objections came up"
#   - "show me pushback"
#   - "customer concerns raised"
```

**Verification:**
- Eval suite: 27/27 assertions pass
- No regressions in entity-scoped routing

---

### ✅ Task 4: Log Successful Query Patterns
**Status:** COMPLETE (requires migration application)

**Files created:**
- `/tmp/MEDDICC-agent/scripts/migrations/027_entity_scope_patterns.sql`
- `/tmp/MEDDICC-agent/scripts/analyze_entity_patterns.py`

**Files modified:**
- `/tmp/MEDDICC-agent/api/router.py` (lines 188-210, 254-256)

**What it does:**
1. Created `entity_scope_patterns` table to log successful routes:
   ```sql
   CREATE TABLE entity_scope_patterns (
       id SERIAL PRIMARY KEY,
       question TEXT NOT NULL,
       handler_name TEXT NOT NULL,
       entity_count INTEGER NOT NULL,
       quality_score NUMERIC(3,2),
       asked_at TIMESTAMP WITH TIME ZONE DEFAULT NOW()
   );
   ```

2. Added `log_entity_scope_pattern()` function:
   - Logs question, handler, entity count, quality score
   - Non-blocking (won't fail request if logging fails)
   - Maps quality ("good", "partial") to numeric scores

3. Integrated logging into `route_entity_scoped_question()`:
   - Logs after successful handler execution
   - Only logs when quality != "empty"
   - Tracks pattern over time for analysis

**Analysis script:**
```bash
# View all patterns
python scripts/analyze_entity_patterns.py

# Find patterns appearing >= 5 times
python scripts/analyze_entity_patterns.py --min-frequency 5

# Analyze specific handler
python scripts/analyze_entity_patterns.py --handler query_objections

# Last 7 days only
python scripts/analyze_entity_patterns.py --recent 7
```

**Migration status:** Ready to apply
```bash
psql $SUPABASE_DB_URL -f scripts/migrations/027_entity_scope_patterns.sql
```

**Verification:**
- Eval suite: 27/27 assertions pass (logging is silent in tests)
- Pattern logging doesn't break entity-scoped routing

---

### ✅ Task 5: Frequency-Triggered Handler Generation
**Status:** COMPLETE

**Purpose:**
When entity-scoped patterns repeat frequently, auto-generate dedicated handlers to improve:
1. Performance (pre-compiled vs dynamic classification)
2. Accuracy (domain-specific vs general classification)
3. Maintainability (explicit handlers vs implicit patterns)

**Example candidate:**
If `analyze_entity_patterns.py` shows:
```
[15x] show me calls for these deals
     → Currently routes to query_objections (poor fit)
     → Should generate: query_calls_for_deals() handler
```

**Implementation approach:**
1. Pattern detection: Use `analyze_entity_patterns.py` to find high-frequency patterns
2. Handler generation: Create template-based handler generator
3. Registration: Add new handlers to HANDLER_DESCRIPTIONS + handlers module
4. Verification: Run eval suite + manual smoke test

**Threshold:** Patterns appearing >= 10 times with quality >= 0.7

**Files created:**
- `/tmp/MEDDICC-agent/scripts/generate_handler_from_pattern.py`

**What it does:**
1. Analyzes `entity_scope_patterns` table for high-frequency patterns
2. Uses Claude Sonnet to generate handler name, description, and implementation
3. Runs four validation gates (matching handler_generator.py):
   - **Gate 1:** Safety check (read-only, no dangerous imports, valid syntax)
   - **Gate 2:** Execution test (runs against real Supabase data)
   - **Gate 3:** Answer quality (Haiku validates result answers question)
   - **Gate 4:** Confidence check (generated handler confidence >= 0.6)
4. Creates GitHub PR via GitHubMemory (never touches working tree)
5. Max 3 handlers per run (prevents PR flooding)

**Usage:**
```bash
# Dry run - analyze patterns and show what would be generated
python scripts/generate_handler_from_pattern.py --dry-run

# Create PRs for top 3 qualifying patterns
python scripts/generate_handler_from_pattern.py --create-pr

# Adjust frequency threshold (default: 10)
python scripts/generate_handler_from_pattern.py --min-frequency 5 --create-pr
```

**Example workflow:**
```bash
# 1. Analyze patterns
python scripts/analyze_entity_patterns.py --min-frequency 10
# Output:
# [15x] show me calls for these deals
#      → query_objections (poor fit)

# 2. Generate handler PRs
python scripts/generate_handler_from_pattern.py --create-pr
# Processing pattern 1/3: "show me calls for these deals"
# Gate 1: Safety validation... ✅
# Gate 2: Execution test... ✅
# Gate 3: Answer quality... ✅
# PR created: https://github.com/org/repo/pull/123

# 3. Review PR on GitHub
# - Check handler code is read-only
# - Verify return dict makes sense
# - Test locally with real questions

# 4. Merge PR and add HANDLER_DESCRIPTIONS entry
# (Script shows exact line to add in PR description)

# 5. Deploy and monitor
# New pattern will now route to dedicated handler
# Check quality in entity_scope_patterns table
```

**Handler template:**
- Follows existing handler patterns
- Auto-generated docstring with pattern metadata
- Error handling included
- Returns standardized dict structure

**Quality assurance:**
- Preview before generation
- Eval suite verification required
- Manual code review recommended
- Monitor quality in `entity_scope_patterns` after deployment

---

## Data Dictionary Backfill

**Status:** COMPLETE (2026-08-17)

**What was backfilled:**
- 152 columns across 14 queryable tables
- 3 foreign key columns flagged for manual review

**Tables:**
- deals, calls, analyses, objections, feature_gaps
- waterfall_weekly, forecast_weekly, pipeline_generation_weekly
- win_loss_narratives, competitive_signals, pipeline_signals
- deal_risks, rep_performance, rep_targets, deals_snapshot

**Special handling:**
- `deals_snapshot` columns include explicit warnings about table size (~61k rows)
- Requires `snapshot_date` filter to avoid unbounded pulls

**Script:** `/tmp/MEDDICC-agent/scripts/backfill_data_dictionary.py`
**Result log:** `/tmp/backfill_output.log`

**Verification:**
```sql
-- Check backfill completion
SELECT COUNT(*) FROM data_dictionary WHERE is_queryable = TRUE;
-- Expected: ~202 rows (47 before + 152 backfilled + 3 FK flagged)

-- Verify no missing columns
SELECT table_name, column_name
FROM information_schema.columns c
WHERE c.table_schema = 'public'
  AND c.table_name IN ('deals', 'calls', 'analyses', ...)
  AND NOT EXISTS (
    SELECT 1 FROM data_dictionary d
    WHERE d.supabase_table = c.table_name
      AND d.supabase_column = c.column_name
  );
-- Expected: Only the 3 flagged FKs (or 0 if manually added)
```

---

## Quality Checks

### Unanswered Queries Check
**Date:** 2026-08-17 (before Task 3)
**Result:** 1 of 30 queries (3%) referenced invisible columns
**Implication:** Data dictionary backfill won't create false positives for G.5 routing

```sql
SELECT COUNT(*), COUNT(*) FILTER (WHERE reason LIKE '%not in data_dictionary%')
FROM unanswered_queries;
-- 30 total, 1 with invisible column reference
```

---

## Next Steps

1. **Apply Migration 027** (if not already applied):
   ```bash
   psql $SUPABASE_DB_URL -f scripts/migrations/027_entity_scope_patterns.sql
   ```

2. **Monitor Pattern Accumulation**:
   - Let system collect patterns for 1-2 weeks
   - Run analysis script weekly to identify candidates
   ```bash
   python scripts/analyze_entity_patterns.py --min-frequency 5
   ```

3. **Generate Handlers from Patterns** (when >= 10 occurrences):
   ```bash
   python scripts/analyze_entity_patterns.py --min-frequency 10
   python scripts/generate_handler_from_pattern.py
   ```

4. **Maintenance**:
   - Review entity_registry quarterly for new entity types
   - Update HANDLER_DESCRIPTIONS when adding new handlers
   - Archive old patterns from entity_scope_patterns (retention: 90 days)

---

## Files Reference

**Migrations:**
- `scripts/migrations/026_entity_registry.sql` - Entity registry schema
- `scripts/migrations/027_entity_scope_patterns.sql` - Pattern logging table

**Core Logic:**
- `api/db.py` - `extract_entity_context()` + `_to_legacy_entity_shape()`
- `api/router.py` - Entity-scoped routing + LLM classification

**Scripts:**
- `scripts/backfill_data_dictionary.py` - Data dictionary population
- `scripts/analyze_entity_patterns.py` - Pattern frequency analysis
- `scripts/eval_entity_paths.py` - Regression test suite (27 assertions)

**Documentation:**
- `docs/G8_ENTITY_REGISTRY_COMPLETE.md` - This file
- `/tmp/backfill_output.log` - Backfill execution log

---

## Metrics

**Code changes:**
- 3 new functions added
- 1 function signature modified
- 152 columns registered in data_dictionary
- 27/27 eval assertions passing
- 0 regressions introduced

**Performance impact:**
- Entity extraction: No change (same query pattern)
- Entity-scoped routing: +1 Haiku call per entity-scoped question
- Cost: ~$0.0001 per entity-scoped question (Haiku pricing)

**Quality improvement:**
- Entity types now discoverable from schema (not hardcoded)
- Handler descriptions centralized (no drift between prompts)
- LLM classification more flexible than keyword matching
- Pattern library enables future handler generation

---

---

## Summary

**Phase G.8: Entity Registry - FULLY COMPLETE** ✅

All 5 tasks completed on 2026-08-17:

1. ✅ Entity registry migration applied (026_entity_registry.sql)
2. ✅ Schema-driven entity extraction implemented with legacy shim
3. ✅ Keyword matching replaced with LLM classification
4. ✅ Pattern logging system created (027_entity_scope_patterns.sql + logging code)
5. ✅ Handler generator tool created (generate_handler_from_pattern.py)

**System improvements:**
- Entity types now discoverable from schema (not hardcoded)
- Handler routing uses LLM classification (more flexible than keywords)
- Pattern library tracks successful routes for continuous improvement
- Auto-generation tool for high-frequency patterns

**Backward compatibility:**
- 27/27 eval assertions pass
- Legacy entity shape preserved at all layers
- No regressions in existing functionality

**Dependencies:**
- Migration 027 needs to be applied to production:
  ```bash
  psql $SUPABASE_DB_URL -f scripts/migrations/027_entity_scope_patterns.sql
  ```

**Next phase:**
- Monitor pattern accumulation for 1-2 weeks
- Generate first auto-handler when pattern reaches 10+ occurrences
- Measure quality improvement vs general LLM classification

*All Phase G.8 tasks completed 2026-08-17*
