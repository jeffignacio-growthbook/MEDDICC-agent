# Stage-Relative MEDDICC Implementation — Session Summary

**Date:** 2026-09-07
**Tasks Completed:** 1, 2, 3 (of 5)
**Status:** Ready for testing and review tracking

---

## Overview

Implemented stage-relative MEDDICC interpretation infrastructure following user request to wire coaching config into query_deal and add hand-picked stage expectations. Work done in response to MEDDICC validation session where Jeff corrected stage-relative interpretation (EB-red acceptable in Discovery, champion-yellow = coordinator behavior).

---

## Tasks Completed

### ✅ Task 1: Add stage_at_analysis Capture (Complete)

**Purpose:** Enable future empirical derivation of stage expectations by capturing deal stage at time of analysis.

**What was done:**
1. Modified `scripts/supabase_client.py` insert_analysis signature to accept stage_at_analysis parameter
2. Added stage_at_analysis field to database insert
3. Updated all 3 callers:
   - `scripts/run_nightly.py:515` → passes `deal.get('stage')`
   - `scripts/rollup_deal_scores.py:183` → passes `deal.get('stage')`
   - `scripts/test_component_scores.py:242` → passes `None` (test script)
4. Created migration `058_add_stage_at_analysis.sql`

**Database migration:**
```sql
ALTER TABLE analyses ADD COLUMN IF NOT EXISTS stage_at_analysis TEXT;
CREATE INDEX IF NOT EXISTS idx_analyses_stage_at_analysis ON analyses(stage_at_analysis);
CREATE INDEX IF NOT EXISTS idx_analyses_stage_outcome ON analyses(stage_at_analysis, deal_id);
```

**To run migration:**
```bash
export SUPABASE_DB_URL="postgresql://..."
python scripts/setup_supabase.py
```

**Re-derivation trigger:**
- Once ~315 analyses with stage_at_analysis populated
- Run `scripts/derive_stage_meddicc_expectations.py`
- Replace hand-picked expectations with empirically derived (where n≥5 per cell)

**Files modified:**
- scripts/supabase_client.py (238-278)
- scripts/run_nightly.py (508-515)
- scripts/rollup_deal_scores.py (179-183)
- scripts/test_component_scores.py (235-242)
- scripts/migrations/058_add_stage_at_analysis.sql (created)

**Documentation:** `TASK1_STAGE_CAPTURE_COMPLETE.md`

---

### ✅ Task 2: Wire query_deal to load_coaching_config (Complete)

**Purpose:** Enable stage-aware MEDDICC interpretation by passing coaching config and stage context to synthesis layer.

**What was done:**
1. Added coaching_config import and loading to query_deal
2. Calculated stage_bucket using field_semantics.stage_bucket()
3. Added stage_context to result (current_stage, stage_bucket)
4. Added stage_scoring_expectations to result (per current bucket)

**Code changes:**
```python
# Load coaching config for stage-relative MEDDICC interpretation
sys.path.insert(0, str(Path(__file__).parent.parent / "scripts"))
from coaching_config import load_coaching_config
coaching_config = load_coaching_config()

# Get stage bucket (discovery/scoping/proposal/closed_won/closed_lost)
current_stage = deal.get("stage", "")
current_bucket = stage_bucket(current_stage)

# Add to result
result = {
    "deal": deal,
    "latest_analysis": latest,
    "objections": objections,
    "stage_context": {
        "current_stage": current_stage,
        "stage_bucket": current_bucket,
    },
}

# Add stage-relative expectations
stage_scoring_expectations = coaching_config.get("stage_scoring_expectations", {})
if stage_scoring_expectations and current_bucket in stage_scoring_expectations:
    result["stage_scoring_expectations"] = stage_scoring_expectations[current_bucket]
```

**Files modified:**
- api/handlers.py (913-988)

**What this enables:**
- Router receives stage context with every query_deal call
- Synthesis can interpret bands relative to stage (e.g., "EB-red acceptable in Discovery")
- Follows same pattern as query_pre_call_brief (already uses coaching_config)

**Documentation:** `TASKS_2_3_COMPLETE.md`

---

### ✅ Task 3: Add Hand-Picked Expectations to coaching_client.yaml (Complete)

**Purpose:** Encode Jeff-validated stage-relative MEDDICC interpretations in governed config rather than applying inconsistently in conversation.

**What was done:**
1. Added `stage_scoring_expectations` section (7 components × 3 stages = 21 cells)
2. Added `champion_behavior_criteria` section (genuine vs. coordinator distinction)
3. Labeled provenance honestly:
   - JEFF-VALIDATED: EB + Champion (2026-09-07 Deel/DocPlanner/EA session)
   - EXTRAPOLATED (PENDING JEFF REVIEW): Other 5 components

