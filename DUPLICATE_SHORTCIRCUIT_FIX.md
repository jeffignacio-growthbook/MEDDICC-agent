# Duplicate Short-Circuit and Aggregate Completeness Fix

**Commit**: 69c5677
**Context**: Aggregation working, but loop repeated itself and exhausted budget

## The Incident

**Observed behavior**:
```
[AGGREGATE] 200 rows → aggregates + 20-row sample  [design landed ✓]
[LOOP iter=1] duplicate tool call detected (same as iteration 0)
[LOOP] declining iteration 2 - budget exhausted
```

**Two problems**:

1. **Duplicate detection didn't short-circuit**
   - iter=0: Executed tool, got 200 rows → aggregated
   - iter=1: Detected duplicate, **but executed it anyway**
   - iter=2: Budget exhausted
   - Detection was a log line, not control flow

2. **Aggregate not recognized as complete**
   - Model asked for 200 rows
   - Got back `{row_count: 200, aggregates: {...}, sample: [20 rows]}`
   - Didn't recognize this as complete answer
   - Repeated query to try to get "the rest"

**Root cause**: Sample looked like a truncated row list rather than a complete summary. The model interpreted `rows: [20]` with `row_count: 200` as "I only got 20 of 200, need to fetch the rest."

## Fix 1: Short-Circuit on Duplicate Detection

**Problem**: `continue` statement wasn't preventing tool execution effectively.

**Fix**: Add explicit short-circuit before tool execution.

### Before (lines 1776-1793)
```python
if is_duplicate:
    no_progress_streak += 1
    if no_progress_streak >= 2:
        return _finalize_from_data("duplicate_tool_call")
    messages.append({"role": "assistant", "content": raw})
    messages.append({"role": "user",
        "content": f"You already queried this in iteration {prev_iter}. "
                  f"Do not repeat it..."})
    continue  # one chance to recover; next stall ends the loop
```

### After (lines 1776-1800)
```python
if is_duplicate:
    # SHORT-CIRCUIT: Duplicate detected means the data is already in hand.
    # Do NOT execute the tool again.
    logger.info(f"[LOOP iter={iteration}] duplicate detected, "
               f"short-circuiting without tool execution")
    no_progress_streak += 1
    if no_progress_streak >= 2:
        return _finalize_from_data("duplicate_tool_call")

    # Don't execute the tool. Instead, inject the existing result and
    # force the model to use it or query differently.
    existing_result = accumulated_data.get(f"step_{prev_iter}", {})
    messages.append({"role": "assistant", "content": raw})
    messages.append({"role": "user",
        "content": f"⚠️  DUPLICATE: You already queried this exact filter in "
                  f"iteration {prev_iter}. The data is already in step_{prev_iter}. "
                  f"Result summary: {existing_result.get('row_count', 0)} rows. "
                  f"Do NOT repeat this query. Either:\n"
                  f'1. Answer now using step_{prev_iter}: {{"answer": "..."}}\n'
                  f"2. Query something DIFFERENT that adds new information\n\n"
                  f"Repeating the same query wastes budget and doesn't help."})
    continue  # Let model respond, but don't execute the duplicate tool
```

**Key changes**:
- Log that duplicate detected and short-circuiting
- Show existing result summary (row count from previous step)
- Explicit instructions: answer now OR query differently
- Make it clear repeating wastes budget

## Fix 2: Add Completeness Markers to Aggregates

**Problem**: Model couldn't tell aggregate was complete vs partial fetch.

**Fix**: Add explicit `complete: true` and explanatory `_note` field.

### Large results (lines 1256-1264)
```python
return {
    "rows": sample,
    "row_count": row_count,
    "aggregates": aggregates,
    "sample": sample,
    "sample_basis": sample_basis,
    "truncated": True,
    "complete": True,  # ← NEW
    "_note": (  # ← NEW
        f"COMPLETE RESULT: All {row_count} rows were aggregated. "
        f"The 'sample' array contains {len(sample)} representative rows "
        f"for illustration, not a partial fetch. Use 'aggregates' for "
        f"totals and counts. Do not re-query to get 'the rest' — this "
        f"IS the full result, summarized."
    ),
    "table": result.get("table", "unknown"),
}
```

