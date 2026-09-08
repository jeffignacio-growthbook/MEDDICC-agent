# Enterprise Discovery Manual Override

**Date:** 2026-09-07
**Status:** ACTIVE — Temporary override pending n≥5 Enterprise Discovery clean won deals

---

## Override Specification

**Cell:** Discovery × Enterprise
**Threshold:** 35 days (MANUAL_OVERRIDE)
**Replaces:** 19-day stage-only fallback
**Set by:** Jeff (domain knowledge validation)

---

## Rationale

The 19-day stage-only fallback threshold (derived from Mid-Market/SMB Discovery data, n=14 clean won deals) flagged **73.9% of Enterprise Discovery deals (34/46)** — an implausibly high rate.

Sample review confirmed this threshold does not reflect genuine Enterprise Discovery risk:

**Deals flagged at 19 days but working normally:**
- **Expedia Group ($62k):** 37 days in stage, activity 10 days ago
- **Zurich Insurance Group ($74k):** 28 days in stage, activity 5 days ago
- **Robinhood ($150k):** 20 days in stage, activity 19 days ago

These deals show recent activity and deal values suggesting normal Enterprise evaluation cycles (more stakeholders, longer engagement) rather than genuine stale/neglected status.

**Root cause:** Enterprise Discovery has insufficient sample size (n=2 clean won deals) for segment-specific derivation. The stage-only fallback borrows from Mid-Market/SMB data, which have faster evaluation cycles not representative of Enterprise.

---

## Impact of 35-Day Override

### Before Override (19-day threshold)
- **Flagged:** 34/46 Enterprise Discovery deals (73.9%)
- **Healthy:** 12/46 deals (26.1%)

### After Override (35-day threshold)
- **Flagged:** 27/46 Enterprise Discovery deals (58.7%)
- **Healthy:** 19/46 deals (41.3%)

### Reduction
- **7 deals no longer flagged** (moved from flagged to healthy)
- **Newly healthy deals:** 20-35 day range
  - Virgin Media O2 UK Limited (35 days)
  - Zynga (32 days)
  - Guidepoint (32 days)
  - Zurich Insurance Group (28 days)
  - Zurich Insurance (27 days)
  - ATrack Solutions (25 days)
  - Robinhood (20 days)

### Still Flagged (>35 days)
Top flagged deals (n=27, genuinely stale):
1. **Rippling** — 130 days, 82 days since activity
2. **Comcast ($350k)** — 130 days, 103 days since activity
3. **DM** — 116 days, 111 days since activity
4. **Square** — 110 days, 96 days since activity
5. **Khan Academy** — 102 days, no activity data
6. **Zocdoc ($150k)** — 102 days, no activity data

These deals are **genuinely at-risk** (90-130 days in stage, many with no recent activity).

---

## Assessment

**58.7% flagging rate is STILL HIGH**, suggesting either:
1. **Enterprise Discovery pipeline has real issues** (many deals sitting 50-130 days genuinely stale)
2. **35 days is still slightly aggressive** for Enterprise evaluation cycles

However, this is a **significant improvement from 73.9%**, and the deals now flagged (>35 days) are much more likely to be genuinely at-risk rather than normal pipeline.

**Confidence level:** Moderate
- 35 days (5 weeks) is more reasonable for Enterprise than 19 days (2.7 weeks)
- Deals 20-35 days no longer flagged (likely normal evaluation)
- Deals >35 days still flagged (likely genuinely stale)

---

## Re-Derivation Trigger

**Condition:** Enterprise Discovery clean won deal count reaches **n≥5**

**Current state:**
- Enterprise Discovery clean won deals: **n=2**
- Required for segment-specific derivation: **n≥5**
- Gap: Need 3 more clean Enterprise Discovery won deals

**Action:**
- Run `scripts/derive_signal2_clean.py` **quarterly**
- Check Enterprise Discovery sample size each run
- When n≥5 reached:
  1. Remove manual override from config/field_semantics.yaml
  2. Use derived segment-specific threshold
  3. Document transition in SESSION_SUMMARY

**Monitoring:**
- Track Enterprise Discovery won deals in clean population (after exclusions)
- Alert when n≥5 reached
- Re-derive immediately when threshold met

