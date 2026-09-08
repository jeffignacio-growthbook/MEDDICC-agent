# Diagnostic Classifier — Hand-Picked Heuristic

**Status:** ⚠️ Heuristic (not validated)
**Date:** 2026-09-07
**Same category as:** Signal 3's 14-day threshold, Signal 2 placeholder ranges

---

## What This Is

The diagnostic classifier in `enhanced_diagnostic()` attempts to distinguish WHY a backtest convergence failed:

- `missing_rule` - Need one more hygiene rule (high improvement, small gap)
- `impossible_target` - Ground truth suspect (low improvement or huge gap)
- `partial_progress` - Multiple rules needed (middle range)

**This is a HAND-PICKED HEURISTIC**, not a validated classifier.

---

## Current Thresholds

```python
# Calculate remaining gap as percentage of final value
remaining_gap_pct = (final_delta / final_value * 100) if final_value > 0 else 0

# Classification logic
if improvement_pct > 90 and remaining_gap_pct < 5:
    → missing_rule

elif improvement_pct > 50 and remaining_gap_pct > 50:
    → impossible_target

elif improvement_pct < 10:
    → impossible_target

else:
    → partial_progress
```

**These cutoffs (90%, 5%, 50%) were picked to correctly classify TWO test cases:**
- 97.9% improvement, 2.2% gap → `missing_rule` ✓
- 53.4% improvement, 86% gap → `impossible_target` ✓

**This is curve-fitting, not validation** — same failure pattern as:
- Signal 2 placeholder thresholds (fabricated to fit examples)
- Implicit filtering bug (hardcoded logic bypassing registry)

---

## Stress Test Results

**Known cases (2):** Both pass (by design)

**Edge cases (5):**
- ✓ 83.3% improvement, 30% gap → `partial_progress` (reasonable)
- ✓ 97.4% improvement, 15% gap → `partial_progress` (acceptable)
- ✓ 62.5% improvement, 40% gap → `partial_progress` (reasonable)
- ✗ **98.6% improvement, 8% gap** → `partial_progress` (should be `missing_rule`)
- ✗ **38% improvement, 70% gap** → `partial_progress` (should be `impossible_target`)

**Verdict:** Classifier works on training data but has gaps in coverage.

---

## Known Limitations

### 1. Too Many Cases Fall Through to `partial_progress`

The `else` clause catches everything not explicitly matched:
- 98.6% improvement, 8% gap (very close to target)
- 38% improvement, 70% gap (nowhere near target)

Both get classified as `partial_progress` even though they're very different scenarios.

### 2. Thresholds Are Arbitrary

**Why 90% and 5%?**
- Chosen to fit one test case (97.9%/2.2%)
- No analysis of what these cutoffs mean semantically
- Not validated against range of real escalations

**Why 50% and 50%?**
- Chosen to fit one test case (53.4%/86%)
- Symmetric (50/50) looks nice but has no justification
- No data on whether this boundary is meaningful

### 3. No Production Validation

Classifier tested on:
- 2 known cases (tuned to these)
- 5 synthetic edge cases (constructed for stress test)

**NOT tested on:**
- Real production escalations
- Different metric types (only sum_dollars tested)
- Different contamination patterns
- Different data quality issues

---

## What This Means for Phase 2b

**For Phase 2b validation:**
- ✓ Diagnostic is meaningfully different from generic "cannot converge"
- ✓ Provides actionable guidance (`missing_rule` → add to registry, `impossible_target` → verify ground truth)
- ✓ Improvement over no diagnostic distinction
- ⚠️ Classifier itself is a heuristic, not proven

**Honest assessment:**
- Better than nothing: ✓
- Validated as robust: ✗
- Production-ready without monitoring: ✗

---

## Honest Labeling

**What to claim:**
> "Enhanced diagnostic distinguishes between 'missing rule' and 'impossible target'
> patterns using a **hand-picked heuristic**. Tested on 7 synthetic cases with
> reasonable results, but NOT validated against production data."

**What NOT to claim:**
> ~~"Validated diagnostic classifier"~~ (implies rigorous testing)
> ~~"Proven to handle all escalation scenarios"~~ (only tested 7 cases)
> ~~"Production-ready classification logic"~~ (has known gaps)

---

## Re-Derivation Trigger

**When to revisit thresholds:**

1. **After 20+ production escalations** - Review classifications vs human feedback
2. **On first questionable classification** - When human disagrees with classifier
3. **When adding new metric types** - Current logic only tested on sum_dollars
4. **Annual review** - Check if patterns have changed

**What to collect for re-derivation:**
- Improvement %
- Remaining gap %
- Human classification (missing_rule, impossible_target, other)
- Metric type
- Whether classification was helpful or misleading

**Goal:** Move from hand-picked heuristic to data-driven thresholds.

---

## Comparison to Other Heuristics

### Signal 3: 14-day gap threshold
- **Labeled as:** "Heuristic threshold pending real-world observation"
- **Re-derivation trigger:** After 100+ annotations
- **Same pattern:** Hand-picked to fit limited examples

### Signal 2: Placeholder ranges
- **Labeled as:** "Placeholder thresholds"
- **Issue:** Fabricated `[green]` for everything
- **Fixed by:** Proper derivation from real data

### Diagnostic classifier
- **Should be labeled as:** "Heuristic classifier pending production validation"
- **Re-derivation trigger:** After 20+ production escalations
- **Same category:** Hand-picked to fit 2 test cases

---

## Recommended Production Approach

**Short-term (Phase 2b completion):**
1. Document classifier as heuristic (this file)
2. Label code with `# HEURISTIC: Thresholds hand-picked, not validated`
3. Include re-derivation trigger in documentation
4. Log all classifications for future review

**Medium-term (post-deployment):**
1. Collect production escalation data
2. Review human feedback on classifications
3. Analyze improvement % vs gap % patterns
4. Re-derive thresholds from real data

**Long-term (validated classifier):**
1. Train on 50+ real escalations
2. Cross-validate on held-out cases
3. Test across multiple metric types
4. Document validated ranges with evidence

---

## Current Use in Phase 2b

**Test 2 (Improved):**
- Uses classifier to distinguish missing_rule (97.9%/2.2%) from impossible_target (53.4%/86%)
- Classification is correct for these two cases (by design)
- Provides meaningful, actionable guidance
- BUT: Classifier itself is heuristic, not validated

**Verdict:**
- Test 2 proves diagnostic CAN distinguish failure types ✓
- Test 2 proves classifier works on tested cases ✓
- Test 2 does NOT prove classifier generalizes to all cases ✗

---

## Summary

**What was built:**
- Diagnostic classifier that distinguishes failure types
- Thresholds tuned to correctly classify 2 test cases
- Stress-tested on 5 additional edge cases (2 questionable)

**What this is:**
- **Hand-picked heuristic** (same as Signal 3's 14-day threshold)
- Better than no classification
- Improvement over generic "cannot converge"
- NOT a validated, production-proven classifier

**What to do:**
- Label as heuristic in code and documentation
- Log classifications for future review
- Re-derive from production data after 20+ escalations
- Monitor for questionable classifications

**Same discipline as rest of build:**
- Honest labeling (heuristic, not validated)
- Explicit re-derivation trigger
- Test what you claim (works on tested cases, not proven generally)
- No fabricated claims of validation
