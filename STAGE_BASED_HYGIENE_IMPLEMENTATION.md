# Stage-Based Hygiene Rules Implementation

## Date
September 6, 2026

## Context
Updated query_pipeline handler to apply stage-based hygiene rules for flagging data quality issues, replacing the previous broad "all deals with $0 incremental ARR" approach.

## Stage-Based Rules

### Rule 1: Meeting Set (Expected $0)
**Stage**: Meeting Set
**Rule**: $0 incremental ARR is EXPECTED at this early qualification stage
**Action**: Do NOT flag as hygiene issue
**Rationale**: Deals are too early to size - reps create the deal record at meeting set, then add ARR values as they progress through discovery/scoping

### Rule 2: Renewal Stages (Check Renewal Base)
**Stages**: Upcoming Renewal, Renewal Engaged
**Rule**: Check `renewal_revenue`, NOT `incremental_arr`
**Action**: Flag if `renewal_revenue` = 0 or NULL
**Rationale**: At renewal stages, we expect the renewal base to be recorded. Having $0 expansion/new ARR is NORMAL (pure renewal), but $0 renewal_revenue is a data quality gap

### Rule 3: All Other Stages (Check Incremental ARR)
**Stages**: Discovery, Scoping, Technical Evaluation, Negotiating, Review, Awaiting Signature, etc.
**Rule**: Check `incremental_arr` (expansion_arr + new_arr)
**Action**: Flag if `incremental_arr` = 0
**Rationale**: Past Meeting Set, deals should have ARR values populated. $0 incremental ARR means data quality gap or stale placeholder

## Implementation

### Code Changes

**File**: `/Users/jeffignacio/MEDDICC-agent/api/handlers.py`
**Function**: `query_pipeline` (lines ~2000-2020)

**Updated logic**:
```python
if is_incremental_pipeline(deal):
    deal["_incremental_value"] = incremental_value
    incremental_deals.append(deal)

    # Stage-based hygiene rules
    stage = stage_label(deal.get("stage"))

    if stage == "Meeting Set":
        # Expected at this stage, don't flag
        pass
    elif stage in ["Upcoming Renewal", "Renewal Engaged"]:
        # For renewal stages, check renewal_revenue instead of incremental ARR
        if renewal_revenue == 0:
            zero_arr_deals.append(deal)
    else:
        # All other stages: $0 incremental ARR is a hygiene issue
        if incremental_value == 0:
            zero_arr_deals.append(deal)
```

### Verification Results

**Script**: `/Users/jeffignacio/MEDDICC-agent/scripts/verify_stage_based_hygiene.py`

#### Scope 1: Company-Wide (ALL Active Deals)
- Flagged deals: **70 hygiene issues**
  - Renewal stages ($0 renewal_revenue): 40 deals
  - Other stages ($0 incremental ARR): 30 deals
- Meeting Set excluded: 96 deals
- Valid renewal stages (renewal_revenue > 0): 108 deals

#### Scope 2: Incremental Pipeline Only (query_pipeline handler)
- Flagged deals: **31 hygiene issues**
  - Renewal stages ($0 renewal_revenue): 2 deals
    - Neon: $30K expansion_arr, $0 new_arr, renewal_revenue = NULL
    - Funding Pips: $0 expansion_arr, $60K new_arr, renewal_revenue = $0
  - Other stages ($0 incremental ARR): 29 deals
    - Discovery: 21 deals
    - Scoping: 4 deals
    - Review: 2 deals
    - Technical Evaluation: 1 deal
    - Empty stage: 1 deal
- Meeting Set excluded: 96 deals
- Valid renewal stages (renewal_revenue > 0): 9 deals

### Canonical Value Update

**File**: `/Users/jeffignacio/MEDDICC-agent/config/canonical_questions.yaml`
**Question ID**: q011

**Updated verified_value**:
```yaml
zero_arr_deals: 31  # Within incremental pipeline scope
zero_arr_deals_company_wide: 70  # Across all active deals
```

## Interpretation

### For query_pipeline Handler
The handler shows **incremental pipeline only**, so it should flag **31 hygiene issues** (Scope 2).

This is the correct count for the handler's scope:
- 2 renewal stage deals in incremental pipeline with $0 renewal_revenue
- 29 other stage deals in incremental pipeline with $0 incremental ARR
- Total: 31 deals requiring data quality cleanup

### Company-Wide Context
The company-wide count (70 hygiene issues) includes:
- 40 renewal stage deals (both in incremental and renewal base pipelines) with $0 renewal_revenue
- 30 other stage deals with $0 incremental ARR

This is informational context but out of scope for query_pipeline handler.

## User-Facing Response Framing

When presenting hygiene issues in Slack, the synthesis should:

1. **Frame as hygiene issues, not "zero ARR deals"**:
   - ✅ "31 hygiene issues requiring cleanup"
   - ❌ "126 deals with $0 ARR"

2. **Explain stage-based logic briefly**:
   - "Meeting Set excluded (expected $0 at this stage)"
   - "Renewal stages: 2 deals missing renewal_revenue"
   - "Other stages: 29 deals missing incremental ARR"

3. **Offer proactive follow-up**:
   - "Want the full list of deals needing cleanup?"
   - "I can show which reps own these hygiene issues"

## Next Steps

1. ✅ Update query_pipeline handler logic (DONE)
2. ✅ Update canonical_questions.yaml (DONE)
3. ✅ Create verification script (DONE)
4. ⏳ Slack validation (5-10 test queries)
5. ⏳ Proceed to remaining Wave 4 calibration questions

## Related Files

- `/Users/jeffignacio/MEDDICC-agent/api/handlers.py` - Handler implementation
- `/Users/jeffignacio/MEDDICC-agent/config/canonical_questions.yaml` - Canonical values
- `/Users/jeffignacio/MEDDICC-agent/scripts/verify_stage_based_hygiene.py` - Verification script
- `/Users/jeffignacio/MEDDICC-agent/scripts/analyze_zero_arr_deals.py` - Original analysis (126 deals)
- `/Users/jeffignacio/MEDDICC-agent/scripts/verify_zero_arr_age_activity.py` - Age/activity analysis
- `/Users/jeffignacio/MEDDICC-agent/scripts/verify_activity_baseline.py` - Baseline verification (invalidated "no activity" claim)
- `/Users/jeffignacio/MEDDICC-agent/zero_arr_deals_analysis.csv` - Full deal list (126 deals in incremental pipeline with $0 incremental ARR)

---

**Implementation complete**: September 6, 2026
**Ready for Slack validation**: Yes
**Expected behavior**: Query "What is our pipeline this quarter?" should show 31 hygiene issues using stage-based rules