---

## Overall Classification Impact

With 35-day Enterprise Discovery override:

| Classification | Count | % of Pipeline |
|----------------|-------|---------------|
| CRITICAL | ~102 | ~23% |
| WARN | ~47 | ~11% |
| **Total at-risk** | **~142** | **~32.0%** |

**Reduction from clean (19d):** 149 → 142 at-risk deals (~7 deal reduction)

**Context:**
- Contaminated thresholds: 29 at-risk deals (6.5%)
- Clean thresholds (19d): 149 at-risk deals (33.6%)
- With override (35d): **142 at-risk deals (32.0%)**

The override provides a **modest reduction** while maintaining focus on genuinely at-risk deals.

---

## Domain Knowledge Validation

**Jeff's assessment:**
- 19 days too aggressive for Enterprise Discovery
- Enterprise evaluation cycles naturally longer (more stakeholders, longer engagement)
- 35 days (5 weeks) more appropriate for Enterprise segment
- Not confident 19 days reflects genuine Enterprise risk

**Evidence supporting override:**
- 73.9% flagging rate implausibly high
- Sample deals at 28-37 days showed recent activity
- Mid-Market/SMB thresholds (19-25 days) appropriate for those segments
- Enterprise needs distinct threshold accounting for segment characteristics

---

## Files Updated

1. **config/field_semantics.yaml**
   - Signal 2 derivation changed from "DERIVED" to "PARTIALLY_DERIVED"
   - Added `manual_overrides.enterprise_discovery` section
   - Documented rationale, impact, re-derivation trigger
   - Status marked as "MANUAL_OVERRIDE" (distinct from DERIVED/STAGE_ONLY_FALLBACK/HAND_PICKED)

2. **ENTERPRISE_DISCOVERY_OVERRIDE.md** (this document)
   - Complete specification of override
   - Impact analysis
   - Re-derivation trigger conditions

3. **SIGNAL2_PRE_PRODUCTION_VALIDATION.md**
   - Full validation checks (Proposal contamination, Enterprise fallback, sample checks)
   - Rationale for override decision

---

## Production Readiness

**Status:** ✅ READY FOR SLACK VALIDATION

With Enterprise Discovery override applied:
- **Methodology:** Correct (centralized functions, proper exclusions)
- **Proposal threshold:** Clean (0 renewals, 105d appropriate)
- **Mid-Market/SMB thresholds:** Derived (19-25 days, align with domain knowledge)
- **Enterprise Discovery threshold:** Manual override (35 days, pending n≥5 for derivation)

**Next step:** Slack validation with sales team
- Pull sample at-risk deals from CRITICAL/WARN classifications
- Verify these deals genuinely need intervention
- Confirm thresholds match operational reality
- Deploy to production once validated

---

## Comparison: All Four Threshold Status Types

1. **DERIVED** (e.g., Mid-Market Discovery 19 days)
   - Empirically derived from clean won deal data
   - Sample size n≥5
   - Highest confidence

2. **STAGE_ONLY_FALLBACK** (e.g., Proposal 105 days)
   - Aggregated across segments when cells insufficient
   - Still empirically derived, just broader
   - Moderate confidence

3. **HAND_PICKED** (e.g., Signal 3: 14 days)
   - Domain knowledge validation, not empirical
   - Used when data doesn't support derivation
   - Lower confidence, explicit placeholder

4. **MANUAL_OVERRIDE** (e.g., Enterprise Discovery 35 days)
   - **NEW category added for Signal 2**
   - Overrides derived/fallback value for specific cell
   - Temporary pending sufficient sample size
   - Explicit, checkable re-derivation trigger
   - Lowest confidence, marked for replacement

---

## Temporary Status

This override is **TEMPORARY** and will be **replaced with derived threshold** once Enterprise Discovery clean won deal count reaches n≥5.

**Expected timeline:**
- Current rate: ~2-3 Enterprise deals close per quarter
- Need 3 more clean Enterprise Discovery wins
- **Estimate:** 1-2 quarters to reach n≥5

**Do not treat as permanent:** This is an interim solution, not final threshold.
