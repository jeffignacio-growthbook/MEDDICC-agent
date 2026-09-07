# Stage MEDDICC Derivation: Bugs Fixed and Honest Assessment

**Date:** 2026-09-07
**Status:** Both bugs caught and fixed before implementation

---

## Bug #1: Script Fabricating Confident Output from No Data

### Original Problem

**Output showed:** "26 derived (n≥5), 4 hand-picked (n<5), 41.3% coverage"

**Raw output showed:** Every single stage × component cell printed "RED: No data / YELLOW: No data / GREEN: No data"

**Auto-generated config showed:** All 21 cells assigned `acceptable_bands: ['green']` with `derivation_status: DERIVED`

**This was fabricated, not real data.**

### Root Cause

**Line 283** in `generate_stage_scoring_expectations()`:
```python
# Green is always acceptable (by definition)
acceptable_bands.append('green')
```

This unconditionally appended `green` even when red_result, yellow_result, green_result were ALL empty dicts.

**Lines 286-299:** Checked `.get('predictive')` on empty dicts:
- `{}.get('predictive')` returns `None`
- `None is False` evaluates to `False` (not `True`)
- So yellow/red were never added when data was missing

**Line 311-314:** Marked as `DERIVED` when no `HAND_PICKED` status found:
- Empty dicts have no `'status'` key
- So defaults to `'DERIVED'` despite having zero evidence

**Result:** Generated `acceptable_bands: ['green']` + `derivation_status: 'DERIVED'` for every cell with no data.

### Fix Applied

Added data availability check before generating expectations:

```python
# Check if we have ANY data for this component at this stage
has_any_data = any(r.get('sample_size') is not None for r in [red_result, yellow_result, green_result])

if not has_any_data:
    # No data - mark as insufficient
    expectations[bucket][label] = {
        'acceptable_bands': None,
        'concerning_threshold': None,
        'interpretation_notes': 'INSUFFICIENT_DATA - no analyses at this stage',
        'derivation_status': 'INSUFFICIENT_DATA'
    }
    continue
```

### Verified Honest Output

**After fix:**
```
Total component × stage cells: 21
Derived or partially derived: 0
Insufficient data: 21
Coverage: 0% (no cells had sufficient data for derivation)

⚠️  21 component × stage cells have insufficient data
Stage bucketing may be broken (check that deals.stage contains
HubSpot canonical stage names, not human-readable labels)
```

**All cells now honestly report:**
```yaml
Economic Buyer:
  acceptable_bands: null
  concerning_threshold: null
  interpretation_notes: INSUFFICIENT_DATA - no analyses at this stage
  derivation_status: INSUFFICIENT_DATA
```

---

## Bug #2: Deeper Root Cause (Not Just Stage Name Mapping)

### Initial Hypothesis: Stage Label vs. Numeric ID Mismatch

**Confirmed:** `stage_bucket()` expects HubSpot canonical names ('appointmentscheduled') or numeric IDs ('1297321623'), but deals table has human-readable labels ('Discovery', 'Scoping', 'Proposal').

**Test results:**
```
Discovery      → bucket: unknown
Scoping        → bucket: unknown
Proposal       → bucket: unknown
appointmentscheduled → bucket: discovery ✓
1297321623     → bucket: closed_won ✓
```

### Actual Root Cause: Missing stage_at_analysis Column

**Debug output revealed:**
```
Matrix total entries: 315
Matrix buckets populated: ['closed_lost', 'closed_won']
```

**What's happening:**
1. Closed deals have 315 analyses with outcomes
2. But `deal.stage` for closed deals is ALWAYS 'Closed Won' or 'Closed Lost' (current stage)
3. Not the stage the deal was in AT THE TIME of analysis
4. So all 315 analyses bucket into closed stages, not discovery/scoping/proposal

**Fundamental data limitation:** The `analyses` table doesn't have `stage_at_analysis` column.

To derive stage-relative expectations, we need to know what stage the deal was in when each analysis was done, not what stage it's in now (after closing).

### Three Paths to Fix

**Option A:** Add `stage_at_analysis` to analyses table
- Capture `deal.stage` at analysis time
- Requires schema change + backfill (may not be possible for historical analyses)

**Option B:** Infer from deal timeline
- Query HubSpot property history for stage changes
- Match analysis timestamp to stage at that time
- Possible but computationally expensive

**Option C:** Use only active deals
- Active deals haven't closed yet, so current stage is meaningful
- But then can't correlate MEDDICC bands with win/loss outcome
- Defeats purpose of derivation (testing predictiveness)

**Conclusion:** Cannot derive stage-relative expectations empirically yet. Not a sample size problem (315 analyses is decent), but a data structure problem.

---

## Bug #3: Hand-Picked Config Provenance Mismatch

### Problem Caught

**Original rationale claimed:**
> "Validated by Jeff's corrections during Deel/DocPlanner/Electronic Arts interpretation session (2026-09-07)"

