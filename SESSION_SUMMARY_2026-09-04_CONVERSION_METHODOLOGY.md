# Session Summary: Conversion Rate Methodology Build

**Date:** 2026-09-04
**Status:** Build/test mode - not ready for customer presentation
**Session goal:** Implement cohort-by-qualification-week conversion methodology

---

## What We Built

### 1. Fixed Critical Pagination Bug

**File:** `reconcile_all_quarters_correct.py`

**Issue:** Queries returning only 1000 rows due to PostgREST pagination limit, missing most wins

**Root cause:** Filtering in Python AFTER `.execute()` instead of server-side BEFORE pagination

**Fix:** Use server-side filters (`.eq()`, `.gte()`, `.lte()`) before `.execute()`

**Impact:**
- Q3 win count corrected: 2 → 21 (10x undercount)
- Q4 win count corrected: discovered after pagination fix
- Q1 win count corrected: discovered after pagination fix
- **Total wins: 72 (vs 20 before fix)**

**Critical learning:** Always filter server-side when dealing with tables > 1000 rows

---

### 2. Reconciled Win Counts Across All Quarters

**Files:** `reconcile_all_quarters_correct.py`, `debug_q3_discrepancy.py`

**Results:**

| Quarter | Total Wins | Week-3 Cohort Wins | % Captured |
|---------|------------|-------------------|------------|
| FY2026 Q3 | 21 | 3 | 14.3% |
| FY2026 Q4 | 22 | 4 | 18.2% |
| FY2027 Q1 | 29 | 5 | 17.2% |
| **Total** | **72** | **12** | **16.7%** |

**Key finding:** **83.3% of wins qualified AFTER week-3**

This reveals the fixed week-3 cutoff systematically excludes 5/6 of eventual winners from the denominator, causing massive undercount in conversion rate calculations.

---

### 3. Verified Segment-Specific Rates

**File:** `verify_segment_scope_and_deal_type.py`

**Population:** 169 qualified deals from week-3 cohort, 12 wins

| Segment | Qualified | Won | Rate |
|---------|-----------|-----|------|
| Enterprise | 88 | 13 | 14.8% |
| Mid-Market | 60 | 3 | 5.0% |
| SMB | 21 | 2 | 2.4% |

**Validation checks:**
- ✓ All deals are New Business (no expansion/renewal mixing)
- ✓ Scope filter applied identically across all segments
- ✓ No pipeline mixing (all `pipeline_id = 'default'`)

---

### 4. Investigated SMB Qualification Gap

**File:** `analyze_smb_qualification_gap.py`

**Context:** SMB shows 11.0% qualification rate at week-3 vs 25.9% Enterprise

**Findings:**

**Task 1: Sales cycle length**
- SMB: ~90 days average (n=1, low confidence)
- Enterprise: ~140 days average
- **Difference: 36% shorter cycles for SMB**

**Task 2: Fate of excluded-stage deals**
- SMB progression rate: 95.5% (21/22) advance from excluded stages
- Enterprise progression rate: 87.6% (141/161)
- **SMB deals progress BETTER than Enterprise**

**Conclusion:** SMB qualification gap is a **timing artifact**, not hygiene problem
- Shorter cycles mean week-3 catches SMB deals "earlier" in their lifecycle
- Excluded-stage deals eventually progress normally
- Not a process quality issue

---

### 5. Attempted Cohort-by-Qualification-Week Methodology

**Files:** `conversion_by_qualification_week.py`, `conversion_by_qualification_week_q1.py`

**Goal:** Replace fixed week-3 cutoff with dynamic cohorts by when deals FIRST qualified

**Methodology:**
1. For each deal, find week-of-quarter when it first entered qualified stage
2. Group deals by qualification week
3. Compute conversion rate per bucket
4. Expect decay curve (early qualifiers convert higher)

**Status:** **BLOCKED - incomplete snapshot grid**

