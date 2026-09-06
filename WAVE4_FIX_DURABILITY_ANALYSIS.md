# Wave 4 Fix Durability Analysis

## Problem Statement

Items 6, 8, 9 were fixed via DYNAMIC_SYSTEM_PROMPT guidance, not structural code.
This creates drift risk:
- Prompt rewrites lose the guidance
- Rephrased questions bypass the pattern matching
- No enforcement mechanism like field_semantics or dedicated handlers

This analysis assesses each fix for durability and proposes structural alternatives.

---

## Item 6: q020 - Field Extraction ("missing owner_email")

**Current Fix:** Prompt-guidance
- Added MISSING VALUE DETECTION section to DYNAMIC_SYSTEM_PROMPT
- Pattern: "For 'missing X' questions, extract field name and filter with is_ null"

**Structural Alternative:** None practical
- Field extraction from natural language inherently requires prompt understanding
- No way to hardcode "missing X" → field_name mapping for arbitrary fields
- This is a legitimate use of prompt guidance (NLP pattern recognition)

**Durability:** ⚠️ Soft (prompt-dependent)
**Recommendation:** Keep as prompt-guidance, but add to prompt engineering review checklist

**Rephrase Robustness Test:** Will test 3 variations below

---

## Item 7: q003 - Synthesis Truncation ("showing 20 of 142 deals")

**Current Fix:** Prompt-guidance
- Added _truncated to exceptions list in synthesis prompt
- Instructed: "Always lead with total count when _truncated present"

**Structural Alternative:** ✅ POSSIBLE - Enforce in synthesis code
```python
# In router.py synthesis generation:
def _synthesize_with_count_preservation(tool_results, ...):
    # BEFORE sending to LLM:
    # 1. Check if any _truncated keys exist
    # 2. Extract total counts
    # 3. Prepend count statement to synthesis prompt as hard constraint
    # OR: Post-process synthesis to inject count if missing
```

**Durability:** ⚠️ Soft (prompt-dependent)
**Recommendation:** Make structural - enforce count preservation in synthesis code

**Rephrase Robustness Test:** Will test 3 variations below

---

## Item 8: q011 - Pipeline Over-Filtering ("What is our pipeline?")

**Current Fix:** Prompt-guidance
- Added DEFAULT SCOPING section to DYNAMIC_SYSTEM_PROMPT
- Instructs: "Generic pipeline means ALL active deals, no implicit filters"

**Structural Alternative:** ✅ SHOULD EXIST - Create dedicated handler
```python
# api/handlers.py
async def query_pipeline(params: dict, sb) -> dict:
    """
    Current pipeline snapshot: all active deals with totals.

    Default scope: ALL active deals (no filters)
    Optional filters (only if explicitly in params):
    - stage_filter: qualified/discovery/proposal
    - pipeline_filter: new_business/renewal
    - owner_filter: specific rep
    """
    # Structural enforcement: default to NO filters
    filters = [("eq", "deal_status", "active")]

    # Only add filters if explicitly requested
    if params.get("stage_filter"):
        filters.append(...)
    # etc.
```

**Durability:** ⚠️ Soft (prompt-dependent)
**Recommendation:** ✅ CREATE STRUCTURAL - Add dedicated query_pipeline handler

**Rephrase Robustness Test:** Will test 3 variations below

---

## Item 9: q016 - Cycle Time ("sales cycle time")

**Current Fix:** Prompt-guidance
- Added CYCLE TIME CALCULATION section to DYNAMIC_SYSTEM_PROMPT
- Instructs: "Use close_date - create_date, median not average, all closed deals"

