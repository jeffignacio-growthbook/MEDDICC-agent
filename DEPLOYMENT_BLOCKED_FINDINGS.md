# DEPLOYMENT BLOCKED - Critical Findings

**Date:** 2026-09-04
**Status:** DO NOT DEPLOY until these findings are addressed

---

## Executive Summary

Two pre-deployment verification checks revealed **deployment-blocking issues**:

1. **Aug 9 batch is 6x larger than expected** (49 deals, not 8)
2. **SMB segment rate shift is material** (+4.9pp, requires recomputation)
3. **Data quality exclusion scope is insufficient** (static list of 8 won't cover full batch)

---

## Finding 1: Aug 9 Batch - Systematic Bulk Import

### Original Assessment (INCORRECT)
- "Scattered manual entry"
- 8 deals with impossible timelines
- Bluesky/Quizlet appearing twice was "coincidence"

### Actual Finding (VERIFIED)
**506 deals touched** in 2-minute window (Aug 9, 08:38-08:40)
**49 deals owned by christian@growthbook.io** from this batch

**6 companies have DUPLICATE deals:**
- LeoVegas: 3 deals
- Quizlet: 2 deals
- 7shifts: 2 deals
- Hey Harper: 3 deals
- InvestEngine: 2 deals
- higgsfield.ai: 2 deals

**Data Quality Issues Found:**
- 4 impossible timelines (0-day or negative cycles)
- 6 duplicate company entries
- 1 won deal with zero ARR

### Evidence
```
created_at timestamps (all within 45 seconds):
  2026-08-09 08:38:56 - Quizlet deal 1
  2026-08-09 08:38:57 - Quizlet deal 2  (1 second later)
  2026-08-09 08:39:06 - Bluesky deal 1  (10 seconds later)
  2026-08-09 08:39:42 - Bluesky deal 2  (36 seconds later)
```

**All owned by:** christian@growthbook.io

### Why This Matters

**Static exclusion list insufficient:**

Current migration:
```sql
INSERT INTO data_quality_exclusions (deal_id, ...)
VALUES ('5790911698', ...), ('5681417580', ...), ...  -- 8 static IDs
```

**This only flags 8 deals, but 49 came from the same corrupted batch.**

If other deals from Aug 9 batch have subtler issues (wrong ARR, wrong stage, wrong dates that don't show as "impossible"), they'll pollute metrics without being caught.

### Recommended Fix

**Option A: Temporal + owner filter**
```sql
-- Flag all deals from the corrupted batch
SELECT deal_id FROM deals
WHERE created_at BETWEEN '2026-08-09 08:38:00' AND '2026-08-09 08:40:00'
  AND owner_email = 'christian@growthbook.io'
```

Pros:
- Captures all 49 deals from batch
- Catches subtler issues we haven't detected
- More accurate than cherry-picking 8

Cons:
- May flag deals that are actually fine
- Broader exclusion (49 vs 8)

**Option B: Enhanced vetting**
- Audit all 49 deals individually
- Determine which are genuinely bad
- Create exclusion list of vetted bad deal_ids

Pros:
- More precise
- Only excludes truly bad deals

Cons:
- Time-consuming
- Risk of missing subtle issues

**Option C: Hybrid**
- Flag all 49 as "suspect_aug9_batch"
- Allow per-metric decision on whether to exclude
- Document why each metric excludes or includes

**RECOMMENDED: Option A** - temporal filter captures systematic issue at source

---

## Finding 2: Sept 3 Update - Mass ETL (Not Correction)

### Question
What happened Sept 3 at 20:58 when all 8 data quality deals were updated?

### Finding
**NOT a correction attempt.**

**773 deals** updated in 20:57-21:00 window
**1,889 deals total** updated on Sept 3
**This was system-wide ETL/sync**, not targeted fix

The 8 data quality deals were incidentally updated along with everything else. Whatever update occurred, it:
- Did NOT fix the impossible timelines
- Did NOT correct the data quality issues
- Was part of routine ETL/sync operation

### Implication
No evidence of prior correction attempt. The bad data has persisted since Aug 9 import.

---

## Finding 3: SMB Segment Rate Shift - Material Change

### Question
Does cross-quarter fix (7.2% → 7.9% overall) require segment recomputation?

### Finding
**YES - SMB segment shifts materially.**

**Carry-over deal segments:**
- Fellow: **SMB** (Q3 close)
- Yeet!: **SMB** (Q4 close)
- Wellhub: **Mid-Market** (Q1 close)

**Impact:**

| Segment | Before | After | Change | Material? |
|---------|--------|-------|--------|-----------|
| SMB | 1/41 = 2.4% | 3/41 = 7.3% | **+4.9pp** | **YES** |
| Mid-Market | 3/60 = 5.0% | 4/60 = 6.7% | +1.7pp | No |
| Enterprise | 8/54 = 14.8% | (no change) | 0pp | No |

**SMB rate TRIPLES** with cross-quarter fix. This is statistically significant given n=41.

### Why This Matters

If we deploy cross-quarter fix and update overall rate (7.2% → 7.9%) but **don't** update SMB segment rate (2.4% → 7.3%), we have:
- Inconsistent metrics (overall updated, segments stale)
- Misleading SMB forecasts (off by 4.9pp)
- Violated fragility warning (small n means changes matter)

### Recommended Action

**Before deployment:**
1. Run `conversion_by_qualification_week_CROSS_QUARTER.py` with segment breakdown
2. Recompute all segment rates with carry-over deals included
3. Update `config/metrics.yaml`:
   ```yaml
   by_segment:
     smb:
       value: 0.073  # 3/41, was 0.024
       n: 41
       won: 3  # was 1
   ```
4. Keep volatility warnings in place

---

## Deployment Decision Tree

### Can we deploy as currently scoped?

**NO.** Both follow-up items have blocking issues:

#### Item 1 (Data Quality Exclusions)
- ❌ Static list of 8 deal_ids is insufficient
- ❌ 49 deals from Aug 9 batch need evaluation
- ❌ Migration scope must be revised

**Action Required:**
1. Decide on exclusion scope (8 vs 49 deals)
2. If 49: Revise migration to use temporal + owner filter
3. If 8: Audit remaining 41 deals, document why excluded

#### Item 2 (Cross-Quarter Lookup)
- ❌ SMB segment rate is stale (+4.9pp material change)
- ❌ Deploying without segment recomputation creates inconsistency

**Action Required:**
1. Run cross-quarter script with segment breakdown
2. Recompute SMB, Mid-Market, Enterprise rates
3. Update config/metrics.yaml with new segment rates
4. Document +4.9pp shift in SMB (2 carry-over wins)

---

## Revised Deployment Checklist

### Before Deploying Item 1 (Data Quality):
- [ ] Decision: Exclude 8 or 49 deals from Aug 9 batch?
- [ ] If 49: Revise migration to temporal + owner filter
- [ ] If 8: Audit remaining 41, document rationale
- [ ] Update DATA_QUALITY_EXCLUSIONS_README.md with findings
- [ ] Apply revised migration
- [ ] Verify exclusion in test query

### Before Deploying Item 2 (Cross-Quarter):
- [ ] Run conversion script with segment breakdown enabled
- [ ] Verify SMB: 3/41 = 7.3% (was 1/41 = 2.4%)
- [ ] Verify Mid-Market: 4/60 = 6.7% (was 3/60 = 5.0%)
- [ ] Verify Enterprise: 8/54 = 14.8% (unchanged)
- [ ] Update config/metrics.yaml with new rates
- [ ] Document +4.9pp SMB shift (carry-over Fellow + Yeet!)
- [ ] Test production script
- [ ] Deploy

### After Both Deployed:
- [ ] Rerun reconciliation (should show 30/379 = 7.9%)
- [ ] Verify segment rates match computed values
- [ ] Update dashboards/reports with new rates
- [ ] Communicate changes to stakeholders

---

## Files Generated

Investigation scripts:
- `investigate_aug9_batch.py` - Aug 9 batch analysis (49 deals)
- `investigate_sept3_update.py` - Sept 3 update investigation (mass ETL)
- `confirm_smb_rate_shift.py` - SMB rate shift verification

Output files:
- `aug9_batch_full_analysis.txt` - Complete Aug 9 findings
- `sept3_update_analysis.txt` - Complete Sept 3 findings

---

## Recommendation

**DO NOT DEPLOY until:**

1. **Aug 9 batch scope decided** (8 vs 49 deals)
2. **Segment rates recomputed** (especially SMB +4.9pp)
3. **Migration revised** (if needed for broader scope)
4. **Documentation updated** with actual findings

The original "scattered manual entry" assessment was incorrect. This is a **systematic bulk import** with **6 companies affected by duplicates**, not just 2.

The SMB segment shift is **material** (+4.9pp on n=41). Deploying cross-quarter fix without updating SMB rate creates metric inconsistency.

**Estimated additional work:** 2-4 hours
- Audit Aug 9 batch scope: 1-2 hours
- Recompute segment rates: 30 min
- Revise migration (if needed): 30 min
- Update documentation: 30 min

---

## Questions for Decision

1. **Aug 9 batch:** Exclude all 49 deals (safer) or just the 8 with timeline issues (narrower)?

2. **Duplicates:** What should happen to the 6 companies with multiple deals from Aug 9 batch?
   - Keep all deals?
   - Flag for manual review?
   - Auto-dedup based on criteria?

3. **Zero ARR deal:** 7shifts won deal with $0 ARR - is this data error or legitimate?

4. **Segment recomputation:** Who needs to approve SMB rate changing from 2.4% → 7.3%?

---

**Bottom Line:** Both verification checks found deployment-blocking issues. Original scope was too narrow (8 deals vs 49), and segment rates need updating. Deployment should wait until these are resolved.
