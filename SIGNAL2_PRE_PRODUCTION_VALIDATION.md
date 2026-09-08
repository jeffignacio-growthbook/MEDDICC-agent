# Signal 2 Pre-Production Validation Report

**Date:** 2026-09-07
**Status:** ⚠️ FINDINGS REQUIRE REVIEW — Not production-ready without adjustments

---

## Executive Summary

Clean Signal 2 derivation methodology is **correct**, but three validation checks reveal operational concerns that must be addressed before deployment:

1. ✅ **Proposal contamination:** PASS — 0 renewals out of 8 deals, 105-day threshold is clean
2. ⚠️ **Enterprise Discovery fallback:** **CONCERN** — 73.9% flagging rate suggests 19-day threshold over-aggressive for Enterprise
3. ⚠️ **Newly flagged deals sample:** **MIXED** — Some genuinely stale (167 days, no activity), others borderline (55-66 days, recent activity)

**Key finding:** +413% swing (29 → 149 flagged deals) is catching **both real issues AND potential over-flagging**, especially for Enterprise Discovery. The 19-day threshold derived from Mid-Market/SMB may not translate to Enterprise evaluation cycles.

---

## Validation Check #1: Proposal Stage Contamination

### Question
Is the unchanged 105-day Proposal threshold truly uncontaminated, or did renewals reach Proposal and inflate it like Discovery?

### Finding: ✅ PASS — No Contamination

**Proposal stage population:**
- Total deals with Proposal time: 8
- Renewal deals: **0 (0.0%)**
- Clean deals: 8 (100.0%)

**Conclusion:** The assumption "renewals rarely reach proposal" is **correct**. The 105-day threshold is based entirely on clean deals and requires no adjustment.

**Domain validation:** 105 days (~3.5 months) for proposal stage aligns with technical evaluation + procurement cycles for complex B2B deals.

---

## Validation Check #2: Enterprise Discovery Fallback

### Question
Enterprise Discovery (n=2) falls back to stage-only 19-day threshold derived mostly from Mid-Market/SMB. Is this over-aggressive for Enterprise, which typically has more stakeholders and longer evaluation cycles?

### Finding: ⚠️ CONCERN — 73.9% Flagging Rate

**Enterprise Discovery population:**
- Total active Enterprise Discovery deals: 46
- Flagged by 19-day threshold: **34 (73.9%)**
- Healthy (≤ 19 days): 12 (26.1%)

**Flagged deals time-in-stage statistics:**
- Min: 20 days
- Median: **66 days**
- Max: 130 days

### Sample Flagged Deals

**CRITICAL (Signal 2 + Signal 3):**
- **Deel ($175k)**: 55 days in stage, 19 days since activity
- **Brussels Airlines ($200k)**: 66 days in stage, 53 days since activity
- **Amazon**: 53 days in stage, 33 days since activity

**WARN (Signal 2 only, recent activity):**
- **The New York Times**: 61 days in stage, 3 days since activity
- **Expedia Group ($62k)**: 37 days in stage, 10 days since activity
- **Douglas**: 91 days in stage, 7 days since activity

### Interpretation

**73.9% flagging rate is HIGH** — suggests threshold may be over-aggressive for Enterprise segment.

**Two competing explanations:**
1. **Threshold is correct:** Enterprise Discovery pipeline is genuinely stale/neglected, 73.9% of deals need intervention
2. **Threshold is over-aggressive:** 19 days (2.7 weeks) is too short for Enterprise evaluation cycles, which naturally take 4-8 weeks

**Evidence for over-aggressive:**
- Median time-in-stage for flagged deals is **66 days** (9.4 weeks)
- Many flagged deals have recent activity (WARN classification)
- Enterprise typically has more stakeholders, longer evaluation
- Derived from Mid-Market/SMB won deals (n=14), which may have faster cycles

**Evidence for threshold being correct:**
- Some deals clearly stale (Comcast 130 days, no activity 103 days)
- Many CRITICAL deals with no activity 30-90 days
- If Enterprise naturally takes 60-90 days, why are only n=2 Enterprise won deals showing Discovery time in clean sample?

### Recommendation

**Before production deployment:**
1. **Slack validation with sales team:** "Is 19 days (2.7 weeks) reasonable for Enterprise Discovery, or do Enterprise deals naturally sit here 6-8 weeks?"
2. **If threshold too aggressive:** Consider Enterprise-specific adjustment (30-45 days) via manual override until n≥5 for segment-specific derivation
3. **If threshold appropriate:** Accept 73.9% flagging rate as real pipeline hygiene issue

**This is the critical gate for production readiness.**

---

## Validation Check #3: Newly Flagged Deals Sample

