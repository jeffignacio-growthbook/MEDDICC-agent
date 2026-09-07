# Tasks 2-3: Wire Config & Add Expectations — COMPLETE

**Date:** 2026-09-07
**Status:** ✅ Both tasks complete, ready for testing

---

## Task 2: Wire query_deal to load_coaching_config — COMPLETE

### Changes Made to api/handlers.py

**Lines 913-951: Updated query_deal function**

Added coaching config loading and stage context:
```python
# Load coaching config for stage-relative MEDDICC interpretation
sys.path.insert(0, str(Path(__file__).parent.parent / "scripts"))
from coaching_config import load_coaching_config
coaching_config = load_coaching_config()

# Get stage bucket (discovery/scoping/proposal/closed_won/closed_lost)
current_stage = deal.get("stage", "")
current_bucket = stage_bucket(current_stage)
```

**Lines 975-988: Enhanced result structure**

Added stage context and stage-relative expectations to returned data:
```python
result = {
    "deal": deal,
    "latest_analysis": latest,
    "objections": objections,
    "stage_context": {
        "current_stage": current_stage,
        "stage_bucket": current_bucket,
    },
}

# Add stage-relative MEDDICC scoring expectations from coaching config
stage_scoring_expectations = coaching_config.get("stage_scoring_expectations", {})
if stage_scoring_expectations and current_bucket in stage_scoring_expectations:
    result["stage_scoring_expectations"] = stage_scoring_expectations[current_bucket]
```

### What This Enables

**Stage-aware synthesis:**
- Router now receives stage_context (current stage + bucket)
- Router receives stage_scoring_expectations for the deal's current stage
- LLM can interpret MEDDICC bands relative to stage (e.g., "EB-red acceptable in Discovery")

**Follows same pattern as query_pre_call_brief:**
- Both handlers now load coaching_config
- Both calculate stage_bucket using field_semantics
- Both pass stage context to synthesis layer

---

## Task 3: Add Hand-Picked Expectations to coaching_client.yaml — COMPLETE

### Changes Made to config/coaching_client.yaml

**Added two new sections at end of file (lines 325+):**

#### 1. stage_scoring_expectations (lines 327-594)

Full stage-relative MEDDICC expectations for all 7 components × 3 stages:

**Discovery stage:**
- EB/Champion: JEFF-VALIDATED
- Other 5: EXTRAPOLATED (PENDING JEFF REVIEW)

**Scoping stage:**
- EB/Champion: JEFF-VALIDATED
- Other 5: EXTRAPOLATED (PENDING JEFF REVIEW)

**Proposal stage:**
- EB/Champion: JEFF-VALIDATED
- Other 5: EXTRAPOLATED (PENDING JEFF REVIEW)

Each component includes:
- `acceptable_bands`: Which bands (red/yellow/green) are acceptable at this stage
- `concerning_threshold`: Which band triggers concern
- `interpretation_notes`: Context for why this band is/isn't acceptable
- `derivation_status`: HAND_PICKED (cannot derive empirically yet)
- `validated_by`: Provenance (Jeff-validated vs. extrapolated)

**Example (Economic Buyer at Discovery):**
```yaml
Economic Buyer:
  acceptable_bands: ["red", "yellow", "green"]
  concerning_threshold: null  # All bands acceptable in Discovery
  interpretation_notes: >
    JEFF-VALIDATED (2026-09-07): Discovery focus is IDENTIFICATION.
    EB-red means "not yet identified" which is expected early-stage.
    Concern only if still red by Scoping.
  derivation_status: HAND_PICKED
  validated_by: "Jeff (2026-09-07 Deel/DocPlanner/EA session)"
```

**Example (Champion at Scoping):**
```yaml
Champion:
  acceptable_bands: ["green"]
  concerning_threshold: "yellow"
  interpretation_notes: >
    JEFF-VALIDATED (2026-09-07): Champion should be actively helping
    by Scoping. Yellow means coordinator (schedules meetings when asked)
    not genuine champion (sells internally unprompted).
  derivation_status: HAND_PICKED
  validated_by: "Jeff (2026-09-07 Deel/DocPlanner/EA session)"
```

#### 2. champion_behavior_criteria (lines 596-659)

Explicit criteria for distinguishing genuine champion from coordinator:

**genuine_champion signals (3+ for green):**
- Introduces you to EB or stakeholders unprompted
- Shares internal political landscape proactively
- Asks for materials to present internally
- Defends solution against internal objections
- Guides on timing/process/stakeholders proactively
- Risks political capital to advocate