**Structure added:**
```yaml
stage_scoring_expectations:
  discovery:
    Economic Buyer:
      acceptable_bands: ["red", "yellow", "green"]
      concerning_threshold: null
      interpretation_notes: "JEFF-VALIDATED (2026-09-07): Discovery focus is IDENTIFICATION..."
      derivation_status: HAND_PICKED
      validated_by: "Jeff (2026-09-07 Deel/DocPlanner/EA session)"

    Champion:
      acceptable_bands: ["yellow", "green"]
      concerning_threshold: "red"
      interpretation_notes: "JEFF-VALIDATED (2026-09-07): Should have engaged contact..."
      derivation_status: HAND_PICKED
      validated_by: "Jeff (2026-09-07 Deel/DocPlanner/EA session)"

    Metrics:
      acceptable_bands: ["red", "yellow", "green"]
      concerning_threshold: null
      interpretation_notes: "EXTRAPOLATED: Standard MEDDICC logic, not specifically validated..."
      derivation_status: HAND_PICKED
      validated_by: "Domain knowledge (PENDING JEFF REVIEW)"

    # ... (same for Decision Criteria, Decision Process, Pain, Competition)

  scoping:
    # ... (same structure, different expectations per stage)

  proposal:
    # ... (same structure, strictest expectations)

champion_behavior_criteria:
  genuine_champion:
    signals:
      - "Introduces you to EB or stakeholders unprompted"
      - "Shares internal political landscape proactively"
      - "Asks for materials to present internally"
      - "Defends solution against internal objections"
      - "Guides on timing/process/stakeholders proactively"
      - "Risks political capital to advocate"
    minimum_signals_for_green: 3
    minimum_signals_for_yellow: 1
    validated_by: "Jeff (2026-09-07 Deel/DocPlanner/EA session)"

  coordinator_behavior:
    signals:
      - "Schedules meetings when asked"
      - "Answers questions when asked"
      - "Responds promptly"
      - "Attends demos"
      - "Facilitates but doesn't advocate"
    interpretation: "Coordinator behavior places ceiling at yellow/red border (4-5)"
    validated_by: "Jeff (2026-09-07 Deel/DocPlanner/EA session)"
```

**Files modified:**
- config/coaching_client.yaml (325-659, ~334 lines added)

**Provenance summary:**
- JEFF-VALIDATED: EB + Champion stage expectations (6 cells), all champion_behavior_criteria
- EXTRAPOLATED (PENDING JEFF REVIEW): Metrics, Decision Criteria, Decision Process, Pain, Competition (15 cells)

**User directive:** "Do not let 'PENDING JEFF REVIEW' become a permanent, ignored label. Track corrections over coming weeks, update config with validated_by changes once confirmed."

**Documentation:** `TASKS_2_3_COMPLETE.md`

---

## Tasks Remaining

### Task 4: Test Against Real Deals (Next)

**Purpose:** Verify that stage-aware config actually changes synthesis output as expected.

**Test cases (reuse from validation session):**
1. **Deel (Discovery, EB-red):** Confirm NOT treated as red flag
2. **DocPlanner (Scoping, Champion-yellow):** Confirm interpreted as coordinator
3. **TRT (stage TBD):** Check stage-relative interpretation
4. **Electronic Arts (stage TBD):** Check stage-relative interpretation
5. **Expedia (stage TBD):** Check stage-relative interpretation

**What to verify:**
- `stage_context` appears in query_deal result
- `stage_scoring_expectations` appears for current bucket
- Router synthesis references stage when interpreting bands
- Deel EB-red interpretation: "acceptable in Discovery (identification phase), would be concerning by Scoping"
- Champion-yellow interpretation: "coordinator behavior (schedules meetings when asked), not genuine champion (sells internally unprompted)"

**How to test:**
```python
# Option A: Via API endpoint
curl -X POST http://localhost:8000/slack/question \
  -H "Content-Type: application/json" \
  -d '{"text": "Tell me about the Deel deal"}'

# Option B: Direct handler call
from api.handlers import query_deal
result = await query_deal({"company": "Deel"}, sb)
print(result["stage_context"])
print(result["stage_scoring_expectations"])
```

**Expected outcome:**
- Stage context flows through correctly
- LLM uses stage-relative expectations in synthesis
- Matches Jeff's corrections from validation session

---

### Task 5: Set Review Reminder for EXTRAPOLATED Components (Next)

**Purpose:** Ensure PENDING JEFF REVIEW doesn't become a permanent label. Track corrections to extrapolated components over coming weeks.

**What to create:**
1. **Tracking document:** `EXTRAPOLATED_COMPONENTS_REVIEW_TRACKING.md`
2. **Structure:**
   ```markdown
   # EXTRAPOLATED Components Review Tracking

   ## Purpose
   Track real-usage feedback on 5 extrapolated MEDDICC components (Metrics,
   Decision Criteria, Decision Process, Pain, Competition) to validate or
   correct hand-picked stage expectations.

   ## Components Pending Review
   - Metrics (15 stage × band expectations)
   - Decision Criteria (15 stage × band expectations)
   - Decision Process (15 stage × band expectations)
   - Pain (15 stage × band expectations)
   - Competition (15 stage × band expectations)

   ## Review Process
   1. Watch for cases where LLM stage-relative reasoning feels wrong
   2. Document discrepancy (deal name, component, stage, what was wrong)
   3. Jeff reviews and corrects
   4. Update coaching_client.yaml with correction
   5. Change validated_by from "PENDING JEFF REVIEW" to "Jeff (correction date)"

   ## Corrections Log

   ### [Date] - [Component] - [Stage]
   **Deal:** [Name]
   **Original expectation:** [What config said]
   **Actual observation:** [What happened]
   **Jeff's correction:** [What it should be]
   **Config updated:** [Yes/No]
   **New validated_by:** "Jeff (YYYY-MM-DD correction)"
   ```

