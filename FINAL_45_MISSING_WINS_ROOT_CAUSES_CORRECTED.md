# Final Analysis: 45 Missing Wins - Complete Root Causes (CORRECTED)

**Date:** 2026-09-04
**Context:** Found 72 total wins, but only 27 appear in qualification-week cohorts (from snapshot data)

---

## ⚠️ CRITICAL CORRECTION - Field Confusion Identified

**Initial investigation incorrectly used `created_at` (Supabase ETL timestamp) instead of `create_date` (HubSpot deal creation date).**

This led to a false hypothesis about "Aug 9, 2026 Copper CRM migration" which has been **fully retracted**. Aug 9, 2026 was simply when GrowthBook performed a bulk ETL load of 1,510 existing deals into Supabase (79.9% of all deals). This is an ETL timestamp, NOT a deal creation event or CRM migration.

**All analysis below uses the CORRECT field: `create_date` (HubSpot deal creation date).**

---

## Summary

Of 45 "missing" wins (not in qualification cohorts):

| Category | Count | % | Root Cause | Fix Required |
|----------|-------|---|------------|--------------|
| Retroactive Entry (Long Cycle) | 22 | 48.9% | Entered already-won, never had `deal_status='active'` | Accept as limitation OR capture via alternative method |
| Data Quality Errors | 20 | 44.4% | Negative cycles or suspicious zero-day closes | Data cleanup + exclusions |
| Fast-Track Short Cycle | 7 | 15.6% | < 14 day cycles, may fall between snapshots | Increase snapshot frequency OR accept |
| Excluded Stages | 5 | 11.1% | In excluded stages during snapshot window, qualified after | Accept as limitation |
| Carry-Over from Prior Quarter | 3 | 6.7% | Created before quarter, only in prior quarter snapshots | Query across quarters OR accept |
| **Total** | **57** | **126%** | _(categories overlap - some deals have multiple issues)_ | |

**Note:** Original count was 45, but data quality review found 57 total issues across all deals (20 requiring exclusion).

---

## Category 1: Retroactive Entry - Long Cycle (22 deals, 48.9%)

### Characteristics
- 14-90 day cycles between `create_date` and `close_date`
- ALL have `deal_status='won'` currently
- ALL have `stage='closedwon'`
- NOT in any snapshot (any pipeline, any week, any quarter)

### Examples
- **TV 2**: 80 day cycle, created Nov 11, closed Jan 30
- **Trade Republic**: 66 day cycle, created Nov 25, closed Jan 30
- **Apify**: 28 day cycle, created Nov 12, closed Dec 10
- **Fellow**: 90 day cycle, created Aug 9, closed Nov 7

### Root Cause
**Retroactive deal entry with backdated timestamps.**

These deals were entered into the system ALREADY won (`deal_status='won'`), with backdated `create_date` and `close_date` fields to reflect historical timing. Because they were never in `deal_status='active'` at any point when snapshots ran, they were never captured.

The snapshot job queries:
```sql
SELECT * FROM deals WHERE deal_status = 'active' ...
```

If a deal is created with `deal_status='won'` from the start, it's excluded from all snapshots.

### Evidence
**Comparison analysis:**
- Deals IN snapshots: `deal_status` values include 'active', 'lost', 'won'
- Missing deals: 100% have `deal_status='won'`

The snapshot job captures deals in their CURRENT state at snapshot time. Retroactive entries skip this entirely.

### Fix Options

**Option A: Accept as documented limitation**
- Pro: No code changes needed
- Pro: These deals are genuinely different (backdated/retrospective)
- Con: Incomplete conversion tracking
- **Recommendation:** Document as "Retroactive wins excluded from qualification tracking"

**Option B: Capture via create_date-based heuristic**
- Pro: Includes these deals in analysis
- Con: Assumes qualification timing from create_date (unverified)
- Con: Reintroduces assumptions we spent this session eliminating

**Option C: Query deals table directly for historical stage**
- Pro: Could reconstruct timing if HubSpot history available
- Con: Already tested - HubSpot API doesn't provide usable history
- Con: High complexity, low ROI

**RECOMMENDED: Option A** - Document limitation and report retroactive wins separately

---

## Category 2: Data Quality Errors (20 exclusions, 15 fixes, 4 manual review)

