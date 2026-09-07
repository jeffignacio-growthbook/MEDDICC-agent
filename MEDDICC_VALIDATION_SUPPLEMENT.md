# MEDDICC as Optional Validation Supplement

**Status:** OPTIONAL third signal — validation proceeds regardless of coverage
**Coverage:** 7/16 validation deals have recent MEDDICC scores (43.8%)
**Role:** Additive diagnostic context where available, NOT required for validation to count
**Primary validation:** System classification vs. rep's unprompted answer (required, 16/16 deals)

**See also:** VALIDATION_FRAMEWORK_GOVERNANCE.md for coverage requirements and graceful degradation principles

---

## Framework Position

Per VALIDATION_FRAMEWORK_GOVERNANCE.md:

**Required signals (100% coverage):**
1. System classification (Signal 2 + Signal 3)
2. Rep's unprompted read ("moving" / "stalled" / "not sure")

**Optional signals (no coverage threshold):**
3. MEDDICC scores (available for 7/16 deals)
4. Other enrichment (future)

**Agreement rate:** Calculated from system + rep for ALL 16 deals, regardless of MEDDICC availability.

MEDDICC refines WHY mismatches occur, but does NOT override system-vs-rep comparison or its interpretation thresholds.

---

## MEDDICC Scores (Pre-Validation Reference)

**Do NOT show these to reps** - same anchoring risk as day counts.

Pull these BEFORE sending rep questions, keep as independent third data point.

### Deals with MEDDICC Scores

| Deal | System Class | Days in Stage | MEDDICC Overall | Key Weaknesses |
|------|--------------|---------------|-----------------|----------------|
| **Deel** | CRITICAL | 55d | 42/70 (moderate) | Champion 5/10, Econ Buyer 4/10 |
| **DocPlanner** | CRITICAL | 59d | 23/70 (weak) | Champion 3/10, all scores low |
| **TRT** | CRITICAL | 59d | 21/70 (weak) | Metrics 2/10, Competition 2/10 |
| **Electronic Arts** | WARN | 37d | 34/70 (moderate) | Econ Buyer 2/10 |
| **Expedia Group** | WARN | 37d | 23/70 (weak) | **Econ Buyer 0/10**, low overall |
| **Zurich Insurance** | HEALTHY | 27d | 17/70 (very weak) | **Econ Buyer 0/10**, Competition 1/10 |
| **Robinhood** | HEALTHY | 20d | 31/70 (moderate) | Econ Buyer 0/10 |

### Deals WITHOUT MEDDICC Scores

- Rippling (CRITICAL, 130d)
- GitLab Inc. (no_signal_at_risk, 54d)
- Amazon (CRITICAL, 53d)
- Hy-Vee (WARN, 44d)
- Virgin Media O2 UK Limited (HEALTHY, 35d)
- Zynga (HEALTHY, 32d)
- Guidepoint (HEALTHY, 32d)
- Zurich Insurance Group (HEALTHY, 28d)
- ATrack Solutions (HEALTHY, 25d)

---

## Three-Way Comparison Template

After collecting rep answers, compare three independent signals:

### Deal: Deel ($175k, 55 days in Discovery)

| Signal | Classification | Details |
|--------|----------------|---------|
| **System** | CRITICAL | 55d > 35d threshold, activity 19d ago (>14d) |
| **MEDDICC** | Moderate-weak | 42/70, Champion 5/10, Econ Buyer 4/10 |
| **Rep answer** | [collect unprompted] | "Still moving" / "Stalled" / "Not sure" |

**Analysis:**
- If rep "stalled" + MEDDICC weak (42/70) + System CRITICAL → **All agree, deal at-risk**
- If rep "moving" + MEDDICC weak (42/70) + System CRITICAL → **Rep may be overly optimistic** (data shows weak deal sitting long)
- If rep "stalled" + MEDDICC moderate (42/70) + System CRITICAL → **Rep has context** (recent development not captured in score?)

### Deal: Expedia Group ($62k, 37 days in Discovery)

| Signal | Classification | Details |
|--------|----------------|---------|
| **System** | WARN | 37d > 35d threshold, activity 10d ago (≤14d) |
| **MEDDICC** | Weak | 23/70, **Econ Buyer 0/10**, low across all components |
| **Rep answer** | [collect unprompted] | "Still moving" / "Stalled" / "Not sure" |