**Structural Alternative:** ✅ SHOULD EXIST - Create utility function or handler
```python
# api/handlers.py
def compute_cycle_time(sb, since_date: str = None) -> dict:
    """
    Canonical sales cycle time calculation.

    Single source of truth for cycle time methodology:
    - ALL closed deals (won + lost)
    - Calculation: close_date - create_date (days)
    - Aggregation: MEDIAN (not average)
    - Returns: median, p25, p75, sample size, date range
    """
    # Structural enforcement of correct methodology
    deals = sb.table("deals").select(
        "deal_id,create_date,close_date,deal_status"
    ).in_("deal_status", ["won", "lost"])

    if since_date:
        deals = deals.gte("close_date", since_date)

    cycle_times = [
        (parse_date(d["close_date"]) - parse_date(d["create_date"])).days
        for d in deals.execute().data
        if d["close_date"] and d["create_date"]
    ]

    return {
        "median_days": median(cycle_times),
        "p25_days": percentile(cycle_times, 25),
        "p75_days": percentile(cycle_times, 75),
        "sample_size": len(cycle_times),
        # ...
    }
```

**Durability:** ⚠️ Soft (prompt-dependent)
**Recommendation:** ✅ CREATE STRUCTURAL - Add compute_cycle_time() utility

**Rephrase Robustness Test:** Will test 3 variations below

---

## Summary Table

| Item | Fix Type | Structural Alternative | Durability | Action |
|------|----------|----------------------|------------|--------|
| q020 | Prompt | None (NLP inherent) | ⚠️ Soft | Document as legitimate prompt-guidance |
| q003 | Prompt | ✅ Synthesis code | ⚠️ Soft | Make structural (enforce in code) |
| q011 | Prompt | ✅ Dedicated handler | ⚠️ Soft | **CREATE query_pipeline handler** |
| q016 | Prompt | ✅ Utility function | ⚠️ Soft | **CREATE compute_cycle_time()** |

---

## Rephrase Testing Protocol

For each fix, test 3 rephrased versions of the original question:
- Different wording (synonyms, sentence structure)
- Different specificity (more/less explicit)
- Different context (embedded in longer question)

Pass criteria: Fix must work for ALL 3 rephrasings, not just the calibration question.

Failure indicates overfitting to test case.

---

## Next Steps

1. **Rephrase Testing** - Test all 4 fixes with variations (see below)
2. **Structural Fixes** - Implement query_pipeline handler and compute_cycle_time utility
3. **Re-test** - Verify structural fixes work on rephrases
4. **Re-calibration** - Run full Wave 4 with fresh verified values
5. **Documentation** - Update fix durability status in this document

---

## Rephrase Test Results

### q020: Field Extraction
Original: "How many active deals are missing owner_email?"

Rephrase 1: "Which deals have no owner assigned?"
- Expected: Filter owner_email IS NULL
- Result: [PENDING]

Rephrase 2: "Show me deals without owner_email"
- Expected: Filter owner_email IS NULL
- Result: [PENDING]

Rephrase 3: "How many deals don't have an owner?"
- Expected: Filter owner_email IS NULL
- Result: [PENDING]

**Status:** [PENDING]

---

### q003: Synthesis Truncation
Original: "Which deals have no ARR recorded?"

Rephrase 1: "Show me all deals with no ARR"
- Expected: Total count stated (not just sample size)
- Result: [PENDING]

Rephrase 2: "Which deals are missing ARR values?"
- Expected: Total count stated
- Result: [PENDING]

Rephrase 3: "How many deals have zero ARR?"
- Expected: Total count stated
- Result: [PENDING]

**Status:** [PENDING]

---

### q011: Pipeline Over-Filtering
Original: "What is our pipeline this quarter?"

Rephrase 1: "How much pipeline do we have?"
- Expected: ALL active deals (not filtered to qualified/new-business)
- Result: [PENDING]

Rephrase 2: "Show me the pipeline"
- Expected: ALL active deals
- Result: [PENDING]

Rephrase 3: "What's in our pipeline right now?"
- Expected: ALL active deals
- Result: [PENDING]

**Status:** [PENDING]

---

### q016: Cycle Time
Original: "Would you be able to calculate historical win rates by stage, sales cycle times..."

Rephrase 1: "What's our average sales cycle?"
- Expected: Median (not average), close_date - create_date, all closed deals
- Result: [PENDING]

Rephrase 2: "How long does it take to close deals?"
- Expected: Median, correct date fields
- Result: [PENDING]

Rephrase 3: "What's the typical time from opportunity to close?"
- Expected: Median, correct date fields
- Result: [PENDING]

**Status:** [PENDING]
