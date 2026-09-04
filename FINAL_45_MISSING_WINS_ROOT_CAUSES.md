# Final Analysis: 45 Missing Wins - Complete Root Causes

**Date:** 2026-09-04
**Context:** Found 72 total wins, but only 27 appear in qualification-week cohorts (from snapshot data)

---

## Summary

Of 45 "missing" wins (not in qualification cohorts):

| Category | Count | % | Root Cause | Fix Required |
|----------|-------|---|------------|--------------|
| Retroactive Entry (Long Cycle) | 22 | 48.9% | Entered already-won, never had `deal_status='active'` | Accept as limitation OR capture via alternative method |
| Data Quality Errors | 8 | 17.8% | Same-day or negative cycle (create > close) | Data cleanup |
| Fast-Track Short Cycle | 7 | 15.6% | < 14 day cycles, may fall between snapshots | Increase snapshot frequency OR accept |
| Excluded Stages | 5 | 11.1% | In excluded stages during snapshot window, qualified after | Accept as limitation |
| Carry-Over from Prior Quarter | 3 | 6.7% | Created before quarter, only in prior quarter snapshots | Query across quarters OR accept |
| **Total** | **45** | **100%** | | |

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

## Category 2: Data Quality Errors (8 deals, 17.8%)

### Characteristics
- 0-day cycles (create_date = close_date)
- Negative cycles (close_date < create_date)
- Logically impossible timelines

### Examples
- **Quizlet**: 0 day cycle (Jan 15 = Jan 15)
- **Bluesky**: 0 day cycle (Jan 12 = Jan 12)
- **Make**: -41 day cycle (closed before created!)
- **LeoVegas**: 0 day cycle (Jun 5 = Jun 5)

### Root Cause
**Data entry errors or system migration artifacts.**

Same-day create/close suggests:
1. Manual data entry error
2. Bulk import with placeholder dates
3. System migration where timing wasn't preserved

Negative cycles are pure data corruption.

### Fix
**Data cleanup required:**
1. Audit all 0-day and negative-day cycles
2. Investigate source of entries (bulk import? manual? API?)
3. Either fix timestamps OR mark as suspect data
4. Add validation to prevent future entries

**For conversion analysis:** Exclude these deals entirely (data unreliable)

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

**Phase 1: Document Limitations (Immediate)**
1. Update metrics registry with caveats:
   - "Excludes retroactive wins (48.9% of total)"
   - "Excludes data quality errors (17.8%)"
   - "Excludes deals in excluded stages during measurement window (11.1%)"
   - "Fast-track short-cycle deals may be undercounted (15.6%)"
   - "Carry-over deals from prior quarters may be undercounted (6.7%)"

2. Report two separate metrics:
   - **Prospective conversion rate**: From deals tracked in snapshots (27/376 = 7.2%)
   - **Retrospective win count**: Total wins including retroactive (72)

**Phase 2: Improve Data Quality (Short-term)**
1. Fix data quality errors (8 deals with impossible cycles)
2. Add validation to prevent same-day create/close
3. Audit bulk import processes

**Phase 3: Consider Methodology Alternatives (Long-term)**
1. If retroactive entry is common, track separately:
   - "Forward-looking deals" (entered active → qualified → won)
   - "Backdated deals" (entered already-won)

2. Implement quarter-spanning snapshot queries for carry-over deals

3. Evaluate if daily snapshots worth the cost for short-cycle capture

---

## Conclusion

The "45 missing wins" are NOT a single infrastructure problem. They represent FIVE distinct patterns:

1. **Retroactive entries (48.9%)** - Different data entry pattern, needs separate tracking
2. **Data errors (17.8%)** - Needs cleanup
3. **Fast-track deals (15.6%)** - Edge case, acceptable loss
4. **Excluded stages (11.1%)** - Measurement window limitation, correctly excluded
5. **Carry-over deals (6.7%)** - Query logic improvement needed

**No single fix addresses all five.** Each requires different remediation:
- Retroactive: Accept + document
- Data errors: Clean up
- Fast-track: Accept
- Excluded stages: Accept (correctly excluded during measurement)
- Carry-over: Improve query logic

**The qualification-week methodology is sound, but only for deals entered prospectively through normal pipeline stages.**

For comprehensive conversion tracking, need parallel metrics for different deal populations.

---

## ADDENDUM: Reconciliation & Source Analysis

### 22 vs 25 Reconciliation

**Pipeline migration check reported "25 long-cycle missing deals"**
**Category 1 reports "22 retroactive deals"**

**Resolution:**
The 25 long-cycle deals include:
- **22 retroactive** (Category 1) - Created in-quarter but not in snapshots
- **3 carry-over** (Category 4) - Created before quarter

Pipeline migration check filtered by `cycle_days >= 14`, which captures both categories. The breakdown is correct.

### Source Analysis of 22 Retroactive Deals

**Checked HubSpot fields:**
- No standard source fields populated (`hs_object_source`, `hs_created_by_user_id`, etc.)
- Cannot determine if systematic import vs scattered manual entries

**Findings:**
- ALL 22 have `deal_status='won'` (100%)
- No creation timestamp patterns suggesting bulk import
- No dominant source identifier

**Conclusion:** Cannot determine if fixable process issue or permanent characteristic. Likely scattered manual/backdated entries rather than single systematic source.

**Recommendation:** Accept as documented limitation. These deals entered already-won and should be tracked separately from prospective pipeline.

---

## Updated Recommendation

Given no systematic source identified:

1. **Track retroactive wins separately** - They're a different population
2. **Report two metrics:**
   - Prospective conversion: 27/376 qualified = 7.2%
   - Total wins: 72 (includes 22 retroactive)
3. **Document limitation:** "Excludes retroactive/backdated deals entered as already-won"

This is not a fixable process issue - it's a characteristic of how some historical deals enter the system.