**coordinator_behavior signals (ceiling at yellow):**
- Schedules meetings when asked
- Answers questions when asked
- Responds promptly
- Attends demos
- Facilitates but doesn't advocate

**behavioral_scoring_rules:**
- Red → Yellow: At least one coordinator signal
- Yellow → Green: At least three genuine champion signals
- Override: Coordinator-only behavior MUST score yellow or red regardless of helpfulness

All sections validated by Jeff (2026-09-07 session).

---

## Provenance Labeling Summary

### JEFF-VALIDATED (direct corrections from 2026-09-07 session):
- Economic Buyer stage-relative expectations (all 3 stages)
- Champion stage-relative expectations (all 3 stages)
- All champion_behavior_criteria sections

### EXTRAPOLATED (domain knowledge, PENDING JEFF REVIEW):
- Metrics stage-relative expectations (all 3 stages)
- Decision Criteria stage-relative expectations (all 3 stages)
- Decision Process stage-relative expectations (all 3 stages)
- Pain stage-relative expectations (all 3 stages)
- Competition stage-relative expectations (all 3 stages)

**User directive:** "Do not let 'PENDING JEFF REVIEW' become a permanent, ignored label."

---

## What Flows Through Now

### Before (Tasks 1-3):
```
query_deal → pulls deal data
           → uses rubric.py (universal bands, not stage-aware)
           → returns meddicc_bands + next_steps
```

### After (Tasks 1-3):
```
query_deal → pulls deal data
           → loads coaching_config
           → calculates stage_bucket (discovery/scoping/proposal)
           → returns:
               - stage_context (stage, bucket)
               - stage_scoring_expectations (acceptable_bands, concerning_threshold)
               - meddicc_bands
               - champion_behavior_criteria (via config)
```

Router synthesis now receives stage-aware context for MEDDICC interpretation.

---

## Re-Derivation Path (Future)

**When to re-derive:**
- Once migration 058 runs (analyses.stage_at_analysis column exists)
- After ~315 analyses with stage_at_analysis populated (5 per 63 cells)

**How to re-derive:**
```bash
python scripts/derive_stage_meddicc_expectations.py
```

Will produce empirically-derived acceptable_bands per stage × component, replacing hand-picked where n≥5.

**Update strategy:**
- Replace EXTRAPOLATED components with DERIVED once validated
- Keep JEFF-VALIDATED labels for EB/Champion unless data contradicts
- Update validated_by field to "Empirical derivation (2026-MM-DD, n=X)"

---

## Next Steps

**Task 4: Test against real deals**
- Run query_deal for Deel, DocPlanner, TRT, Electronic Arts, Expedia
- Verify stage_context and stage_scoring_expectations appear in result
- Verify Deel EB-red not treated as red flag (Discovery stage)
- Verify champion_behavior_criteria distinguishes real champions from coordinators

**Task 5: Set review reminder**
- Create tracking document for EXTRAPOLATED components
- Watch for cases where LLM stage-relative reasoning feels wrong
- Track corrections (same as EB/Champion were tracked today)
- Update config with corrections + change validated_by labels

---

## Verification Checklist

- [x] query_deal imports load_coaching_config
- [x] query_deal calculates stage_bucket using field_semantics
- [x] query_deal adds stage_context to result
- [x] query_deal adds stage_scoring_expectations to result
- [x] coaching_client.yaml contains full stage_scoring_expectations (7 components × 3 stages)
- [x] coaching_client.yaml contains champion_behavior_criteria
- [x] EB/Champion labeled JEFF-VALIDATED
- [x] Other 5 components labeled EXTRAPOLATED (PENDING JEFF REVIEW)
- [ ] Testing (Task 4): query_deal returns stage-aware context
- [ ] Testing (Task 4): Router synthesis uses stage context correctly
- [ ] Reminder set (Task 5): Track EXTRAPOLATED component corrections

---

## Summary

Tasks 2-3 complete. query_deal now wired to coaching_config and coaching_client.yaml now contains hand-picked stage-relative MEDDICC expectations with honest provenance labeling. Ready for Task 4 (testing against real deals) and Task 5 (set review reminder for EXTRAPOLATED components).

Same discipline as earlier work: derive when possible, hand-pick with honest labels when insufficient, set re-derivation trigger once data structure supports it (Task 1 migration provides that structure).