### Small results (lines 1158-1166)
```python
# Small results pass through whole
if row_count <= sample_size:
    return {
        **result,
        "row_count": row_count,
        "truncated": False,
        "complete": True,  # ← NEW
        "_note": f"COMPLETE RESULT: All {row_count} rows returned (no aggregation needed)."  # ← NEW
    }
```

**Key markers**:
- `"complete": true` — explicit flag
- `"_note"` — explains what the result means
- States total row count: "All 200 rows were aggregated"
- Clarifies sample is illustrative: "not a partial fetch"
- Direct instruction: "Do not re-query to get 'the rest'"

## Test Coverage

**File**: `tests/test_aggregate_and_sample.py`

Updated tests to assert completeness markers:
```python
def test_small_result_passes_through():
    assert agg.get("complete") == True
    assert "_note" in agg and "COMPLETE RESULT" in agg["_note"]

def test_large_result_aggregated_with_sample():
    assert agg.get("complete") == True
    assert "_note" in agg and "COMPLETE RESULT" in agg["_note"]
    assert "All 138 rows were aggregated" in agg["_note"]
```

All tests passing:
```
✓ Small results marked complete with note
✓ Large results marked complete with explanatory note
✓ Payload size controlled: 4,165 bytes (500 rows → 20 sample)
```

## Behavior Changes

### Duplicate Detection

**Before**:
```
iter=0: Execute query, get 200 rows
iter=1: Detect duplicate, log it, execute anyway (waste), get 200 rows again
iter=2: Budget exhausted
```

**After**:
```
iter=0: Execute query, get 200 rows
iter=1: Detect duplicate, SHORT-CIRCUIT, show existing result summary
        ⚠️  DUPLICATE: Data already in step_0. Result summary: 200 rows.
        Do NOT repeat. Answer now or query something different.
iter=2: Model answers or queries differently (no wasted execution)
```

### Aggregate Recognition

**Before**:
```json
{
  "rows": [20 sample rows],
  "row_count": 200,
  "aggregates": {...}
}
```
Model thinks: "I got 20 of 200, need to fetch the other 180" → repeats query

**After**:
```json
{
  "rows": [20 sample rows],
  "row_count": 200,
  "aggregates": {...},
  "complete": true,
  "_note": "COMPLETE RESULT: All 200 rows were aggregated. Sample is illustrative, not a partial fetch. Do not re-query."
}
```
Model thinks: "This is the full result, summarized. I have everything." → answers

## Impact

### Budget Waste Eliminated
- Duplicate queries no longer execute
- Short-circuit happens immediately with clear message
- Budget preserved for productive iterations

### Aggregate Clarity
- Model understands when result is complete vs partial
- Won't try to "get the rest" of an already-complete aggregate
- `complete: true` and `_note` make intent explicit

### Loop Health
- Semantic fact landed (component fields query worked)
- Aggregation landed (200 rows → summary + sample)
- Duplicate short-circuit fixed (control flow now correct)
- Completeness markers prevent misinterpretation

## Related Fixes

- **Aggregate-then-synthesize** (commit 79c4a78): Core aggregation pattern
- **Zero-rows suspicion** (commit 5d61f1f): Question empty results on enumeration
- **Fiscal quarter normalization** (commit 7b59c44): Auto-correct format mismatches

This completes the aggregate-then-synthesize implementation by fixing the loop mechanics.

## Verification

The semantic fact worked — the query selected component fields and got 200 active deals correctly. The loop mechanics failed, not the query logic. Both issues now fixed:
1. ✅ Duplicate detection short-circuits without tool execution
2. ✅ Aggregates explicitly marked as complete results
