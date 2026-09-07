# EXTRAPOLATED Components Review Tracking

**Created:** 2026-09-07 (Task 5 completion)
**Purpose:** Track real-usage feedback on 5 extrapolated MEDDICC components to validate or correct hand-picked stage expectations
**User directive:** "Do not let 'PENDING JEFF REVIEW' become a permanent, ignored label"

---

## Components Pending Review

### Metrics (3 stages × 5 cells = 15 expectations)

**Discovery:**
- acceptable_bands: ["red", "yellow", "green"]
- concerning_threshold: null
- Status: EXTRAPOLATED (PENDING JEFF REVIEW)

**Scoping:**
- acceptable_bands: ["yellow", "green"]
- concerning_threshold: "red"
- Status: EXTRAPOLATED (PENDING JEFF REVIEW)

**Proposal:**
- acceptable_bands: ["green"]
- concerning_threshold: "yellow"
- Status: EXTRAPOLATED (PENDING JEFF REVIEW)

### Decision Criteria (3 stages × 5 cells = 15 expectations)

**Discovery:**
- acceptable_bands: ["red", "yellow", "green"]
- concerning_threshold: null
- Status: EXTRAPOLATED (PENDING JEFF REVIEW)

**Scoping:**
- acceptable_bands: ["yellow", "green"]
- concerning_threshold: "red"
- Status: EXTRAPOLATED (PENDING JEFF REVIEW)

**Proposal:**
- acceptable_bands: ["green"]
- concerning_threshold: "yellow"
- Status: EXTRAPOLATED (PENDING JEFF REVIEW)

### Decision Process (3 stages × 5 cells = 15 expectations)

**Discovery:**
- acceptable_bands: ["red", "yellow", "green"]
- concerning_threshold: null
- Status: EXTRAPOLATED (PENDING JEFF REVIEW)

**Scoping:**
- acceptable_bands: ["yellow", "green"]
- concerning_threshold: "red"
- Status: EXTRAPOLATED (PENDING JEFF REVIEW)

**Proposal:**
- acceptable_bands: ["green"]
- concerning_threshold: "yellow"
- Status: EXTRAPOLATED (PENDING JEFF REVIEW)

### Pain (3 stages × 5 cells = 15 expectations)

**Discovery:**
- acceptable_bands: ["yellow", "green"]
- concerning_threshold: "red"
- Status: EXTRAPOLATED (PENDING JEFF REVIEW)

**Scoping:**
- acceptable_bands: ["green"]
- concerning_threshold: "yellow"
- Status: EXTRAPOLATED (PENDING JEFF REVIEW)

**Proposal:**
- acceptable_bands: ["green"]
- concerning_threshold: "yellow"
- Status: EXTRAPOLATED (PENDING JEFF REVIEW)

### Competition (3 stages × 5 cells = 15 expectations)

**Discovery:**
- acceptable_bands: ["red", "yellow", "green"]
- concerning_threshold: null
- Status: EXTRAPOLATED (PENDING JEFF REVIEW)

**Scoping:**
- acceptable_bands: ["yellow", "green"]
- concerning_threshold: "red"
- Status: EXTRAPOLATED (PENDING JEFF REVIEW)

**Proposal:**
- acceptable_bands: ["green"]
- concerning_threshold: "yellow"
- Status: EXTRAPOLATED (PENDING JEFF REVIEW)

**Total:** 75 stage × component × band expectations pending validation

---

## Review Process

### How to Track Corrections

1. **Watch for discrepancies during normal usage:**
   - User asks about a deal via Slack
   - LLM uses stage_scoring_expectations to interpret MEDDICC bands
   - Jeff notices interpretation feels wrong or inconsistent

2. **Document the discrepancy immediately:**
   - Record deal name, component, stage, and what felt wrong
   - Add entry to "Corrections Log" below

3. **Jeff reviews and corrects:**
   - Determine correct acceptable_bands for that stage × component
   - Decide if correction is specific to one deal or applies generally

4. **Update coaching_client.yaml:**
   - Modify stage_scoring_expectations section
   - Change validated_by from "Domain knowledge (PENDING JEFF REVIEW)" to "Jeff (correction date)"
   - Update interpretation_notes with corrected reasoning

5. **Mark as validated here:**
   - Update component status in this document
   - Note date validated and whether it matched extrapolation or needed correction

### Review Cadence

**Week 1-2 (2026-09-07 to 2026-09-21):**
- Monitor all query_deal calls that reference stage expectations
- Focus on deals in Discovery/Scoping (where most variation expected)
- Log any discrepancies

