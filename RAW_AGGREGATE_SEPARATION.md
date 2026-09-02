# Raw and Aggregate Storage Separation

**Commit**: 8231964
**Context**: Entity extraction and synthesis need different views of the same data

## The Issue

**Observation from logs**:
```
[TOOL] filter_table rows=200
[AGGREGATE] 200 rows → aggregates + 20-row sample
[STORE] saved step_0 with 200 rows      ← says 200, not the sample
```

**Question**: What does `accumulated_data["step_0"]` actually hold?

**Answer**: Only the aggregated result (20-row sample), not the raw 200 rows.

**Problem**: Entity extraction and synthesis both read from `accumulated_data`, but need different views:
- **Entity extraction** should read **raw rows** (all 200 deal_ids)
- **Synthesis** should read **aggregated result** (20 sample + aggregates)
- Both reading the same view breaks entity extraction

## Why This Matters

### Entity Extraction (Correct Behavior)
```python
# Question: "Which deals are at risk?"
# Result: 200 deals from query
# Entity extraction should preserve all 200 deal_ids
# Next question: "Show me those deals" → needs all 200 IDs
```

If entity extraction only sees 20-row sample:
- Stores 20 deal_ids instead of 200
- Follow-up questions lose context for 180 deals
- Silent data loss, no error

### Synthesis (Correct Behavior)
```python
# Question: "Which deals have no ARR recorded?"
# Result: 200 deals from query
# Synthesis should read 20-row sample + aggregates
# Answer: "200 deals with no value recorded. The 20 largest are: ..."
```

If synthesis reads raw 200 rows:
- Context bloat (27,969 chars for 100 rows)
- Budget exhaustion
- Defeats purpose of aggregation

## The Fix

**Store BOTH raw and aggregated results with clear separation:**

### Storage (lines 1843-1857)
```python
# Before:
accumulated_data[f"step_{iteration}"] = aggregated  # Only aggregate

# After:
accumulated_data[f"step_{iteration}_raw"] = result      # Full rows for extraction
accumulated_data[f"step_{iteration}"] = aggregated      # Sample for synthesis
```

**Log output**:
```
[STORE] saved step_0: 200 rows total (20 in aggregate, 200 in raw)
```

### Extraction Logic (lines 1306-1332)

**Synthesis mode** (reads aggregates):
```python
# Filter out _raw keys — synthesis reads aggregates only
step_keys = sorted([k for k in accumulated_data.keys()
                   if not k.endswith("_raw")], reverse=True)
for step_key in step_keys:
    step_data = accumulated_data.get(step_key, {})
    rows = step_data.get("rows", [])  # Gets 20-row sample
    if rows:
        logger.info(f"[EXTRACT] synthesis mode: returning {len(rows)} rows from {step_key} (aggregate)")
        return {"rows": rows, ...}
```

**Entity extraction mode** (reads raw):
```python
# Scan _raw steps to get full populations
raw_step_keys = sorted([k for k in accumulated_data.keys()
                       if k.endswith("_raw")], reverse=True)
for step_key in raw_step_keys:
    step_data = accumulated_data.get(step_key, {})
    rows = step_data.get("rows", [])  # Gets all 200 rows
    if matching_entities:
        entity_bearing_steps.append((step_key, step_data, matching_entities))
```

## Data Flow

### Question: "Which deals have no ARR recorded?"

**Step 0: Query executes**
```
[TOOL] filter_table rows=200
Result: 200 deals with all five value columns
```

**Step 1: Aggregation**
```
[AGGREGATE] 200 rows → aggregates + 20-row sample
aggregated = {
  "row_count": 200,
  "aggregates": {
    "deal_value": {"sum": 0, "mean": 0, "min": 0, "max": 0},
    "null_counts": {"new_arr": 200, "expansion_arr": 200, "renewal_revenue": 200}
  },
  "sample": [20 rows],
  "complete": true,
  "_note": "COMPLETE RESULT: All 200 rows were aggregated..."
}
```

**Step 2: Storage (BOTH views)**
```python
accumulated_data["step_0_raw"] = result       # 200 full rows
accumulated_data["step_0"] = aggregated       # 20 sample + aggregates
```

**Step 3a: Entity extraction (reads raw)**
```
[EXTRACT] mode=entity_extraction
Reading from: step_0_raw
Result: 200 deal_ids preserved for follow-up context
```

**Step 3b: Synthesis (reads aggregate)**
```
[EXTRACT] mode=synthesis
Reading from: step_0 (aggregate)
Result: 20-row sample + aggregates for answer
```

**Step 4: Answer**
```
"200 active deals have no ARR recorded in component fields
(new_arr, expansion_arr, renewal_revenue all null).
The 20 largest by deal_value are: [list]"
```

**Step 5: Follow-up** (uses entity extraction)
```
Q: "Show me those deals"
Entity context: 200 deal_ids from step_0_raw
Result: All 200 deals shown (not just 20)
```

## Verification Checklist

Ready to test: **"Which deals have no ARR recorded?"**

**Watch for**:
1. ✅ `[AGGREGATE]` firing (confirms aggregation runs)
2. ✅ No duplicate tool call execution after detection (confirms short-circuit)
3. ✅ Real count in answer, not budget exhausted (confirms completeness markers work)
4. ✅ `[STORE] ... (20 in aggregate, 200 in raw)` (confirms dual storage)
5. ⚠️  Count verification: Earlier work suggested 138 deals with no value, but query pulled 200 active deals

**Count verification**:
- This is the third attempt at establishing the true number
- Worth verifying answer against direct SQL count
- Expected: ~200 active deals with null component fields
- If different: investigate which population is correct

## Lesson Learned

**"truncated: true" was honest metadata that read as an instruction to retry.**

The field was technically accurate but semantically confusing:
- Told model "this result is truncated"
- Model interpreted: "I need to fetch the rest"
- Repeated query to get "missing" data

**Fix**: Explicit completeness markers
- `"complete": true` — clear boolean flag
- `"_note"` — explains what the result means
- States: "All 200 rows were aggregated. Do not re-query."

**Wording in a payload the model reads is as load-bearing as the data.**

Metadata fields aren't just documentation — they're instructions. The model treats them as semantic facts about what to do next.

## Related Fixes

- **Aggregate-then-synthesize** (commit 79c4a78): Core pattern implementation
- **Duplicate short-circuit** (commit 69c5677): Prevent wasted tool execution
- **Completeness markers** (commit 69c5677): Signal result is complete
- **Raw/aggregate separation** (commit 8231964): Dual-purpose data storage

The stack is now complete:
1. ✅ Aggregation reduces synthesis context
2. ✅ Completeness prevents retry loops
3. ✅ Duplicate detection short-circuits
4. ✅ Raw storage preserves entity extraction

Ready for production testing.