**But Jeff only actually validated:**
- Economic Buyer stage-relative expectations
- Champion coordinator-vs-genuine-champion distinction

**He did NOT validate:**
- Metrics, Decision Criteria, Decision Process, Pain, Competition stage tables
- Those are reasonable MEDDICC extrapolations, not Jeff-validated corrections

### Fix Applied

Created `STAGE_SCORING_EXPECTATIONS_HANDPICKED.yaml` with precise provenance labeling:

**Jeff-validated sections:**
```yaml
Economic Buyer:
  validated_by: "Jeff (2026-09-07 Deel/DocPlanner/EA session)"
  interpretation_notes: >
    JEFF-VALIDATED (2026-09-07): Discovery focus is IDENTIFICATION...

Champion:
  validated_by: "Jeff (2026-09-07 Deel/DocPlanner/EA session)"
  interpretation_notes: >
    JEFF-VALIDATED (2026-09-07): Should have engaged contact by Discovery...
```

**Extrapolated sections:**
```yaml
Metrics:
  validated_by: "Domain knowledge (PENDING JEFF REVIEW)"
  interpretation_notes: >
    EXTRAPOLATED: Metrics can be partially quantified in Discovery.
    Standard MEDDICC progression logic, not specifically validated by Jeff.

Decision Criteria:
  validated_by: "Domain knowledge (PENDING JEFF REVIEW)"
  interpretation_notes: >
    EXTRAPOLATED: Early discovery of requirements. Standard MEDDICC
    logic, not specifically validated by Jeff.

# ... (same for Decision Process, Pain, Competition)
```

**Champion behavior criteria (all Jeff-validated):**
```yaml
champion_behavior_criteria:
  genuine_champion:
    validated_by: "Jeff (2026-09-07 Deel/DocPlanner/EA session)"
  coordinator_behavior:
    validated_by: "Jeff (2026-09-07 Deel/DocPlanner/EA session)"
  behavioral_scoring_rules:
    validated_by: "Jeff (2026-09-07 Deel/DocPlanner/EA session)"
```

**Honest labeling distinguishes:**
1. What Jeff actually reviewed and corrected (EB + Champion)
2. What's reasonable domain-knowledge extrapolation (other 5 components)
3. Flag extrapolations for Jeff's review before treating as equally confirmed

---

## Summary: Real State After Bug Fixes

### Data Availability (Honest Numbers)

**Closed deals (after exclusions):** 631 (won + lost)
**MEDDICC analyses (passed quality gate):** 45
**Analyses with usable stage data:** 0

**Why zero:**
- analyses table lacks stage_at_analysis column
- Using deal.stage gives 'Closed Won'/'Closed Lost' for all closed deals
- 315 analyses bucket into closed stages (not discovery/scoping/proposal)
- Cannot correlate component bands at open stages with eventual outcome

### Derivation Status

**Can derive stage-relative expectations?** ❌ No (not yet)

**Why not:**
- NOT a sample size problem (315 analyses is decent)
- NOT just a stage name mapping problem (fixable)
- Fundamental data structure limitation (need stage_at_analysis)

**Re-derivation trigger:**
- Add stage_at_analysis column to analyses table
- OR: Build stage inference from timeline/property history
- Once available, re-run with n≥5 threshold per cell

### Hand-Picked Config Status

**Proceed with hand-picked expectations:** ✅ Yes

**Provenance labeling (honest):**
- Economic Buyer + Champion: Jeff-validated (2026-09-07 session)
- Other 5 components: Domain-knowledge extrapolations (pending Jeff review)
- Champion behavior criteria: Jeff-validated (2026-09-07 session)

**Same discipline as Signal 2/3:**
- Signal 3: 14-day threshold marked HAND_PICKED
- Signal 2 Enterprise: 35-day override marked MANUAL_OVERRIDE
- Stage MEDDICC: EB/Champion marked JEFF-VALIDATED, rest marked EXTRAPOLATED

---

## Implementation Path (After Bug Fixes)

**Approved sequencing:**
1. **Option C (wire query_deal):** Pure plumbing, implement now
2. **Option A (hand-picked expectations):** Add to coaching_client.yaml with honest provenance labels
3. **Review extrapolated components:** Jeff reviews Metrics/Decision Criteria/etc. tables before treating as validated
4. **Monitor:** Deploy A+C, observe LLM consistency
5. **Option D only if needed:** Pursue deterministic bands if LLM shows inconsistent interpretation
6. **Re-derive when data available:** Once stage_at_analysis added, re-run empirical derivation

---

## Key Takeaway

**Same pattern caught multiple times this session:**
- Fabricated "68 cleaned" reconciliation number (Q016)
- Placeholder Signal 2 thresholds presented as derived
- "26 derived, 41.3% coverage" from script with zero usable data

**Same fix applied consistently:**
- Check that reported metric reconciles with underlying evidence
- Label honestly: DERIVED vs. HAND_PICKED vs. EXTRAPOLATED
- Don't fabricate confidence from no data

Bugs fixed before implementation, not discovered in production.
