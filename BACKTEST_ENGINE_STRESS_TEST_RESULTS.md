# Backtest Engine Stress Test Results

**Date:** 2026-09-07
**Status:** ⚠️ Validation Incomplete (1/3 tests passed)

---

## Executive Summary

Stress testing revealed **critical gaps** in the original validation:

1. **❌ Multi-rule iteration NOT tested** - Even with tight tolerance (±1 day), first rule alone converged. Engine's multi-step iteration logic remains unproven.

2. **✅ Non-convergence path works** - Engine correctly exhausted all rules and reported "cannot converge" with clear diagnostic. Failure path validated.

3. **❌ Multi-period validation failed** - Sample sizes too small per period (n=1, n=2), results inconsistent. Period-based testing needs better approach.

**Key finding:** The original "successful" test only proved single-rule application works. The harder problems (multi-rule iteration, cross-period stability) remain unvalidated.

---

## Bug Fixed Before Testing

**Critical bug found in execute_candidate_query:**

```python
# ORIGINAL (WRONG):
if cycle_days >= 0:  # Implicit filtering!
    cycle_times.append(cycle_days)

# FIXED:
cycle_times.append(cycle_days)  # Include ALL cycle times unless explicit rule applied
```

**Impact:** Original code silently filtered negative cycle times even when `exclude_invalid_cycle_time` was NOT in applied_rules. This caused false convergence - engine appeared to succeed with one rule because the second rule was being applied implicitly during calculation.

**Evidence:** Netthandelsgruppen deal (-658 days) was in the "renewals excluded" population but didn't affect median because negative values were being filtered during calculation, not just during explicit rule application.

---

## Test 1: Forced Multi-Rule Iteration

### Goal
Prove multi-step iteration works by using tight tolerance (±1 day) to force engine to apply BOTH hygiene rules before convergence.

### Result: ❌ FAIL

**Iteration 0 (Naive):**
- Result: 95 days (n=121)
- Delta: 43 days
- Status: ✗ MISMATCH

**Iteration 1 (exclude_renewals only):**
- Result: 52 days (n=23)
- Delta: 0 days (exactly at ground truth!)
- Status: ✓ CONVERGED

### Why This Failed

Even with ±1 day tolerance (very tight), `exclude_renewals` alone achieved exact convergence (52 days). The -658 day Netthandelsgruppen outlier is present in the n=23 population but doesn't affect the median.

**Median is robust to outliers:** With 23 deals sorted by cycle time, the median is the 12th value. One extreme outlier at position 1 doesn't change the middle value.

**Implication:** Multi-rule iteration logic was NOT tested. Only single-rule application was proven.

### What This Means

**Original claim:** "Engine converged from 116 → 52.5 days on iteration 1, proving registry-driven iteration works"

**Reality:** Engine converged with first rule tried because:
1. Median is robust to single outliers
2. The outlier happens to be extreme enough to sit far left without affecting middle
3. ±3 day (and even ±1 day) tolerance accepts this

**Not proven:** What happens when first rule leaves meaningful contamination that second rule must clean up. The multi-step "try rule 1, still mismatched, try rule 2, converge" logic remains untested.

### How to Actually Test Multi-Rule Iteration

Need a test case where:
1. First rule reduces contamination but leaves measurable residual
2. Residual exceeds tolerance (forces mismatch)
3. Second rule cleans remaining contamination
4. Only then does engine converge

**Possible approaches:**
- Use mean instead of median (sensitive to outliers)
- Use different metric (win_rate) where exclusions have additive effect
- Use sum/count metrics where each exclusion materially changes result
- Artificially inject multiple contaminants that require sequential cleaning

---

## Test 2: Deliberate Non-Convergence

### Goal
Feed impossible ground truth (30 days when actual is ~52 days), exhaust all hygiene rules, confirm engine reports "cannot converge" correctly.

### Result: ✅ PASS

**All rule combinations tried:**
- Naive: 95 days (Δ = 65 days)
- exclude_renewals: 52 days (Δ = 22 days)
- exclude_invalid_cycle_time: 116 days (Δ = 86 days)
- Both rules: 52.5 days (Δ = 22.5 days)

**Closest result:** 52 days with exclude_renewals alone, still 22 days away from impossible target.

**Engine correctly:**
1. ✓ Tried all registered hygiene rules
2. ✓ Did NOT false-converge on any result
3. ✓ Reported "cannot converge" after exhausting rules
4. ✓ Provided clear diagnostic (closest result, delta, rules tried)

### Why This Passed

The failure path works correctly. Engine doesn't:
- Silently accept a close-but-wrong answer
- Infinite-loop trying to find impossible convergence
- Crash when no convergence achieved
- Report success when actually failed

**Validation confidence:** ✅ High

The "or correctly report that it cannot converge and why" requirement from original spec is proven.

---

## Test 3: Multi-Period Validation

### Goal
Test against FY2026 Q4 and FY2027 Q1 separately, confirm same hygiene rules produce consistent results across time windows.

### Result: ❌ FAIL

**FY2026 Q4 (Nov 2025 - Jan 2026):**
- Result: 0 days (n=1)
- ⚠️ Sample size too small