**Analysis:**
- If rep "moving" + MEDDICC very weak (23/70, no econ buyer) + System WARN → **Rep optimistic on structurally weak deal**
- If rep "stalled" + MEDDICC weak (23/70) + System WARN → **All agree, deal has issues**

### Deal: Zurich Insurance ($100k, 27 days in Discovery)

| Signal | Classification | Details |
|--------|----------------|---------|
| **System** | HEALTHY | 27d < 35d threshold, activity 27d ago (>14d but didn't flag) |
| **MEDDICC** | Very weak | 17/70, **Econ Buyer 0/10**, Competition 1/10 |
| **Rep answer** | [collect unprompted] | "Still moving" / "Stalled" / "Not sure" |

**Analysis:**
- If rep "moving" + MEDDICC very weak (17/70) + System HEALTHY → **System missed weak deal** (under-flagging)
- If rep "stalled" + MEDDICC very weak (17/70) + System HEALTHY → **System definitely under-flagged** (threshold too lenient)
- If rep "moving" + MEDDICC weak but System HEALTHY → **System correct, MEDDICC may be stale/pessimistic**

### Deal: Robinhood ($150k, 20 days in Discovery)

| Signal | Classification | Details |
|--------|----------------|---------|
| **System** | HEALTHY | 20d < 35d threshold, activity 19d ago (>14d but didn't flag) |
| **MEDDICC** | Moderate-weak | 31/70, Econ Buyer 0/10 |
| **Rep answer** | [collect unprompted] | "Still moving" / "Stalled" / "Not sure" |

**Analysis:**
- If rep "moving" + MEDDICC moderate (31/70) + System HEALTHY → **All agree, deal healthy** (control case)
- If rep "stalled" + MEDDICC moderate + System HEALTHY → **Rep has concern** (threshold may be too lenient, or rep knows something recent)

---

## Most Diagnostically Interesting Patterns

### Pattern 1: Rep optimistic, data pessimistic
**Signature:** Rep "moving" + MEDDICC weak (<30/70) + System flagged
**Interpretation:** Rep may be overly optimistic about structurally weak deal
**Example:** If Expedia rep says "moving" but MEDDICC 23/70 with no econ buyer
**Action:** Flag for deeper investigation - is rep seeing progress data doesn't capture, or missing red flags?

### Pattern 2: Rep pessimistic, data optimistic
**Signature:** Rep "stalled" + MEDDICC strong (>40/70) + System healthy
**Interpretation:** Rep has context not captured in scoring (recent development, competitive threat, internal blocker)
**Example:** If rep says "stalled" but MEDDICC recently scored 45/70
**Action:** Trust rep's ground truth over data - they have real-time context

### Pattern 3: All agree (strong signal)
**Signature:** Rep, MEDDICC, and System all align
**Interpretation:** High-confidence classification
**Example:** Rep "stalled" + MEDDICC 23/70 + System CRITICAL
**Action:** These are your most reliable at-risk flags

### Pattern 4: Data agrees, rep disagrees
**Signature:** Rep answer differs from both MEDDICC and System
**Interpretation:** Either rep has unique context OR rep is misreading the deal
**Example:** Rep "moving" but both MEDDICC weak (21/70) and System CRITICAL (59 days)
**Action:** Most diagnostic - reveals either threshold calibration issue or rep blind spot

---

## Analysis After Collecting Rep Answers

For each of the 7 deals with MEDDICC:

```
THREE-WAY COMPARISON RESULTS
============================

Full agreement (all 3 signals align):
- [List deals where rep, MEDDICC, System all agree]
- Interpretation: High-confidence classifications

Rep optimistic (rep says moving, data says at-risk):
- [List deals where rep "moving" but MEDDICC weak + System flagged]
- Interpretation: Potential rep blind spots OR threshold over-aggressive

Rep pessimistic (rep says stalled, data says healthy):
- [List deals where rep "stalled" but MEDDICC strong + System healthy]
- Interpretation: Rep has context not in data OR threshold under-aggressive

Mixed signals (no clear pattern):
- [List deals with conflicting signals across all three]
- Interpretation: Context-dependent, needs case-by-case investigation
```

---

## Key Principles

**1. MEDDICC is optional, not required**
- Validation proceeds for ALL 16 deals (required: system + rep)
- MEDDICC available for 7/16 deals → adds diagnostic richness for those 7
- MEDDICC unavailable for 9/16 deals → standard two-way validation for those 9
- **No minimum coverage threshold** — even 1-2 MEDDICC scores add value
- Unlike Signal 2/3 derivation (which needed n≥5 for stable statistics), this is individual-deal context with no aggregation requirement

**2. Agreement rate includes all deals**
- Numerator: System-rep matches (out of 16 total)
- Denominator: 16 (NOT 7 — MEDDICC absence doesn't exclude deals from calculation)
- MEDDICC column shows "N/A" for 9 deals without scores
- Interpretation thresholds unchanged: >80% well-calibrated, systematic patterns trigger adjustment

**3. Don't show MEDDICC to reps**
- Same anchoring risk as day counts
- Let rep answer unprompted, compare after
- MEDDICC is independent third data point, not shown during elicitation

**4. MEDDICC refines WHY, not WHETHER**
- System-vs-rep comparison determines WHETHER threshold is well-calibrated (match/mismatch)
- MEDDICC (where available) refines WHY a mismatch occurred:
  - Rep optimistic + MEDDICC weak → rep may miss structural red flags
  - Rep pessimistic + MEDDICC moderate → rep has operational context not in data
  - All three agree → highest confidence classification
- But MEDDICC never overrides the core system-rep match/mismatch status

**5. Graceful degradation (same as Signal 1/3 coverage gaps)**
- Never silently treat MEDDICC absence as agreement
- Explicitly use two-way interpretation logic for deals without MEDDICC
- Absence of optional data is not evidence of anything — handle explicitly

---

## For 9 Deals Without MEDDICC

**These deals use the core validation framework** (system vs. rep, two required signals):

| Deal | System Class | Days | Rep Answer | Agreement? |
|------|--------------|------|------------|------------|
| Rippling | CRITICAL | 130d | [collect] | [compare] |
| GitLab Inc. | no_signal | 54d | [collect] | [compare] |
| Amazon | CRITICAL | 53d | [collect] | [compare] |
| Hy-Vee | WARN | 44d | [collect] | [compare] |
| Virgin Media O2 UK | HEALTHY | 35d | [collect] | [compare] |
| Zynga | HEALTHY | 32d | [collect] | [compare] |
| Guidepoint | HEALTHY | 32d | [collect] | [compare] |
| Zurich Insurance Group | HEALTHY | 28d | [collect] | [compare] |
| ATrack Solutions | HEALTHY | 25d | [collect] | [compare] |

**These 9 deals provide the same calibration signal as the 7 with MEDDICC** — the validation is two-way (required signals only) vs. three-way (required + optional), not "complete" vs. "incomplete."

**All 16 deals contribute equally to:**
- Agreement rate calculation (matches / 16)
- Systematic pattern detection (over-flagging, under-flagging)
- Threshold adjustment decision (>80%, systematic, <60%)

**MEDDICC absence is handled via graceful degradation:**
- Comparison matrix includes MEDDICC column with "N/A" for these 9 deals
- Interpretation logic switches from three-way to two-way automatically
- No reduction in these deals' validation weight or contribution

---

## Implementation Steps

### Required Steps (Load-Bearing Validation)

1. ✅ **System classification computed** (16/16 deals via Signal 2 + Signal 3)
2. **Send unprompted questions to all 16 reps** (no numbers, no MEDDICC mentions)
3. **Collect rep answers** (still moving / stalled / not sure) for all 16 deals
4. **Calculate agreement rate:** matches / 16 (all deals count equally)
5. **Identify systematic patterns:** over-flagging, under-flagging, or mixed
6. **Make threshold decision:**
   - >80% agreement → deploy 35d threshold as-is
   - Systematic over-flagging → raise threshold
   - Systematic under-flagging → lower threshold
   - <60% agreement → investigate context factors

### Optional Steps (Diagnostic Enrichment)

1. ✅ **Confirmed MEDDICC availability** (7/16 deals, 43.8% — no minimum required)
2. ✅ **Pulled scores BEFORE sending rep questions** (this document — independent data point)
3. **Build comparison matrices:**
   - Two-way for all 16 deals (system + rep) — load-bearing
   - Three-way for 7 deals with MEDDICC (system + rep + MEDDICC) — diagnostic richness
4. **Analyze MEDDICC-enriched patterns** (where available):
   - Rep optimistic + MEDDICC weak → potential blind spot
   - Rep pessimistic + MEDDICC moderate → operational context not in data
   - All three agree → highest confidence

**Key principle:** Steps 1-6 (required) produce the threshold decision. Optional steps add context but never gate validation completion or override the decision.

**No coverage gates:** Even if MEDDICC were available for only 1-2 deals, validation proceeds with 16-deal agreement rate calculation.