### Question
The +413% swing (29 → 149 flagged deals) is methodologically correct, but operationally sound? Random sample of newly flagged deals: genuinely at-risk, or over-flagging normal pipeline?

### Finding: ⚠️ MIXED — Some Genuinely Stale, Others Borderline

**Sample:** 15 random deals flagged CRITICAL/WARN under clean thresholds, were HEALTHY under contaminated thresholds

**Sample characteristics:**
- All 15 deals in **Discovery stage** (100%)
- Time in stage: 25-167 days (median **55 days**)
- Classification: 9 CRITICAL (60%), 6 WARN (40%)
- Segments: 6 Enterprise (40%), 4 Mid-Market (27%), 3 SMB (20%), 2 Unknown (13%)

### Clear Stale Deals (Genuinely At-Risk)

**AMBOSS (Mid-Market, $50k)**
- 167 days in Discovery, activity 165 days ago
- **Assessment:** Clearly neglected, legitimate flag

**Brussels Airlines (Enterprise, $200k)**
- 66 days in Discovery, activity 53 days ago
- **Assessment:** Stale, no recent engagement

**Visible (SMB, $150k)**
- 60 days in Discovery, activity 60 days ago
- **Assessment:** Stale, no activity since entering stage

**Felt (SMB)**
- 61 days in Discovery, activity 58 days ago
- **Assessment:** Stale

### Borderline Deals (Could Go Either Way)

**The New York Times (Enterprise)**
- 61 days in Discovery, activity **3 days ago**
- **Assessment:** Long time-in-stage BUT being worked actively
- **Question:** Is 61 days (8.7 weeks) normal for Enterprise Discovery?

**Expedia Group (Enterprise, $62k)**
- 37 days in Discovery, activity **10 days ago**
- **Assessment:** Moderately long BUT recent activity
- **Question:** Is 37 days (5.3 weeks) concerning for Enterprise?

**Deel (Enterprise, $175k)**
- 55 days in Discovery, activity 19 days ago (Signal 3 fires at >14 days)
- **Assessment:** Flagged CRITICAL, but is 55 days genuinely stale for $175k Enterprise deal?

**Zurich Insurance Group (Enterprise, $74k)**
- 28 days in Discovery, activity **5 days ago**
- **Assessment:** Just over threshold (19d), but actively worked
- **Question:** Is 28 days (4 weeks) concerning?

### Interpretation

**Mixed picture suggests threshold may be over-aggressive for Enterprise, appropriate for Mid-Market/SMB:**

**Genuinely at-risk (support clean thresholds):**
- AMBOSS (167 days, no activity)
- Brussels Airlines (66 days, 53 days no activity)
- Visible (60 days, no activity)

**Borderline/over-flagged (question clean thresholds for Enterprise):**
- The New York Times (61 days, but activity 3 days ago)
- Expedia Group (37 days, activity 10 days ago)
- Zurich Insurance Group (28 days, activity 5 days ago)

**Key insight:** Sample is **100% Discovery stage**, reinforcing Enterprise Discovery fallback concern.

---

## Cross-Check: Sample Size Warning

### Issue
Several "segment-specific" cells barely above minimum threshold (n=5):

| Stage | Segment | n | P75 | Status |
|-------|---------|---|-----|--------|
| Discovery | Mid-Market | 7 | 19 days | Viable, but thin |
| Discovery | SMB | **5** | 25 days | **Exactly at minimum** |
| Scoping | Mid-Market | **5** | 23 days | **Exactly at minimum** |

**SMB Discovery (n=5)** and **Scoping Mid-Market (n=5)** are sitting **exactly at the n≥5 gate**. One different deal could meaningfully shift these thresholds.

### Recommendation

Document in implementation guide:
- These thresholds are **viable but not robust**
- Re-derive quarterly as more deals close to improve sample size
- Watch for threshold volatility as new won deals added

---

## Overall Assessment

### What's Correct
✅ Methodology is sound (centralized functions, proper exclusions)
✅ Proposal stage uncontaminated (0 renewals, 105d threshold clean)
✅ Mid-Market/SMB thresholds appear reasonable (19-25 days aligns with 2-4 week cycles)
✅ Some flagged deals are genuinely stale (AMBOSS 167 days, Brussels Airlines 66 days)

### What's Concerning
⚠️ **Enterprise Discovery 73.9% flagging rate** (34/46 deals) — suggests 19d threshold too aggressive
⚠️ **Median flagged time-in-stage is 55-66 days** — questioning if 19d is appropriate for Enterprise
⚠️ **Borderline deals flagged** (Expedia 37d, Zurich 28d) — could be normal Enterprise evaluation
⚠️ **Sample sizes thin** — SMB Discovery (n=5), Scoping Mid-Market (n=5) exactly at minimum

### What This Means for +413% Swing

