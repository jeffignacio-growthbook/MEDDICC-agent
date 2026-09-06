# Active-Filter Bug Pattern Audit Results

**Date**: 2026-09-05
**Purpose**: Check if the q016 bug pattern (filtering `deal_status = 'active'` when computing historical win rates) exists elsewhere in the codebase

---

## Summary

**Result**: ✓ Bug pattern is ISOLATED to answer_pending_canonical_questions.py (already fixed)

**Files scanned**: 364 Python files
**Initial suspects**: 9 files flagged by automated scan
**Actual bugs**: 0 (all other instances are false positives)

---

## Bug Pattern Definition

**The bug**:
```python
# WRONG: Only fetches active deals
deals = sb.table('deals').select('*').eq('deal_status', 'active').execute().data

# Then tries to calculate historical win rate
historical_deals = [d for d in deals if d.get('close_date') >= six_months_ago]
won_deals = [d for d in historical_deals if d.get('deal_status') == 'won']  # Zero results!
```

**Why it's wrong**:
- Filtering to `deal_status = 'active'` excludes ALL won/lost deals
- Historical win rate calculation has zero closed deals to analyze
- Returns 0% win rate (implausible)

**Correct approach**:
```python
# CORRECT: Fetch all deal statuses
all_deals = sb.table('deals').select('*').execute().data

# Then filter to closed deals
closed_deals = [d for d in all_deals
                if d.get('deal_status') in ['won', 'lost']
                and d.get('close_date') >= six_months_ago]
```

---

## Files Reviewed

### 1. answer_pending_canonical_questions.py ✓ FIXED

**Status**: Known bug, already fixed

**Original bug** (line 63):
```python
deals = sb.table('deals').select('*').eq('deal_status', 'active').execute().data
```

**Fix created**: `fix_q016_win_rate.py`
- Fetches ALL deal statuses
- Correctly returns 10.4% win rate (48 won / 461 closed)

**Action**: None needed - bug already documented and fixed

---

### 2. scripts/analytics/compute_forecast.py ✓ FALSE POSITIVE

**Status**: Correctly implemented

**Why flagged**: Mentions "won deals" and has active filter

**Actual implementation**:
```python
# Line 87: Active filter for CURRENT pipeline (correct)
if d.get('deal_status') == 'active'

# Lines 171-177: Historical won deals use STAGE-based filtering (correct)
won_stages = ['closedwon', '1297321623']
all_won_deals = [
    d for d in deals
    if d.get('stage') in won_stages  # Uses stage, not deal_status
]
```

**Verdict**: Uses two different filters appropriately:
- `deal_status = 'active'` for current open pipeline
- `stage in won_stages` for historical won deals

---

### 3. measure_review_exclusion_impact.py ✓ FALSE POSITIVE

**Status**: Correctly implemented

**Why flagged**: Mentions "won deals" and has active filter

**Actual implementation**:
```python
# Line 50: Active filter for CURRENT Q3 pipeline analysis (correct)
WHERE deal_status = 'active' AND close_date >= '2026-08-01'

# Lines 92-97: Won deals use STAGE-based filtering (correct)
WHERE stage IN ('closedwon', '1297321623')
```

**Verdict**: Two separate queries for different purposes - both correct

---

### 4. diagnose_historical_conversion.py ✓ FALSE POSITIVE

**Status**: Correctly implemented

**Why flagged**: File name says "historical" but filters to active

**Actual purpose**: Diagnosing a forecast calculation method that uses CURRENT pipeline

**From comments** (lines 78-79):
```python
print(f"CURRENT Pipeline (what compute_forecast.py uses)")
```

**Verdict**: Despite the filename, this script analyzes current pipeline (not historical closed deals). Filter is correct for its purpose.

---

### 5. measure_review_impact_corrected.py ✓ FALSE POSITIVE

**Status**: Correctly implemented

**Similar to #3** - uses stage-based filtering for won deals, active filter for current pipeline

---

### 6. scripts/eval_ae_handlers.py ✓ FALSE POSITIVE

**Status**: Test/eval script with mock data

**Context**: Handler evaluation tests with sample active deals (not computing real win rates)

---

### 7. api/router.py ✓ FALSE POSITIVE

**Status**: Default filter, not used for historical calculations

**Context**: Line 1091 is a default filter in router logic, not computing win rates

---

### 8. scripts/analytics/compute_waterfall.py ✓ FALSE POSITIVE

**Status**: Correctly implemented

**Purpose**: Waterfall tracks pipeline movement week-over-week (deals moving between stages)

**Context**: Filtering to active deals is CORRECT for waterfall - tracks changes in open pipeline, not historical win rates

---

### 9. audit_active_filter_bug.py ✓ FALSE POSITIVE

**Status**: This is the audit script itself

**Why flagged**: Contains the pattern in its own code as examples

---

## Pattern Analysis

### Why the bug was isolated to one file

**Key insight**: Most scripts in the codebase use **stage-based filtering** to identify won/lost deals, not `deal_status` filtering:

```python
# Common correct pattern throughout codebase
won_stages = ['closedwon', '1297321623']  # From field_semantics.yaml
won_deals = [d for d in all_deals if d.get('stage') in won_stages]
```

**Why this works**: HubSpot deals retain their stage even when marked won/lost, so stage-based filtering correctly identifies historical closed deals.

### When `deal_status = 'active'` is appropriate

Filtering to active deals is CORRECT when:
1. **Current pipeline analysis** - "What's in our Q3 pipeline?"
2. **Data quality checks** - "Which active deals are missing ARR?"
3. **Forecast coverage** - "Do we have enough pipeline to hit target?"
4. **Waterfall** - "What changed in our open pipeline this week?"

### When it's WRONG

Only wrong when computing metrics that require historical closed deals:
- Win rates (won / total closed)
- Conversion rates (qualified → won)
- Cycle times (create → close for won deals)
- Loss analysis (recent closed-lost deals)

---

## Root Cause of the Isolated Bug

**Why answer_pending_canonical_questions.py had this bug**:

```python
# Line 63 - fetched deals once for all 11 questions
deals = sb.table('deals').select('*').eq('deal_status', 'active').execute().data
```

**Design flaw**: One query tried to serve multiple question types:
- q002-q013: Current pipeline questions (need active deals) ✓
- q016: Historical win rate (needs closed deals) ✗

**The fix**: Separate query for q016 that fetches ALL deal statuses

---

## Recommendations

### ✓ No code changes needed

All other instances of `deal_status = 'active'` are appropriate for their context.

### ✓ Pattern is well-contained

The codebase already follows best practices:
- Stage-based filtering for historical analysis
- Status-based filtering only for current pipeline

### ✓ Future prevention

When adding new queries for historical metrics:
1. **Check**: Does this metric need closed deals?
2. **If yes**: Use stage-based or status-in filtering, NOT active-only
3. **Test**: Verify results are plausible (not 0%)

---

## Conclusion

**Audit result**: ✓ Clean

The bug pattern found in q016 is **isolated and already fixed**. No other files in the codebase have the same issue.

**Key takeaway**: The codebase's widespread use of stage-based filtering (vs status-based) naturally prevented this bug from spreading. The q016 case was an exception because it tried to reuse an active-only query for a historical calculation.
