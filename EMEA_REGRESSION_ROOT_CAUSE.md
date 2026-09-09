# EMEA Regression Root Cause Analysis

**Date:** 2026-09-09
**Production Failure:** Slack query "How has EMEA pipeline moved in the last 2 weeks" returned fabricated "EMEA doesn't exist" claim
**Severity:** HIGH - Confidently wrong answer with fabricated claims

---

## Summary

Production query failed with TWO issues:
1. **Query generation bug (iteration 0):** Model didn't add region=eq.EMEA filter
2. **Premature answer (iteration 1):** Model answered from incomplete data instead of drilling down

Recent synthesis prompt changes (b830d2d, 0bdd0a5, f1d42d7) likely made issue #2 worse.

---

## Evidence

### Production Query (2026-09-09 17:12 UTC)

**Iteration 0:**
```
Query: waterfall_weekly
Filters: week_ending >= 2026-08-24, week_ending <= 2026-09-09
NO REGION FILTER ❌
Result: 50 rows (all regions: NAM, EMEA, APAC, LATAM, ROW, UNKNOWN mixed)
```

**Iteration 1:**
```
Answer: "⚠️ EMEA region isn't tracked as a distinct segment...
         There is no 'EMEA' bucket. EMEA deals are likely rolled into ROW."
FABRICATED ❌
```

### Test Query (2026-09-09 post-investigation)

**Iteration 0:**
```
Query: waterfall_weekly
Filters: week_ending >= 2026-08-24, region = EMEA
Result: 16 rows (EMEA only)
```

**Iteration 1:**
```
Answer: "EMEA pipeline movement over the last 2 weeks...
         Enterprise: $2.20M → $2.20M, Mid-Market: $1.12M → $1.12M..."
CORRECT ✅
```

### Database Verification

```sql
SELECT DISTINCT region FROM waterfall_weekly;
```

Result: APAC, EMEA, LATAM, NAM, ROW, UNKNOWN

**EMEA exists in data.** The production answer fabricated its absence.

---

## Root Cause Analysis

### Issue #1: Query Generation Failure (Iteration 0)

**What happened:**
- Model generated filter_table query for waterfall_weekly
- Extracted time range from question ("last 2 weeks")
- Did NOT extract region from question ("EMEA")
- Query returned all 50 rows across all regions

**Why intermittent:**
- Test query correctly extracted EMEA and filtered
- This is LLM variability in query generation, not systematic

**Not caused by synthesis changes:**
- Aggregation instruction added AFTER iteration 0
- Query generation happens before any synthesis prompt changes

### Issue #2: Premature Answer (Iteration 1)

**What happened:**
- Model received 50 rows (20-row sample + aggregates)
- Saw aggregation instruction: "Report data from EVERY row in retrieved results"
- Interpreted this as "I have all the data"
- Didn't realize rows were unfiltered (all regions mixed)
- Answered immediately instead of drilling down with region filter

**Why this is worse after synthesis changes:**

Recent changes (b830d2d, 0bdd0a5, f1d42d7) added:
```python
"Report data from EVERY row/week/segment in retrieved results"
"Only call another tool if essential data is still missing"
```

This instruction was meant to prevent dropping segments/weeks from synthesis.

**Unintended side effect:** Made model think having "every row" means having complete data, even when query was wrong.

**Before changes:**
- Model might have noticed EMEA not in sample → drilled down

**After changes:**
- Model saw "report EVERY row" → thought it had everything → answered

---

## Why Production Failed But Test Succeeded

**Production differences:**
1. User persona: Jeff Ignacio (RevOps) vs test (no persona)
2. History: Unknown (thread_ts from Slack) vs test (empty history)
3. LLM randomness: Different query generation choice at iteration 0

**Test succeeded because:**
- Query generation correctly filtered by region at iteration 0
- Model got clean EMEA data → synthesis worked correctly

**Key insight:** When query generation is correct, synthesis changes work fine. When query generation fails, synthesis changes make it less likely to recover.