The +413% increase (29 → 149 flagged deals) is **partially legitimate, partially over-flagging:**

**Legitimate increase (catching real issues):**
- Contaminated thresholds (400+ days) were absurdly high
- Some deals clearly stale (167 days no activity)
- Clean thresholds catching genuinely neglected pipeline

**Potential over-flagging:**
- Enterprise Discovery may have normal 4-8 week evaluation cycles
- 19-day threshold derived from Mid-Market/SMB may not translate
- 73.9% Enterprise flagging rate suggests threshold mismatch

---

## Production Readiness Decision Tree

### Option 1: Deploy As-Is (Not Recommended)

**Accept:**
- 149 flagged deals (33.6% of pipeline)
- 73.9% of Enterprise Discovery flagged
- Potential over-flagging of normal Enterprise evaluation cycles

**Risk:**
- Sales team loses trust in Signal 2 if too many false positives
- Enterprise deals get flagged that don't need intervention

### Option 2: Validate with Sales Team First (Recommended)

**Before deployment:**
1. **Slack validation:** Ask sales team if 19 days (2.7 weeks) is reasonable for Enterprise Discovery
2. **Pull 5-10 specific Enterprise Discovery deals** flagged by 19d threshold
3. **Review with sales team:** "Do these need intervention, or are they being worked normally?"
4. **Adjust if needed:** If consensus is "too aggressive," implement Enterprise override (30-45d)

**Then deploy** with confidence that thresholds match operational reality.

### Option 3: Segment-Specific Enterprise Override (Interim Solution)

**Acknowledge:**
- Enterprise Discovery sample size insufficient (n=2)
- 19-day fallback may be too aggressive
- Need more data for segment-specific derivation

**Implement:**
- **Enterprise Discovery:** 30-day override (vs 19d fallback) until n≥5
- **Mid-Market Discovery:** 19 days (segment-specific, n=7)
- **SMB Discovery:** 25 days (segment-specific, n=5)

**Rationale:**
- 30 days (4.3 weeks) more reasonable for Enterprise stakeholder engagement
- Reduces flagging rate from 73.9% to more manageable level
- Re-evaluate when Enterprise won deals increase sample size

**Deploy** with this adjustment, monitor, re-derive quarterly.

---

## Recommended Path Forward

### Step 1: Slack Validation (Gate for Production)

**Ask sales team:**
```
Quick validation needed for at-risk deal thresholds:

We derived Discovery stage threshold at 19 days (2.7 weeks) from historical
won deals. For Enterprise deals specifically, this flags 74% of active
Discovery deals.

Question: Is 19 days reasonable for Enterprise Discovery, or do Enterprise
deals naturally sit here 4-8 weeks while engaging stakeholders?

Sample flagged Enterprise deals:
- Deel ($175k): 55 days in Discovery
- The New York Times: 61 days in Discovery, activity 3 days ago
- Expedia Group ($62k): 37 days in Discovery, activity 10 days ago

Do these need intervention, or are they being worked normally?
```

### Step 2: Adjust Based on Feedback

**If "19 days too aggressive for Enterprise":**
- Implement Enterprise override: 30-45 days
- Document as interim until n≥5 for segment-specific
- Deploy with adjustment

**If "19 days appropriate, those deals ARE stale":**
- Deploy clean thresholds as-is
- Accept 149 flagged deals (33.6% of pipeline)
- Document as real pipeline hygiene issue surfaced

### Step 3: Monitor and Re-Derive

**Quarterly re-derivation:**
- Track exclusion counts (should remain ~30%)
- Watch for sample size improvements
- Re-compute thresholds as more deals close
- Adjust overrides when segment-specific samples reach n≥5

---

## Files Created

1. **scripts/check_proposal_contamination.py** — Validation check #1
2. **scripts/check_enterprise_discovery_fallback.py** — Validation check #2
3. **scripts/sample_newly_flagged_deals.py** — Validation check #3
4. **SIGNAL2_PRE_PRODUCTION_VALIDATION.md** — This document

---

## Conclusion

**Methodology:** ✅ Correct (centralized functions, proper exclusions)
**Proposal threshold:** ✅ Clean (0 renewals, 105d appropriate)
**Mid-Market/SMB thresholds:** ✅ Appear reasonable (19-25 days)
**Enterprise Discovery threshold:** ⚠️ **REQUIRES VALIDATION** (73.9% flagging rate)

**NOT production-ready** until Enterprise Discovery threshold validated with sales team. The +413% swing is catching **both real issues (167-day stale deals) AND potential over-flagging (37-day actively worked deals)**.

**Critical next step:** Slack validation with sales team on whether 19 days is reasonable for Enterprise Discovery, or if 30-45 day override needed.

Once validated: ✅ Ready for production deployment with appropriate threshold adjustments.
