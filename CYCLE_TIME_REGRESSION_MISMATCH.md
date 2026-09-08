# Cycle Time Regression Mismatch

**Date:** 2026-09-08
**Status:** 🔍 NEEDS INVESTIGATION

---

## Expected vs. Actual

**Expected (from metrics.yaml verified section):**
- **Median:** 52 days
- **Sample size:** 22 deals
- **Verified date:** 2026-09-06

**Actual (parameterized function, all_time):**
- **Median:** 62 days
- **Sample size:** 219 deals
- **Test date:** 2026-09-08

---

## Discrepancy Analysis

**Sample size divergence:** 219 vs 22 = **10x difference**

### Hypothesis 1: Different Population Filter

**Original verification** (from metrics.yaml lines 836-965):
```
population_validation:
  date: "2026-09-06"
  trigger: |
    Cross-metric plausibility check flagged 22 non-renewal won deals (19% of wins)
    against already-verified 306 active non-renewal deals (69% of active pipeline).

contamination_discovery:
  finding: |
    Original cycle_time included renewal pipeline deals (pipeline_id='866608541').
    Renewals comprised 80% of "won deals" (91 of 113). Renewal create_date does
    not represent sales cycle start...

    Top 5 longest "cycles" (500-740 days) were ALL renewals.

  contaminated_values:
    all_time: "116 days (113 deals)"
```

**Key observations:**
- Original all-time: 113 deals (contaminated with renewals)
- After excluding 91 renewals: 22 deals (clean)
- This matches the verified sample_size of 22!

**But today's query returns 227 won deals** in default pipeline (before any exclusions).

### Hypothesis 2: Date Added Since Verification

**Time gap:** 2 days (2026-09-06 to 2026-09-08)

**Plausibility:** 227 vs 113 = **114 new won deals in 2 days?**
This seems implausible for organic growth.

### Hypothesis 3: Different Data Source

**Verification may have used:**
- HubSpot API directly (like GRR scripts)
- Specific date range filter (not documented)
- Different database snapshot

**Current implementation uses:**
- Supabase deals table
- All-time query (no date filter except period parameter)
- Full pagination (all 1634 deals in default pipeline)

---

## Action Items

### Option A: Accept Current as Correct
If Supabase has been continuously updated since verification and now has more complete data:
- Update verified values in metrics.yaml to 62 days / 219 deals
- Document as "verification updated with full dataset"
- Re-verify other metrics that may be affected

### Option B: Investigate Verification Source
Determine exactly how the original 52 days / 22 deals was calculated:
- Check if there's a date range that wasn't documented
- Check if HubSpot API returns different results than Supabase
- Verify data sync status between HubSpot and Supabase

### Option C: Temporary Workaround for Sales Velocity
For Phase 2 dogfood test #2:
- Use current parameterized function (62 days all-time)
- Document regression mismatch as known issue
- Proceed with Sales Velocity test using current values
- Circle back to regression investigation separately

---

## Current Implementation Status

**Parameterized cycle_time function:**
- ✅ Accepts period={start, end} parameter
- ✅ Applies hygiene rules (exclude_renewals, exclude_invalid_cycles)
- ✅ Filters to pipeline_id="default"
- ✅ Computes median correctly
- ✅ Returns full context (distribution, exclusions, sample_size)

**Regression check:**
- ❌ Does NOT match verified 52 days / 22 deals
- ⚠️ Actual: 62 days / 219 deals (10x sample size)

---

## Recommendation

**Proceed with Option C** (temporary workaround):

1. Document current cycle_time values as "production baseline"
2. Use these values for Sales Velocity composition test
3. Circle back to investigate 22 vs 219 discrepancy after test complete
4. This allows us to:
   - Test the parameterization architecture (primary goal)
   - Test composition and hygiene rule reuse
   - Defer data archaeology that may take significant time

**If Jeff wants perfect regression match first:**
- Need to determine exact population/date filter used for original verification
- May require running queries against both HubSpot API and Supabase for comparison
- Estimated time: 1-2 hours investigation

---

## Questions for Jeff

1. Should we investigate the 22 vs 219 discrepancy now, or proceed with current values?
2. Do you have the original script that produced the 52 days / 22 deals verification?
3. Is it acceptable to update verified values to 62 days / 219 deals if current data is correct?