**Week 3 Review (2026-09-21):**
- Jeff reviews first batch of logged discrepancies
- Update config with corrections
- Identify any patterns (e.g., "Pain expectations too strict across all stages")

**Week 4-6 (2026-09-21 to 2026-10-05):**
- Continue monitoring with updated expectations
- Log any remaining discrepancies

**Final Review (2026-10-05):**
- Validate all remaining EXTRAPOLATED components
- Change all validated_by labels to either:
  - "Jeff (validated YYYY-MM-DD)" if extrapolation was correct
  - "Jeff (corrected YYYY-MM-DD)" if extrapolation needed adjustment

**Outcome:** All 5 components graduate from EXTRAPOLATED to VALIDATED within 4 weeks.

---

## Corrections Log

### Instructions

For each correction, create an entry with this format:

```markdown
### [Date] - [Component] - [Stage]

**Deal:** [Company name]
**Current stage bucket:** [discovery/scoping/proposal]
**Component band:** [red/yellow/green]

**What config said:** [Current acceptable_bands and concerning_threshold]

**What happened in synthesis:**
[How LLM interpreted the band using current expectations]

**Why it felt wrong:**
[Jeff's observation about why the interpretation was incorrect]

**Jeff's correction:**
[What the acceptable_bands should actually be for this stage × component]
[Updated interpretation_notes]

**Config update status:** [✅ Updated / ⏳ Pending]
**New validated_by:** "Jeff (YYYY-MM-DD correction)"
```

---

## Corrections Logged

### [Add corrections below as they occur]

---

## Validation Summary

*To be updated after 4-week review period*

| Component | Discovery | Scoping | Proposal | Status |
|-----------|-----------|---------|----------|--------|
| Metrics | ⏳ | ⏳ | ⏳ | PENDING REVIEW |
| Decision Criteria | ⏳ | ⏳ | ⏳ | PENDING REVIEW |
| Decision Process | ⏳ | ⏳ | ⏳ | PENDING REVIEW |
| Pain | ⏳ | ⏳ | ⏳ | PENDING REVIEW |
| Competition | ⏳ | ⏳ | ⏳ | PENDING REVIEW |

**Legend:**
- ⏳ Pending Jeff review
- ✅ Validated (matched extrapolation)
- 🔧 Corrected (extrapolation adjusted)

---

## Comparison to Validated Components

### Already Validated (for reference)

**Economic Buyer + Champion:**
- Validated during: Deel/DocPlanner/Electronic Arts interpretation session (2026-09-07)
- Validation method: Direct corrections during real deal review
- Status: No further review needed (JEFF-VALIDATED)

**Champion Behavior Criteria:**
- Validated during: Same session (2026-09-07)
- Validation method: Coordinator vs. genuine champion distinction confirmed across multiple deals
- Status: No further review needed (JEFF-VALIDATED)

### Goal for Extrapolated Components

Achieve same validation confidence level as EB/Champion through:
1. Real usage observation (not theoretical extrapolation)
2. Correction tracking (same as EB/Champion corrections were tracked)
3. Jeff sign-off (same validated_by label format)

---

## Re-Derivation Trigger (Future)

**Once this tracking completes:**
- All 7 components will have validated hand-picked expectations
- Can serve as ground truth for empirical derivation validation

**When stage_at_analysis data accumulates (Task 1):**
- Run `scripts/derive_stage_meddicc_expectations.py`
- Compare empirically derived expectations to hand-picked
- Where they disagree (and n≥5), favor empirical
- Where empirical has thin data (n<5), keep validated hand-picked

**Expected timeline:**
- Hand-picked validation: 4 weeks (2026-09-07 to 2026-10-05)
- Data accumulation: 3-6 months (~315 analyses needed)
- Re-derivation: Q1 2027

---

## Notes

**Why this matters:**
- Same as earlier fabrication bugs: don't claim something is validated when it's extrapolated
- PENDING JEFF REVIEW is an explicit trigger, not a permanent disclaimer
- Real usage validation > theoretical extrapolation
- Matches discipline from Signal 2 derivation: honest labels, re-derivation triggers

**How this differs from Signal 2 derivation:**
- Signal 2: Derived from data first, hand-picked only where n<5
- Stage MEDDICC: Hand-picked first (data blocker), validate through usage, re-derive later
- Both: Honest provenance labeling, explicit re-derivation triggers

**Success criteria:**
- Within 4 weeks: All EXTRAPOLATED → VALIDATED or CORRECTED
- Within 6 months: Sufficient stage_at_analysis data for empirical derivation
- Within 9 months: Replace hand-picked with empirically derived (where supported by data)
