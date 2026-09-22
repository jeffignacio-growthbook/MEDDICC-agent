# MEDDICC Statistical Significance Analysis — September 21, 2026

## Executive Summary

**Decision:** MEDDICC overall score displayed as **INFORMATIONAL CONTEXT ONLY** — NOT weighted into risk classification.

**Rationale:** Statistical test shows pre-close discrimination (+0.5/70 points) is **NOT distinguishable from zero** (p=0.80). Direction could flip by chance on next data batch.

---

## Analysis Conducted

After implementing MEDDICC signal with 15% weighting, performed statistical significance test on pre-close-only discrimination as requested.

### Sample

- **Won deals (pre-close):** n=40, mean=27.10, SD=12.18
- **Lost deals (pre-close):** n=276, mean=26.59, SD=11.63
- **Raw discrimination:** +0.51 points on 70-point scale (0.73% of scale)

---

## Statistical Tests

### Two-Sample T-Test (Welch's)
- **t-statistic:** 0.2503
- **p-value:** 0.8034
- **Significance at α=0.05:** NO
- **Significance at α=0.10:** NO

### Confidence Intervals (Bootstrap, 10k iterations)
- **95% CI:** [-3.44, +4.45]
- **90% CI:** [-2.83, +3.86]
- **CI includes zero:** YES

**Interpretation:** We cannot determine if won deals score higher OR lower than lost deals. The direction is indeterminate.

### Mann-Whitney U Test (Non-Parametric)
- **U-statistic:** 5141.00
- **p-value:** 0.4823
- **Significance at α=0.05:** NO
- **Significance at α=0.10:** NO

**Interpretation:** Non-parametric test confirms the same finding (not sensitive to non-normality).

### Effect Size
- **Cohen's d:** 0.0438
- **Interpretation:** Negligible (< 0.2)

Even if a true difference existed, it would be practically meaningless.

---

## Practical Implications

1. **Sample size imbalance:** 1:6.9 (won:lost) reduces power to detect small effects
2. **Raw difference:** 0.51/70 = 0.73% of scale
3. **p-value of 0.80** means the observed difference is VERY likely due to chance alone
4. **Direction uncertainty:** 95% CI spans from -3.44 to +4.45, meaning:
   - True difference could be -3.44 (won scores LOWER than lost)
   - True difference could be +4.45 (won scores HIGHER than lost)
   - Most likely: difference is near zero

---

## Decision Rationale

### Original Plan (Before Statistical Test)
- MEDDICC weighted at 15% (low end)
- Combined with cycle-length (85%)
- Justified by "+0.5 discrimination, though weak"

### After Statistical Test
- **p=0.80 is VERY high** - not even marginally significant
- **CI includes zero** - can't determine direction
- **Cohen's d negligible** - effect is meaningless even if real

### Conclusion
Carrying a noise signal at ANY real weight (even 3-5%) risks nudging borderline deals' risk labels based on nothing. The +0.5 discrimination observed could easily reverse to -0.5 on the next 40 won deals collected.

---

## Final Implementation

### What Changed
1. **_classify_risk()**: Reverted to cycle-length-only logic (removed MEDDICC weighting)
2. **assess_deal_risk()**: MEDDICC still fetched and displayed, but with explicit caveat
3. **Output text:** "shown for context only; not yet strong enough signal to weight into risk classification - p=0.80"

### Why This Is The Right Call
- **Same standard as other primitives:** forecast-trustworthiness, pipeline-coverage both gate on real evidence floors
- **Transparency preserved:** MEDDICC score still shown to user (already fetched, already displayed)
- **No fabricated signal:** Risk bucket NOT moved by noise

### What Users See
**Before:**
```
Risk: moderate_risk (influenced by both cycle-length AND low MEDDICC score)
```

**After:**
```
Risk: moderate_risk (cycle-length only)
MEDDICC: 25/70 overall score (fresh, 3 days old) [shown for context only;
not yet strong enough signal to weight into risk classification - p=0.80]
```

---

## When Could MEDDICC Be Weighted?

**Evidence floor to clear:**
1. **Larger sample size:** n=100+ won deals (vs current n=40 pre-close)
2. **Statistically significant discrimination:** p < 0.05 (vs current p=0.80 pre-close)
3. **Meaningful effect size:** Cohen's d > 0.2 (vs current d=0.04 pre-close)
4. **Stable direction:** Consistent across multiple data collection periods

**Current status:** 0 of 4 criteria met for pre-close analyses (the only predictive population).

**Note:** Mixed-set (pre-close + post-close combined) DOES meet criteria 2-3 (p=0.02, d=0.35), but post-close analyses are non-predictive for in-progress deals, so mixed-set significance is not actionable.

---

## Mixed-Set Analysis: Was The Original +4.0 Discrimination Real?

**Question:** If the isolated pre-close number (+0.51) is pure noise, was the inflated mixed-set number (+4.04) real signal contaminated by post-close analyses, or also noise?

**Answer:** The mixed-set discrimination WAS statistically significant.

### Mixed-Set Results (All 67 Won vs All 495 Lost)

