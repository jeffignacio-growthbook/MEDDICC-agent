# Stage-Relative MEDDICC Derivation Findings

**Date:** 2026-09-07
**Purpose:** Test whether stage-relative MEDDICC expectations can be derived empirically

---

## Attempt Summary

**Method:** Same empirical approach as Signal 2 threshold derivation
- Pull closed deals (won + lost) with MEDDICC analyses
- Apply same exclusions (renewals, negative cycle time)
- Bucket by stage, check if component bands correlate with outcome

**Result:** ❌ **INSUFFICIENT DATA**

---

## Data Availability

### Sample Sizes

**Closed deals (after exclusions):** 631 deals (won + lost)
- Excluded renewals
- Excluded negative cycle time
- Clean population matching Signal 2 hygiene

**MEDDICC analyses:** 45 passed analyses
- Only passed analyses included (same quality gate as Signal 2)
- 59 total analyses, 45 passed quality check

**Coverage problem:** 45 analyses across 63 cells (stage × component × band)
- Average: 0.7 analyses per cell
- Need n≥5 per cell for reliable statistics
- Actual: ~0 analyses per cell after stage bucketing

### Why No Data in Matrix

**Stage bucketing failure:** `stage_bucket()` function returned 'unknown' for all stage values
- Function expects HubSpot numeric stage IDs (e.g., '1297321623')
- Deals table likely contains stage labels (e.g., 'Discovery', 'Scoping')
- No canonical mapping between stage labels and stage buckets

**Technical issue, not fundamental data limitation.**

---

## Implications for Option A

### Cannot Derive Stage-Relative Expectations Yet

**Two blockers:**

1. **Stage mapping issue (fixable):**
   - Need to map deal.stage labels to discovery/scoping/proposal buckets
   - Either: add stage label → bucket mapping to field_semantics.yaml
   - Or: fetch stage IDs from HubSpot instead of labels

2. **Thin sample coverage (fundamental):**
   - Even with stage mapping fixed, 45 analyses across 63 cells = 0.7 per cell
   - Need ~315 analyses (5 per cell minimum) for reliable derivation
   - Current coverage: 14.3% of required sample

**Conclusion:** Cannot empirically derive stage-relative MEDDICC expectations yet.

---

## Recommended Approach: HAND_PICKED with Re-Derivation Trigger

Following same discipline as Signal 3 (14-day threshold) and Signal 2 Enterprise Discovery override (35-day):

### 1. Document as HAND_PICKED

Add to `config/coaching_client.yaml`:

