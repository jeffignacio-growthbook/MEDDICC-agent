# Pagination Bug Investigation Summary

**Date:** 2026-09-04
**Session:** Conversion Rate Methodology Build
**Status:** RESOLVED - Root cause identified and fixed

---

## Executive Summary

**Initial claim:** "Snapshot grid has infrastructure gaps (Q3 weeks 3+, Q4 weeks 1-3 missing)"

**Actual finding:** PostgREST 1000-row pagination limit was silently truncating all multi-week queries. Snapshot grid is COMPLETE for all quarters.

**Impact:** Every multi-week analysis from this session was affected until pagination fix implemented.

---

## Investigation Timeline

### Phase 1: False Infrastructure Gap Claim

**Observation:** `conversion_by_qualification_week.py` showed:
- Q3: Only weeks 1-2 had qualified deals
- Q4: Missing weeks 1-3
- Q1: All weeks 1-13 "complete" but only 70 deals found

**Incorrect conclusion:** "Snapshot table incomplete - infrastructure issue"

**Created:** `SNAPSHOT_GRID_INFRASTRUCTURE_ISSUE.md` (NOW OBSOLETE)

### Phase 2: Methodology Discrepancy

**Contradiction discovered:**
- Week-3 snapshot method: 76 qualified deals in Q1
- Qualification-week method: 0 deals qualified in week 3

**Investigation:** User correctly identified this as impossible if both querying same data

**Root cause found:** Methodologies measure different things:
- Week-3 snapshot: "Deals qualified AT week 3" (cumulative)
- Qualification-week: "Deals FIRST qualified IN week 3" (incremental)

### Phase 3: Pagination Bug Discovered

**Audit revealed:**

| Query Type | Actual Rows | Fetched | Status |
|------------|-------------|---------|--------|
| Q3 week-3 | 249 | 249 | ✓ Safe |
| Q4 week-3 | 425 | 425 | ✓ Safe |
| Q1 week-3 | 593 | 593 | ✓ Safe |
| **Q3 all weeks** | **3,017** | **1,000** | **⚠️ TRUNCATED** |
| **Q4 all weeks** | **5,382** | **1,000** | **⚠️ TRUNCATED** |
| **Q1 all weeks** | **5,697** | **1,000** | **⚠️ TRUNCATED** |

**Verified:** All weeks 1-13 exist for all quarters. Data is complete.

### Phase 4: Pagination Fix Implemented

**Created:** `scripts/utils/pagination.py` with `fetch_all_rows()` function

**Fixed scripts:**
- `conversion_by_qualification_week_q1_FIXED.py`
- `conversion_by_qualification_week_ALL_QUARTERS_FIXED.py`

**Results after fix:**
- Q1: 5,697 rows fetched (vs 1,000 before)
- Found: 167 qualified deals (vs 70 before)
- Captured: 11 wins (vs 5 before)

---

## Technical Root Cause

### PostgREST Pagination Behavior

