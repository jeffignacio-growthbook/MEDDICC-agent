# Validation Framework Governance

**Purpose:** Formalize validation principles for threshold calibration testing, including graceful degradation for optional data sources.

**Status:** Active framework as of 2026-09-07

---

## Core Validation Principle

**Load-bearing test:** System classification vs. rep's unprompted read of deal status.

This two-signal comparison stands on its own and is sufficient for threshold calibration validation. All additional signals (MEDDICC, customer interviews, CRM activity patterns) are purely additive context and never required for validation to proceed or be considered complete.

---

## Signal Requirements by Type

### Required Signals (Always Present)

**1. System Classification (Signal 2 + Signal 3)**
- Source: Computed from deals table (time_in_stage, notes_last_updated)
- Coverage: 100% of deals in scope
- Quality gate: Must use clean population (exclude renewals, negative cycle time)
- Output: CRITICAL, WARN, no_signal_at_risk, HEALTHY, no_signal_healthy

**2. Rep's Unprompted Read**
- Source: Sales rep owner of each deal
- Coverage: 100% of validation deals (by design — ask all 16 reps)
- Quality gate: Zero anchoring (no day counts, no system numbers shown)
- Output: "Still moving" / "Stalled" / "Not sure"

### Optional Signals (Additive Context Only)

**3. MEDDICC Scores (Optional)**
- Source: analyses table (overall_score, component scores)
- Coverage: 43.8% of validation deals (7/16) — **NO minimum threshold required**
- Quality gate: Recency (<30 days old), stage-adjusted interpretation
- Output: overall_score /70, component breakdown
- Role: Refines WHY a system-vs-rep mismatch occurred, does NOT override core comparison

**4. Other Enrichment (Future)**
- Customer interviews, competitive intel, CRM activity patterns, etc.
- Same principle: additive context, never required for validation to count

---

## Interpretation Logic

### Two Signals Available (System + Rep)

**Standard interpretation applies to all 16 deals, regardless of MEDDICC availability:**

| System | Rep | Match? | Interpretation |
|--------|-----|--------|----------------|
| CRITICAL/WARN | "Stalled" | ✅ Correct | System well-calibrated |
| HEALTHY | "Moving" | ✅ Correct | System well-calibrated |
| CRITICAL/WARN | "Moving" | ❌ Over-flagging | Threshold too aggressive |
| HEALTHY | "Stalled" | ❌ Under-flagging | Threshold too lenient |

**Agreement rate calculation:**
- Sample: All 16 boundary case deals
- Numerator: Matches (system + rep agree)
- Denominator: 16 (MEDDICC availability does NOT affect denominator)

**Threshold adjustment triggers:**
- >80% agreement → Deploy as-is (well-calibrated)
- Systematic over-flagging pattern → Raise threshold
- Systematic under-flagging pattern → Lower threshold
- <60% agreement → Investigate context factors

### Three Signals Available (System + Rep + MEDDICC)

**MEDDICC adds diagnostic richness but does NOT override core system-vs-rep comparison:**

**Pattern 1: All three agree**
- Example: Rep "stalled" + MEDDICC 23/70 + System CRITICAL
- Interpretation: Highest-confidence classification
- Action: No adjustment needed

**Pattern 2: Rep optimistic, data pessimistic**
- Example: Rep "moving" + MEDDICC 23/70 + System CRITICAL
- Interpretation: Rep may be overly optimistic about structurally weak deal
- MEDDICC role: Confirms deal has structural weaknesses (low econ buyer, weak champion)
- Action: Flag for deeper investigation — is rep missing red flags in data?

**Pattern 3: Rep pessimistic, data optimistic**
- Example: Rep "stalled" + MEDDICC 42/70 + System HEALTHY
- Interpretation: Rep has context not captured in scoring (recent development, blocker)
- MEDDICC role: Suggests deal not structurally weak, so rep's concern may be operational
- Action: Trust rep's ground truth — they have real-time context

**Pattern 4: MEDDICC disagrees with both**
- Example: Rep "moving" + System HEALTHY + MEDDICC 17/70
- Interpretation: MEDDICC may be stale or pessimistic
- MEDDICC role: Flags potential structural risk, but doesn't override system-rep agreement
- Action: Note for follow-up, but system-rep agreement still drives threshold calibration

**Key principle:** MEDDICC refines interpretation of WHY mismatches occur, but the match/mismatch status itself (agreement rate, systematic patterns) is determined by system-vs-rep comparison alone.

---

## Coverage Requirements

### Minimum Sample Size (Applies to Required Signals Only)

**Signal 2 Threshold Derivation:**
- Minimum n≥5 won deals per stage × segment cell for empirical derivation
- Below threshold → fallback to stage-only aggregation or manual override
- Rationale: Insufficient sample produces unstable percentiles

**Signal 3 Threshold Derivation:**
- Hand-picked (14 days) based on domain knowledge
- No minimum sample required (not empirically derived)

**Validation Sample (System + Rep):**
- 16 boundary case deals (8 boundary flagged, 6 boundary healthy, 2 control cases)
- ALL 16 contribute to agreement rate calculation
- Rationale: Testing threshold calibration, not deriving a new threshold