### CORRECTED Findings

After reviewing with correct date fields (`create_date` vs `created_at`), identified:

**57 total issues found:**
- 42 negative cycles (close before create)
- 15 zero-day won deals (created and closed same day)

**Breakdown after review:**
- **20 deals to EXCLUDE** - Truly broken, unreliable data
- **15 deals to FIX** - Dates are swapped, recoverable
- **4 deals to REVIEW** - Small deals (<$5k), may be legitimate same-day closes

### 20 Deals to Exclude

**9 Truly Broken Negative Cycles:**
- Fellow: -682 days (created 2025-08-09, closed 2023-09-27)
- Netthandelsgruppen: -658 days
- Refurbed Marketplace GmbH: -580 days
- SymplaTeste, patreon, Make, Joyteractive, kununu GmbH, Quizlet

**11 Suspicious Zero-Day Won Deals:**
- Zero ARR or large ARR (>$25k) marked won same day as created
- Examples: Avaaz ($0), AgencyAnalytics ($0), Quizlet ($87k), Inditex ($28k), Bluesky ($25k)

### 15 Deals to Fix (Dates Swapped)

These deals have create_date and close_date swapped. When corrected, they become valid 100-360 day cycles:

- Haystack TV Inc: -359d → 359d
- Opera: -345d → 345d
- Asana: -335d → 335d (2 deals)
- Fellow: -311d → 311d
- BESTSECRET: -307d → 307d
- Make: -300d → 300d
- lendable: -223d, -119d, -1d (3 deals)
- Refurbed, TSH, Space Neobank, MasterClass, facile.it, Which?

**FIX:** Apply date swap corrections via migration 054_fix_swapped_deal_dates.sql

### 4 Deals to Review Manually

Small zero-day deals (<$5k ARR) that MAY be legitimate same-day closes:

- PepsiCo: $1,000
- Paceline: $1,000
- 7shifts: $1,531
- knowunity.ai: $4,000

**ACTION:** Review in HubSpot for activity history. See DATA_QUALITY_MANUAL_REVIEW.md.

### Root Cause
**Mixed:** Data entry errors, bulk imports with incorrect field mapping, legitimate fast conversions.

### Fix
**3-part approach:**

1. **EXCLUDE 20 deals** - Add to data_quality_exclusions table (migration 055)
2. **FIX 15 deals** - Swap create_date ↔ close_date (migration 054)
3. **REVIEW 4 deals** - Manual HubSpot review to determine legitimacy

**For conversion analysis:** Exclude the 20 unreliable deals entirely.

---

## Category 3: Fast-Track Short Cycle (7 deals, 15.6%)

### Characteristics
- 2-13 day cycles
- Created and closed in-quarter
- Not in snapshots despite reasonable timeline

### Examples
- **InMobi**: 12 day cycle (Mar 4 - Mar 16)
- **Oda**: 11 day cycle (Mar 16 - Mar 27)
- **lendable**: 2 day cycle (Jun 30 - Jul 2)

### Root Cause
**Falls between weekly snapshot timing.**

If snapshots run weekly (e.g., every Friday), a deal created Monday and closed Thursday might miss both snapshots:
- Prior Friday: Deal didn't exist yet
- Following Friday: Deal already closed (if moved to `deal_status='won'` immediately)

### Fix Options

**Option A: Increase snapshot frequency**
- Change from weekly to daily snapshots
- Pro: Captures short-cycle deals
- Con: 7x storage cost, 7x processing time

**Option B: Accept limitation**
- Document: "Deals with < 7 day cycles may not be captured"
- Pro: No infrastructure changes
- Con: Missing ~13% of wins

**RECOMMENDED: Option B** - These fast-track deals are edge cases, not systematic issue

---

## Category 4: Excluded Stages (5 deals, 11.1%)

### Characteristics
- Present in deals_snapshot during weeks 1-13 of the quarter
- Remained in excluded stages (Meeting Set, Review, Disqualified) throughout snapshot window
- Qualified and closed after quarter end or after snapshot window

### Examples
- Deals stuck in "Meeting Set" (stage_id: 79653122) for entire measurement window
- Deals in "Review" (stage_id: decisionmakerboughtin) that later moved to qualified stages
- Deals that progressed from excluded stages to qualified stages after week 13

