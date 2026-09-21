# MEDDICC Coverage Re-Audit — September 21, 2026

## Context

Original deferral decision (2026-09-16):
- Only 4/327 closed-won deals had MEDDICC scores (1.2% coverage)
- Those 4 showed **reverse correlation**: Champion & EB scores were LOWER on won deals than at-risk deals
- Decision: Defer MEDDICC component in `assess_deal_risk()` until min_evidence_count=30 bar cleared
- Concern: Were analyses pre-close (predictive) or post-close artifacts (retrospective)?

Post-backfill (2026-09-21): 457 deals backfilled, re-audit requested to determine if deferral should be reconsidered.

---

## 1. Coverage Results

### Closed-Won Deals
- **Total in database:** 229 deals
- **With MEDDICC scores:** 67 deals
- **Coverage:** 29.3%

### Closed-Lost Deals
- **Total in database:** 826 deals
- **With MEDDICC scores:** 495 deals
- **Coverage:** 59.9%

### Comparison
| Metric | Sept 16 (Original) | Sept 21 (Post-Backfill) | Status |
|--------|-------------------|------------------------|--------|
| Won deals with scores | 4/327 (1.2%) | 67/229 (29.3%) | ✅ **24x increase** |
| Minimum threshold | 30 deals | 30 deals | ✅ **MET** (67 >= 30) |

**Conclusion:** Coverage threshold cleared. Sample size sufficient for discrimination testing.

---

## 2. Discrimination Check: Won vs Lost Deals

### Component Score Averages

| Component | Won Avg (n=67) | Lost Avg (n=495) | Discrimination | Status |
|-----------|---------------|-----------------|----------------|--------|
| **Overall** | **30.4** | **26.4** | **+4.0** | ✅ **Higher on Won** |
| Economic Buyer | 3.6 | 2.2 | +1.4 | ✅ Higher on Won |
| Decision Process | 5.0 | 3.8 | +1.2 | ✅ Higher on Won |
| Competition | 4.3 | 3.2 | +1.0 | ✅ Higher on Won |
| Decision Criteria | 5.1 | 4.7 | +0.4 | ✅ Higher on Won |
| Champion | 3.5 | 3.4 | +0.1 | ✅ Higher on Won (weak) |
| Metrics | 3.8 | 3.8 | -0.0 | ❌ Tied |
| Pain | 5.1 | 5.2 | -0.2 | ❌ **Reverse** (slight) |

### Score Distributions

**Won deals (n=67):**
- Range: 0-55/70
- Median: 27/70
- 25th-75th percentile: 21-44/70

**Lost deals (n=495):**
- Range: 0-54/70
- Median: 28/70
- 25th-75th percentile: 21-33/70

### Key Findings

1. **Overall discrimination is POSITIVE** (+4.0 points): Won deals score higher on average ✅
2. **Original reverse correlation has FLIPPED**:
   - Champion: Was reverse in 4-deal sample → now +0.1 (weak positive)
   - Economic Buyer: Was reverse in 4-deal sample → now +1.4 (moderate positive)
3. **Most components discriminate correctly**: 5 of 7 show positive discrimination
4. **Two components still problematic**:
   - Metrics: No discrimination (tied at 3.8)
   - Pain: Slight reverse correlation (-0.2)

**Conclusion:** The original reverse-correlation finding was a **small-sample artifact**. At larger scale (67 vs 495), MEDDICC scores show predictive signal in the expected direction.

---

## 3. Timing Analysis: Pre-Close vs Post-Close

### Results
- **Pre-close analyses:** 40/67 (59.7%)
- **Post-close analyses:** 27/67 (40.3%)

### Pre-Close Timing Distribution
- Range: 0 to 34 days before close
- **Median: 7 days before close**
- Examples:
  - Angel: 34 days before close
  - Airalo: 22-23 days before close

### Post-Close Timing Distribution
- Range: 0 to 1162 days after close
- **Median: 145 days after close**
- Examples:
  - Goodnotes: 0 days after (same day)
  - bet365: 201 days after (backfilled)
  - Salesforce: 224 days after (backfilled)

