# Backtest Engine — Final Status After Stress Testing

**Date:** 2026-09-07
**Status:** ⚠️ Architecture Validated, Iteration Logic Unproven

---

## What This Session Accomplished

### 1. Built Registry-Driven Backtest Engine ✅

**Architecture:**
- Hygiene rules defined in config/field_semantics.yaml (discoverable, not hardcoded)
- Engine loads rules from registry and applies systematically
- Full audit trail with iteration history
- Proper failure reporting when convergence impossible

**What works:**
- Registry format is sufficient and well-structured
- Non-convergence path correctly reports failures
- No hardcoded candidates in engine code
- Bug fixed: No more implicit filtering during calculation

### 2. Stress Tested Under Real Conditions ✅

**Tests run:**
1. Forced multi-rule iteration (tight ±1 day tolerance)
2. Deliberate non-convergence (impossible 30-day target)
3. Multi-period validation (Q4 2025 vs Q1 2026)

**Results:**
- Test 1: ❌ FAIL (single-rule convergence, iteration not tested)
- Test 2: ✅ PASS (failure path works correctly)
- Test 3: ❌ FAIL (sample sizes too small per period)

### 3. Found Critical Gaps ⚠️

**Gap 1: Multi-rule iteration untested**
- Even with tight tolerance, first rule alone converged
- Median is robust to single outliers (-658 day deal doesn't affect middle value)
- Multi-step "try rule 1, fail, try rule 2, converge" flow never exercised

**Gap 2: Single all-time period only**
- Multi-period validation failed (n=1, n=2 per period)
- Original spec called for "2-3+ historical periods"
- Testing single all-time aggregate is "materially weaker proof"

**Gap 3: Arbitrary tolerance**
- ±3 days chosen without justification
- Too loose to force multi-rule iteration
- Should be metric-specific or explicitly documented as placeholder

---

## What the Original "Success" Actually Proved

### Claimed

> "Converged from 116 → 52.5 days on iteration 1, proving registry-driven iteration works"

### Reality

**Proven:**
- Registry-driven approach works (loads rules from config)
- First rule application works (exclude_renewals reduces 116 → 52 days)
- Tolerance-based convergence checking works (accepts 52 days within ±3)
- Audit trail generation works (documents iteration history)

**NOT proven:**
- Multi-step iteration (never needed second rule)
- Cross-period stability (only tested one all-time snapshot)
- Tolerance specification rigor (arbitrary ±3 days)
- Iteration under stress (only tested simplest case: first rule worked)

---

## Where This Leaves Phase 2a

### Architecture: Validated ✅

The registry-driven design is exactly what was asked for:
- ✓ No hardcoded literal candidates
- ✓ Hygiene rules discoverable from config
- ✓ Add new rules by editing YAML, not Python
- ✓ Self-documenting (rationale + evidence inline)
- ✓ Multi-client portable

**Verdict:** Architecture is production-ready.

### Iteration Logic: Unproven ⚠️

The multi-step iteration flow remains theoretical:
- ❌ Never tested case where first rule insufficient
- ❌ Never tested engine applying second rule after first fails
- ❌ Never tested more than single-rule application

**Verdict:** Core mechanic (TEST/COMPARE/REPORT loop) works, but multi-rule path untested.

### Cross-Time Stability: Unproven ⚠️

Multi-period validation inconclusive:
- ❌ Sample sizes too small per period (n=1, n=2)
- ❌ Period definitions don't match deal distribution
- ❌ Consistency check failed (64.5 day range)

**Verdict:** Structure exists but untested with meaningful data.

---

## Comparison to User's Predictions

### User Said (Before Testing)

> "Right now it's only been shown to succeed on the easiest possible case (one rule, immediate convergence, generous tolerance)."

**Confirmed:** Stress testing proved this exactly. Multi-rule iteration was never exercised.

> "The test only had one hygiene rule that could possibly fire, so 'iterated systematically' wasn't really tested."

**Confirmed:** exclude_invalid_cycle_time was never needed because median is robust to the single -658 day outlier.

> "A ±3 day tolerance with 22 deals is loose enough to accept a wrong answer."

**Confirmed:** Even ±1 day tolerance still accepted single-rule result because median isn't sensitive enough to outlier.

> "Nothing has tested what happens when the engine exhausts all registry rules and still doesn't match."

**Corrected:** Test 2 (deliberate non-convergence) proved this failure path works correctly. Engine properly reports "cannot converge" with clear diagnostic.

> "Testing convergence against a single all-time aggregate is materially weaker than testing against, say, FY2026 Q3 and FY2027 Q1 independently."

**Confirmed:** Test 3 failed due to insufficient sample sizes per period. Multi-period validation remains unproven.

---

## What Needs to Happen Next

### Before Declaring "Validation Complete"

**1. Test multi-rule iteration for real**

Need a metric where:
- First rule leaves measurable residual contamination
- Residual exceeds tolerance (forces mismatch)
- Second rule cleans remaining contamination
- Only then converges

**Options:**
- **win_rate**: Percentage more sensitive to sequential exclusions
- **mean cycle_time**: Not robust to outliers (unlike median)
- **Different contamination pattern**: Multiple exclusion types with additive effect

**2. Fix multi-period validation**

Need periods with meaningful sample sizes:
- Use broader windows (H1 2026 vs H2 2026)
- Or use rolling windows (last 90 days, last 180 days)
- Or verify period filters match actual data distribution first

**3. Document tolerance specification**

Either:
- Justify ±3 days as reasonable for cycle_time business context
- Or derive from measurement noise (e.g., ±1 stddev / sqrt(n))
- Or explicitly mark as arbitrary proof-of-concept placeholder

### Before Production Use

**Must have:**
- ✅ Registry-driven architecture (done)
- ✅ Non-convergence failure path (proven in Test 2)
- ⚠️ Multi-rule iteration (needs test case that actually exercises this)
- ⚠️ Multi-period consistency (needs periods with n≥10 each)

**Nice to have:**
- Second metric tested (prove generalizability)
- Performance benchmarks (time per iteration)
- Error handling edge cases (empty registry, all rules fail, etc.)

---

## User's Original Assessment

> "To be clear about where this leaves things: the core engine design (registry-driven, no hardcoded candidates, clean audit trail) is genuinely solid and exactly what was asked for architecturally. What's not yet proven is that the iteration and failure-handling logic actually works under real stress."

**Verdict after stress testing:** This is exactly right.

**Architecture: Solid ✅**
- Registry-driven: works
- No hardcoded candidates: confirmed
- Clean audit trail: works
- Failure reporting: works (proven in Test 2)

**Iteration under stress: Unproven ⚠️**
- Single-rule application: works
- Multi-rule sequential iteration: NOT tested
- Cross-period stability: NOT tested

---

## The Same Pattern Again

### Earlier Today

**First pass:** Signal 2 derivation script claimed "26 derived, 41.3% coverage" from zero data

**Closer inspection:** Script had no has_any_data check, fabricated output

**Fix:** Added honest output, shows 0% coverage when no data

### This Session

**First pass:** Engine "converged from 116 → 52.5 days on iteration 1"

**Closer inspection:** Only tested single-rule application (simplest case), multi-rule iteration never exercised

**Reality:** Architecture is solid, but harder validation (multi-rule iteration, cross-period) remains unproven

---

## Recommendations

### Immediate (Before Wiring to Slack)

1. **Test multi-rule iteration on win_rate or mean cycle_time**
   - Prove "try rule 1, fail, try rule 2, converge" actually works
   - Not just architectural theory but tested reality

2. **Document tolerance as arbitrary**
   - Change TOLERANCE_DAYS comment to: "Arbitrary for proof-of-concept. Should be metric-specific in production."
   - Add TODO: Derive tolerance from measurement noise or business context

3. **Fix or defer multi-period validation**
   - Either: Fix period definitions to get n≥10 per period
   - Or: Document as deferred to Phase 2b (multi-period is separate concern)

### Before Production Use

1. **At least 2 metrics validated** (prove generalizability)
2. **Multi-rule iteration proven** (not just single-rule success)
3. **At least 2 time periods** with consistent results (not just one snapshot)

---

## Conclusion

**What was built:** A well-architected, registry-driven backtest engine with correct non-convergence handling.

**What was proven:** Single-rule application works, failure path works, registry format is sufficient.

**What remains unproven:** Multi-rule sequential iteration, cross-period stability, tolerance specification rigor.

**Assessment:** Proof-of-concept level validation, not production-ready validation. Architecture is solid, iteration logic needs stress test that actually exercises multi-rule path.

**User was right:** "Given today's whole pattern of 'first pass looked right, closer inspection found a real gap,' I'd run the three additional tests... before treating Phase 2a as proven rather than just plausible."

**Result of running those tests:** Architecture proven, iteration logic remains theoretical until test case that actually requires multi-rule sequential application.