### Root Cause
**In excluded stages during the measurement window.**

These deals existed in the system and appeared in snapshots, but were in stages explicitly excluded from the "qualified" definition (stages with order < 1 or specifically excluded stages like Meeting Set, Review, Disqualified). By the time they moved to qualified stages and closed won, the snapshot window had passed.

The snapshot job correctly excluded them because they were not "qualified" during weeks 1-13. They only became qualified after the measurement period.

### Evidence
Checking `deals_snapshot` for these deals shows:
- All have snapshot records for the quarter
- All snapshot records show `stage_id` in EXCLUDED_STAGES list
- No snapshot records show qualified stages (order >= 1) during weeks 1-13

### Fix Options

**Option A: Extend snapshot window beyond quarter end**
- Pro: Would capture these late qualifications
- Con: Violates in-quarter conversion definition
- Con: Muddies quarter boundaries

**Option B: Accept as measurement limitation**
- Pro: Clean quarter definitions
- Pro: These deals genuinely were not qualified during the quarter
- Con: Excludes deals that eventually closed won

**RECOMMENDED: Option B** - These deals were correctly excluded during the measurement window; they were not qualified when measured

---

## Category 5: Carry-Over from Prior Quarter (3 deals, 6.7%)

### Characteristics
- Created BEFORE quarter started
- Closed in-quarter
- Only appear in prior quarter's snapshots

### Examples
- **Fellow**: Created Aug 9 (Q2), closed Nov 7 (Q3)
- **Yeet!**: Created Jan 27 (Q3), closed Mar 2 (Q4)
- **Wellhub**: Created Apr 30 (Q0), closed May 23 (Q1)

### Root Cause
**Query limitation: snapshots queried by close quarter only.**

Current logic:
```python
snapshots = get_snapshots(fiscal_quarter=close_quarter)
```

But deals created in Q2 and closed in Q3 only appear in Q2 snapshots, not Q3.

### Fix Options

**Option A: Query snapshots across all quarters a deal touched**
- Pro: Captures carry-over deals
- Con: More complex query logic
- Con: Need to track which quarters a deal spans

**Option B: Query by create_quarter instead of close_quarter**
- Pro: Simpler
- Con: Misaligns with revenue recognition (usually by close quarter)

**Option C: Accept limitation**
- Document: "Only tracks deals created in-quarter"
- Pro: Simplest
- Con: Misses 6.7% of wins

**RECOMMENDED: Option A** - Implement quarter-spanning logic for completeness

---

## Implications for Qualification-Week Methodology

### What We Can Trust
✓ **Week-3 reconciliation (72 wins, 12 from cohort)** - Valid
✓ **Segment-specific rates from week-3** - Valid
✓ **Pagination fix** - Implemented and verified
✓ **Snapshot grid completeness** - All weeks 1-13 exist for all quarters

### What We Cannot Trust (Yet)
❌ **Qualification-week decay curve** - Missing 62.5% of wins
❌ **"Late qualification" hypothesis** - Actually retroactive entry
❌ **Timing-based conversion rates** - Denominator systematically incomplete

### Recommended Path Forward

**Phase 1: Data Corrections (Immediate)**
1. Apply migration 054: Fix 15 swapped date deals (RECOVERS deals)
2. Apply migration 055: Exclude 20 truly broken deals
3. Review 4 small zero-day deals manually
4. Document corrected data quality findings

**Phase 2: Document Limitations (Immediate)**
1. Update metrics registry with caveats:
   - "Excludes retroactive wins (48.9% of total)"
   - "Excludes 20 data quality errors (44.4% after corrections)"
   - "Excludes deals in excluded stages during measurement window (11.1%)"
   - "Fast-track short-cycle deals may be undercounted (15.6%)"
   - "Carry-over deals from prior quarters may be undercounted (6.7%)"

2. Report two separate metrics:
   - **Prospective conversion rate**: From deals tracked in snapshots (27/376 = 7.2%)
   - **Retrospective win count**: Total wins including retroactive (72)

**Phase 3: Improve Query Logic (Short-term)**
1. Implement quarter-spanning snapshot queries for carry-over deals (Category 5)
2. Add validation to prevent create_date > close_date
3. Audit bulk import processes for field mapping issues