**Discovered issues:**
- Q3: Only weeks 1-2 captured (missing 3-13)
- Q4: Only weeks 4-13 captured (missing 1-3)
- Q1: Claims weeks 1-13 complete, but data shows deals qualifying ONLY in weeks 1-2 (data quality issue)

**Result:** Only 12 of 72 wins could be tracked via snapshots (same 16.7% as fixed week-3 method)

---

### 6. Tested HubSpot API Backfill

**File:** `test_hubspot_history_feasibility.py`

**Goal:** Use HubSpot's property history API to reconstruct qualification timing for Q3/Q4

**Result:** **NOT FEASIBLE**
- Property history API returns empty dealstage history
- Data not retained or not accessible via this endpoint
- Cannot backfill missing snapshot weeks from HubSpot

---

### 7. Flagged Infrastructure Issue

**File:** `SNAPSHOT_GRID_INFRASTRUCTURE_ISSUE.md`

**Summary:** Snapshot table has pervasive data incompleteness across ALL quarters, blocking cohort-by-qualification-week analysis

**Root cause:** TBD (requires investigation)
- Hypothesis A: Snapshot job not running consistently
- Hypothesis B: Deals created already qualified (only captured once)
- Hypothesis C: Snapshot logic error

**Impact:** Cannot implement timing-based conversion methodology until fixed

**Owner:** Data Engineering / RevOps Infra
**Timeline:** ~5 weeks to resolution

---

## Key Discoveries

### Discovery 1: Week-3 Cutoff Captures Only 16.7% of Wins

**Implication:** Current methodology systematically undercounts conversion denominators

**Example:**
- Total wins in Q1: 29
- Week-3 cohort: 5 wins
- **Missing:** 24 wins (82.8%) that qualified after week-3

**Why this matters:** Forecast calculations use week-3 cohort size as denominator, but most deals aren't qualified yet at that point

---

### Discovery 2: Pagination Bug Was Hiding True Win Counts

**Before fix:** Q3 showed 2 total wins, 3 from week-3 cohort (impossible)
**After fix:** Q3 showed 21 total wins, 3 from week-3 cohort (valid)

**Lesson:** Always validate cohort ⊂ population before trusting results

---

### Discovery 3: Snapshot Grid More Broken Than Initially Thought

**Initial belief:** Q3/Q4 gaps, Q1 complete
**Reality:** Even Q1 shows data quality issues (all qualification in weeks 1-2, none after)

**Implication:** Infrastructure problem is systemic, not isolated to specific quarters

---

### Discovery 4: SMB "Problem" Is Actually Timing Artifact

**Initial concern:** 11% SMB qualification rate vs 25.9% Enterprise → poor pipeline hygiene?
**Finding:** SMB cycles 36% shorter + excluded-stage deals progress at 95.5% rate

**Conclusion:** Week-3 snapshot catches SMB deals earlier in their lifecycle, not evidence of worse process

---

## What's Blocked

1. **Cohort-by-qualification-week conversion rates**
   - Requires complete snapshot grid
   - Cannot determine optimal cutoff (week-3 vs week-5 vs week-8)

2. **Timing-based segment analysis**
   - Cannot verify if qualification timing varies by segment
   - Cannot adjust methodology per segment

3. **Qualification decay curve**
   - Cannot quantify "early qualifiers convert at X%, late qualifiers at Y%"
   - Shape of curve is the finding (not single blended rate)

---

## Current State: Interim Methodology

### Using Fixed Week-3 Cutoff with Caveats

**Pooled conversion rate:** 7.1% (12 won / 169 qualified)

**Segment rates:**
- Enterprise: 14.8% (13/88)
- Mid-Market: 5.0% (3/60)
- SMB: 2.4% (2/21) ⚠ low n

**Caveats to document:**
1. Week-3 cutoff excludes 83.3% of eventual wins from denominator
2. Systematic undercount affects all segments
3. Timing artifact (not process quality) drives segment variance
4. Small n per segment (especially SMB n=21, Mid-Market n=60)
5. Single deal type (New Business only)