### No Coverage Requirement (Applies to Optional Signals)

**MEDDICC Scores:**
- 7/16 deals (43.8%) have recent scores
- **No minimum threshold for MEDDICC to be "useful"**
- Even 1-2 deals with MEDDICC add helpful diagnostic context
- Rationale: Unlike threshold derivation (which needs stable statistics), this is individual-deal corroboration — any additional data point is valuable

**Contrast with Signal 2/3 derivation:**
- Signal 2/3 derivation genuinely needed coverage thresholds to produce trustworthy THRESHOLDS (aggregate statistical estimate)
- Validation uses MEDDICC for individual-deal context (no aggregation, no minimum required)

---

## Graceful Degradation Principle

**Never silently treat absence as agreement.**

This principle was established for Signal 1/3 coverage gaps and applies identically here:

### Signal 1 (Days in Stage)

**Problem:** Some deals have NULL time_in_stage (no enter_stage_date)
**Solution:** Classify as no_signal_at_risk or no_signal_healthy, NOT as HEALTHY
**Rationale:** Absence of data is not evidence of health

### Signal 3 (Activity Recency)

**Problem:** Some deals have NULL notes_last_updated (no activity data)
**Solution:** Classify as no_signal_at_risk or no_signal_healthy, NOT as HEALTHY
**Rationale:** Absence of activity data is not evidence of recent activity

### MEDDICC (Optional Context)

**Problem:** 9/16 validation deals have no MEDDICC scores
**Solution:** Use two-way comparison (system + rep) for these deals
**Rationale:** Absence of MEDDICC does NOT reduce these deals' contribution to validation
**Implementation:**
- Agreement rate denominator = 16 (all deals count)
- MEDDICC column in comparison matrix shows "N/A" for 9 deals
- Interpretation logic switches from three-way to two-way for these deals

### Future Optional Signals

**Same pattern applies:** Any optional enrichment (customer interviews, competitive intel) degrades gracefully:
- If available: adds diagnostic context
- If absent: validation proceeds with system + rep comparison
- Coverage rate is informational only, never a gate

---

## Documentation and Change Control

### When to Update This Document

1. **Adding new optional signals:** Document coverage approach, interpretation logic, graceful degradation
2. **Changing required signal definitions:** Update "Required Signals" section
3. **Adjusting coverage thresholds:** Update "Minimum Sample Size" section with rationale
4. **Validation framework changes:** Any modification to interpretation logic or agreement rate calculation

### Related Documents

- **SIGNAL2_CLEAN_DERIVATION_SUMMARY.md:** Threshold derivation methodology
- **ENTERPRISE_DISCOVERY_OVERRIDE.md:** Manual override governance
- **MEDDICC_VALIDATION_SUPPLEMENT.md:** Operational playbook for MEDDICC-enriched validation
- **SLACK_VALIDATION_NATURAL.md:** Rep elicitation approach

### Version History

- **2026-09-07:** Initial version formalizing optional signal framework
- **Next review:** After first validation round completion (threshold adjustment decision)

---

## Key Differences: Derivation vs. Validation

Understanding why coverage requirements differ:

### Threshold Derivation (Signal 2)

**Goal:** Produce empirically-derived time-in-stage thresholds per stage × segment
**Method:** Calculate P75 of historical won deals' time-in-stage
**Coverage requirement:** n≥5 won deals per cell
**Why minimum matters:** Below n=5, P75 becomes unstable (insufficient data for reliable percentile)
**Failure mode:** Thin samples produce unreliable thresholds → flag wrong deals

### Validation (System vs. Rep)

**Goal:** Test whether derived thresholds match operational reality
**Method:** Compare system classification to reps' unprompted read for boundary cases
**Coverage requirement (required signals):** 100% of 16 validation deals
**Coverage requirement (optional signals):** None — any MEDDICC data is helpful
**Why minimum doesn't matter:** Each deal is individually validated (no aggregation)
**Failure mode:** With optional signals, absence simply means less diagnostic richness, validation still succeeds

**Same principle as Signal 1/3 coverage gaps:** Absence of data is not evidence of anything — handle explicitly, never silently treat as a default value.

---

## Operational Checklist

Before running validation:

- [ ] System classification computed for all 16 deals (required)
- [ ] Rep owners identified for all 16 deals (required)
- [ ] Unprompted questions prepared with zero day counts (required)
- [ ] MEDDICC scores pulled for available deals (optional — proceed regardless of count)
- [ ] Comparison matrix template includes columns for all required signals + N/A for optional
- [ ] Agreement rate calculation defined (numerator/denominator = matches/16)
- [ ] Interpretation thresholds documented (>80%, 60-80%, <60%)

After collecting rep answers:

- [ ] All 16 rep answers recorded (required)
- [ ] Agreement rate calculated (matches / 16)
- [ ] Systematic patterns identified (over-flagging, under-flagging, mixed)
- [ ] MEDDICC-enriched interpretation applied where available (optional)
- [ ] Threshold adjustment decision documented with rationale
- [ ] Results written to ENTERPRISE_DISCOVERY_OVERRIDE.md or equivalent

MEDDICC availability does NOT gate any of these steps.
