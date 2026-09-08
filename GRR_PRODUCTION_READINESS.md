# GRR Production Readiness - Final Validation

**Date:** 2026-09-07
**Formula:** Cohort-based GRR/NRR (no prior_arr/gb_arr dependency)

---

## Status Summary

**Primary proof:** ✅ PASSED (contraction handling verified, exact $-2,000 match)
**Formula validation:** ✅ Cohort approach works, no manual field dependency
**Remaining checks:** 3 open questions before production sign-off

---

## Check 1: "Other Stage" Deals Status

**Finding from Q2 2026:** 3 deals in "other stage" (not won/lost)

Need to determine:
- Are these still open (provisional) or terminal state?
- If open: Does historical GRR need "provisional until resolved" flag?

**Required decision:**
Per qualification-week cohort discipline: deals that haven't resolved by period end don't count as wins (conservative). For closed historical periods, GRR should be treated as FINAL once computed.

**Action:** Inspect these 3 Q2 deals manually to understand their status.

---

## Check 2: Expansion Scope for NRR

**Current implementation:** NRR includes expansion_revenue from won renewal deals only.

**Question:** Should NRR also include:
- DEFAULT pipeline deals (upsells/expansions) for cohort companies?
- Risk: Double-counting if deal appears in both pipelines

**Recommendation:**
Start with renewal pipeline only (conservative, current implementation). Expand to all pipelines only if:
1. User explicitly requests broader definition
2. We verify no double-counting risk (deal can't be in both pipelines simultaneously)

**Action:** Document as design choice, make it configurable if needed.

---

## Check 3: Multi-Period Sanity Check

**Test:** Run formula on Q1, Q2, Q3 2026 to check for erratic behavior.

**Expected:** GRR should be relatively stable (±10-20 percentage points reflects normal business volatility).

**Why this matters:** Single-period convergence proved insufficient multiple times today (implicit filtering, Signal 2 thin cells, etc.). Need to verify formula doesn't produce erratic/implausible results across periods.

**Action:** Execute multi-period comparison (see below).

---

## Multi-Period Results (To Be Completed)

### 2026 Q1
- Cohort: TBD
- GRR: TBD%
- NRR: TBD%

### 2026 Q2 (Already Validated)
- Cohort: 27 deals (19 won, 5 lost, 3 other)
- GRR: 73.92%
- NRR: 100.02%
- Contraction verified: ✅ Exact match

### 2026 Q3
- Cohort: TBD
- GRR: TBD%
- NRR: TBD%

**Stability analysis:** TBD

---

## Formula Definition (Production)

```python
# 1. Define cohort
cohort = deals.filter(
    pipeline == "renewal",
    close_date.in_period(X)
)

# 2. Calculate GRR
denominator = SUM(cohort.renewal_revenue)  # All deals up for renewal
won_deals = cohort.filter(status == "won")
numerator = SUM(won_deals.renewal_revenue) - SUM(won_deals.contraction_revenue)
GRR = numerator / denominator

# 3. Calculate NRR (optional)
expansion = SUM(won_deals.expansion_revenue)  # From renewal deals only
NRR = (numerator + expansion) / denominator
```

**Key inputs:**
- renewal_revenue: Well-populated, reliable (Q2+ 2026)
- contraction_revenue: Sparsely populated but proven correct when present
- expansion_revenue: Well-populated

**No dependency on:**
- prior_arr (manual, unreliable)
- gb_arr (manual, inconsistent)

---

## What's Preserved from Earlier Work

**Contraction handling proof (remains valid):**
- With/without comparison: Exact match ($-2,000)
- Formula correctly isolates contraction term
- No compensating errors
- Ready to use when contraction data present

**Process improvement finding:**
- prior_arr/renewal_revenue started being populated consistently in Q2 2026
- Now documented as data maturity constraint

**Honest labeling:**
- GRR requires renewal_revenue to be populated for cohort
- If pre-Q2 2026 periods requested: Surface data quality warning
- Same pattern as "field only recently started being tracked" finding

---

## Production Readiness Checklist

- [x] Formula validated on Q2 2026
- [x] Contraction handling proven correct
- [x] No dependency on manual fields (prior_arr/gb_arr)
- [ ] Check 1: Other stage deals status (manual inspection needed)
- [ ] Check 2: Expansion scope decision (document as design choice)
- [ ] Check 3: Multi-period sanity check (Q1, Q3 comparison)

**Sign-off required:** Complete checks 1-3 before marking production-ready.

---

## Next Steps

1. **Complete validation checks** (above)
2. **Document in registry:** GRR/NRR metric definitions with cohort formula
3. **Add to Phase 2d:** Conversational agent should be able to compute GRR for any period where renewal_revenue is populated
4. **Data maturity check:** Agent should warn if pre-Q2 2026 periods have sparse renewal_revenue
5. **Preserve contraction proof:** Keep with/without comparison technique for future metric validation

---

## Lessons for Phase 2d

**Conversational flow needs to discover:**
1. "This field only recently started being reliably populated" (same as prior_arr finding)
2. Suggest alternative formulations if manual fields unreliable (cohort vs. per-deal)
3. Multi-period sanity check before declaring metric "validated" (not just single-period convergence)

**This session showed:**
- Single-period success ≠ general validity (implicit filtering, Signal 2, prior_arr all passed one test but failed broader validation)
- Data quality investigation > working around blindly (renewal_pipeline, Byborg contraction, prior_arr all had clean, dateable explanations)
- Honest labeling > silent workarounds (same pattern as Signal 3 threshold, diagnostic classifier)
