# aggregate_results Fix - Implementation Guide

**Status:** Ready to implement
**Priority:** HIGH
**Estimated effort:** 30-45 minutes
**Testing required:** Yes (validation tests included)

---

## Summary of Findings

### The Bug
**66.7% failure rate:** LLM passes `data: []` instead of `data: "step_0"`
- 2 of 3 aggregate_results calls in last 30 days returned 0 rows
- One failure caused budget exhaustion (visible)
- One failure succeeded silently (user received incomplete answer)

### Root Cause
Prompt ambiguity (line 1121-1123):
```
data: list of dicts from a previous filter_table result,
      OR the string key "step_N" to reference a prior result
```

LLM tries to pass full array, can't fit in JSON, defaults to empty array.

### User Impact
**Sept 6 query:** "How much expansion ARR is in renewal pipeline for Q3 and Q4?"
- Initial query: 55 deals
- Aggregation: FAILED (0 rows with empty array)
- Recovery query: 7 deals (12.7% of original)
- Delivered answer: "$110K Q3 expansion" (based on 7 deals, not 55)
- **Unknown if answer is accurate or missing data**

---

## Three-Layer Fix

### Fix 1: Prompt Change (Primary Fix)

**File:** `api/router.py`
**Lines:** 1120-1130

**Current:**
```python
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
```

**Replacement:**
```python
  aggregate_results(data, group_by, aggregations)
    data: ALWAYS use "step_N" to reference a previous result
          (e.g. "step_0" for the first filter_table result,
           "step_1" for the second result)
          NEVER pass the data array directly - always use step reference
    group_by: column name to group by
    aggregations: dict of {{"column": "sum"|"count"|"avg"}}
    Example: aggregate_results(
      data="step_0",  # Reference to first query result
      group_by="owner_email",
      aggregations={{"deal_value": "sum", "deal_id": "count"}}
    )
```

**Also add to RULES section (line 1134-1140):**
```python
RULES:
- Only use column names that appear in the schema above
- Filters: [["operator", "column", "value"], ...]
  operators: eq neq gt gte lt lte like ilike is_ in_
- Maximum 5 tool calls per question
- If data genuinely doesn't exist, say so plainly
- Never invent numbers
- When calling aggregate_results, ALWAYS pass data="step_N"
  NEVER pass data as [] or a full array - step references only
```

---

### Fix 2: Validation in aggregate_results (Safety Net)

**File:** `api/tools.py`
**Function:** `aggregate_results` (line 156)

**Add at start of function (before line 157):**
```python
async def aggregate_results(data, group_by, aggregations):
    # VALIDATION: Catch empty data bug
    if isinstance(data, list) and len(data) == 0:
        return {
            "error": "Empty data array. Use data='step_N' to reference previous result.",
            "rows": [],
            "validation_failed": "empty_array"
        }

    # VALIDATION: Catch missing group_by column
    if isinstance(data, list) and data and group_by not in data[0]:
        available_cols = list(data[0].keys())[:10]
        return {
            "error": f"Column '{group_by}' not found in data. Available: {available_cols}",
            "rows": [],
            "validation_failed": "invalid_group_by"
        }

    # Existing validation and logic continues...
```

---

### Fix 3: Router-Level Validation (Detection + Logging)

**File:** `api/router.py`
**Lines:** 2067-2075 (tool execution for aggregate_results)

**Current:**
```python
if tool_name == "aggregate_results":
    data = tool_params.get("data", [])
    if isinstance(data, str):
        # Agent passed a key reference like "step_0"
        data = accumulated_data.get(data, {}).get("rows", [])
    elif not isinstance(data, list):
        data = []
    tool_params["data"] = data
    result = await tool_fn(**tool_params)
```