3. **Calendar reminder:** 2 weeks from now, review first batch of real usage

**Outcome:**
- EXTRAPOLATED components either validate or get corrected
- validated_by changes from "Domain knowledge (PENDING JEFF REVIEW)" to "Jeff (YYYY-MM-DD correction)"
- Same correction-tracking discipline as today's EB/Champion validations

---

## Implementation Patterns Followed

### Same Discipline as Previous Work

**Signal 2 threshold derivation:**
- Derive from data when possible (n≥5)
- Hand-pick with honest labeling when insufficient
- Set re-derivation trigger

**Stage MEDDICC expectations:**
- Attempted empirical derivation first (found data blocker)
- Hand-picked with honest provenance labels
- Set re-derivation trigger (Task 1 migration enables it)

**Provenance labeling consistency:**
- Signal 3: 14-day threshold marked HAND_PICKED
- Signal 2 Enterprise: 35-day override marked MANUAL_OVERRIDE
- Stage MEDDICC: EB/Champion marked JEFF-VALIDATED, rest marked EXTRAPOLATED

### Bug Fixes Applied Before Implementation

**Bug #1: Fabricated derivation output**
- Script claimed "26 derived, 41.3% coverage" from zero actual data
- Fixed: Added has_any_data check, honest output shows 0% coverage
- Same pattern as earlier fabricated "68 cleaned" reconciliation number

**Bug #2: Provenance mismatch**
- Claimed all components Jeff-validated when only EB + Champion were
- Fixed: Precise labeling distinguishing JEFF-VALIDATED from EXTRAPOLATED
- User feedback: "Do not let PENDING JEFF REVIEW become permanent label"

### Infrastructure Before Scale

**Task 1 (stage_at_analysis capture):**
- Builds data structure needed for future empirical derivation
- Doesn't block Tasks 2-5 (forward-looking)
- Same as earlier work: build infrastructure, accumulate data, re-derive later

**Tasks 2-3 (wire config, add expectations):**
- Encode Jeff's corrections in governed config
- Consistent interpretation across all query_deal calls
- No more turn-by-turn inconsistency in conversation

---

## Files Created/Modified

### Created:
- `scripts/migrations/058_add_stage_at_analysis.sql`
- `TASK1_STAGE_CAPTURE_COMPLETE.md`
- `TASKS_2_3_COMPLETE.md`
- `IMPLEMENTATION_SESSION_SUMMARY.md` (this file)

### Modified:
- `scripts/supabase_client.py` (lines 238-278)
- `scripts/run_nightly.py` (line 515)
- `scripts/rollup_deal_scores.py` (line 183)
- `scripts/test_component_scores.py` (line 242)
- `api/handlers.py` (lines 913-988)
- `config/coaching_client.yaml` (lines 325-659, ~334 lines added)

### Reference (not modified):
- `COACHING_CONFIG_WIRING_INVESTIGATION.md` (investigation findings)
- `STAGE_MEDDICC_DERIVATION_FINDINGS.md` (why can't derive yet)
- `STAGE_MEDDICC_BUGS_FIXED.md` (bugs caught before implementation)
- `STAGE_SCORING_EXPECTATIONS_HANDPICKED.yaml` (source for Task 3 content)

---

## Next Session Pickup

**Start with Task 4:**
1. Test query_deal against Deel, DocPlanner, TRT, EA, Expedia
2. Verify stage_context and stage_scoring_expectations flow through
3. Check synthesis matches Jeff's corrections from validation session

**Then Task 5:**
1. Create `EXTRAPOLATED_COMPONENTS_REVIEW_TRACKING.md`
2. Set calendar reminder for 2-week review
3. Document correction process

**Then deploy:**
- Migration 058 can run anytime (doesn't block Tasks 4-5)
- A+C+monitoring already functional without migration
- Re-derivation happens later once data accumulates

---

## Summary

Implemented stage-relative MEDDICC interpretation infrastructure (Tasks 1-3). query_deal now loads coaching config, calculates stage bucket, and passes stage-aware expectations to synthesis layer. coaching_client.yaml now contains hand-picked expectations with honest provenance labels (EB/Champion Jeff-validated, others extrapolated pending review). Ready for testing (Task 4) and review tracking (Task 5).

Same discipline throughout: derive when possible, hand-pick with honest labels when insufficient, set re-derivation trigger once data structure supports it. Bugs caught and fixed before implementation, not discovered in production.