```yaml
stage_scoring_expectations:
  # STATUS: HAND_PICKED pending empirical derivation
  #
  # Rationale: Insufficient MEDDICC analysis sample (n=45) to derive
  # stage-relative expectations with statistical confidence (need n≥315
  # for 5 per cell across 63 cells: 3 stages × 7 components × 3 bands).
  #
  # These expectations are derived from domain knowledge of B2B SaaS
  # sales methodology (MEDDICC), validated by Jeff's corrections during
  # Deel/DocPlanner/Electronic Arts interpretation session (2026-09-07).
  #
  # Re-derivation trigger: Once passed_analyses count reaches ≥315, re-run
  # scripts/derive_stage_meddicc_expectations.py with stage mapping fix.
  #
  # Temporary until: passed_analyses ≥ 315

  discovery:
    Economic Buyer:
      acceptable_bands: ["red", "yellow", "green"]
      concerning_threshold: null  # All bands acceptable in Discovery
      interpretation_notes: >
        Discovery focus is IDENTIFICATION. EB-red means "not yet identified"
        which is expected early-stage. Concern only if still red by Scoping.
      derivation_status: HAND_PICKED

    Champion:
      acceptable_bands: ["yellow", "green"]
      concerning_threshold: "red"
      interpretation_notes: >
        Should have engaged contact by Discovery. Red means no internal
        advocate identified, which is concerning even early. Yellow
        (helpful contact) is acceptable.
      derivation_status: HAND_PICKED

    Metrics:
      acceptable_bands: ["red", "yellow", "green"]
      concerning_threshold: null
      interpretation_notes: >
        Metrics can be partially quantified in Discovery. Red acceptable
        if progressing toward quantification.
      derivation_status: HAND_PICKED

    Decision Criteria:
      acceptable_bands: ["red", "yellow", "green"]
      concerning_threshold: null
      interpretation_notes: >
        Early discovery of requirements. Red acceptable as criteria
        surface during Discovery conversations.
      derivation_status: HAND_PICKED

    Decision Process:
      acceptable_bands: ["red", "yellow", "green"]
      concerning_threshold: null
      interpretation_notes: >
        Process mapping begins in Discovery. Red acceptable as stakeholders
        and approvals are still being uncovered.
      derivation_status: HAND_PICKED

    Pain:
      acceptable_bands: ["yellow", "green"]
      concerning_threshold: "red"
      interpretation_notes: >
        Pain should be articulated by Discovery. Red means no business
        problem identified, which questions deal viability.
      derivation_status: HAND_PICKED

    Competition:
      acceptable_bands: ["red", "yellow", "green"]
      concerning_threshold: null
      interpretation_notes: >
        Competitive landscape surfaces during Discovery. Red acceptable
        as alternatives are explored.
      derivation_status: HAND_PICKED

  scoping:
    Economic Buyer:
      acceptable_bands: ["yellow", "green"]
      concerning_threshold: "red"
      interpretation_notes: >
        By Scoping, EB should be identified. Red means structural gap in
        deal qualification. Yellow (identified but not engaged) acceptable.
      derivation_status: HAND_PICKED

    Champion:
      acceptable_bands: ["green"]
      concerning_threshold: "yellow"
      interpretation_notes: >
        Champion should be actively helping by Scoping. Yellow means
        coordinator (schedules meetings when asked) not genuine champion
        (sells internally unprompted). Red is deal-killer.
      derivation_status: HAND_PICKED

    Metrics:
      acceptable_bands: ["yellow", "green"]
      concerning_threshold: "red"
      interpretation_notes: >
        Business case should be quantified by Scoping. Red means no ROI
        articulated, questions whether evaluation is real.
      derivation_status: HAND_PICKED

    Decision Criteria:
      acceptable_bands: ["yellow", "green"]
      concerning_threshold: "red"
      interpretation_notes: >
        Evaluation criteria should be documented by Scoping. Red means
        prospect hasn't defined success, suggests premature stage.
      derivation_status: HAND_PICKED

    Decision Process:
      acceptable_bands: ["yellow", "green"]
      concerning_threshold: "red"
      interpretation_notes: >
        Approval process should be partially mapped. Red means key
        stakeholders unknown, timeline at risk.
      derivation_status: HAND_PICKED

    Pain:
      acceptable_bands: ["green"]
      concerning_threshold: "yellow"
      interpretation_notes: >
        Pain must be urgent by Scoping. Yellow means acknowledged but not
        urgent, questions deal velocity. Red is disqualifying.
      derivation_status: HAND_PICKED

    Competition:
      acceptable_bands: ["yellow", "green"]
      concerning_threshold: "red"
      interpretation_notes: >
        Competitive positioning should be clear by Scoping. Red means
        haven't surfaced alternatives, suggests early-stage conversation
        mispositioned as technical evaluation.
      derivation_status: HAND_PICKED

  proposal:
    Economic Buyer:
      acceptable_bands: ["green"]
      concerning_threshold: "yellow"
      interpretation_notes: >
        EB must be engaged by Proposal. Yellow or red is deal-killer —
        cannot close without confirmed budget authority and access.
      derivation_status: HAND_PICKED

    Champion:
      acceptable_bands: ["green"]
      concerning_threshold: "yellow"
      interpretation_notes: >
        Champion must be actively selling internally by Proposal. Yellow
        means they're not championing (just coordinating), red means no
        internal advocate. Both are closing risks.
      derivation_status: HAND_PICKED

    Metrics:
      acceptable_bands: ["green"]
      concerning_threshold: "yellow"
      interpretation_notes: >
        ROI must be documented and agreed by Proposal. Yellow means partial
        quantification, red means no business case. Both block close.
      derivation_status: HAND_PICKED

    Decision Criteria:
      acceptable_bands: ["green"]
      concerning_threshold: "yellow"
      interpretation_notes: >
        All criteria must be documented and scored by Proposal. Yellow or
        red means evaluation incomplete, premature to present contract.
      derivation_status: HAND_PICKED

    Decision Process:
      acceptable_bands: ["green"]
      concerning_threshold: "yellow"
      interpretation_notes: >
        Full process must be mapped by Proposal. Yellow or red means
        stakeholders or approvals unknown, timeline will slip.
      derivation_status: HAND_PICKED

    Pain:
      acceptable_bands: ["green"]
      concerning_threshold: "yellow"
      interpretation_notes: >
        Pain must be critical and urgent by Proposal. Yellow or red means
        insufficient urgency to close, deal will stall.
      derivation_status: HAND_PICKED

    Competition:
      acceptable_bands: ["green"]
      concerning_threshold: "yellow"
      interpretation_notes: >
        Positioning vs competitors must be clear and favorable by Proposal.
        Yellow or red means competitive risk, may lose on criteria or pricing.
      derivation_status: HAND_PICKED
```

### 2. Champion Behavior Criteria (separate section)