**Replacement:**
```python
if tool_name == "aggregate_results":
    data = tool_params.get("data", [])
    original_ref = data if isinstance(data, str) else None

    if isinstance(data, str):
        # Agent passed a key reference like "step_0"
        step_ref = data
        data = accumulated_data.get(data, {}).get("rows", [])

        # VALIDATION: Warn if step reference resolved to empty
        if not data:
            available_steps = [k for k, v in accumulated_data.items()
                             if k.startswith("step_") and v.get("rows")]
            logger.warning(
                f"[BUG] aggregate_results: step reference '{step_ref}' "
                f"resolved to empty data. Available steps with data: {available_steps}")

            # Return error instead of continuing with empty data
            result = {
                "error": f"Step reference '{step_ref}' has no data. "
                        f"Available: {available_steps}",
                "rows": [],
                "validation_failed": "invalid_step_reference"
            }
            tool_params["data"] = data
            # Skip tool execution, use error result
            # (continue to result handling below)
        else:
            tool_params["data"] = data
            result = await tool_fn(**tool_params)

    elif isinstance(data, list):
        # Agent passed data array directly
        if len(data) == 0:
            # Check if previous step had data that should have been referenced
            prev_steps_with_data = [
                (k, len(v.get("rows", [])))
                for k, v in accumulated_data.items()
                if k.startswith("step_") and v.get("rows")
            ]

            if prev_steps_with_data:
                logger.error(
                    f"[BUG] aggregate_results received empty array, "
                    f"but previous steps have data: {prev_steps_with_data}. "
                    f"LLM should have passed data='step_0' or similar.")

        tool_params["data"] = data
        result = await tool_fn(**tool_params)
    else:
        data = []
        tool_params["data"] = data
        result = await tool_fn(**tool_params)
```

---

## Testing

### Test 1: Validation Tests (Included)
```bash
python test_aggregate_results_validation.py
```

Expected: All 13 tests pass

### Test 2: End-to-End Test

Create a test query that previously failed:

```python
# Simulate the Sept 9 EMEA query
# Should now succeed with proper step reference
question = "How has EMEA pipeline moved in the last 2 weeks"

# Expected: LLM generates
# {"tool": "aggregate_results", "params": {"data": "step_0", ...}}

# Verify in logs:
# [LOOP iter=1] parsed=True tool=aggregate_results has_answer=False
# [TOOL] aggregate_results rows=4 error=none  (not 0!)
```

### Test 3: Invalid Reference Test

Manually trigger validation:

```python
# Pass invalid step reference
result = await aggregate_results(
    data="step_99",  # Doesn't exist
    group_by="week",
    aggregations={"value": "sum"}
)

# Expected error:
# "Step reference 'step_99' has no data. Available: ['step_0', 'step_1']"
```

---

## Verification Steps

### Pre-Implementation
1. ✅ Confirm only aggregate_results has this pattern (done - grep found only 1 instance)
2. ✅ Test validation logic catches all failure modes (done - 13/13 tests pass)
3. ✅ Review Sept 6 impact (done - documented in SEPT6_SILENT_FAILURE_IMPACT.md)

### Post-Implementation
1. ⏳ Deploy fixes to all 3 files
2. ⏳ Run validation test suite (should still pass)
3. ⏳ Monitor fallback_log for 7 days:
   ```sql
   SELECT * FROM fallback_log
   WHERE EXISTS (
     SELECT 1 FROM jsonb_array_elements(queries_run) q
     WHERE q->>'tool' = 'aggregate_results'
       AND (q->>'rows_returned')::int = 0
   )
   AND created_at >= CURRENT_DATE - INTERVAL '7 days'
   ORDER BY created_at DESC;
   ```
4. ⏳ Verify no new 0-row aggregate_results calls
5. ⏳ Check if previous failures now succeed:
   - Ask "How much expansion ARR is in renewal pipeline for Q3 and Q4?" again
   - Ask "How has EMEA pipeline moved in the last 2 weeks" again
   - Both should complete without empty aggregations