### Interpretation
- **60% pre-close**: Useful for predictive signal in `assess_deal_risk()`
- **40% post-close**: Mix of same-day analyses (0 days) and backfilled historical deals
  - Same-day analyses may still reflect deal state at close
  - Backfilled analyses (145+ days) are retrospective artifacts, not predictive

**Conclusion:** Majority (60%) are pre-close analyses, consistent with original finding. Timing concern partially addressed but not eliminated.

---

## 4. Recommendation: Un-Defer with Caveats

### Arguments FOR Un-Deferring

1. ✅ **Minimum evidence threshold met**: 67 won deals >= 30 minimum bar
2. ✅ **Positive overall discrimination**: +4.0 points (won > lost)
3. ✅ **Original reverse correlation was artifact**: Flipped at larger sample size
4. ✅ **Majority pre-close**: 60% analyzed before deal closure (predictive value)
5. ✅ **5 of 7 components discriminate correctly**: EB, DP, Competition, DC, Champion all positive

### Arguments AGAINST Un-Deferring (Caveats)

1. ⚠️ **Discrimination strength is moderate, not strong**: +4.0 points on 70-point scale (5.7% delta)
2. ⚠️ **Two components fail**: Metrics (tied) and Pain (reverse) show no/negative discrimination
3. ⚠️ **40% post-close analyses**: Some scores reflect "what happened" not "what will happen"
4. ⚠️ **Sample size still modest**: 67 won deals is above minimum but not robust for fine-grained modeling

### Honest Assessment

**The data NOW supports un-deferring the MEDDICC component, BUT:**

- MEDDICC should be **one signal among many** in `assess_deal_risk()`, not the primary signal
- Weight should be **moderate** given the +4.0 point discrimination (not dominant)
- Consider **overall score** rather than individual components (since Metrics and Pain fail)
- Acknowledge that **not all analyses are predictive** (40% post-close, some backfilled months later)
- Monitor discrimination stability as more data accumulates (current 67 won deals vs 495 lost is imbalanced 1:7.4)

### Proposed Implementation Approach

If un-deferring:
1. Use **overall MEDDICC score** (0-70 scale) as the signal, not individual components
2. Apply a **moderate weight** (e.g., 15-25% of total risk score, alongside pipeline progression, engagement velocity, stage duration)
3. **Filter out post-close analyses** for in-progress deals (only use pre-close analyses for prediction)
4. **Set a score threshold** for risk flagging (e.g., deals <25/70 = higher risk, >35/70 = lower risk)
5. **Document the limitation** that discrimination is moderate (+4 points) and may not be decisive for borderline deals

### Next Verification Step

Before implementing:
- Check discrimination on **open/in-progress deals** stratified by current stage (are higher MEDDICC scores correlated with later stages, suggesting progression likelihood?)
- This would validate that MEDDICC scores predict future outcomes, not just correlate with past outcomes

---

## Decision Matrix

| Criterion | Status | Weight | Meets Bar? |
|-----------|--------|--------|------------|
| Min evidence count (30) | 67 won deals | Critical | ✅ Yes |
| Positive discrimination | +4.0 points overall | High | ✅ Yes (moderate) |
| Pre-close timing | 60% pre-close | Medium | ✅ Yes (majority) |
| Component discrimination | 5/7 positive | Medium | ⚠️ Partial |
| Reverse correlation resolved | Flipped from original | High | ✅ Yes |

**Overall: Un-defer MEDDICC component with moderate weighting and documented caveats.**

---

## Appendix: Original vs Current Findings

| Aspect | Original (Sept 16) | Current (Sept 21) |
|--------|-------------------|-------------------|
| Won deal coverage | 4/327 (1.2%) | 67/229 (29.3%) |
| Champion discrimination | Reverse (lower on won) | +0.1 (weak positive) |
| EB discrimination | Reverse (lower on won) | +1.4 (moderate positive) |
| Overall discrimination | Not calculated (n=4) | +4.0 (positive) |
| Pre-close timing | 100% (all 43 analyses) | 59.7% (40/67) |
| Sample adequacy | ❌ Too small (n=4) | ✅ Above threshold (n=67) |

**Verdict:** The original deferral was the correct decision given 4-deal sample size and reverse correlation. The backfill has fundamentally changed the evidence base, clearing the threshold for reconsideration.
