# Synthesis Aggregation Bug - Time-Range Queries

**Date:** 2026-09-09
**Severity:** High - silent failure mode, no reconciliation check possible
**Status:** Identified, not yet fixed

---

## Discovery

While verifying the waterfall integration fix from Sept 8, a Slack query revealed a synthesis bug:

**User Question:** "How has EMEA pipeline moved in the last 2 weeks"

**LLM Response:** "$0 across all movements"

**Actual Data:** $20K won + $175K lost = $195K total activity

---

## Root Cause Analysis

### Data Retrieved (Correct)
The backend correctly retrieved 20 EMEA waterfall rows covering Aug 17 - Sep 8:

```
Rows 1-4:   Aug 17 ($75K lost in Unknown segment)
Rows 5-8:   Aug 24 ($0 activity)
Rows 9-12:  Aug 28 ($20K won Mid-Market, $100K lost SMB)
Rows 13-16: Sep 7  ($0 activity)
Rows 17-20: Sep 8  ($0 activity)
```

### Synthesis Failure (Incorrect)
The LLM had all 20 rows but reported "$0 across all movements."

**Pattern identified:**
1. LLM scanned the data
2. Noticed rows 13-20 (most recent 8 rows) all showed $0
3. Anchored on "recent weeks are flat" pattern
4. Reported flatness as representative of full period
5. **Silently dropped $120K of Aug 28 activity** (rows 9-12)

---

## Why This Is Worse Than Data Bugs

### Data Layer Was Correct
- All 5 waterfall bugs from Sept 8 were fixed
- Reconciliation: 952/954 rows perfect (99.8%)
- Backend computation: verified correct
- **The underlying data was right the entire time**

### No Reconciliation Check Possible
- Data bugs can be caught by reconciliation checks (beginning + net_change = ending)
- Synthesis errors cannot - the raw data is correct, synthesis just summarizes it wrong
- **Silent failure mode** - numbers look plausible, just incorrect

### Will Recur Systematically
This isn't a one-off mistake, it's a pattern:
- Any "how has X moved over N weeks" question
- Where activity exists in EARLIER weeks but recent weeks are flat
- Synthesis will anchor on recent data, miss earlier activity

---

## Historical Context: This Is Bug Category #2

### Earlier Synthesis Bug (Same Pattern)
**Stage-breakdown truncation (q003/q011):**
- LLM dropped 3 of 10 stages
- Reported 287 of 306 deals
- Fix: instruct synthesis to verify sum-of-parts equals total

### Current Bug (Same Root Cause)
**Time-range aggregation:**
- LLM dropped earlier weeks from period summary
- Reported $0 instead of $195K
- **Same underlying issue:** synthesis under-representing retrieved data

---

## Investigation Timeline

### Sept 8: Waterfall Integration
- Fixed 5 data/computation bugs
- Achieved 99.8% reconciliation
- Verified with strict reconciliation check

### Sept 9: Discovered Synthesis Layer Failure
```
6:56 AM - User asks: "How has EMEA pipeline moved in the last 2 weeks"
6:57 AM - Slack reports: "$0 across all movements"

Investigation:
1. Check 1: Reconciliation ✅ (all EMEA rows reconcile perfectly)
2. Check 2: Actual data ✗ (waterfall shows $120K activity, not $0)
3. Check 3: Query logs ✗ (LLM had correct 20 rows, synthesized wrong)
```

### Root Cause Confirmed
- Not a regression (yesterday's fix still working)
- Not a data sync issue (waterfall has the data)
- **Synthesis aggregation bug** (LLM anchored on recent rows, missed earlier activity)

---

## Fix Strategy

### 1. Immediate Prompt Fix
Add explicit synthesis instruction for time-range questions:

```
CRITICAL: When answering "how has X moved over [time range]" questions:

1. Explicitly SUM all retrieved rows across ALL weeks in range
2. Present per-week breakdown, not just period total
   Format: "Week 1 (date): $X won, $Y lost | Week 2 (date): $A won, $B lost"
3. State total ONLY after showing breakdown: "Total period: $Z won, $W lost"

DO NOT anchor on most recent data as representative of full period.
DO NOT summarize without explicit aggregation.
```

### 2. Post-Generation Verification
Add programmatic check (like reconciliation for data):

```python
# After synthesis, before returning answer
retrieved_total_won = sum(row['won_value'] for row in retrieved_rows)
retrieved_total_lost = sum(row['lost_value'] for row in retrieved_rows)

# Extract stated totals from LLM response
stated_won = extract_number_from_text(response, pattern='won.*\\$([0-9,]+)')
stated_lost = extract_number_from_text(response, pattern='lost.*\\$([0-9,]+)')

# Verify match
if abs(stated_won - retrieved_total_won) > 0.01:
    raise SynthesisVerificationError(
        f"Stated won ${stated_won:,.0f} doesn't match data ${retrieved_total_won:,.0f}"
    )
```

### 3. Test Case
Create regression test:

```python
def test_time_range_aggregation_with_earlier_activity():
    """
    Test case: Activity in EARLIER week, $0 in recent week.
    Synthesis must report full-period total, not anchor on recent.
    """
    # Set up data: Week 1 has $100K won, Week 2-3 have $0
    # Query: "last 3 weeks"
    # Expected: "$100K won"
    # Common bug: "$0" (anchored on weeks 2-3)
```

---

## Impact Assessment

### Questions Affected
Any time-range aggregation query:
- "How has [region] pipeline moved in the last N weeks"
- "What changed in [segment] over the last month"
- "Show me [metric] movement since [date]"

### Severity
**High** - because:
1. Silent failure (no reconciliation check catches it)
2. Systematic pattern (will recur for all similar questions)
3. User receives confident-sounding but incorrect answer
4. Revealed only through manual cross-check

### Distinction from Data Bugs
This is **NOT** waterfall bug #6. It's a separate category:
- **Waterfall bugs (1-5):** Data layer errors (fixed Sept 8)
- **Synthesis bug:** Answer generation layer (found Sept 9)

The data layer is now solid and verified. This is a new defect at a different layer.

---

## Lessons

### 1. Correctness at Data Layer ≠ Correctness at Answer Layer
- Spent full day fixing 5 compounding data bugs
- Achieved 99.8% reconciliation, strict checks passing
- **But synthesis can still report data incorrectly**
- Lesson: need verification at BOTH layers

### 2. Reconciliation Checks Can't Catch Everything
- Data reconciliation: beginning + net_change = ending ✅
- Synthesis verification: stated total = data total ✗ (missing)

### 3. Synthesis Bugs Are Worse In One Specific Way
- Data bugs: eventually caught by reconciliation or user reports
- Synthesis bugs: numbers look plausible, no mechanical check
- Harder to detect, easier to trust incorrectly

---

## Next Steps

1. ✅ Document in PENDING_WORK.md (done)
2. ⏳ Implement prompt fix for time-range questions
3. ⏳ Add post-generation verification
4. ⏳ Create regression test case
5. ⏳ Check if other query types have same pattern

---

## Files

**Investigation:**
- `investigate_emea_flatness.py` - initial investigation
- `investigate_synthesis_bug.py` - root cause analysis
- `emea_final_check.py` - confirmed data correctness

**To Modify:**
- `api/router.py` - synthesis prompts
- `api/handlers.py` - add verification step
- Add test case to test suite

**Documentation:**
- This file
- PENDING_WORK.md (updated)