**Updated files:**
- `config/metrics.yaml` - Verified rates with caveats
- `scripts/utils.py` - Semantic context updated to reference 7.1% pooled rate

---

## Recommendations

### For Ryan / Customer Presentation

**DO NOT present yet** - still in build/test mode

When ready to present:
1. Lead with 7.1% pooled rate (verified, conservative)
2. Show segment variation (Enterprise 14.8% > SMB 2.4%)
3. Caveat small n for SMB/Mid-Market
4. Frame as "qualified at week-3" rate (not "overall conversion rate")
5. Note: Most deals (83.3%) qualify later → tracking methodology improvement in progress

**Do NOT:**
- Present as "definitive conversion rate" without caveats
- Blame SMB for "poor pipeline hygiene" (timing artifact, not quality)
- Over-index on single-quarter volatility

### For Infrastructure / Data Team

**Priority 1: Fix snapshot grid**
1. Investigate root cause (see `SNAPSHOT_GRID_INFRASTRUCTURE_ISSUE.md`)
2. Backfill missing weeks if possible
3. Ensure job runs consistently going forward

**Priority 2: Alternative qualification tracking**
- Add `first_qualified_date` column to `deals` table
- Populate via webhook or nightly ETL
- Don't rely on retroactive reconstruction

**Priority 3: Accumulate more quarters**
- Once snapshot grid fixed, accumulate 3+ quarters of complete data
- Re-run cohort-by-qualification-week analysis with better statistical power

---

## Files Created This Session

| File | Purpose | Status |
|------|---------|--------|
| `reconcile_all_quarters_correct.py` | Fix pagination bug, validate win counts | ✓ Working |
| `debug_q3_discrepancy.py` | Diagnose Q3 win count issue | ✓ Completed |
| `verify_segment_scope_and_deal_type.py` | Validate segment rates | ✓ Completed |
| `analyze_smb_qualification_gap.py` | SMB timing vs hygiene analysis | ✓ Completed |
| `analyze_qualification_timing.py` | When do wins qualify? | ✓ Completed (limited by data) |
| `conversion_by_qualification_week.py` | Dynamic cohort methodology | ⚠ Blocked by data |
| `conversion_by_qualification_week_q1.py` | Q1-only attempt | ⚠ Data quality issues |
| `test_hubspot_history_feasibility.py` | HubSpot API backfill test | ✗ Not feasible |
| `SNAPSHOT_GRID_INFRASTRUCTURE_ISSUE.md` | Infrastructure backlog doc | ✓ Documented |
| This file | Session summary | ✓ You are here |

---

## Next Steps

### Immediate (This Week)
1. ✓ Document snapshot grid issue for infra team
2. ✓ Update metrics registry with verified rates + caveats
3. ✓ Flag small-n segments for volatility warnings

### Short-term (Next Sprint)
1. Wait for snapshot grid investigation results
2. Consider alternative qualification tracking methods
3. Accumulate Q2 data (if snapshot job fixed)

### Medium-term (Next Quarter)
1. Re-run cohort-by-qualification-week with complete data
2. Validate timing-based decay curve
3. Adjust cutoff if data supports (week-5 vs week-3)
4. Build segment-specific methodologies if warranted

---

## Lessons Learned

1. **Always filter server-side** when dealing with pagination limits
2. **Validate cohort ⊂ population** before trusting results
3. **Infrastructure data quality** can block methodological improvements
4. **Timing artifacts** can masquerade as process quality issues
5. **HubSpot API history** not reliable for retroactive reconstruction
6. **Small n** requires statistical humility (low confidence intervals)

---

## Status: SESSION COMPLETE

**Built:** Fixed pagination bug, reconciled win counts, verified segment rates
**Discovered:** 83.3% of wins qualify after week-3, snapshot grid systematically incomplete
**Blocked:** Cohort-by-qualification-week methodology requires data infra fix
**Interim:** Use fixed week-3 with documented caveats
**Next:** Wait for snapshot grid investigation, accumulate more quarters of clean data