PostgREST (Supabase's API layer) has a **default 1000-row limit** per query.

**Broken pattern:**
```python
# This silently truncates at 1000 rows
result = supabase.table('deals_snapshot') \
    .select('deal_id, week_of_quarter, stage_id') \
    .eq('fiscal_quarter', 'FY2027 Q1') \
    .execute()
```

**Fixed pattern:**
```python
# This paginates automatically
all_rows = []
offset = 0
while True:
    result = supabase.table('deals_snapshot') \
        .select('deal_id, week_of_quarter, stage_id') \
        .eq('fiscal_quarter', 'FY2027 Q1') \
        .range(offset, offset + 999) \
        .execute()

    all_rows.extend(result.data)
    if len(result.data) < 1000:
        break
    offset += 1000
```

### Why Week-3 Queries Weren't Affected

Single-week queries returned < 1000 rows:
- Q3 week-3: 249 rows
- Q4 week-3: 425 rows
- Q1 week-3: 593 rows

All below the pagination limit, so no truncation occurred.

### Why We Didn't Notice Initially

1. No error thrown (silent truncation)
2. Some results returned (partial data looks complete)
3. No row count validation

---

## Affected Analyses

### ✓ VALID (Not Affected)

These used single-week queries or server-side filters that stayed under 1000 rows:

1. **reconcile_all_quarters_correct.py**
   - Week-3 snapshots only
   - Correctly found 72 wins, 12 from week-3 cohort

2. **analyze_smb_qualification_gap.py**
   - Week-3 snapshots only
   - Cycle length and excluded-stage fate analysis valid

3. **verify_segment_scope_and_deal_type.py**
   - Week-3 snapshots only
   - Segment-specific rates valid

### ❌ INVALID (Were Truncated)

These used multi-week queries that exceeded 1000 rows:

1. **analyze_qualification_timing.py**
   - BEFORE: Found only 20 wins total (truncated)
   - AFTER: Found 72 wins (correct)

2. **conversion_by_qualification_week.py**
   - BEFORE: Found 70 qualified in Q1 (truncated)
   - AFTER: Found 167 qualified in Q1 (correct)

3. **conversion_by_qualification_week_q1.py**
   - BEFORE: Found 70 qualified, 5 wins (truncated)
   - AFTER: Found 167 qualified, 11 wins (correct)

---

## Scripts That Filter by pipeline_id='default'

### Audit Results

**Analysis scripts created today:** Many filter by `pipeline_id='default'` (expected for analysis)

**Production scripts:** `scripts/analytics/*` properly handle multiple pipelines via config

**Blind spot:** None in production code. The `pipeline_id='default'` filter is correct - it's the intended scope.

**Pipeline migration:** Checked 25 "missing" deals - ZERO were in other pipelines. All genuinely missing due to retroactive entry pattern (see `FINAL_45_MISSING_WINS_ROOT_CAUSES.md`)

---

## Lessons Learned

### 1. Always Validate Row Counts

**Bad:**
```python
result = query.execute()
# Assume result.data is complete
```

**Good:**
```python
result = query.execute()
print(f"Fetched {len(result.data)} rows")

# For validation, check expected count
count_result = query.select('*', count='exact').limit(1).execute()
if count_result.count > 1000:
    print(f"⚠️ WARNING: {count_result.count} rows exist, may need pagination")
```

### 2. Don't Assume "No Error" Means "Complete Data"

PostgREST silently truncates. Always check for the 1000-row boundary.

### 3. Verify Contradictions Before Generalizing

When Q1 showed "week-3 = 0 qualified", the initial reaction was "infrastructure gap."

User correctly pushed back: "Reconcile this contradiction first."

The contradiction revealed a methodology difference, not a data gap.

### 4. Test Fixes End-to-End

After implementing pagination:
- Re-ran all affected analyses
- Verified row counts increased
- Confirmed results reconciled with expectations

---

## Permanent Fixes Implemented

### 1. Pagination Utility

Created `scripts/utils/pagination.py`:
```python
def fetch_all_rows(supabase, table, select_cols, filters, page_size=1000):
    """Fetch all rows with automatic pagination."""
    # ... (see file for implementation)
```

### 2. Fixed Scripts

All qualification-week analyses now use pagination:
- `conversion_by_qualification_week_q1_FIXED.py`
- `conversion_by_qualification_week_ALL_QUARTERS_FIXED.py`

### 3. Documentation

This document serves as:
1. Record of investigation for template port
2. Warning for future developers about pagination
3. Validation that snapshot grid is complete (not broken)

---

## Corrected Findings

### What We Know NOW (After Pagination Fix)

**Snapshot Grid:**
- ✓ Q3: All weeks 1-13 exist (3,017 rows)
- ✓ Q4: All weeks 1-13 exist (5,382 rows)
- ✓ Q1: All weeks 1-13 exist (5,697 rows)

**Qualified Deals:**
- 376 deals qualified across all quarters (not 169)
- 27 wins captured in cohorts (not 12)
- 7.2% overall conversion rate

**Missing Wins:**
- 45 of 72 wins not in cohorts (62.5%)
- Root causes: Retroactive entry (48.9%), data errors (17.8%), fast-track (13.3%), carry-over (6.7%)
- NOT an infrastructure gap

### What Was WRONG Before

**❌ "Q3 has only weeks 1-2"** - FALSE, all weeks exist (pagination bug)
**❌ "Q4 missing weeks 1-3"** - FALSE, all weeks exist (pagination bug)
**❌ "Q1 data quality issues"** - FALSE, data is complete (pagination bug)
**❌ "Snapshot infrastructure gap"** - FALSE, grid is complete (pagination bug)

---

## Status: CLOSED

**Issue:** Pagination bug in multi-week snapshot queries
**Resolution:** Implemented pagination utility, fixed all affected scripts
**Remaining work:** Document 45 missing wins root causes (separate issue, see `FINAL_45_MISSING_WINS_ROOT_CAUSES.md`)

**Snapshot grid is COMPLETE and WORKING AS DESIGNED.**