### Verify Sept 6 Answer Accuracy
```sql
-- Pull full renewal pipeline data
SELECT
  deal_id,
  company_name,
  close_date,
  incremental_arr,
  deal_status
FROM deals
WHERE pipeline_id = '866608541'
  AND close_date >= '2026-08-01'
  AND close_date <= '2027-01-31'
  AND deal_status = 'active'
ORDER BY close_date;

-- Check Q3 expansion total
SELECT
  COUNT(*) as deals,
  SUM(incremental_arr) as total_expansion
FROM deals
WHERE pipeline_id = '866608541'
  AND close_date >= '2026-08-01'
  AND close_date <= '2026-10-31'
  AND deal_status = 'active'
  AND incremental_arr > 0;
```

Compare to delivered answer: "$110K Q3 expansion"
- If matches: ✅ Answer was correct despite bug
- If differs: ❌ Document discrepancy, consider notifying stakeholder

---

## Rollback Plan

If fix causes issues:

1. **Revert prompt change** (api/router.py:1120-1130)
   - Restore "list of dicts OR step reference" wording
   - Remove RULES addition

2. **Keep validation** (api/tools.py)
   - Validation is defensive, safe to keep
   - Helps catch future bugs even if prompt reverted

3. **Keep logging** (api/router.py:2067-2075)
   - Logging is observability, no user impact
   - Helps diagnose issues even if prompt reverted

**Unlikely scenarios requiring rollback:**
- LLM starts failing to pass step references at all
- New error mode emerges worse than original bug
- Performance impact from logging (very unlikely)

---

## Success Metrics

**Week 1 after deployment:**
- Zero 0-row aggregate_results calls in fallback_log
- Zero budget_exhausted triggers from aggregate_results loops
- All time-range aggregation queries complete successfully

**Week 2-4:**
- Sustained zero failure rate
- No user reports of incomplete answers
- Verified Sept 6 answer accuracy (if possible to reconstruct)

---

## Files Modified

1. `api/router.py` (2 sections)
   - Lines 1120-1130: Tool description
   - Lines 1134-1140: RULES section
   - Lines 2067-2075: Tool execution logic

2. `api/tools.py` (1 section)
   - Lines 156-157: Add validation before existing logic

3. Tests (new file)
   - `test_aggregate_results_validation.py` (included, passing)

---

## Documentation

**Investigation:**
- AGGREGATE_RESULTS_BUG_REPORT.md (full analysis)
- SEPT6_SILENT_FAILURE_IMPACT.md (user impact)
- investigate_aggregate_results_bug.py (pattern finder)
- investigate_sept6_silent_failure.py (specific case)
- test_aggregate_results_validation.py (test suite)

**Implementation:**
- This file (implementation guide)

**Tracking:**
- PENDING_WORK.md (updated - High Priority #1)

---

## Commit Message Template

```
Fix aggregate_results 66.7% failure rate (empty data bug)

ISSUE:
- LLM passes data=[] instead of data="step_0" (2 of 3 calls failed)
- Prompt ambiguity: "list OR step reference" → LLM tries array, defaults to empty
- aggregate_results returns 0 rows silently (no error, no validation)
- One failure caused budget exhaustion (visible symptom)
- One failure succeeded with incomplete data (silent, user affected)

USER IMPACT:
- Sept 6: "Q3 expansion ARR" query returned incomplete answer
- Sept 9: "EMEA pipeline movement" query failed with budget exhaustion
- Unknown how many other queries affected by silent failures

FIX:
1. Prompt: Force step references (remove "list OR reference" ambiguity)
2. Validation: Reject empty data at tool boundary
3. Logging: Warn when step reference resolves to empty

FILES:
- api/router.py (prompt + logging fixes)
- api/tools.py (validation fix)
- test_aggregate_results_validation.py (test suite: 13/13 passing)

VERIFICATION:
- Grep confirmed: only aggregate_results has this pattern
- Test suite confirms: all failure modes now caught
- Sept 6 query reviewed: documented in SEPT6_SILENT_FAILURE_IMPACT.md

See: AGGREGATE_RESULTS_BUG_REPORT.md for full investigation
```
