# Zero-Rows Suspicion Fix — Confident Wrong Answers

**Commit**: 5d61f1f
**Problem Type**: The more dangerous failure mode — confident wrong answer that reads as reassuring

## The Incident

**Question**: "Which deals have no ARR recorded?"

**Agent behavior**:
1. Query: `select=...arr_usd,new_arr,expansion_arr,renewal_revenue,deal_value&deal_value=is.null`
2. Result: 0 rows
3. Conclusion: "Every deal has ARR recorded" ← **confident, wrong**

**Reality**:
- Forecast answer minutes earlier mentioned 61 uncategorized deals
- Earlier analysis found renewals showing $0
- 138 deals with no value were found before

**Root cause**: `deal_value` is populated (0 or computed fallback) while component fields (`new_arr`, `expansion_arr`, `renewal_revenue`) are null. Agent filtered on wrong column, got zero rows, and asserted absence rather than questioning the filter.

## Why This Is Dangerous

This is worse than an obvious failure:
- An error says "I don't know" → user investigates
- A confident wrong answer says "everything is fine" → user trusts and moves on
- Silent data quality issues remain hidden

The zero-row result should have been **suspicious**, not **conclusive**.

## Two Fixes Implemented

### Fix 1: Semantic Fact About Missing ARR

**File**: `config/field_semantics.yaml` (lines 251-276)

Added section: **MISSING VALUE SEMANTICS — WHAT "NO ARR RECORDED" MEANS**

Key points:
```yaml
# "Which deals have no ARR recorded?" is ambiguous across five columns:
# deal_value, arr_usd, new_arr, expansion_arr, renewal_revenue.
#
# deal_value is often populated with 0 or a computed fallback even when the
# component fields are null, so filtering on deal_value=null returns zero rows
# and produces a confident wrong answer.
#
# A deal has no ARR recorded when BOTH conditions hold:
# 1. The pipeline-appropriate value field is null or zero:
#    - New business: deal_value (incremental ARR)
#    - Renewals: renewal_revenue (renewal base)
# 2. The component fields are also empty or zero:
#    - new_arr, expansion_arr, renewal_revenue all null/zero
#
# Correct filter approaches:
# - Check component fields: new_arr=is.null AND expansion_arr=is.null
# - Check zero values: deal_value=eq.0 OR deal_value=is.null
# - Aggregate first, then filter on computed "has_any_arr" flag
#
# Never filter on deal_value=is.null alone for "no ARR" questions.
```

**Also updated**: `scripts/utils.py` (lines 629-659)
- Added "Field Value Semantics" section to `build_semantic_context()`
- Includes missing value detection rules in semantic context
- Injected into all dynamic query loop prompts

### Fix 2: Zero-Rows Suspicion Check

**File**: `api/router.py` (lines 1847-1870)

Added suspicion check in `dynamic_query_loop()` after tool execution:

```python
# Zero-rows suspicion check: when a "which deals" question returns nothing,
# question the filter rather than asserting absence.
suspicion_note = ""
if row_count == 0 and tool_name == "filter_table":
    # Detect enumeration questions: "which", "show", "list", "what deals"
    enum_patterns = ["which", "show", "list", "what deals", "what are the"]
    if any(p in question.lower() for p in enum_patterns):
        filters_used = tool_params.get("filters", [])
        filter_desc = ", ".join([f"{f[1]}={f[0]}.{f[2]}" for f in filters_used])
        suspicion_note = (
            f"\n\n⚠️  SUSPICION: Zero rows on an enumeration question. "
            f"The filter ({filter_desc}) may be checking the wrong column or "
            f"the field may be defaulted rather than null. Consider: "
            f"(1) checking component fields instead of aggregate fields, "
            f"(2) checking for zero values not just nulls, or "
            f"(3) stating what was checked rather than asserting absence."
        )
```

This injects a suspicion note into the next message to the model, telling it:
- What filter was used
- Why zero rows is suspicious
- Three alternative approaches to try
- To state what was checked rather than assert absence

## Test Coverage

**File**: `tests/test_zero_rows_suspicion.py`

All tests passing:
```
✓ Enumeration questions detected correctly:
  - "which deals have no ARR recorded" → detected
  - "show me deals with zero value" → detected
  - "list all deals in Discovery" → detected

✓ Non-enumeration questions don't trigger false positives:
  - "what is the pipeline total" → not detected
  - "how much are we forecasting" → not detected

✓ Suspicion message format correct:
  - Contains "⚠️  SUSPICION"
  - States filter used (deal_value=is_.null)
  - Suggests alternatives (component fields, zero values)

✓ Semantic context includes missing value semantics:
  - "No ARR recorded" found
  - "deal_value is often populated with 0" found
  - "Zero-rows suspicion rule" found
  - "component fields" found
```

## Behavior Changes

### Before
```
Q: "Which deals have no ARR recorded?"
Agent: [filters on deal_value=is.null]
Result: 0 rows
Agent: "Every deal has ARR recorded. ✓"
User: [trusts wrong answer, moves on]
```

### After
```
Q: "Which deals have no ARR recorded?"
Agent: [filters on deal_value=is.null]
Result: 0 rows
System: ⚠️  SUSPICION: Zero rows on enumeration question...
Agent: "No deals had a null deal_value. That may mean the field is
        defaulted rather than that values are recorded — worth checking
        the component fields (new_arr, expansion_arr, renewal_revenue)."
User: [investigates further, finds real issue]
```

## Impact

### Semantic Guidance
- Model now knows "no ARR" is ambiguous across five columns
- Knows `deal_value` can be populated even when components are null
- Gets explicit correct filter approaches
- Won't confidently answer from wrong column alone

### Runtime Suspicion
- Zero rows on enumeration questions trigger warning
- Model told to question filter, not assert absence
- Suggests checking component fields, zero values
- States what was checked rather than what wasn't found

### False Positive Tolerance
- Prefer unnecessary suspicion over missed real issues
- "What deals" will trigger even on "what deals are closing" (total question)
- Better to question too often than miss a wrong filter once

## Related Fixes

This complements:
- **Aggregate-then-synthesize** (commit 79c4a78): Prevents context bloat from large results
- **Fiscal quarter normalization** (commit 7b59c44): Prevents format mismatches returning zero rows
- **Plausibility check registry divergence**: Already catches mismatched columns in precomputed handlers

This extends the "empty-result honesty rule" to queries that **succeeded but found nothing**, not just queries that failed.

## Verification Questions

### 1. Original failing question (should now be suspicious)
```
"Which deals have no ARR recorded?"
Expected: Model questions deal_value filter, suggests checking component fields
```

### 2. Similar enumeration questions
```
"Show me deals with zero value"
"List deals missing revenue data"
"What deals have no close date"
All should trigger suspicion on zero rows
```

### 3. Non-enumeration questions (should NOT trigger)
```
"What's the pipeline total?"
"How much ARR is in Discovery?"
These can legitimately return zero without suspicion
```

## Design Principle

**Empty-result honesty**: When a query finds nothing and the question implies something should exist, say what was checked rather than asserting absence.

This is defensive data quality practice — assume the schema or field population may not match expectations, especially on fields that are "nullable but populated with defaults."

## Next Steps (Optional)

1. Monitor suspicion trigger rate in production logs
2. Add similar check for other defaulted fields (stage, owner)
3. Consider proactive validation: "deal_value is populated for all deals — checking component fields for actual nulls"
4. Track confident wrong answers via learning_log for pattern analysis
