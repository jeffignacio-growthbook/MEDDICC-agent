# Segment Name Regression Investigation

**Date:** 2026-09-09
**Issue:** Original test showed dollar-value references instead of segment names
**Question:** Was this a side effect of aggregation fix or coincidental?

---

## Original Observation

First test of synthesis fix (commit 0bdd0a5) showed:
```
Week of Aug 28 — Net −$120K
• $20K won (closed out of $1.12M segment)
• $100K lost (dropped from $979K segment)
```

Instead of expected:
```
• Mid-Market: $20K won
• SMB: $100K lost
```

**Hypothesis A:** Aggregation instruction inadvertently discouraging segment labels
**Hypothesis B:** Coincidental phrasing in one test run

---

## Investigation Method

**Test 1:** Run 3 different query types to check if pattern is query-specific
- EMEA pipeline movement (region + segment)
- Win rate by segment (segment only)
- Pipeline by region (region only)

**Test 2:** Run same EMEA query 3 times to check if pattern is intermittent
- Repeat exact query to detect LLM variability
- Check consistency across runs

---

## Test Results

### Multi-Query Test (3 different questions)

| Test | Type | Explicit Names | Dollar Refs | Pass/Fail |
|------|------|----------------|-------------|-----------|
| EMEA pipeline | region+segment | 5/5 (100%) | 0 | ✅ Pass |
| Win rate | segment | 0/3 (0%) | 0 | ⚠️ Budget exhaustion (invalid) |
| Pipeline by region | region | 5/5 (100%) | 0 | ✅ Pass |

**Result:** 2 of 3 valid tests showed 100% explicit naming

### Repeat Test (same EMEA query 3x)

| Run | Segment Names | Dollar Refs | Pass/Fail |
|-----|---------------|-------------|-----------|
| 1 | 4/4 (100%) | 0 | ✅ |
| 2 | 4/4 (100%) | 0 | ✅ |
| 3 | 4/4 (100%) | 0 | ✅ |

**Result:** 3/3 runs showed 100% explicit naming, ZERO dollar-value references

---

## Answer Samples

### Run 1 (Repeat Test)
```
*Week of Aug 17:*
• Enterprise: flat ($2.20M → $2.20M)
• Mid-Market: flat ($1.12M → $1.12M)
• SMB: -$30K ($1.01M → $980K)
• Unknown segment: -$75K lost ($125K → $50K)
```

### Run 2 (Repeat Test)
```
*Week of Aug 17:*
• Enterprise: $2.20M → $2.20M (flat)
• Mid-Market: $1.12M → $1.12M (flat)
• SMB: $1.01M → $979.5K (–$30K)
• Unknown segment: $125K → $50K (–$75K lost)
```

### Run 3 (Repeat Test)
```
*Week of Aug 17:*
• Enterprise: Flat ($2.20M → $2.20M)
• Mid-Market: Flat ($1.12M → $1.12M)
• SMB: -$30K ($1.01M → $979.5K)
• Unknown: -$75K lost ($125K → $50K)
```

**Pattern:** All runs explicitly name segments (Enterprise, Mid-Market, SMB, Unknown)

---

## Verdict

**Hypothesis B confirmed:** Dollar-value references were **coincidental/one-off**, not a regression.

**Evidence:**
1. Repeat tests show 100% consistent explicit naming (12/12 segments across 3 runs)
2. Multi-query tests show 100% explicit naming when queries succeed (10/10 dimensions)
3. Zero dollar-value references across 6 total test runs
4. Original test was an outlier in LLM phrasing, not a pattern

**Conclusion:** The aggregation fix did NOT cause segment name regression.

---

## Preventive Measure

While current behavior is correct, added explicit dimension naming instruction to prevent future variability:

```python
"⚠️  USE EXPLICIT DIMENSION NAMES:"
"• Use actual segment names (Enterprise, Mid-Market, SMB) not '$1.12M segment'"
"• Use actual region names (NAM, EMEA, APAC) not '$2.20M region'"
"• Use actual stage names from data, not generic 'pipeline stage'"

"Correct: 'Mid-Market: $20K won, SMB: $100K lost'"
"Wrong: '$20K won (closed out of $1.12M segment)' ← name the segment!"
```

**Rationale:** While it's working now (100% explicit), adding instruction makes it:
- More robust against LLM variability
- Self-documenting for future prompt changes
- Aligned with user's principle: "report every row" AND "name what you're reporting"

---

## Files

**Test Scripts:**
- test_segment_name_regression.py — Multi-query test (3 different questions)
- test_emea_repeat.py — Repeat test (same query 3x)

**Results:**
- Multi-query: 76.9% explicit (but 1 test invalid due to budget exhaustion)
- Repeat test: 100% explicit across all runs

**Code Changes:**
- api/router.py:2287-2302 — Added dimension naming instruction (synthesis)
- api/router.py:1872 — Added dimension naming instruction (finalization)

**Commits:**
- [TBD] — Add explicit dimension naming instruction

---

## Recommendation

✅ **Proceed with current fix** (aggregation + zero/missing + dimension naming)

**Monitoring:**
- Watch for dollar-value references in production (should be 0%)
- If any appear, check if they're in complex multi-dimensional breakdowns
- Current instruction should prevent recurrence

**No further action needed** unless production shows different pattern than test results.
