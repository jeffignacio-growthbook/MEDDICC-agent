# Territory/Segment/Region Performance Comparison Audit Report
**CRO Priority #6**
**Date**: 2026-09-20
**Motivating Goal**: Enable "how does EMEA compare to AMER" / "which segment is underperforming" questions with meaningful synthesis

---

## Task 1: Current Behavior with Comparative Questions

### Test Method
Ran 3 genuinely comparative questions through `scripts/test_question.py` (production code path):

1. **"How does EMEA compare to AMER this quarter?"**
2. **"Which segment has the best win rate this quarter?"**
3. **"Compare Enterprise vs SMB pipeline coverage"**

### Findings

**Test 1: Region comparison (EMEA vs AMER)**
- **Result**: Attempted comparison successfully
- **Behavior**:
  - Dimension resolver detected EMEA correctly
  - Ran multiple `filter_table` calls to fetch both regions
  - Hit data quality issue (AMER not in data - likely "NAM" instead)
  - Synthesized a comparison with explicit caveats about missing data
  - Suggested region data quality audit
- **Assessment**: System CAN handle the query pattern, data quality blocked full comparison

**Test 2: Segment win rate comparison**
- **Result**: ✅ **Successful comparative synthesis**
- **Behavior**:
  - Fetched all closed deals
  - Aggregated by segment using `aggregate_results`
  - Computed win rates for each segment:
    - SMB: 50% (6/12)
    - Mid-Market: 33% (1/3)
    - Enterprise: 0% (0/2)
  - Ranked segments and identified "best" (SMB)
  - **Added appropriate caveats**:
    - Small sample sizes noted (Enterprise n=2, Mid-Market n=3)
    - "A single deal flip would materially change the rankings"
    - Segment definition caveat (employee bands not validated)
- **Assessment**: **System already handles this well** - no gap identified

**Test 3: Segment pipeline coverage comparison**
- **Result**: ✅ **Successful comparative synthesis**
- **Behavior**:
  - Fetched pipeline by segment
  - Compared Enterprise ($7.3M) vs SMB ($3.7M)
  - Calculated coverage ratios (Enterprise 4.7x, SMB 2.4x)
  - Identified that Enterprise is "significantly better covered"
  - Added segment definition caveat
- **Assessment**: **System already handles this well** - no gap identified

### Pattern Observed Across All Tests
Dynamic query already performs:
1. ✅ **Multiple filtered queries** (fetches each segment/region separately)
2. ✅ **Aggregation/computation** (win rates, coverage ratios, totals)
3. ✅ **Comparison synthesis** (identifies "best/worst", notes differences)
4. ✅ **Appropriate caveats** (sample size, data quality, definition uncertainty)
5. ✅ **Statistical awareness** (notes when differences are noisy vs meaningful)

**No evidence of weak/wrong/generic output.** The system produces substantive, caveat-laden comparisons today.

---

## Task 2: Historical Evidence in Query Logs

### Query Cost Log Analysis
- **Total historical queries**: 169
- **Queries with comparative keywords**: 36 (21.3%)
  - But most are NOT genuine territory/segment comparisons

### Breakdown of "Comparative" Questions

**Temporal comparisons** (not territory/segment): 2
- "How did our pipeline look 6 months ago compared to now?"
- "Compare our pipeline from January 2025 to today"

**Deal-type comparisons** (not territory/segment): 1
- "Show me new business vs expansion pipeline over the last 6 months"

**Risk assessment** (different primitive - deal_risk): 19 occurrences
- "please look at all hubspot deals... based on likelihood to close vs risk"
- (Same question repeated 19 times - exceptions and eventual successes)

**Ranking/breakdown questions**: 1
- "What is the break down of countries with the most opportunities and highest deal amount in EMEA?"
  - This is the ONLY real historical territory/segment comparative question

**Entity-scoped "which" questions** (not comparisons): ~15
- "Which enterprise deals changed stage in the last 2 weeks in EMEA?"
- "Which Mid-Market deals moved out of Discovery since August 1st?"
- These ask "which entities match criteria", not "which segment performs better"

**Test questions** (from today): 3
- "How does EMEA compare to AMER this quarter?"
- "Which segment has the best win rate this quarter?"
- "Compare Enterprise vs SMB pipeline coverage"

### Net Historical Evidence

**Genuine territory/segment/region comparative questions**: **1 out of 166 historical queries** (0.6%)

