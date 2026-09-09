# aggregate_results Bug Report - Silent Failure Pattern

**Date:** 2026-09-09
**Severity:** HIGH - Silent data loss in "successful" queries
**Status:** CONFIRMED - Case 1 (Real bug)

---

## Executive Summary

**66.7% failure rate on aggregate_results calls** - LLM passes empty array instead of step reference, causing aggregate_results to return 0 rows despite previous query having data.

**Critical:** One query with empty aggregation still reported `answered: True`, meaning users received incomplete answers without knowing data was missing.

---

## Evidence

### Failure Rate
- **3 aggregate_results calls** in last 30 days
- **2 returned 0 rows** (66.7% failure)
- **1 returned 18 rows** (33.3% success)

### Failed Calls Pattern

**Sept 9 (EMEA pipeline):**
```
Query 0: filter_table → 50 rows ✅
Query 1: aggregate_results
  data: []  ← EMPTY
  group_by: week_ending
  Result: 0 rows ❌
  answered: False
```

**Sept 6 (Renewal pipeline):**
```
Query 0: filter_table → 55 rows ✅
Query 1: aggregate_results
  data: []  ← EMPTY
  group_by: deal_status
  Result: 0 rows ❌
  answered: True ⚠️  (succeeded despite empty aggregation)
```

### Successful Call Pattern

**Sept 6 (Renewal pipeline - retry):**
```
Query 0: filter_table → 20 rows ✅
Query 1: aggregate_results
  data: [full array of 20 dicts]  ← FULL DATA
  group_by: close_date
  Result: 18 rows ✅
  answered: True
```

---

## Root Cause Analysis

### The Bug

**LLM generates wrong parameter format:**
```json
{
  "tool": "aggregate_results",
  "params": {
    "data": [],  ← WRONG: Empty array
    "group_by": "week_ending",
    "aggregations": {...}
  }
}
```

**Should generate:**
```json
{
  "tool": "aggregate_results",
  "params": {
    "data": "step_0",  ← CORRECT: Step reference
    "group_by": "week_ending",
    "aggregations": {...}
  }
}
```

### Why LLM Passes Empty Array

**Prompt says (line 1121-1123):**
```
data: list of dicts from a previous filter_table result,
      OR the string key "step_N" to reference a prior
      tool result (e.g. "step_0" for the first result)
```

**Hypothesis:**
1. LLM reads "list of dicts" and tries to pass the actual data
2. When generating JSON response, it doesn't have access to the 50 rows
3. Defaults to empty array `[]` as placeholder
4. Empty array passes to aggregate_results → 0 rows returned

**The successful call:** LLM somehow included full 20-row array in JSON (verbose but works)

**The failed calls:** LLM couldn't/didn't include data, passed empty array (fails silently)

### Why Step References Rarely Used

The prompt presents step references as the **second option** ("OR the string key").

LLM prioritizes first option ("list of dicts") and only falls back to step reference when it can't generate the list. But instead of falling back to step reference, it generates empty list.

---

## Impact Assessment

### Severity: HIGH

**Silent failure mode:**
- aggregate_results returns 0 rows (technically correct for empty input)
- No error message generated
- Loop continues with empty aggregation
- Query either:
  1. Fails with budget exhaustion (visible failure), or
  2. Completes with incomplete data (silent failure)

**User impact:**
- Sept 9: User saw "ran out of budget" (bad but visible)
- Sept 6: User saw "answered: True" despite empty aggregation (silent data loss)
- Unknown how many other queries completed with missing aggregations

### Affected Query Types

Any time-range aggregation query:
- "How has X moved over N weeks"
- "What changed in [segment] over [period]"
- "Show me [metric] by [dimension] for [date range]"

These queries:
1. Filter to get detailed rows (step 0)
2. Aggregate by dimension (step 1 - FAILS 66% of time)
3. Either fail visibly (budget) or succeed with incomplete data

---

## Why This Wasn't Caught

### No Validation

**aggregate_results doesn't validate input:**
```python
async def aggregate_results(data, group_by, aggregations):
    groups = defaultdict(list)
    for row in data:  # If data=[], loop never runs
        groups[row.get(group_by, "unknown")].append(row)
    # ...
    return {"rows": result}  # Returns [] if data was []
```

No check for:
- Empty input data
- Whether step reference was intended but not resolved
- Whether previous query had data that should be aggregated

### No Logging

When aggregate_results returns 0 rows, there's no warning:
- No log: "aggregate_results received empty data"
- No log: "step_0 had 50 rows but aggregate_results got []"
- Only logged: "[TOOL] aggregate_results rows=0 error=none"

Looks like a normal result, not a bug.

---

## Fixes Required

### Fix 1: Prompt Change (Primary)

**Current (ambiguous):**
```
aggregate_results(data, group_by, aggregations)
  data: list of dicts from a previous filter_table result,
        OR the string key "step_N" to reference a prior
        tool result (e.g. "step_0" for the first result)
```

**Proposed (explicit):**
```
aggregate_results(data, group_by, aggregations)
  data: ALWAYS use "step_N" to reference a previous result
        (e.g. "step_0" for the first filter_table result,
         "step_1" for the second result)
        NEVER pass the data array directly - use the step reference
  group_by: column name to group by
  aggregations: dict of {{"column": "sum"|"count"|"avg"}}
```

