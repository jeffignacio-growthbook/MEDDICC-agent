# Aggregate-Then-Synthesize Implementation Complete

**Commit**: 79c4a78
**Based on**: `/Users/jeffignacio/Downloads/DESIGN_AGGREGATE_THEN_SYNTHESIZE.md`

## Problem Solved

The 50-row hard cap was wrong in both directions:
- **Waste**: Forecast answer needed 10 rows, got capacity for 50 (5x overhead)
- **Silent truncation**: "138 deals with no value" could only show 50, losing 88
- **Context bloat**: 100-row result = 27,969 chars → budget exhaustion

The cap tried to solve a context problem by discarding data — wrong lever.

## Solution

Three-stage pipeline with explicit boundaries:

### 1. Fetch (unbounded within reason)
- Raised `filter_table` max_limit from 50 → 500
- Safety ceiling on database queries, not synthesis budget
- Fetched rows never go direct to synthesis

### 2. Aggregate (in loop, before synthesis)
- When result > 20 rows:
  - Compute aggregates (sum/mean/min/max, counts by category, null counts)
  - Keep 20-row sample (largest/soonest based on ordering)
  - Add `truncated: true` and `sample_basis` description
- When result ≤ 20 rows: pass through whole (no aggregation overhead)

### 3. Synthesize (from summary)
- Never receives more than 20 rows
- Gets aggregates + sample + full counts
- Can say "138 deals totalling $4.2M — the ten largest are..."

## Files Changed

### api/router.py

**Added** `_aggregate_and_sample()` (lines 1137-1256):
```python
def _aggregate_and_sample(result: dict, sample_size: int = 20,
                         order_by: str = None) -> dict:
    """
    Aggregate large result sets and sample for synthesis.
    Small results (≤ sample_size) pass through whole.
    Large results get aggregated + sampled + truncation flag.
    """
```

**Modified** `dynamic_query_loop()` (lines 1815-1827):
```python
# Aggregate large results before storing for synthesis
order_by_param = tool_params.get("order_by") if tool_name == "filter_table" else None
aggregated = _aggregate_and_sample(result, sample_size=20, order_by=order_by_param)

if aggregated.get("truncated"):
    logger.info(f"[AGGREGATE] {aggregated['row_count']} rows → "
               f"aggregates + {len(aggregated.get('sample', []))}-row sample")
```

### api/tools.py

**Raised filter_table limit** (lines 46-51):
```python
# BEFORE:
max_limit = 50  # Hard cap for synthesis

# AFTER:
max_limit = 500  # Fetch ceiling (aggregation happens before synthesis)
```

### tests/test_aggregate_and_sample.py

**New test file** with full coverage:
- Small result passes through whole ✓
- Large result aggregated with sample ✓
- Null counts surface in aggregates ✓
- Stage counts computed correctly ✓
- Sample basis states ordering ✓
- Numeric aggregates (sum/mean/min/max) ✓
- Payload size controlled (500 rows → 3,880 bytes) ✓

## Aggregation Logic

### Numeric columns (deal_value, arr_usd, etc.)
```json
{
  "deal_value": {
    "sum": 4200000,
    "mean": 30434.78,
    "min": 5000,
    "max": 850000
  }
}
```

### Low-cardinality text (stage, segment, owner)
```json
{
  "stage_counts": {
    "Discovery": 87,
    "Scoping": 24,
    "Proposal": 27
  }
}
```

### Dates (close_date, created_at)
```json
{
  "close_date": {
    "earliest": "2026-08-01",
    "latest": "2027-01-31",
    "past_today": 15
  }
}
```

### Null counts (always)
```json
{
  "null_counts": {
    "deal_value": 15
  }
}
```

## Test Results

All tests passing:

```
✓ Small result passes through whole
✓ Large result aggregated with sample
✓ Null counts surface in aggregates
✓ Stage counts computed correctly
✓ Sample basis correct when no ordering
✓ Numeric aggregates (sum/mean/min/max) correct
✓ Payload size controlled: 3,880 bytes (500 rows → 20 sample)

✅ All tests passed
```

## Impact

### Before
- Hard cap: 50 rows
- 100-row result: 27,969 chars → budget exhaustion
- Silent truncation: "show all deals" → only 50, no indication
- Waste: forecast query gets 50-row capacity for 10 rows

### After
- Fetch ceiling: 500 rows (safety limit)
- 500-row result: 3,880 chars (aggregates + 20 sample)
- Explicit truncation: "138 deals totalling $4.2M — the 20 largest are..."
- Efficient: 10 rows pass through whole, no aggregation overhead

### Payload Size Comparison

| Scenario | Before | After | Savings |
|---|---|---|---|
| 10 rows (forecast) | ~2KB | ~2KB | 0% (pass-through) |
| 50 rows | ~14KB | ~4KB | 71% |
| 100 rows | 28KB | ~4KB | 86% |
| 500 rows | Would fail | ~4KB | 100% |

### Budget Impact

- Aggregation is cheap (Python, not LLM call)
- Budget pressure came from passing raw rows to synthesis
- This removes that pressure
- Can likely raise MAX_ITERATIONS from 5 → 7+

## Verification Questions

### 1. Forecast query (should be unchanged)
```
"What do you forecast for the quarter?"
Expected: 10 rows pass through whole, no aggregation
```

### 2. Large result query (should aggregate + sample)
```
"Which deals have no ARR recorded?"
Expected: "138 deals, 15 with no value recorded. The 20 largest are: ..."
```

### 3. Synthesis payload
- Before: Up to 28KB (100 rows)
- After: Max ~4KB (aggregates + 20 sample)

## What This Replaces

- ❌ Hard cap of 50 rows → ✅ 500 fetch ceiling + aggregation
- ❌ Silent truncation → ✅ Explicit aggregates + sample
- ❌ Fixed limit for all queries → ✅ Adaptive (small pass through, large aggregate)

## Next Steps (Optional)

1. Raise MAX_ITERATIONS from 5 → 7 (budget pressure removed)
2. Consider removing `_cap_rows_for_synthesis()` (line 2605) — now redundant
3. Monitor synthesis payload sizes in production logs
4. Track aggregation frequency to optimize column type detection

## Git State

**Before changes:**
```
api/router.py: 0e0ef994bdbd7c25c1dfe659f46457db29f09878
api/tools.py:  1812b31af0266860ee3dd0a73abb5261be91eb32
```

**After changes:**
```
Commit: 79c4a78 Implement aggregate-then-synthesize pattern
Files: api/router.py, api/tools.py, tests/test_aggregate_and_sample.py
```
