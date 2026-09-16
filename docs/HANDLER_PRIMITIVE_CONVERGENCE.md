# Handler-Primitive Convergence Initiative

**Status:** Scoped for future work (multi-day effort)
**Date Identified:** 2026-09-14
**Context:** Discovered during pipeline_filter gap investigation

---

## Problem Statement

Dedicated handlers (query_pipeline, query_waterfall, query_deal_health, etc.) contain hand-written logic that duplicates what governed primitives (filter_table, aggregate_results) and field_semantics.py functions already do correctly.

**Tonight's incident:** The pipeline_filter gap went undetected because:
1. Handler code (query_pipeline) has its own in-memory filtering logic
2. That logic was never tested against the same classification/primitive path dynamic_query uses
3. A parameter gap (classifier schema missing pipeline_filter) meant the handler's filtering code never executed
4. CI passed because tests called the handler directly with pipeline_filter set
5. Production failed because the upstream classifier couldn't populate the parameter

This is a structural risk: every dedicated handler is a parallel implementation that can diverge from the governed path.

---

## Root Cause: Dual Implementation Paths

```
Path 1 (Dynamic Query - Governed):
  Question → Classifier → dynamic_query_loop → Primitives (filter_table, aggregate_results)
    → field_semantics.py functions (is_incremental_pipeline, stage_bucket, etc.)
    → Consistent business logic

Path 2 (Dedicated Handlers - Hand-Written):
  Question → Classifier → Handler (query_pipeline, etc.)
    → Custom filtering/aggregation/classification logic
    → Duplicates business logic independently
```

**Risk:** Any fix to business logic (like the pipeline_id comparison fix) must be applied in BOTH paths, or they diverge. Tests can pass on one path while the other path is broken.

---

## Three-Part Solution

### Part 1: Audit and Refactor Existing Handlers

**Scope:** Every dedicated handler that contains duplicated logic.

**Examples of duplication to eliminate:**

1. **Pipeline-type classification:**
   - query_pipeline lines 2257-2263: Custom pipeline_id comparison logic
   - SHOULD USE: field_semantics.is_incremental_pipeline() (already used elsewhere in same handler)
   - Benefit: One source of truth for "what is a renewal deal"

2. **Stage bucketing/filtering:**
   - query_pipeline lines 2221-2232: Custom stage_filter logic with bucket comparisons
   - SHOULD USE: field_semantics.stage_bucket() + filter_table with stage dimension
   - Benefit: Consistent stage taxonomy across all queries

3. **Date resolution:**
   - Multiple handlers: Custom time_window → SQL filter conversion
   - SHOULD USE: time_resolver.resolve_time_window() (already partially adopted)
   - Benefit: Single timezone/fiscal-quarter logic

4. **Dimension filtering (region, segment, owner):**
   - query_pipeline lines 2128-2130: Custom owner_email filtering
   - SHOULD USE: resolve_dimension_filter() or filter_table with dimension params
   - Benefit: Consistent canonicalization (name → email, ilike vs eq)

5. **Aggregation:**
   - query_pipeline lines 2268-2270: Manual sum(incremental_value)
   - SHOULD USE: aggregate_results primitive with sum/group_by
   - Benefit: Consistent aggregation rules, easier to extend

6. **Classifier schema gaps (2026-09-15):**
   - Handlers may have parameter logic that never executes because HANDLER_SCHEMA is missing parameters
   - Example: query_pipeline had pipeline_filter/stage_filter logic, but classifier couldn't populate them
   - FIXED: test_handler_schema_completeness.py now enforces schema completeness (2026-09-09)
   - Benefit: Impossible to add handler param without adding to classifier schema
   - Note: This isn't handler duplication per se, but a parallel risk - handlers bypass primitives AND may have dead code due to schema gaps

**Audit checklist for each handler:**
- [ ] Dimension filtering (region, segment, pipeline_type, stage, owner)
- [ ] Date/time window resolution
- [ ] Business rule application (incremental vs renewal, stage buckets, etc.)
- [ ] Aggregation (sum, count, group by)
- [ ] Field canonicalization (name → email, stage label → stage_id)

**Implementation approach:**
- Start with query_pipeline (most used, highest impact)
- Refactor incrementally: one duplicated logic type at a time
- Add regression tests before/after each refactor
- Verify live behavior unchanged (same Slack questions → same answers)

---

### Part 2: Primitives-First for New Clients

**Policy for new client implementations:**

1. **Build primitives first:**
   - Start with filter_table, aggregate_results, field_semantics functions
   - Cover full data model with primitives before writing any dedicated handlers
   - Verify dynamic_query_loop can answer common questions using primitives alone

2. **Dedicated handlers as thin wrappers:**
   - Only add a dedicated handler for a proven-common question shape
   - Handler must be a composition of existing primitives, not new business logic
   - Example of correct pattern:
     ```python
     async def query_common_pattern(params, sb):
         # Extract params
         filters = build_filters_from_params(params)  # Shared function

         # Call primitive
         data = await filter_table(sb, "deals", filters)

         # Aggregate with primitive
         result = await aggregate_results(data, group_by=["stage"], sum=["arr"])

         # Apply field semantics
         result = apply_stage_labels(result)  # Shared function

         # Return structured result
         return format_response(result)  # Shared function
     ```