**Statistical Tests:**
- **Raw discrimination:** +4.04 points (5.8% of scale)
- **p-value:** 0.0196 (t-test) ✅ **Significant at α=0.05**
- **95% CI:** [+0.72, +7.30] — Does NOT include zero
- **Cohen's d:** 0.3531 — Small but real effect

### Comparison: Mixed vs Pre-Close-Only

| Metric | Mixed Set | Pre-Close Only | Ratio |
|--------|-----------|----------------|-------|
| Won sample | n=67 | n=40 | 1.7x |
| Lost sample | n=495 | n=276 | 1.8x |
| Discrimination | +4.04 | +0.51 | **8x** |
| p-value | 0.0196 ✅ | 0.8034 ❌ | 41x more significant |
| Cohen's d | 0.3531 | 0.0438 | 8x |

### Interpretation

**The mixed-set signal was REAL, not noise.**

This means: **"Signal diluted by contamination"** NOT **"No signal ever existed"**

- ✅ MEDDICC scoring CAN produce discriminative signal (mixed-set proves this)
- ❌ Pre-close filtering revealed the +4.04 signal was inflated by post-close analyses
- ❌ Pre-close-only signal (+0.51, p=0.80) collapses to statistical noise after filtering
- ❌ For in-progress deals (pre-close only), MEDDICC has no predictive value

### Why The 8x Gap?

**Possible explanations for why mixed-set works but pre-close doesn't:**

1. **Retrospective knowledge:** Post-close analyses have outcome information, leading to more complete/accurate scoring
2. **Scoring bias:** Analysts may score more generously when outcome is known (confirmation bias)
3. **Deal maturity:** Pre-close analyses often captured earlier in cycle when MEDDICC components genuinely less developed
4. **Sample size:** Pre-close n=40 may be underpowered to detect a real but weak effect that exists

### Implication for Future

**MEDDICC isn't fundamentally broken** (mixed-set works), BUT:

- Pre-close signal too weak for current use (p=0.80)
- **More volume MIGHT help** — with n=100+ pre-close won deals, a weak but real signal could become detectable
- However, the 8x gap (4.04 → 0.51) suggests something qualitatively different about pre-close vs post-close, not just sample size

**Threshold to revisit:** When pre-close won-deal sample reaches n=100+, re-run this analysis to see if discrimination becomes significant.

---

## Comparison to Original Deferral (2026-09-16)

| Metric | Sept 16 (Original) | Sept 21 (Post-Backfill) | Cleared Threshold? |
|--------|-------------------|------------------------|-------------------|
| Won deal coverage | 4/327 (1.2%) | 67/229 (29.3%) | ✅ Yes (≥30) |
| Pre-close sample | Not calculated | 40 won, 276 lost | ✅ Yes (≥30) |
| Discrimination | Reverse (-) | +0.5 points | Direction flipped |
| Statistical significance | N/A (n=4) | p=0.80 (NOT significant) | ❌ No |
| Decision | Defer entirely | Display as context only | Both correct |

**Key insight:** Coverage threshold met, but **statistical significance threshold NOT met**. Both decisions (2026-09-16 deferral, 2026-09-21 context-only) follow the same principle: don't ship a signal past its evidence floor.

---

## Verification

- **Tests updated:** 9 tests pass, confirming cycle-length-only classification
- **Planted discrepancy test:** Still passes (pre-close filter working)
- **New test:** `test_assess_deal_risk_with_meddicc_context_only` verifies MEDDICC shown but NOT weighted

---

## Documentation

- **NORTH_STAR.md:** Updated CRO Priority #3 + Decision Log with statistical analysis
- **Code comments:** Updated to reflect context-only status (p=0.80 cited)
- **Test docstrings:** Explain why MEDDICC NOT weighted

---

## Appendix: Full Statistical Output

```
======================================================================
STATISTICAL SIGNIFICANCE TEST: Pre-Close MEDDICC Discrimination
======================================================================

Sample sizes:
  Won (pre-close):  n=40
  Lost (pre-close): n=276

Descriptive statistics:
  Won:  mean=27.10, median=25.00, SD=12.18
  Lost: mean=26.59, median=28.00, SD=11.63

Raw discrimination: +0.51 points on 70-point scale

======================================================================
TWO-SAMPLE T-TEST (Welch's)
======================================================================
  t-statistic: 0.2503
  p-value: 0.8034
  Significance at α=0.05: NO
  Significance at α=0.10: NO

======================================================================
CONFIDENCE INTERVALS (Bootstrap, 10k iterations)
======================================================================
  95% CI: [-3.44, +4.45]
  90% CI: [-2.83, +3.86]

  CI includes zero: YES

======================================================================
MANN-WHITNEY U TEST (non-parametric)
======================================================================
  U-statistic: 5141.00
  p-value: 0.4823
  Significance at α=0.05: NO
  Significance at α=0.10: NO

======================================================================
EFFECT SIZE
======================================================================
  Cohen's d: 0.0438
  Interpretation: Negligible (< 0.2)

======================================================================
INTERPRETATION
======================================================================
❌ NOT STATISTICALLY SIGNIFICANT
   The +0.51 point discrimination could easily be due to chance.
   With p=0.8034, the direction could flip on next data batch.
   RECOMMENDATION: Drop from weighted classification entirely.
   Display MEDDICC score as informational context only.
```