**FY2027 Q1 (Feb 2026 - Apr 2026):**
- Result: 64.5 days (n=2)
- ⚠️ Sample size too small

**Cross-period consistency:**
- Median range: 0 - 64.5 days (span: 64.5 days)
- Mean: 32.2 days
- Consistency check: FAILED (range 64.5 > 6.5 day tolerance)

### Why This Failed

**Insufficient data per period:** With n=1 and n=2 deals per period, results are meaningless:
- n=1: Median is a single data point (not representative)
- n=2: Median is average of two points (high variance)
- Neither can validate metric stability across time

**Possible causes:**
1. Period definitions don't match deal close dates in database
2. Most deals closed outside these specific quarters
3. Fiscal year assumptions incorrect (actual FY starts different month)
4. Test needs all-time data split differently (e.g., first half vs second half of 2026)

### What This Means

**Original claim:** "Structure supports multiple periods" (from BACKTEST_ENGINE_IMPLEMENTATION.md)

**Reality:** Structure exists but untested. Multi-period validation requires:
1. Period definitions that actually contain meaningful sample sizes (n≥10 per period)
2. Ground truth values per period (not just all-time aggregate)
3. Consistency checks that account for natural variance (business cycle, seasonality)

**Not proven:** Whether the same hygiene rules produce stable results across time. A single all-time convergence is indeed "materially weaker proof than the spec called for."

---

## Summary of Findings

### What Was Proven

✅ **Non-convergence path works**
- Engine correctly reports failure when impossible ground truth given
- No false convergence, no infinite loops, no crashes
- Clear diagnostic reporting (closest result, delta, rules tried)

✅ **Registry-driven design works**
- Engine loads hygiene rules from config/field_semantics.yaml
- Rules are discoverable and systematically applied
- No hardcoded candidates in engine code

✅ **Bug fixed**
- Implicit filtering during calculation removed
- Now only applies hygiene rules when explicitly in applied_rules list
- TEST/COMPARE logic no longer masks failures

### What Was NOT Proven

❌ **Multi-rule iteration**
- Only tested single-rule application (first rule worked)
- Never tested "try rule 1, still mismatched, try rule 2, converge" flow
- Iteration loop logic remains unvalidated

❌ **Multi-period stability**
- Sample sizes too small per period (n=1, n=2)
- Period definitions don't match actual deal distribution
- Cross-time consistency check inconclusive

❌ **Tolerance justification**
- ±3 day tolerance arbitrary (not derived or justified)
- Too loose to force multi-rule iteration
- Even ±1 day tolerance still too loose for this metric + outlier combination

---

## Comparison to Original Spec

**Original requirement:** "Iteratively refine a candidate query until it matches all periods within tolerance - or correctly report that it cannot converge and why."

**Met:**
- ✓ Registry-driven iteration structure
- ✓ Convergence checking with tolerance
- ✓ "Cannot converge" failure reporting

**Not met:**
- ❌ Multi-rule iteration (only single-rule tested)
- ❌ "All periods" validation (only tested single all-time aggregate)
- ❌ Tolerance specification (arbitrary, not justified)

---

## Recommendations

### Before Declaring Phase 2a Complete

**1. Test multi-rule iteration with metric sensitive to sequential cleanup**

Options:
- Use **win_rate** instead of cycle_time (percentage more sensitive to exclusions)
- Use **mean** instead of median (not robust to outliers)
- Artificially inject multiple contaminant types requiring sequential cleanup

**2. Fix multi-period validation**

Options:
- Use broader periods (H1 2026 vs H2 2026 instead of single quarters)
- Use rolling windows (last 3 months, last 6 months, last 12 months)
- Verify period filters match actual deal close_date distribution first

**3. Justify or derive tolerance**

Options:
- Document ±3 days as arbitrary proof-of-concept placeholder
- Compute tolerance from measurement noise (e.g., ±1 stddev / sqrt(n))
- Make tolerance metric-specific (cycle_time: ±3 days, win_rate: ±0.5%)

### Before Production Use

**Must have:**
- Multi-rule iteration proven on at least one real test case
- At least 2 separate time periods with n≥10 each, consistent results
- Documented tolerance specification (derived or explicitly arbitrary)

**Nice to have:**
- Second metric tested (prove generalizability beyond cycle_time)
- Failure modes documented (what happens when registry empty, all rules fail, etc.)
- Performance benchmarks (time per iteration, max iterations before timeout)

---

## Conclusion

The backtest engine's **architecture is sound** (registry-driven, no hardcoded candidates, clean audit trail), but its **iteration and cross-time stability remain unproven**.

**Current validation status:** Proof-of-concept level, not production-ready.

**Why this matters:** Same pattern as earlier today - "first pass looked right, closer inspection found real gap." The original convergence (116 → 52.5 days on iteration 1) was **real but insufficient evidence** for the claims made.

**To truly validate Phase 2a:** Need tests that actually stress the multi-rule iteration logic and cross-period consistency, not just the happy path where first rule works.

**Original spec requirement unmet:** "Test against 2-3+ historical periods" was explicitly called for, and testing a single all-time aggregate is indeed "materially weaker proof."
