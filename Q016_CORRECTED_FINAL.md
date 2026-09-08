# Q016 Cycle Time - CORRECTED FINAL (Renewals Excluded)

**Date:** September 6, 2026
**Status:** READY FOR JEFF'S DECISION

---

## Executive Summary

**Critical methodology bug fixed:** Previous cycle_time numbers included renewal pipeline deals (80% of population). Renewal `create_date` does not represent sales cycle start - renewals are often created at initial close, then sit dormant for contract duration.

**Corrected population:** Non-renewal deals only (new business + expansion)

---

## Corrected Numbers (Renewals Excluded)

| Window | Median | Sample | Change from Contaminated |
|--------|--------|--------|--------------------------|
| **All-time** | **52 days** | 22 deals | Was 116 days (Δ=-64) |
| **Rolling 12-month** | **56 days** | 14 deals | Was 156.5 days (Δ=-100) |
| **Rolling 6-month** | **56 days** | 12 deals | Was 158 days (Δ=-102) |

**Key Findings:**
1. **NO lengthening trend** - all windows cluster around 52-56 days
2. **Very small samples** - rolling windows below 20-deal threshold (14, 12 deals)
3. **False "trend" was 100% renewal contamination** - not real business signal

---

## What Was Wrong

### Contaminated Population (Before Fix)
- Total "won deals": 113
- **Renewal pipeline: 91 deals (80.5%)** ← CONTAMINATING
- Non-renewal: 22 deals (19.5%)

### Why Renewals Contaminate
Top 5 longest "cycles" (500-740 days) were **ALL renewals**:
1. Gumtree: 740 days (renewal created 2024-07-17, closed 2026-07-27)
2. idealo: 561 days
3. Reach plc: 518 days
4. Meister: 516 days
5. Eneco: 500 days

**Pattern:** Renewal opps created at initial close → sit dormant for contract duration → renewed after 500+ days. This is **contract duration**, not **sales cycle**.

### Contamination Impact
- Renewal median: 154 days
- Non-renewal median: 52 days
- **Contamination added 64-102 days** to reported medians

---

## Quarter-by-Quarter Trend Analysis (Corrected)

**Non-renewal deals by quarter (non-overlapping):**

| Quarter | Sample | Median | Notes |
|---------|--------|--------|-------|
| FY2026 Q1 | 1 deal | 41 days | Too small |
| FY2026 Q2 | 1 deal | 91 days | Too small |
| FY2026 Q3 | 1 deal | 0 days | Too small |
| FY2026 Q4 | 2 deals | 64 days | Too small |
| **FY2027 Q1** | **8 deals** | **62 days** | Most robust |
| FY2027 Q2 | 2 deals | 32 days | Too small |

**Result:** NOT monotonic. Sequence: 41 → 91 → 0 → 64 → 62 → 32
**Average recent 6 quarters:** 48 days (close to all-time 52 days)

**Conclusion:** No evidence of lengthening. High quarter-to-quarter variance due to very small samples (1-8 deals per quarter).

---

## Recommendation: All-Time Window (52 Days)

**Why all-time, not rolling:**

1. **No trend to track** - all windows cluster at 52-56 days, rolling adds no value
2. **Sample size critical** - only 22 non-renewal wins total
   - Rolling 12-month: 14 deals (below 20 threshold)
   - Rolling 6-month: 12 deals (below 20 threshold)
   - All-time: 22 deals (still small, but best available)
3. **GrowthBook has very few non-renewal wins** - need full dataset for reliability

**Config already updated:** `window_mode: "all_time"` in `config/metrics.yaml`

---

## Methodology Fix Applied

### Handler Updated (`api/handlers.py::compute_cycle_time`)
**Population filter added:**
```python
RENEWAL_PIPELINE_ID = "866608541"
deals = [
    d for d in all_deals.data
    if is_won(d.get("stage")) and d.get("pipeline_id") != RENEWAL_PIPELINE_ID
]
```

### Config Updated (`config/metrics.yaml::cycle_time`)
**Documented:**
- `population: won, non-renewal deals only`
- `pipeline_filter: NON-RENEWAL ONLY (pipeline_id != '866608541')`
- Rationale: renewal create_date ≠ cycle start
- Contamination discovery details (80% contamination, 64-102 day inflation)
- Corrected verified values (52/56/56 days)

### Handler Tested
```bash
python scripts/test_cycle_time_handler.py
# ✅ Returns: 52.5 days (22 deals) - all-time window
```

---

## Renewal Cycle Time (Separate Metric - Not Yet Implemented)

**Renewal deals excluded from cycle_time need their own metric.**

**Open question for Jeff:**
What is the correct **start point** for renewal cycle time?

**Options:**
1. **renewal_engaged_date** (if field exists) → close_date
2. **contract_expiry_date minus N days** → close_date
3. **Some other business-defined start point**

**NOT create_date** - creates 500-700 day "cycles" that are actually contract duration.

**Next step:** Define renewal cycle time separately after new business metric is locked.

---

## What Jeff Needs to Decide

**NO window choice needed** - all-time is the clear choice given:
- No trend (52-56 days across all windows)
- Small samples (rolling windows below threshold)
- All-time provides best stability

**Decision already made in config:** `window_mode: "all_time"`, `current_value: 52 days`

**What Jeff should validate:**
1. **52 days sounds right?** Does this match his intuition for new business cycle time?
2. **Accept 22-deal sample?** Very small, but it's all the non-renewal wins available
3. **Renewal metric priority?** Should we define renewal cycle time as a separate metric?

---

## Files Updated

1. ✅ `api/handlers.py::compute_cycle_time()` - Added renewal exclusion filter
2. ✅ `config/metrics.yaml::cycle_time` - Documented corrected population, updated verified values
3. ✅ `scripts/count_renewal_contamination.py` - Contamination discovery script
4. ✅ `scripts/recompute_cycle_time_corrected.py` - Recomputation with renewals excluded
5. ✅ `scripts/validate_trend_corrected.py` - Quarter-bucket trend analysis (corrected)
6. ✅ `scripts/investigate_outlier_deals.py` - Identified renewal pattern in outliers

---

## Validation Checklist

- ✅ Renewal contamination quantified (80%, 91 of 113 deals)
- ✅ Corrected medians computed (52/56/56 days)
- ✅ Quarter-bucket trend re-analyzed (no trend found)
- ✅ Outliers investigated (100% renewals)
- ✅ Handler updated with population filter
- ✅ Config documented with rationale
- ✅ Handler tested (returns 52.5 days, 22 deals)

---

## Key Takeaway

**The "40-day lengthening trend" never existed.**

It was a methodology bug: 80% renewal contamination inflating medians by 64-102 days. With renewals properly excluded, new business cycle time is stable at **52 days** with no evidence of lengthening.

**Metric is now correct, template-portable, and ready for production.**

---

**Status:** ✅ IMPLEMENTATION COMPLETE
**Blocking Jeff:** Validation only - does 52 days match his intuition?
**Next:** Define renewal cycle time as separate metric (different start point)
