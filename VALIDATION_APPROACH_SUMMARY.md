# Validation Approach Summary

**Purpose:** Quick reference for Enterprise Discovery threshold validation (35-day manual override)

**Status:** Ready to execute (all prep complete)

**Date:** 2026-09-07

---

## What We're Testing

**Hypothesis:** 35-day time-in-stage threshold for Enterprise Discovery is well-calibrated (flags genuinely stalled deals, doesn't over-flag actively-worked deals).

**Test method:** Compare system's classification to sales reps' unprompted read of boundary case deals.

---

## Two Required Signals

### Signal 1: System Classification (Computed)

**Source:** Signal 2 (time-in-stage) + Signal 3 (activity recency)

**For Enterprise Discovery:**
- Signal 2 threshold: 35 days (manual override)
- Signal 3 threshold: 14 days (hand-picked)

**Classifications:**
- CRITICAL: >35 days in stage AND >14 days since activity
- WARN: >35 days in stage AND ≤14 days since activity
- HEALTHY: ≤35 days in stage
- no_signal variants: Missing activity data

**Coverage:** 16/16 validation deals

### Signal 2: Rep's Unprompted Read (Elicited)

**Questions:** Natural pipeline check-in style
- "Hey, where's Deel at?"
- "What's the status on GitLab?"
- "How's Amazon looking - still live?"

**Zero anchoring:** No day counts, no activity timing, no system numbers

**Responses:** "Still moving" / "Stalled" / "Not sure"

**Coverage:** 16/16 validation deals (by design)

---

## One Optional Signal

### Signal 3: MEDDICC Scores (Additive Context)

**Source:** analyses table (overall_score, component scores)

**Coverage:** 7/16 validation deals (43.8%)

**Role:** Refines WHY system-vs-rep mismatches occur, does NOT override agreement rate or threshold decision

**Interpretation:**
- Rep optimistic + MEDDICC weak → rep may miss structural red flags
- Rep pessimistic + MEDDICC moderate → rep has operational context
- All three agree → highest confidence

**No minimum coverage threshold:** Even 1-2 MEDDICC scores add diagnostic value

---

## Validation Sample: 16 Boundary Cases

### Boundary Flagged (8 deals)
System says CRITICAL/WARN (>35 days):
- Rippling (130d, CRITICAL) — control: obvious stale
- Deel (55d, CRITICAL)
- GitLab Inc. (54d, no_signal_at_risk)
- Amazon (53d, CRITICAL)
- DocPlanner (59d, CRITICAL)
- TRT (59d, CRITICAL)
- Hy-Vee (44d, WARN)
- Electronic Arts (37d, WARN)
- Expedia Group (37d, WARN)

### Boundary Healthy (6 deals)
System says HEALTHY (≤35 days):
- Virgin Media O2 UK (35d, HEALTHY)
- Zynga (32d, HEALTHY)
- Guidepoint (32d, HEALTHY)
- Zurich Insurance Group (28d, HEALTHY)
- Zurich Insurance (27d, HEALTHY)
- ATrack Solutions (25d, HEALTHY)
- Robinhood (20d, HEALTHY) — control: obvious healthy

**Test focus:** Deals at 25-60 days test threshold calibration (not obvious 130d or 20d cases)

---

## Interpretation Logic

### Agreement Rate Calculation

**Numerator:** System-rep matches
- Match: Rep "stalled" + System CRITICAL/WARN
- Match: Rep "moving" + System HEALTHY
- Mismatch: Rep "moving" + System CRITICAL/WARN (over-flagging)
- Mismatch: Rep "stalled" + System HEALTHY (under-flagging)

**Denominator:** 16 (all deals count, MEDDICC availability doesn't affect this)

### Decision Thresholds

**>80% agreement:** Deploy 35-day threshold as-is (well-calibrated)

**60-80% agreement:** Deploy with monitoring, minor adjustments if clear pattern

**Systematic over-flagging:** Multiple boundary flagged deals (35-50d) where rep says "moving"
- Action: Raise threshold (try 45-50 days)
- Example: Expedia 37d, Electronic Arts 37d, Hy-Vee 44d all "moving" per reps

**Systematic under-flagging:** Multiple boundary healthy deals (25-35d) where rep says "stalled"
- Action: Lower threshold (try 25-30 days)
- Example: Virgin Media O2 35d, Guidepoint 32d, Zurich 28d all "stalled" per reps

**<60% agreement:** Investigate context factors, consider additional signals beyond time-in-stage

---

## MEDDICC Enrichment (Where Available)

### 7 Deals with MEDDICC Scores

| Deal | System | MEDDICC | Rep | Interpretation Logic |
|------|--------|---------|-----|---------------------|
| Deel | CRITICAL | 42/70 | [collect] | Three-way comparison |
| DocPlanner | CRITICAL | 23/70 | [collect] | Three-way comparison |
| TRT | CRITICAL | 21/70 | [collect] | Three-way comparison |
| Electronic Arts | WARN | 34/70 | [collect] | Three-way comparison |
| Expedia Group | WARN | 23/70 | [collect] | Three-way comparison |
| Zurich Insurance | HEALTHY | 17/70 | [collect] | Three-way comparison |
| Robinhood | HEALTHY | 31/70 | [collect] | Three-way comparison |

**MEDDICC role:** Adds diagnostic context for WHY system-vs-rep match/mismatch occurred, but doesn't change the match/mismatch status itself.

### 9 Deals Without MEDDICC Scores

| Deal | System | Rep | Interpretation Logic |
|------|--------|-----|---------------------|
| Rippling | CRITICAL | [collect] | Two-way comparison |
| GitLab Inc. | no_signal | [collect] | Two-way comparison |
| Amazon | CRITICAL | [collect] | Two-way comparison |
| Hy-Vee | WARN | [collect] | Two-way comparison |
| Virgin Media O2 UK | HEALTHY | [collect] | Two-way comparison |
| Zynga | HEALTHY | [collect] | Two-way comparison |
| Guidepoint | HEALTHY | [collect] | Two-way comparison |
| Zurich Insurance Group | HEALTHY | [collect] | Two-way comparison |
| ATrack Solutions | HEALTHY | [collect] | Two-way comparison |

**These 9 deals contribute equally to agreement rate and threshold decision** — two-way validation is the core framework, three-way is enrichment.

---

## Execution Checklist

### Before Sending Questions

- [x] System classification computed for all 16 deals
- [x] Rep owners identified for all 16 deals
- [x] Unprompted questions prepared (zero day counts)
- [x] MEDDICC scores pulled for available deals (optional)
- [x] Comparison matrix template ready
- [x] Agreement rate calculation defined
- [x] Interpretation thresholds documented

### Send Questions

- [ ] Send unprompted questions to all 16 reps
- [ ] No day counts, no activity timing, no system numbers
- [ ] Casual manager-style check-in, not formal audit

### Collect and Analyze

- [ ] Record all 16 rep answers ("moving" / "stalled" / "not sure")
- [ ] Calculate agreement rate (matches / 16)
- [ ] Identify systematic patterns (over-flagging, under-flagging, mixed)
- [ ] Apply MEDDICC enrichment where available (7 deals)
- [ ] Make threshold decision (>80%, systematic, <60%)

### Document Results

- [ ] Write validation results to ENTERPRISE_DISCOVERY_OVERRIDE.md
- [ ] Update config/field_semantics.yaml if threshold adjusted
- [ ] Record decision rationale and next review date
- [ ] Deploy or iterate based on findings

---

## Key Governance Principles

See VALIDATION_FRAMEWORK_GOVERNANCE.md for full framework.

**Core validation:** System + rep (required, 16/16 deals)

**Optional enrichment:** MEDDICC (7/16 deals, no minimum threshold)

**Graceful degradation:** MEDDICC absence doesn't reduce validation weight of deals without it

**Never silently treat absence as agreement:** Explicitly use two-way logic for deals without MEDDICC

**Agreement rate denominator:** Always 16 (all deals count equally)

---

## Related Documents

- **VALIDATION_FRAMEWORK_GOVERNANCE.md:** Formal framework, coverage requirements, graceful degradation
- **SLACK_VALIDATION_NATURAL.md:** Rep elicitation approach (unprompted questions)
- **MEDDICC_VALIDATION_SUPPLEMENT.md:** Operational playbook for MEDDICC-enriched validation
- **ENTERPRISE_DISCOVERY_OVERRIDE.md:** Manual override specification and results location
- **scripts/identify_deal_owners.py:** Helper to identify rep owners
- **scripts/check_meddicc_scores_for_validation.py:** Helper to pull MEDDICC scores

---

## Next Steps After Validation

**If >80% agreement:** Deploy 35-day threshold to production, monitor quarterly

**If systematic pattern:** Adjust threshold (raise for over-flagging, lower for under-flagging), re-run boundary case check

**If <60% agreement:** Investigate context factors (deal size, competitive pressure, segment differences), consider additional signals

**In all cases:** Document results, rationale, and next review date in ENTERPRISE_DISCOVERY_OVERRIDE.md
