# Wave 4 Calibration - Verification Fixes

**Date**: 2026-09-05
**Issue**: Two verification concerns raised before treating data as "ground truth"

---

## Issue 1: q016 Returned 0% Win Rate (Known-Broken Query) ✓ FIXED

### Problem Identified

**Original query returned**:
```yaml
overall_win_rate: 0.0%
sample_size: 0
data_quality_flag: "Zero won deals in 6mo window suggests query issue"
```

**Why this is dangerous**:
- 0% win rate is implausible on its face (GrowthBook has closed deals per earlier session)
- If left as "verified value", calibration would:
  - ✗ Pass a genuinely wrong agent answer that also returns 0%
  - ✗ Fail a correct agent answer that returns the real rate
- A verified-but-wrong value poisons calibration by creating false ground truth

### Root Cause

**Line 63 of answer_pending_canonical_questions.py**:
```python
deals = sb.table('deals').select('*').eq('deal_status', 'active').execute().data
```

Only fetched active deals. When q016 tried to calculate historical win rate by filtering for won/lost deals from this list, it found zero because all deals in the list were 'active'.

### Fix Applied

**Created fix_q016_win_rate.py**:
```python
all_deals = sb.table('deals').select('*').execute().data  # ALL statuses, not just active
historical_deals = [
    d for d in all_deals
    if d.get('close_date')
    and d['close_date'] >= six_months_ago.isoformat()
    and d.get('deal_status') in ['won', 'lost']
]
```

### Corrected Results ✓

```yaml
overall_win_rate: 10.4%
overall_median_cycle_days: 159
won_count: 48
closed_count: 461
date_range: "2026-03-05 to 2026-09-05"
```

**Validation**: 10.4% win rate is plausible:
- Consistent with q005 showing $197K won in Q3 (12.7% attainment, 2/3 through quarter)
- 48 won deals over 6 months = ~8 wins/month
- Median cycle time 159 days (~5 months) is reasonable for enterprise B2B

### Updated canonical_questions.yaml ✓

Replaced 0% with 10.4%, documented bug fix in notes field.

---

## Issue 2: q012 At-Risk Definition is Circular Validation ✓ FLAGGED

### Problem Identified

**q012 verified_value**:
```yaml
count: 70
definition: "Deals where any MEDDICC component required at the current stage
             is below the threshold band to advance"
```

**Why this is problematic**:
- Definition comes from agent's own placeholder logic (`api/handlers.py` line 345)
- Handler explicitly marked: `"PLACEHOLDER LOGIC until Ryan defines what 'at risk' means"`
- Calibration would test if agent's answer matches agent's own code
- This is **circular validation**: "A canonical set validated against the agent's own output agrees with itself by construction" (Wave 4 spec warning)

**Not the same as q004, q005**:
- q004 (Christian $0): Client-confirmed via direct query, matches reporting
- q005 (Team 12.7%): Client-confirmed via direct query, going to Ryan
- q012 (At-risk 70): Derived from agent's own placeholder code, no client confirmation

### Why This Matters for Calibration

**Independently verified values** (q004, q005):
- Test agent accuracy against ground truth
- Divergence = agent is wrong, needs fixing

**Internally consistent values** (q012):
- Test that code hasn't silently drifted
- Divergence = code changed, not necessarily wrong
- Useful but weaker form of verification

**If treated equally in calibration**:
- False sense of accuracy (passing circular validation ≠ correct answers)
- Trigger 5 (metric divergence) would fire for code changes, not real problems
- Can't distinguish "agent is wrong" from "definition changed"

### Fix Applied ✓

**Updated canonical_questions.yaml**:
```yaml
verified_value:
  count: 70
  verification_type: "internally_consistent"  # NEW FIELD
  note: "INTERNALLY CONSISTENT (not independently verified):
         70 active deals flagged by agent's own placeholder at-risk logic.
         Calibration validates code agrees with itself, not that definition
         matches client intent. If this diverges in production, only means
         code changed, not that answer is wrong."
```

**Added explicit distinction**:
- Field `verification_type: "internally_consistent"` distinguishes from independently verified values
- Note explains this is circular validation, not ground truth
- Future Trigger 5 alerts for this metric should be weighted differently

### Recommendation for Calibration Report

When reporting calibration results, **separate by verification type**:

**Independently Verified (9 questions)**:
- q002, q008, q009, q010, q011, q013, q016, q019, q020
- These test agent accuracy against ground truth
- Target: 100% correct (any "wrong" = real bug)

**Internally Consistent (1 question)**:
- q012
- Tests code hasn't drifted
- Target: Stable (divergence = code change, investigate but not necessarily wrong)

---

## Files Updated

### canonical_questions.yaml ✓
- **q016**: Replaced 0% with 10.4%, documented bug fix
- **q012**: Added `verification_type: "internally_consistent"`, updated note with caveat

### WAVE_4_STATUS.md ✓
- Separated "Independently Verified" (9) from "Internally Consistent" (1)
- Documented q016 bug fix
- Added caveat section for q012

### WAVE_4_DATABASE_QUERY_RESULTS.md ✓
- Updated summary with verification type distinction
- Expanded q012 section with circular validation explanation
- Expanded q016 section with bug fix details
- Added "Questions by Verification Type" section

### New Files Created
- **fix_q016_win_rate.py**: Corrected query that fetches all deal statuses
- **WAVE_4_VERIFICATION_FIXES.md**: This document

---

## Calibration Readiness Status

### Before Fixes
- ✗ 1 known-broken query (q016: 0% win rate)
- ✗ 1 circular validation treated as ground truth (q012: at-risk)
- ✗ Risk of false positives/negatives in calibration

### After Fixes ✓
- ✓ All queries return plausible values
- ✓ Circular validation explicitly flagged
- ✓ Verification types distinguished for proper interpretation
- ✓ Ready for honest calibration run

---

## Next Steps

1. **Deploy CRO Slack agent** to Railway
2. **Add RAILWAY_API_URL** to .env
3. **Run calibration**: `python scripts/run_calibration.py`
4. **Report results separately**:
   - Independently verified questions: Expect 100% correct
   - Internally consistent question (q012): Expect stable (code hasn't drifted)
5. **Investigate any "wrong" answers** in independently verified set
6. **Check fallback rate** (<40% threshold)
7. **Wire Trigger 5** (metric_divergence) with proper handling of verification types

---

## Key Takeaway

**An unverified question is honest; a verified-wrong one poisons calibration.**

By fixing q016 and flagging q012, we now have:
- **9 independently verified values**: Test agent accuracy against ground truth
- **1 internally consistent value**: Test code stability (useful but weaker)
- **Clear distinction**: Different verification types warrant different treatment in calibration and alerting

This honest accounting prevents:
- False confidence from passing circular validation
- Wasted time debugging "divergences" that are just code changes
- Treating placeholder logic as authoritative client requirements
