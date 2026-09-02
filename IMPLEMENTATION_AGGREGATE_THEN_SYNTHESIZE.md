# Implementation Plan: Aggregate in Loop, Sample for Synthesis

**Based on**: `/Users/jeffignacio/Downloads/DESIGN_AGGREGATE_THEN_SYNTHESIZE.md`

## Current State

**Files involved:**
- `api/router.py`:
  - `dynamic_query_loop()` (lines 1297-1718) — multi-turn tool loop
  - `_extract_rows_from_accumulated()` (lines 1137-1250) — extracts rows from loop steps
  - `_cap_rows_for_synthesis()` (lines 2605-2645) — caps arrays for synthesis
- `api/tools.py`:
  - `filter_table()` — has max_limit=50 (just tightened from 200)
  - `aggregate_results()` — exists but rarely called

**Current flow:**
1. Loop fetches data via filter_table (capped at 50 rows)
2. Stores in `accumulated_data[f"step_{iteration}"]`
3. Passes raw rows to synthesis (capped at 20 via `_cap_rows_for_synthesis`)
4. Synthesis sees truncated lists without knowing full counts

**Problems:**
- 50-row cap is wrong in both directions:
  - Forecast answer needed 10 rows (5x waste)
  - "138 deals with no value" needs all 138 counted (silent truncation)
- Context bloat: 100 rows = 27,969 chars → budget exhaustion
- Cap tries to solve context problem by discarding data (wrong lever)

## Design Summary

**Three stages with explicit boundaries:**

### 1. Fetch (unbounded within reason)
- Raise filter_table max_limit to 500 (safety ceiling)
- Fetched rows live in `accumulated_data`, never go direct to synthesis

### 2. Aggregate (in loop, before synthesis)
- When result > sample_size (default 20):
  - Compute aggregates (sum, mean, min, max, null counts)
  - Count by stage/segment/owner
  - Keep sample (largest/soonest/most relevant)
  - Add `truncated: true` and `sample_basis: "10 largest by deal_value"`
- When result ≤ sample_size: pass through whole

### 3. Synthesize (from summary)
- Never receives more than sample_size rows
- Gets aggregates + sample + full counts
- Can say "138 deals totalling $4.2M — the ten largest are..."

## Files to Change

### `api/tools.py`

**filter_table()** (lines 46-51):
```python
# BEFORE:
max_limit = 50

# AFTER:
# Fetch ceiling - never the synthesis budget. Aggregation happens before synthesis.
max_limit = 500
```

### `api/router.py`

**New function** `_aggregate_and_sample()`:
```python
def _aggregate_and_sample(result: dict, sample_size: int = 20,
                         order_by: str = None) -> dict:
    """
    Aggregate large result sets and sample for synthesis.

    Small results (≤ sample_size) pass through whole.
    Large results get aggregated + sampled + truncation flag.

    Args:
        result: Tool result with "rows" key
        sample_size: Max rows for synthesis (default 20)
        order_by: Column result was ordered by (determines sample basis)

    Returns dict with:
        - row_count: Total (always)
        - aggregates: {sum/mean/min/max, counts by category, null counts}
        - sample: Top N rows (when truncated)
        - sample_basis: How sample was selected
        - truncated: True when result > sample_size
        - rows: All rows if ≤ sample_size, else sample
    """
```

**Modify** `dynamic_query_loop()` (lines 1680-1692):
```python
# BEFORE (line 1688):
accumulated_data[f"step_{iteration}"] = result

# AFTER:
# Aggregate large results before storing for synthesis
aggregated = _aggregate_and_sample(result, sample_size=20,
    order_by=tool_params.get("order_by"))
accumulated_data[f"step_{iteration}"] = aggregated
```

**Modify** `_extract_rows_from_accumulated()` (lines 1137-1250):
- Entity extraction mode: merge across all steps, deduplicate
- Synthesis mode: return aggregated summary + sample from last step
- Report which steps contributed: "aggregated 262 unique rows from 3 steps"

**Remove** `_cap_rows_for_synthesis()` (lines 2605-2645):
- No longer needed — aggregation replaces it
- Delete function and call site (line 2074)

## Aggregation Logic

### Derive from columns present

**Numeric columns** (deal_value, arr_usd, etc.):
```python
aggregates[col] = {
    "sum": sum(vals),
    "mean": sum(vals)/len(vals),
    "min": min(vals),
    "max": max(vals),
    "null_count": null_count,
}
```

**Low-cardinality text** (stage, segment, forecast_category, owner):
```python
aggregates[f"{col}_counts"] = {
    "Discovery": 87,
    "Scoping": 24,
    ...
}
```

**Dates** (close_date, created_at):
```python
aggregates[col] = {
    "earliest": min(dates),
    "latest": max(dates),
    "past_today": len([d for d in dates if d < today]),
}
```

**Always**:
```python
aggregates["row_count"] = len(rows)
aggregates["null_counts"] = {col: count for col, count in null_counts.items()}
```

### Sample selection

Default to most relevant ordering:
- If `order_by="deal_value desc"` → sample = largest
- If `order_by="close_date"` → sample = soonest
- If no order → sample = first N

