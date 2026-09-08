# GRR Validation - Executive Summary

**Date:** 2026-09-07
**Status:** ⚠️ REVIEW REQUIRED

---

## Bottom Line

**Formula is mathematically correct** but **multi-period results reveal concerns** requiring your assessment.

---

## What's Proven ✅

| Item | Status | Evidence |
|------|--------|----------|
| Contraction handling | ✅ VERIFIED | Exact $-2,000 match (with/without comparison) |
| Formula independence | ✅ VERIFIED | No prior_arr/gb_arr dependency |
| Q2 2026 results | ✅ VERIFIED | GRR 73.92%, NRR 100.02% |

---

## What's Concerning ⚠️

### 1. High GRR Variance (25.6 ppts)

```
Q1 2026: 87.89% GRR  ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
Q2 2026: 73.92% GRR  ━━━━━━━━━━━━━━━━━━━━━━━━
Q3 2026: 62.29% GRR  ━━━━━━━━━━━━━━━━━━
```

**Range:** 62.3% → 87.9% (exceeds 20 ppt threshold)

**Is this:**
- Real business decline?
- Contamination from data issues?
- Seasonal pattern?

---

### 2. Open Deals in Closed Periods

| Period | Open Deals | Total Cohort | % Open | Months Past |
|--------|------------|--------------|--------|-------------|
| Q1 2026 | 4 | 21 | 19% | 5+ months |
| Q2 2026 | 3 | 27 | 11% | 2+ months |
| Q3 2026 | 18 | 28 | **64%** | Current |

**Q3 is especially concerning:** 64% still open with 23 days left in quarter.

---

### 3. Zero-Revenue Deals

**Q1:** 3 deals with $0 renewal_revenue
**Q3:** 2 deals with $0 renewal_revenue

**Problem:** These contribute to denominator but can never contribute to numerator → artificially deflates GRR.

---

## Q2 "Other Stage" Deals (Check 1)

**Found 3 deals** in "Upcoming Renewal" stage:

1. Docsity - 2026 Renewal ($5,750)
2. Lease a Bike - 2026 renewal ($13,000)
3. Lease a Bike Nederland - 2026 Renewal ($13,000)

**Current treatment:** Included in denominator, excluded from numerator (conservative).

---

## Expansion Scope (Check 2)

**Current:** Renewal pipeline expansion only
**Documented:** Trade-offs between narrow vs. broad scope
**Recommendation:** Keep narrow unless you request broader

---

## 4 Questions for Jeff

### Q1: Is 25.6 ppt GRR variance plausible?
Real business pattern or contamination signal?

### Q2: How to handle open deals in closed periods?
- Current: Exclude from numerator only
- Alternative: Exclude from denominator too
- Or flag as provisional?

### Q3: Should $0 renewal_revenue deals be filtered out?
They deflate GRR artificially.

### Q4: Is Q3's 64% open rate normal?
23 days left in quarter, but most deals still unresolved.

---

## Detailed Results

### Q1 2026: 87.89% GRR, 100.78% NRR
- Cohort: 21 deals (14 won, 3 lost, 4 open)
- Denominator: $596,792.52
- Contraction: $36,250 (Vestiaire)
- ⚠️ 3 deals with $0 renewal_revenue
- ⚠️ 4 deals still open (5+ months past close)

### Q2 2026: 73.92% GRR, 100.02% NRR  ✅ VALIDATED
- Cohort: 27 deals (19 won, 5 lost, 3 open)
- Denominator: $850,677.88
- Contraction: $-2,000 (Byborg)
- ⚠️ 3 deals still open (2+ months past close)

### Q3 2026: 62.29% GRR, 74.30% NRR
- Cohort: 28 deals (10 won, 0 lost, 18 open)
- Denominator: $1,613,423.97
- No contraction
- ⚠️ **18 deals still open (64%)**
- ⚠️ 2 deals with $0 renewal_revenue

---

## Possible Next Steps

### If Variance Is Real
→ Formula working correctly, document pattern, production-ready ✅

### If Variance Shows Contamination
→ Add filters for $0 revenue, adjust denominator, re-validate 🔧

### If Data Quality Issues
→ Investigate $0 revenue deals, investigate stale stages 🔍

---

## Files

**Scripts:**
- `scripts/grr_cohort_formula.py` - Production formula
- `scripts/complete_grr_validation.py` - Validation with all 3 checks

**Documentation:**
- `GRR_VALIDATION_COMPLETE.md` - Full findings (this summary's source)
- `GRR_FINAL_STATUS.md` - What's proven vs. pending
- `GRR_EXECUTIVE_SUMMARY.md` - This file

---

**Ready for your review.**