---

## Is This Systematic?

**Short answer: Partially**

1. **Query generation bug:** INTERMITTENT (LLM variability)
   - Production: No region filter
   - Test: Had region filter
   - Not systematic regression

2. **Premature answer:** SYSTEMATIC (if query is wrong)
   - Before changes: Model might drill down after bad query
   - After changes: Model thinks it has "every row" and answers
   - This IS a regression in recovery behavior

---

## Impact Assessment

### User Trust Impact: HIGH

Production answer:
- Confidently stated EMEA doesn't exist (false)
- Suggested EMEA rolled into ROW (speculation)
- Provided ROW data as if it were EMEA (wrong)
- No indication of uncertainty

User has no way to know answer is wrong unless they check raw data.

### Frequency: UNKNOWN

- This is the first observed instance
- Query generation failures are intermittent (LLM variability ~10-30%?)
- Synthesis making them harder to recover from is new (post-fixes)

---

## Why This Wasn't Caught in Testing

**Yesterday's tests (6 total runs):**
- All had correct query generation (region filter present)
- Synthesis worked correctly on clean data
- Never tested what happens when query generation fails

**Gap in testing:** Didn't simulate "query gets wrong data, does synthesis recover?"

---

## Recommendations

### Immediate (High Priority)

**1. Add query validation check**
```python
# After iteration 0, check if question mentions a dimension that wasn't filtered
question_lower = question.lower()
if 'emea' in question_lower or 'nam' in question_lower:
    # Check if query filtered by region
    if 'region' not in str(result.get('filters', [])):
        # Add recovery instruction to next iteration
        messages.append({
            "role": "user",
            "content": "Note: Question asked about specific region (EMEA/NAM/etc.) "
                      "but your query didn't filter by region. Call filter_table again "
                      "with region filter to get region-specific data."
        })
```

**2. Modify aggregation instruction to be less absolute**
```python
# Current (too strong):
"Report data from EVERY row in retrieved results"

# Better:
"Report data from every row retrieved, but verify the query actually filtered
 for what the question asked (e.g., if question asked about EMEA, check that
 query filtered region=EMEA, not all regions)."
```

**3. Add explicit region extraction hint to schema context**
```python
# In waterfall_weekly schema description:
"region column: NAM, EMEA, APAC, LATAM, ROW, UNKNOWN.
 IMPORTANT: If question mentions a region name, filter by this column."
```

### Medium Priority

**4. Fix query_pipeline_movement handler to handle region filtering**
- Current confidence: 0.70-0.72 (below 0.80 threshold)
- Routes to dynamic_query by default
- Should be fixed to extract region and route correctly

**5. Add recovery mechanism:**
- If synthesis detects dimension mentioned in question but not in data
- Automatically call filter_table again with missing dimension filter
- Don't require model to realize it needs to drill down

### Long Term

**6. Testing protocol:**
- Test not just "does it work when query is correct"
- Test "does it recover when query is wrong"
- Deliberately inject bad queries to test recovery

---

## Files

**Investigation:**
- investigate_emea_regression.py
- test_emea_regression_repro.py

**Documentation:**
- This file

**Production logs:**
- Railway logs 2026-09-09 17:11-17:12 UTC

---

## Next Steps

1. ✅ Confirm EMEA exists in data
2. ✅ Compare production vs test query patterns
3. ✅ Test if reproducible (intermittent)
4. ⏳ Implement query validation check (recommended #1)
5. ⏳ Modify aggregation instruction to be less absolute (recommended #2)
6. ⏳ Add 7-day monitoring for similar failures

---

## Conclusion

**This is a real regression, but not the one expected.**

- Synthesis prompt changes didn't break query generation
- They DID make recovery harder when query generation fails
- The instruction "report EVERY row" made model think incomplete data was complete
- This is fixable with validation checks + softer instruction wording

**Not a synthesis bug** - synthesis worked correctly on the data it received.
**IS a recovery bug** - model didn't realize data was wrong and drill down.