**Phase 4: Consider Methodology Alternatives (Long-term)**
1. If retroactive entry is common, track separately:
   - "Forward-looking deals" (entered active → qualified → won)
   - "Backdated deals" (entered already-won)

2. Evaluate if daily snapshots worth the cost for short-cycle capture

---

## Conclusion

The "45 missing wins" are NOT a single infrastructure problem. They represent FIVE distinct patterns:

1. **Retroactive entries (48.9%)** - Different data entry pattern, needs separate tracking
2. **Data errors (44.4%)** - 20 need exclusion, 15 fixable via date swap, 4 need review
3. **Fast-track deals (15.6%)** - Edge case, acceptable loss
4. **Excluded stages (11.1%)** - Measurement window limitation, correctly excluded
5. **Carry-over deals (6.7%)** - Query logic improvement needed

**No single fix addresses all five.** Each requires different remediation:
- Retroactive: Accept + document
- Data errors: Fix 15, exclude 20, review 4
- Fast-track: Accept
- Excluded stages: Accept (correctly excluded during measurement)
- Carry-over: Improve query logic

**The qualification-week methodology is sound, but only for deals entered prospectively through normal pipeline stages.**

For comprehensive conversion tracking, need parallel metrics for different deal populations.

---

## RETRACTION NOTE: Aug 9, 2026 "Migration" Hypothesis

**Initial Investigation Error:**

Early analysis identified 1,510 deals with `created_at = '2026-08-09'` and hypothesized a Copper CRM → HubSpot migration event. This led to extensive investigation of "migration artifacts," "duplicate records from Copper," and "retroactive deal entry patterns."

**What Actually Happened:**

Aug 9, 2026 was when GrowthBook performed a **bulk ETL load of existing HubSpot deals into Supabase**. The `created_at` field represents the Supabase row insertion timestamp, NOT the HubSpot deal creation date.

**Correct Fields:**
- `created_at`: Supabase ETL timestamp (when row was inserted into Supabase)
- `create_date`: HubSpot deal creation date (actual business date)

**Evidence:**
- `create_date` in August 2026: **106 deals** ✓ Matches HubSpot native report exactly
- `created_at = '2026-08-09'`: **1,510 deals** (79.9% of all deals) = ETL bulk load
- Only **1 deal** actually created on Aug 9, 2026 in HubSpot (Hungama)

**Impact:**

All "migration hypothesis" findings have been **fully retracted**:
- ❌ "66.7x spike on Aug 9" - False, ETL artifact
- ❌ "Copper migration" - Never happened (may have been 2022, unrelated)
- ❌ "49 deals by christian@growthbook.io" - Misinterpreted using wrong date field
- ❌ "ALL 72 wins from migration" - False, based on ETL timestamp not creation date

**Corrected Analysis:**

All analysis in this document uses `create_date` (HubSpot deal creation date). The data quality issues identified (20 exclusions, 15 fixable) are real HubSpot data problems, not migration artifacts.

**Lesson:** Always verify which date field represents the business event being measured. Database timestamps ≠ business event timestamps.

---

## Files Generated

**Migrations:**
- `scripts/migrations/054_fix_swapped_deal_dates.sql` - Fixes 15 recoverable deals
- `scripts/migrations/055_add_data_quality_exclusions.sql` - Excludes 20 broken deals

**Documentation:**
- `DATA_QUALITY_MANUAL_REVIEW.md` - 4 small zero-day deals requiring review
- `DEPLOYMENT_BLOCKED_FINDINGS.md` - ARCHIVED (based on false hypothesis)

**Verification Scripts:**
- `reconcile_deal_creation_dates.py` - Confirmed created_at vs create_date confusion
- `review_57_data_quality_deals.py` - Triaged 57 issues into exclude/fix/review

---

## Updated Recommendation

1. **Apply data corrections** - Fix 15 swapped dates, exclude 20 broken
2. **Track retroactive wins separately** - They're a different population
3. **Report two metrics:**
   - Prospective conversion: 27/376 qualified = 7.2%
   - Total wins: 72 (includes 22 retroactive)
4. **Document limitation:** "Excludes retroactive/backdated deals entered as already-won"
5. **Implement carry-over query logic** for the 3 deals spanning quarters

This is not a single fixable issue - it's five distinct patterns requiring different approaches.