**Add emphasis in RULES section:**
```
- When calling aggregate_results, ALWAYS pass data="step_N" reference
- NEVER pass data as an empty array or full data array
- If you don't have a step to reference, don't call aggregate_results
```

### Fix 2: Validation in aggregate_results (Safety Net)

```python
async def aggregate_results(data, group_by, aggregations):
    # VALIDATION: Catch empty data bug
    if not data or len(data) == 0:
        return {
            "error": "aggregate_results received empty data. Use data='step_N' to reference previous result.",
            "rows": [],
            "empty_input": True
        }

    # VALIDATION: Catch missing group_by column
    if data and group_by not in data[0]:
        available_cols = list(data[0].keys())[:10]
        return {
            "error": f"Column '{group_by}' not found in data. Available: {available_cols}",
            "rows": [],
            "invalid_group_by": True
        }

    # Existing logic...
```

### Fix 3: Router Warning (Detection)

Add logging in router.py when aggregate_results gets empty data:

```python
if tool_name == "aggregate_results":
    data = tool_params.get("data", [])
    if isinstance(data, str):
        data = accumulated_data.get(data, {}).get("rows", [])
        # Log if step reference resolved to empty
        if not data:
            logger.warning(f"[TOOL] aggregate_results: step reference "
                          f"'{tool_params.get('data')}' resolved to empty data. "
                          f"Available steps: {list(accumulated_data.keys())}")
    elif not isinstance(data, list):
        data = []

    # NEW: Warn if data is empty but previous step had rows
    if not data and accumulated_data:
        for key, val in accumulated_data.items():
            if val.get("rows") and len(val["rows"]) > 0:
                logger.warning(f"[BUG] aggregate_results received empty data, "
                              f"but {key} has {len(val['rows'])} rows. "
                              f"LLM should have passed data='{key}'")

    tool_params["data"] = data
    result = await tool_fn(**tool_params)
```

---

## Test Cases

### Test 1: Reproduce Empty Array Bug
```python
# Simulate LLM passing empty array
result = await aggregate_results(
    data=[],
    group_by="week_ending",
    aggregations={"deal_value": "sum"}
)
# Expected: error message, not silent 0 rows
assert "error" in result
assert "empty data" in result["error"].lower()
```

### Test 2: Valid Step Reference
```python
# Set up accumulated_data
accumulated_data = {
    "step_0": {"rows": [{"week": "2026-09-01", "value": 100}]}
}

# Resolve step reference
data = accumulated_data.get("step_0", {}).get("rows", [])
result = await aggregate_results(
    data=data,
    group_by="week",
    aggregations={"value": "sum"}
)
# Expected: 1 row with sum
assert len(result["rows"]) == 1
assert result["rows"][0]["value_sum"] == 100
```

### Test 3: Missing Column Warning
```python
result = await aggregate_results(
    data=[{"week": "2026-09-01", "value": 100}],
    group_by="nonexistent_column",
    aggregations={"value": "sum"}
)
# Expected: error message about missing column
assert "error" in result
assert "not found" in result["error"].lower()
```

---

## Verification Steps

1. ✅ Confirm 66.7% failure rate (done - 2 of 3 calls failed)
2. ✅ Identify root cause (done - LLM passes empty array)
3. ⏳ Implement prompt fix (line 1120-1130 in router.py)
4. ⏳ Implement validation fix (tools.py aggregate_results)
5. ⏳ Implement logging fix (router.py tool execution section)
6. ⏳ Add test cases to eval suite
7. ⏳ Monitor fallback_log for 7 days to confirm fix
8. ⏳ Check if recent "successful" queries had empty aggregations

---

## Related Issues

### Synthesis Aggregation Bug (Sept 9)
- **Different layer:** That bug was synthesis dropping data it had
- **This bug:** Tool layer returning empty data before synthesis even sees it
- **Compounding risk:** Empty aggregation + synthesis anchoring = silent data loss

### Budget Exhaustion (Sept 9)
- Initially thought budget was the issue
- Actually: aggregate_results failure forced extra query
- Extra query pushed token usage past projection threshold
- **Budget exhaustion was a symptom, not root cause**

---

## Priority Justification

**Why HIGH priority:**
1. **66.7% failure rate** - nearly all aggregate_results calls fail
2. **Silent failure** - no error, just missing data
3. **User trust impact** - "answered: True" with incomplete data
4. **Already affecting production** - 2 failures in 4 days
5. **Easy to fix** - prompt change + validation (low effort, high impact)

**Why not URGENT:**
- Only 3 calls in 30 days (low absolute frequency)
- Users can retry or rephrase question
- Budget exhaustion makes some failures visible
- No reported user complaints yet

**Recommendation:** Fix before next sprint, monitor closely.

---

## Files

**Investigation:**
- `investigate_aggregate_results_bug.py` - Queries fallback_log for pattern
- `check_fallback_logs.py` - Sept 9 specific investigation

**To Modify:**
- `api/router.py:1120-1130` - Prompt fix (aggregate_results instructions)
- `api/router.py:2067-2075` - Add warning when empty data detected
- `api/tools.py:156-193` - Add validation to aggregate_results function

**Documentation:**
- `AGGREGATE_RESULTS_BUG_REPORT.md` - This file
- `FALLBACK_BUDGET_ERROR_ANALYSIS.md` - Sept 9 investigation
- `PENDING_WORK.md` - Add this to High Priority section