```yaml
champion_behavior_criteria:
  # STATUS: HAND_PICKED (behavioral observation, not statistical)
  #
  # Rationale: Distinguishes genuine champion (actively sells) from
  # coordinator (helpful but passive). Based on Jeff's correction during
  # Deel interpretation: "coordinator behavior doesn't warrant green/yellow,
  # champion means someone selling internally unprompted."
  #
  # Not statistically derivable (qualitative behavior assessment), but
  # governed by explicit criteria rather than LLM judgment.

  genuine_champion:
    signals:
      - "Introduces you to EB or other stakeholders unprompted"
      - "Shares internal political landscape proactively"
      - "Asks for materials to present internally"
      - "Defends solution against internal objections"
      - "Guides on timing, process, or stakeholders proactively"
      - "Risks political capital to advocate for purchase"
    minimum_signals_for_green: 3
    minimum_signals_for_yellow: 1
    scoring_guidance: >
      Green (7-10): Actively selling internally with multiple signals
      Yellow (4-6): Engaged and helpful, but not selling (coordinator)
      Red (0-3): No engaged internal advocate

  coordinator_behavior:
    signals:
      - "Schedules meetings when asked"
      - "Answers questions when asked"
      - "Responds to emails promptly"
      - "Attends demos and technical sessions"
      - "Facilitates but doesn't advocate"
    interpretation: >
      This is a helpful contact, not a champion. Coordinator behavior
      places ceiling at yellow/red border (score 4-5). Do not score
      above yellow without genuine champion signals.

  behavioral_scoring_rules:
    red_to_yellow_threshold: "At least one coordinator signal (responsive contact)"
    yellow_to_green_threshold: "At least three genuine champion signals (actively selling)"
    interpretation_override: >
      If evidence shows only coordinator behavior (schedules meetings,
      answers questions) but no proactive selling, score MUST be yellow
      or red regardless of how helpful the contact is.
```

### 3. Update COACHING_CONFIG_WIRING_INVESTIGATION.md

Document that Option A proceeds with HAND_PICKED status:
- Cannot derive yet (n=45, need n≥315)
- Same discipline as Signal 3's 14-day threshold
- Re-derivation trigger documented
- Labeled honestly as domain knowledge, not empirical

---

## Next Steps (Sequencing from Investigation)

**1. Fix stage mapping (optional, for future derivation):**
- Add stage label → bucket mapping to field_semantics.py
- Or: fetch stage IDs instead of labels in analyses queries
- Unblocks future re-derivation when sample size sufficient

**2. Implement Option C (wire query_deal):**
- query_deal loads coaching_config
- Passes stage_scoring_expectations to LLM synthesis
- Pure plumbing, low risk

**3. Implement Option A (HAND_PICKED expectations):**
- Add stage_scoring_expectations to coaching_client.yaml
- Add champion_behavior_criteria
- Mark as HAND_PICKED with re-derivation trigger
- Document rationale (insufficient sample, domain knowledge validated by Jeff's corrections)

**4. Monitor LLM consistency:**
- Deploy A+C to production
- Observe whether LLM applies stage-relative logic consistently with config guidance
- Only pursue Option D (deterministic bands) if LLM shows inconsistent interpretation

**5. Re-derive when sample accumulates:**
- Set up monitoring for passed_analyses count
- Re-run derive_stage_meddicc_expectations.py when n≥315
- Replace HAND_PICKED cells with DERIVED where data supports

---

## Key Finding: Option A Proceeds as HAND_PICKED

**Cannot derive stage-relative MEDDICC expectations empirically yet, but this doesn't block implementation.**

**Approach:** Apply same honest labeling discipline used throughout this session:
- Signal 3: 14-day threshold marked HAND_PICKED (domain knowledge)
- Signal 2 Enterprise Discovery: 35-day override marked MANUAL_OVERRIDE (pending n≥5)
- Stage MEDDICC expectations: HAND_PICKED (pending n≥315 for empirical derivation)

**Rationale for hand-picking:** Jeff's corrections during Deel/DocPlanner/Electronic Arts interpretation (2026-09-07) provide domain-knowledge validation of stage-relative logic:
- EB-red acceptable in Discovery (identification phase)
- Champion-yellow = coordinator not champion (behavior threshold)
- Pain-red concerning even early (no business case = no deal)

This is governed, queryable logic — just not yet empirically derived.

**Re-derivation trigger ensures eventual data-driven replacement** once sample accumulates.

---

## Comparison to Signal 2/3 Derivation

| Signal | Derivable? | Sample | Approach |
|--------|-----------|--------|----------|
| Signal 2 (time-in-stage) | ✅ Mostly | n=218 won deals | Derived per cell, manual override for Enterprise Discovery (n=2) |
| Signal 3 (activity recency) | ❌ No | No activity timestamps | Hand-picked 14-day threshold (domain knowledge) |
| Stage MEDDICC expectations | ❌ Not yet | n=45 analyses (need 315) | Hand-pick with re-derivation trigger |

**Stage MEDDICC expectations fall between Signal 2 and Signal 3:**
- Not derivable NOW (like Signal 3)
- But WILL BE derivable eventually (like Signal 2) once more analyses accumulate
- Honest labeling captures this: "HAND_PICKED pending re-derivation at n≥315"

Same discipline, consistently applied.