State in `sample_basis`:
```json
{
  "sample_basis": "10 largest by deal_value",
  "sample_basis": "20 soonest by close_date",
  "sample_basis": "first 20 rows (no ordering specified)"
}
```

## Multi-Step Accumulation

When multiple steps hold rows from same table:
1. Deduplicate on entity ID (same as extraction does)
2. Aggregate across union (not per step)
3. Report which steps contributed

Example:
```
[EXTRACT] aggregated 262 unique rows from 3 steps:
  step_0: 200 rows (deals table)
  step_2: 100 rows (deals table)
  step_4: 50 rows (deals table)
  deduplicated: 262 unique deal_ids
```

## Tests

```python
def test_small_result_passes_through():
    """9 rows with sample_size=20 arrive complete, no truncation."""
    result = {"rows": [{"id": i} for i in range(9)], "table": "deals"}
    agg = _aggregate_and_sample(result, sample_size=20)

    assert len(agg["rows"]) == 9
    assert "truncated" not in agg or agg["truncated"] == False
    assert agg["row_count"] == 9

def test_large_result_aggregated_with_sample():
    """138 rows → aggregates + 20-row sample + truncated flag."""
    rows = [{"deal_id": i, "deal_value": i*1000, "stage": "Discovery"}
            for i in range(138)]
    result = {"rows": rows, "table": "deals"}
    agg = _aggregate_and_sample(result, sample_size=20, order_by="deal_value desc")

    assert agg["row_count"] == 138
    assert len(agg["sample"]) == 20
    assert agg["truncated"] == True
    assert "deal_value" in agg["aggregates"]
    assert agg["aggregates"]["deal_value"]["sum"] == sum(i*1000 for i in range(138))
    assert agg["sample_basis"] == "20 largest by deal_value"

def test_null_counts_surface():
    """15 of 138 deals with null deal_value are counted."""
    rows = [{"deal_id": i, "deal_value": i*1000 if i < 123 else None}
            for i in range(138)]
    result = {"rows": rows, "table": "deals"}
    agg = _aggregate_and_sample(result, sample_size=20)

    assert agg["aggregates"]["null_counts"]["deal_value"] == 15

def test_multi_step_aggregates_union():
    """Two steps → deduplicate, aggregate across union."""
    acc_data = {
        "step_0": {"rows": [{"deal_id": i, "deal_value": 1000} for i in range(200)],
                   "table": "deals"},
        "step_2": {"rows": [{"deal_id": i+150, "deal_value": 2000} for i in range(100)],
                   "table": "deals"},
    }
    # After deduplication: IDs 0-149 from step_0, IDs 150-249 from both (dedupe to 1)
    # Total unique: 250

    result = _extract_rows_from_accumulated(acc_data, mode="synthesis")
    assert result["row_count"] == 250  # deduplicated
    assert "aggregated from 2 steps" in result.get("_note", "")

def test_synthesis_payload_size():
    """500-row fetch → 20-row sample = predictable synthesis context."""
    rows = [{"deal_id": i, "deal_value": i*1000, "stage": "Discovery"}
            for i in range(500)]
    result = {"rows": rows, "table": "deals"}
    agg = _aggregate_and_sample(result, sample_size=20)

    import json
    payload = json.dumps(agg)
    # Aggregates + 20 rows should be < 10KB
    assert len(payload) < 10000
```

## Verification Steps

1. **git ls-tree origin/main** per changed file (before/after)

2. **Re-run forecast question** (should be unchanged):
   ```
   "What do you forecast for the quarter?"
   Expected: 10 rows pass through whole, no aggregation
   ```

3. **Ask new question** (should aggregate + sample):
   ```
   "Which deals have no ARR recorded?"
   Expected: "138 deals, 15 with no value recorded. The 20 largest are: ..."
   ```

4. **Measure synthesis payload size**:
   - Before: 27,969 chars (100 rows)
   - After: < 10,000 chars (20 sample + aggregates)

5. **Check logs**:
   ```
   [AGGREGATE] 138 rows → aggregates + 20-row sample
   [SYNTHESIS] payload size: 8,432 chars (was 27,969)
   ```

## Budget Impact

- Aggregation is cheap (Python, not LLM)
- Budget pressure came from raw rows → synthesis
- This removes that pressure
- Can likely raise MAX_ITERATIONS from 5 → 7
- Constraint was never iterations, it was payload size

## What This Replaces

- ❌ Remove hard cap of 50 in filter_table → ✅ 500 fetch ceiling
- ❌ Remove _cap_rows_for_synthesis → ✅ Aggregation before synthesis
- ✅ Keep entity extraction (preserves full populations)
- ✅ Add aggregate_and_sample (new stage between fetch and synthesis)

## Rollout

1. Implement `_aggregate_and_sample()` with tests
2. Modify `dynamic_query_loop()` to call it after tool execution
3. Update `_extract_rows_from_accumulated()` for multi-step dedup
4. Raise filter_table max_limit to 500
5. Remove `_cap_rows_for_synthesis()` and call site
6. Run tests + verification questions
7. Monitor synthesis payload sizes in production
8. Raise MAX_ITERATIONS if budget allows
