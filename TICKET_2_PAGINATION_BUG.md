# TICKET 2: snapshot_deals.py Pagination Truncation

**Type:** Data Integrity Bug
**Priority:** High
**Status:** ✅ FIXED (Already resolved in commit 7addf1a)
**Root Cause:** Confirmed and patched

---

## Summary

`scripts/analytics/snapshot_deals.py` hit PostgREST's 1000-row default limit, silently truncating snapshots. Issue was confirmed in Q3 weeks 3-4 (exactly 1000 rows).

## ✅ RESOLUTION

**Fixed in commit:** `7addf1a` - "Fix PostgREST 1,000-row cap: paginate all bulk selects"

**Current state:**
- Line 91-96: Now uses `select_all()` wrapper for pagination ✓
- Handles unlimited row counts correctly
- Only `.execute()` remaining is line 192 (INSERT operation - correct, no pagination needed for writes)

## Evidence

### Confirmed Truncation

| Quarter    | Week | Row Count | Status         |
|------------|------|-----------|----------------|
| FY2027 Q3  | 1    | 975       | ✓ Complete     |
| FY2027 Q3  | 2    | 991       | ✓ Complete     |
| **FY2027 Q3**  | **3**    | **1000**      | **⚠️ Truncated**   |
| **FY2027 Q3**  | **4**    | **1000**      | **⚠️ Truncated**   |

Exactly 1000 rows = PostgREST default limit, not a business pattern.

### Root Cause

**File:** `scripts/analytics/snapshot_deals.py`
**Issue:** Direct `.execute()` call without pagination wrapper

**Current code pattern:**
```python
result = supabase.table('deals').select('*').execute()
# Returns max 1000 rows, no error raised
```

**Should be:**
```python
from supabase_client import select_all
result = select_all(supabase.table('deals').select('*'))
# Automatically paginates beyond 1000 rows
```

### Historical Context

**Same bug previously fixed in:**
- Conversion rate computation (August 2026)
- Multiple analytics queries (Wave 5 data quality work)

**Lesson not applied:** snapshot_deals.py was created before this pagination pattern was established and never retrofitted.

## Impact Assessment

### Immediate Impact

**Metrics affected:**
- Weekly pipeline snapshots (deals_snapshot table)
- Waterfall analysis (stage transitions)
- Conversion tracking (cohort snapshots)
- Any downstream analysis using snapshot data

**Severity:** High
- Silent truncation (no error raised)
- Produces plausible wrong numbers
- Affects historical analysis and forecasting

### Scope of Damage

**Need to audit:**
1. All weeks across all quarters for exactly-1000 or multiple-of-1000 row counts
2. Check if backfill ran before or after pagination fix
3. Determine if source data (HubSpot property history) is still queryable for backfill

**Audit query:**
```sql
SELECT
  fiscal_quarter,
  week_of_quarter,
  COUNT(*) as row_count,
  CASE
    WHEN COUNT(*) % 1000 = 0 THEN '⚠️ Possible truncation'
    ELSE '✓ OK'
  END as status
FROM deals_snapshot
GROUP BY fiscal_quarter, week_of_quarter
ORDER BY fiscal_quarter, week_of_quarter;
```

## Fix Implementation

### Step 1: Patch snapshot_deals.py

**File:** `scripts/analytics/snapshot_deals.py`

**Change:**
```diff
- result = sb.table('deals').select(fields).execute()
+ from supabase_client import select_all
+ result = select_all(sb.table('deals').select(fields))
```

**Verify pattern used consistently** throughout file.

### Step 2: Audit Truncation Extent

Run comprehensive audit:
```python
# Check all weeks for truncation signature
quarters = ['FY2026 Q3', 'FY2026 Q4', 'FY2027 Q1', 'FY2027 Q2', 'FY2027 Q3']
for quarter in quarters:
    for week in range(1, 14):
        count = count_snapshot_rows(quarter, week)
        if count % 1000 == 0:
            print(f"⚠️ {quarter} Week {week}: {count} rows (likely truncated)")
```

### Step 3: Backfill Decision

**If HubSpot property history still queryable:**
- Re-run snapshot backfill for truncated weeks
- Use `backfill_snapshots.py --quarters "FY2027 Q3" --weeks "3,4"`
- Verify row counts increase beyond 1000

**If property history unavailable:**
- Document as permanent data gap
- Add data quality note to affected quarters
- Adjust analysis to acknowledge incomplete coverage
- Consider extrapolation for trend analysis (with caveat)

### Step 4: Permanent Prevention

**Add to harness tests** (`scripts/eval_*.py`):
```python
def test_no_direct_execute_in_analytics():
    """Ensure all analytics scripts use pagination wrapper."""
    analytics_dir = Path(__file__).parent / 'analytics'
    violations = []

    for script in analytics_dir.glob('*.py'):
        content = script.read_text()
        if '.execute()' in content and 'select_all' not in content:
            violations.append(script.name)

    assert not violations, f"Scripts using .execute() without pagination: {violations}"
```

**Add to PORT_CHECKLIST.md:**
- Onboarding action item: Audit all snapshot weeks for truncation before trusting data
- Template carries pagination utility and test

## Testing Plan

1. **Unit test:** Verify select_all() handles >1000 rows
2. **Integration test:** Run snapshot job on high-volume week, confirm >1000 rows written
3. **Regression test:** Compare Q3 week 3-4 row counts before/after fix
4. **Validation:** Run waterfall analysis on backfilled data, check for discontinuities

## Success Criteria

- ✅ snapshot_deals.py uses select_all() for all queries
- ✅ Audit identifies all truncated weeks (exact list, not estimate)
- ✅ Backfill completes for recoverable weeks OR gaps documented as permanent
- ✅ Harness test prevents future pagination bugs
- ✅ PORT_CHECKLIST.md updated with pagination verification step

## Rollout Plan

1. **Immediate:** Apply fix to snapshot_deals.py (non-breaking change)
2. **Week 1:** Run truncation audit, identify affected weeks
3. **Week 1-2:** Backfill recoverable data OR document permanent gaps
4. **Week 2:** Add harness test, update PORT_CHECKLIST.md
5. **Week 2:** Notify stakeholders of data quality correction

## Related Tickets/Issues

- Conversion methodology pagination fix (September 2026)
- Wave 5 data quality exclusions work
- PORT_CHECKLIST.md: Pagination onboarding action item (#5)

---

**Filed:** 2026-09-05
**Root Cause Confirmed:** PostgREST 1000-row default + missing select_all() wrapper
**Investigator:** Claude Sonnet 4.5
**Reviewer:** Jeff Ignacio