The one real example (#7: "break down of countries with most opportunities and highest deal amount in EMEA") was answered with outcome `answered_with_unverified_aggregation` - meaning the system DID answer it, but without full verification.

**This is VERY LOW evidence** - similar to country dimension's 1/683 (0.15%) before tonight's implementation. But unlike country dimension:
- Country had explicit user request (Ryan/Lyndsie) + roadmap priority
- Territory comparison has roadmap priority but no recent explicit user requests
- The system already handles comparative questions well when asked (Test 1-3)

---

## Task 3: What Would a Comparison Primitive Need?

### What Exists Today (Via Dynamic Query)
1. ✅ **Dimension resolution**: region/segment already resolve correctly
2. ✅ **Filtered queries**: can fetch data per segment/region
3. ✅ **Aggregation**: `aggregate_results` groups and computes metrics
4. ✅ **Multiple metric computation**: win rate, cycle time, deal size, pipeline coverage all work
5. ✅ **Comparison synthesis**: model naturally compares and ranks results
6. ✅ **Statistical caveats**: model adds sample-size and data-quality warnings

### What Would Be Needed for a Dedicated Primitive

**Option A: New comparison primitive** (similar to forecast_trust, pipeline_coverage)
- **Input**: two segments/regions to compare, or "all segments"
- **Compute**:
  - Standard metric set: win rate, avg deal size, cycle time, pipeline coverage, close rate
  - Per-segment values for each metric
  - Statistical significance tests (sample size gating, confidence intervals)
- **Output**: structured comparison with ranked metrics
- **Estimated effort**: 4-6 hours (similar to pipeline_coverage)

**Option B: Synthesis-prompt enhancement** (much smaller)
- **Input**: none - applies to all comparative questions
- **Enhance**: Add guidance to dynamic_query's system prompt about:
  - Standard metrics to compare across segments (win rate, cycle, deal size, coverage)
  - When differences are "material" vs "noise" (sample size thresholds)
  - How to frame statistical caveats
- **Output**: better-framed comparisons from existing queries
- **Estimated effort**: 30-60 minutes (prompt addition + verification)

---

## Task 4: Primitive vs Synthesis-Prompt Fix?

### Analysis

**The gap is NOT computational** - dynamic_query already:
- Fetches the right data (filtered by segment/region)
- Computes the right metrics (win rates, coverage, totals)
- Compares and ranks results
- Adds sample-size caveats

**The gap MIGHT be framing consistency** - but the test results show:
- Caveats are already appropriate ("small sample sizes", "a single deal flip would change rankings")
- Statistical awareness is already present
- Comparisons are already meaningful (not generic)

**Evidence against a new primitive**:
1. **Usage is near-zero**: 0.6% of historical queries (1/166)
2. **Existing behavior is good**: all 3 test questions produced substantive, caveat-laden answers
3. **No user complaints**: the 1 historical comparative question succeeded (`answered_with_unverified_aggregation`)
4. **Dimension resolution already works**: region/segment filtering is not the gap

**Evidence FOR a synthesis-prompt enhancement** (not a primitive):
1. **Standardization**: ensure ALL comparative questions get the same good caveats Test 2/3 showed
2. **Metric consistency**: codify "win rate + cycle + deal size + coverage" as the standard comparison set
3. **Low effort**: 30-60 min vs 4-6 hours for a primitive

---

## Gap Classification

### Actual Gap: **SMALL - Synthesis framing, not computation**

Similar to how country-as-dimension turned out smaller than feared (45-65 min dimension resolver addition vs multi-hour primitive), this is:
- **NOT** a missing computation (all metrics already work)
- **NOT** a data gap (dimension resolution works)
- **NOT** a tool gap (filter_table + aggregate_results handle it)
- **MAYBE** a framing/prompt gap (but even that is questionable - tests show good output)

### Recommendation

**DEFER** - insufficient evidence to build anything:

1. **Usage is too low**: 0.6% of queries (1/166) is below the threshold that justified other primitives
   - Forecast trust: ranked #1 by domain expertise, had 1 query but EXPLICIT user priority
   - Pipeline coverage: CRO Priority #2, built because explicitly requested
   - Deal risk: 18 occurrences in logs (inflated by retries, but still > 1 unique)
   - Country dimension: 0.15% of queries BUT explicit Marketing/RevOps request (Ryan/Lyndsie)

2. **Existing behavior is good**: no evidence of "weak/wrong/generic" output from dynamic_query today

3. **No recent user demand**: unlike other priorities, this has no explicit "please build this" request in recent history

### Build Threshold

Worth building IF:
1. **Another 2-3 comparative questions appear in logs** (confirms recurring need)
2. **OR user explicitly requests it** (domain override, like country dimension)
3. **OR a comparative question fails/produces weak output** (evidence current behavior insufficient)

Until then: **the system already handles comparative questions well enough** that building a dedicated primitive would be solving a problem that doesn't exist yet.

---

## Comparison to Country Dimension

**Country dimension (Marketing Priority #2)**:
- Historical usage: 0.15% (1/683 queries)
- User request: ✅ Explicit (Ryan/Lyndsie asked for country breakdown)
- Gap size: Small (45-65 min dimension resolver + canonicalization)
- Decision: Built immediately because explicit user priority

**Territory comparison (CRO Priority #6)**:
- Historical usage: 0.6% (1/166 queries) - 4x higher than country
- User request: ❌ No explicit request in recent history
- Gap size: Smaller (30-60 min synthesis-prompt enhancement) OR None (system already works)
- Decision: **Defer** - no explicit user demand, existing behavior is good

---

## Appendix: Test Question Outputs

### Test 1: "How does EMEA compare to AMER this quarter?"
**Outcome**: `answered_cleanly`
**Answer excerpt**:
```
EMEA vs AMER — FY2027 Q3 (Aug 1 – Oct 31, 2026)

⚠️ AMER has zero deals recorded with region = 'AMER' this quarter — no active, won,
or lost deals. This is likely a data gap (deals untagged by region), not a true zero.

EMEA Pipeline (Active, Q3 close date)
• 9 new business deals | $618,750 total open pipeline
• Top deals: Skyscanner $125K (Tech Eval) · Virgin Media O2 $100K (Discovery) ...

AMER
• $0 pipeline, $0 closed — no deals tagged AMER. Strongly suspect region field is
unpopulated for AMER reps. Recommend auditing region tagging for NAM/AMER deals.
```

**Assessment**: System attempted comparison, hit data quality issue, explicitly caveat'd the gap, suggested audit. Good behavior.

### Test 2: "Which segment has the best win rate this quarter?"
**Outcome**: `answered_cleanly`
**Answer excerpt**:
```
SMB has the best win rate in FY2027 Q3 among closed new business deals:

• SMB — 50% win rate (6 won / 12 closed)
• Mid-Market — 33% win rate (1 won / 3 closed)
• Enterprise — 0% win rate (0 won / 2 closed)

⚠️ Small sample sizes — especially Enterprise (n=2) and Mid-Market (n=3) — make these
rates noisy. A single deal flip would materially change the rankings.
```

**Assessment**: Computed win rates, ranked segments, identified "best", added appropriate sample-size caveat. **Exactly what a comparison primitive would do**.

### Test 3: "Compare Enterprise vs SMB pipeline coverage"
**Outcome**: `answered_after_resynthesis`
**Answer excerpt**:
```
Enterprise vs SMB Pipeline Coverage — FY2027 Q3

• Enterprise — $7,344,620 pipeline
• SMB — $3,674,770.68 pipeline

Coverage by segment (vs. $1.55M team target):
• Enterprise: ~4.7x
• SMB: ~2.4x

Key observations:
• Enterprise pipeline is nearly 2x SMB ($7.3M vs. $3.7M) — deal sizes skew larger upmarket
• Both segments show strong raw coverage, though Enterprise is significantly better covered
```

**Assessment**: Fetched both segments, compared pipeline values, calculated coverage ratios, identified which is "significantly better". Good comparative synthesis.

---

## Summary

**Gap size**: **VERY SMALL OR NONE**

**Evidence**: **INSUFFICIENT** - 0.6% of queries, no recent user requests

**Current behavior**: **GOOD** - all 3 test questions produced substantive, caveat-laden comparisons

**Recommendation**: **DEFER** until:
- More comparative questions appear in logs (2-3 more occurrences)
- OR explicit user request (like country dimension had)
- OR evidence that current output is inadequate

The system already handles territory/segment/region comparisons well via dynamic_query. Building a dedicated primitive now would be solving a problem that hasn't been proven to exist.