3. **Handler approval gate:**
   - New dedicated handlers require explicit approval (not just a PR merge)
   - Approval criteria: "Does this handler call shared primitives, or duplicate logic?"
   - If it duplicates logic → reject, extend primitives instead

---

### Part 3: Reduce Handler Logic Overall

**Long-term goal:** Dedicated handlers should be < 50 lines, mostly parameter extraction and primitive composition.

**Current state examples:**
- query_pipeline: ~400 lines with custom filtering, aggregation, and business rules
- query_waterfall: ~300 lines with custom date logic and aggregation
- query_deal_health: ~200 lines with custom scoring logic

**Target state examples:**
- query_pipeline: ~50 lines calling filter_table + aggregate_results + field_semantics functions
- query_waterfall: ~50 lines calling compare_periods primitive (to be built)
- query_deal_health: ~50 lines calling filter_table + score_threshold filter

**Structural benefits:**
1. Business logic lives in ONE place (primitives + field_semantics)
2. Fixes/changes apply everywhere automatically (no dual-path divergence)
3. Testing is simpler (test primitives once, not every handler)
4. New questions are easier (compose primitives, don't write handlers)
5. Parameter gaps are impossible (primitives enforce schema consistency)

---

## Why This Is Not Tonight's Task

**Scope:** This touches:
- 9+ dedicated handlers (from tonight's audit)
- 100s of lines of business logic per handler
- Extensive regression testing (live Slack questions must give same answers)
- Coordination with client (any behavior change must be validated)

**Estimated effort:** 3-5 days, not 3-5 hours

**Current priority:** Fix tonight's fire (pipeline_filter gap) first

---

## Related Context

**Tonight's incidents that led here:**
1. Date-range bug (2026-09-10): Already fixed, but query_pipeline_movement had its own date logic parallel to time_resolver
2. Pipeline_filter gap (2026-09-14): query_pipeline's in-memory filtering never tested against classifier path
3. Migration-64 gap (2026-09-14): "Verified in CI" ≠ "working in production" when upstream steps don't execute

**Pattern:** Dedicated handlers bypass the governed primitive path, creating divergence risk.

---

## Acceptance Criteria (When This Is Executed)

**For Part 1 (Refactor existing handlers):**
- [ ] Every dedicated handler < 100 lines (ideally < 50)
- [ ] No duplicated business logic (pipeline classification, stage bucketing, date resolution, etc.)
- [ ] All handlers call shared primitives/field_semantics functions
- [ ] Handlers satisfy all 4 structural gates:
  - tests/test_date_resolution_single_source.py (no raw date.today() calls)
  - tests/test_primitive_contract.py (detection primitives log + act)
  - tests/test_handler_schema_completeness.py (all params in HANDLER_SCHEMA)
  - scripts/check_schema_dictionary_drift.py (no invisible columns)
- [ ] Regression suite: 20+ live Slack questions answered identically before/after
- [ ] test_handler_schema_completeness.py passes (all handler params registered in schema)

**Available reusable tools for refactoring (2026-09-15):**
- `verify_corrected_value_placement()` (api/placement_verification.py) - Two-signal placement corruption check for any corrected value handed to model
- `resolve_dimension_filter()` (api/dimension_resolver.py) - Governed dimension term resolution (region/segment/owner/deal-type)
- `resolve_time_window()` (api/time_resolver.py) - Fiscal-quarter-aware date resolution
- `field_semantics.py` functions - is_incremental_pipeline(), stage_bucket(), is_renewal_base(), etc.
- `filter_table()` (api/tools.py) - Governed filtering primitive
- `aggregate_results()` (api/tools.py) - Governed aggregation primitive

**For Part 2 (Primitives-first policy):**
- [ ] Documentation: "New Client Setup Guide" requires primitives before handlers
- [ ] PR template: New handlers require "Uses shared primitives: Yes/No" checkbox
- [ ] Example repo: Reference implementation showing primitives-first approach

**For Part 3 (Reduce handler logic):**
- [ ] Average handler length < 75 lines (measured across all handlers)
- [ ] Business logic centralization: 90%+ of rules in primitives/field_semantics (not handlers)
- [ ] Test coverage: Primitives have 95%+ coverage, handlers have 70%+ (since they're thin wrappers)

---

## Implementation Sequencing (When Started)

**Phase 1: Foundation (Week 1)**
- Day 1-2: Audit all handlers, document duplicated logic by category
- Day 3: Build missing primitives (compare_periods, dimension_filter, etc.)
- Day 4-5: Regression test suite (capture current behavior for 20+ questions)

**Phase 2: Refactor High-Impact Handlers (Week 2)**
- Day 1-2: query_pipeline refactor (most used)
- Day 3: query_waterfall refactor (second most used)
- Day 4: query_deal_health refactor
- Day 5: Regression verification, deploy to staging

**Phase 3: Remaining Handlers + Policy (Week 3)**
- Day 1-3: Refactor remaining 6+ handlers
- Day 4: Write "Primitives-First" policy doc
- Day 5: Update PR templates, deploy to production

---

## Notes

This is architectural hygiene, not a new feature. The user-facing behavior should be IDENTICAL before and after - the goal is to reduce maintenance burden and eliminate divergence risk, not to change what answers look like.

**Do NOT start this work without explicit go-ahead.** This is documented for future scoping, not immediate execution.
