# Wave 4 Calibration - Database Direct Query Results

**Date**: 2026-09-05
**Approach**: Query database directly before escalating to client

---

## Summary

**Goal**: Answer 11 canonical questions marked as `null` in config/canonical_questions.yaml

**Results**:
- ✓ 10 of 11 questions answered from database
- ✓ 1 question required query debugging (q016 - fixed)
- ✓ All verified values added to canonical_questions.yaml
- ⚠️ 1 value flagged as "internally consistent" vs independently verified (q012)
- ✓ Ready for calibration run (once API deployed)

**Important Distinction**:
- **Independently verified** (9 questions): Values from direct database facts or client confirmation
- **Internally consistent** (1 question): q012 at-risk count derived from agent's own placeholder logic - validates code agrees with itself, not that definition is correct

---

## Questions Answered Successfully (10)

### q002 - Renewal Pipeline Q3/Q4 ✓

**Question**: "How much expansion ARR is in the renewal pipeline for Q3 and Q4?"

**Verified Value**:
```yaml
q3_renewals:
  count: 33
  base_renewal: $1,082,517
  expansion: $110,000
  total: $1,192,517

q4_renewals:
  count: 21
  base_renewal: $1,534,963
  expansion: $738,755
  total: $2,273,718
```

**Source**: Direct query from `deals` table, filtered by `renewal_revenue > 0` and close date in fiscal quarters

**Notes**: Q3 = Aug-Oct 2026, Q4 = Nov-Jan 2027 (FY2027)

---

### q008 - Customers Due to Renew ✓

**Question**: "Get a list of all customers due to renew in Q3 and then Q4"

**Verified Value**:
```yaml
q3_renewals:
  count: 33
  arr_value: $1,192,517

q4_renewals:
  count: 21
  arr_value: $2,273,718
```

**Source**: Same query as q002

**Notes**: Duplicate of q002 data, just different presentation format

---

### q010 - Recent Closed-Lost Deals ✓

**Question**: "Why did we lose our last three deals?"

**Verified Value**:
```yaml
count: 3
deals:
  - company_name: Creative CX
    close_date: 2026-10-26
    arr: $50,000
    loss_reason: null
  - company_name: Huckberry
    close_date: 2026-09-02
    arr: $0
    loss_reason: null
  - company_name: Hungama
    close_date: 2026-09-02
    arr: $0
    loss_reason: null
```

**Source**: `deals` table filtered to `deal_status = 'lost'`, sorted by `close_date DESC`, limited to 3

**Notes**: Loss reasons not populated in database - field exists but is null

---

### q011 - Active Pipeline Value ✓

**Question**: "What is our pipeline this quarter?"

**Verified Value**:
```yaml
total_arr: $24,985,788
deal_count: 444
quarter: Q3_FY2027
```

**Source**: Sum of `deal_value` from `deals` table where `deal_status = 'active'`

**Notes**: Most commonly asked question - high priority for calibration

---

### q012 - At-Risk Deals ⚠️ INTERNALLY CONSISTENT (Not Independently Verified)

**Question**: "Which of those are at risk?"

**Verified Value**:
```yaml
count: 70
arr_value: null
definition: "Deals where any MEDDICC component required at the current stage is below the threshold band to advance"
verification_type: "internally_consistent"
```

**Source**: `api/handlers.py` function `query_deals_at_risk()` - joins `analyses` table with `deals` table, applies stage-aware MEDDICC threshold checking

**Sample at-risk deals**:
- Comcast: $350K (Pain red, Champion red - needs yellow-or-better to advance from Discovery)
- UPS: $300K (Metrics, Economic Buyer, Champion, Decision Criteria all red - needs yellow-or-better from Scoping)
- Purple: $150K (Pain red, Champion red)

**⚠️ IMPORTANT CAVEAT - Circular Validation**:

This value is **internally consistent** but NOT independently verified. The "70 deals" count comes from the agent's own placeholder at-risk logic, explicitly marked in handlers.py as:

```python
"""
PLACEHOLDER LOGIC until Ryan defines what "at risk" means to him.
"""
```

**Why this matters**:
- **Circular validation**: Calibration will test if agent's answer matches agent's own code - this validates internal consistency, not correctness
- **Not client-confirmed**: Unlike q004 (Christian $0) or q005 (team 12.7%), no client confirmation that "70 deals" is the right answer
- **Weaker verification**: A future divergence alert (Trigger 5) for this metric would only mean the code changed, not that the answer is wrong
- **Different from other verified values**: This is "code agrees with itself" vs "answer matches independent source of truth"

**Use in calibration**: Still useful for testing that the handler is working and hasn't silently drifted, but should NOT be weighted equally with genuinely client-confirmed values when assessing agent accuracy.

---

### q009 - High Champion Score Deals ✓

**Question**: "Which deals have a champion score above 6 and close in Q3?"

**Verified Value**:
```yaml
count: 0
arr_value: $0
```

**Source**: Join `analyses` table with `deals` table, filter `champion_score > 6` and `close_date` in Q3 FY2027

**Notes**: Zero results - no deals with high champion score closing in Q3

---

### q013 - Skyscanner Deal ✓

**Question**: "Show me the Skyscanner deal"

**Verified Value**:
```yaml
exists: true
deal_id: 55660576681
company_name: Skyscanner
stage: Scoping
arr: $125,000
owner: christian@growthbook.io
close_date: 2027-01-31
status: active
```

**Source**: `deals` table filtered by `company_name ILIKE '%skyscanner%'`

**Notes**: Single deal found, active in pipeline

---

### q019 - Forecast Weekly Staleness ✓

**Question**: "When was forecast_weekly last updated?"

**Verified Value**:
```yaml
table: forecast_weekly
last_computed: 2026-09-01 07:00:00
days_stale: 3
expected_refresh_interval: daily
```

**Source**: `SELECT MAX(computed_at) FROM forecast_weekly`

**Notes**: Table was 21 days stale on Sep 2, refreshed Sep 1, now 3 days stale

---

### q020 - Missing Owner Email ✓

**Question**: "How many active deals are missing owner_email?"

**Verified Value**:
```yaml
count: 15
total_active_deals: 444
pct: 3.4%
```

**Source**: `deals` table where `deal_status = 'active'` and `owner_email IS NULL`

**Notes**: Low rate (3.4%) suggests good data quality

---

### q016 - Historical Win Rates & Cycle Times ✓ (Bug Fixed)

**Question**: "Would you be able to calculate historical win rates by stage, sales cycle times, and then apply those learnings to the pipeline for a projected forecast?"

**Verified Value** (CORRECTED):
```yaml
overall_win_rate: 10.4%
overall_median_cycle_days: 159
won_count: 48
closed_count: 461
date_range: "2026-03-05 to 2026-09-05"
```

**Source**: Query `deals` table for ALL deal statuses (active, won, lost) in 6-month window

**Bug Found and Fixed**:
- **Original query** (line 63 of answer_pending_canonical_questions.py):
  ```python
  deals = sb.table('deals').select('*').eq('deal_status', 'active').execute().data
  ```
  Only fetched active deals, so historical win rate calculation had zero won/lost deals → 0% win rate

- **Fixed query** (fix_q016_win_rate.py):
  ```python
  all_deals = sb.table('deals').select('*').execute().data  # ALL statuses
  ```
  Fetches all deals, then filters to won/lost in historical window → 10.4% win rate

**Results**:
- **Overall**: 10.4% win rate (48 won / 461 closed)
- **Median cycle time**: 159 days (range: 5-740 days)
- **Sample size**: 461 closed deals over 6 months

**Validation**: 10.4% win rate is plausible - consistent with q005 showing $197K won in Q3 (12.7% attainment, 2/3 through quarter)

---

## Questions by Verification Type

### Independently Verified (9 questions)
Direct database facts with no ambiguity:
- q002: Renewal pipeline Q3/Q4
- q008: Customers due to renew
- q009: High champion score deals (0 found)
- q010: Recent closed-lost (3 deals)
- q011: Active pipeline value ($25M)
- q013: Skyscanner deal (found, $125K)
- q016: Historical win rates (10.4%, bug fixed)
- q019: forecast_weekly staleness (3 days)
- q020: Missing owner_email (15 deals, 3.4%)

### Internally Consistent (1 question)
Derived from agent's own placeholder logic:
- q012: At-risk deals (70) - validates code agrees with itself, not that definition is correct

**Critical distinction for calibration**:
- **Independently verified** values test agent accuracy against ground truth
- **Internally consistent** values test internal consistency (no silent drift), but are circular validation

---

## At-Risk Definition Deep Dive

Found existing implementation in `api/handlers.py` lines 345-488:

**Function**: `query_deals_at_risk(params, sb)`

**Logic**:
1. Fetch latest MEDDICC analyses for active deals
2. Join with deals table to get stage information
3. For each deal, get stage-specific requirements from `config/client.yaml`
4. Check if any required component's BAND is below threshold
5. Flag deal if ANY component is below required band

**Band-based comparison** (not integer):
- A 5-vs-6 gap is noise (both yellow band)
- Only flag when BAND differs: red vs yellow, yellow vs green
- Gate 6 → needs yellow-or-better
- Gate 7 → needs green-or-better

**Risk flags include**:
- Component name (Pain, Champion, etc.)
- Current band color ("red", "yellow", "green")
- Required band to advance
- Stage name where gap exists

**Status**: PLACEHOLDER marked "PENDING DEFINITION FROM RYAN" but fully functional

**Current result**: 70 active deals flagged as at-risk

---

## Calibration Readiness

### Questions with Verified Values (19 total)

**From Wave 4 Task 1** (already had values):
- q003: Deals with no ARR (127, 28.6%)
- q004: Christian attainment (0%, $0 of $250K)
- q005: Team attainment (12.7%, $197K of $1.55M)
- q006: COMMIT deals (2 deals, $170K)
- q017: GRR Q1 2027 (77%)
- q018: Week-3 conversion (9.9%, deprecated)
- q021: Prospective conversion (7.2%)

**From Wave 4 Task 2** (just populated):
- q002: Renewal pipeline Q3/Q4
- q008: Customers due to renew
- q009: High champion score deals
- q010: Recent closed-lost
- q011: Active pipeline value
- q012: At-risk deals
- q013: Skyscanner deal
- q016: Historical win rates (⚠️ query issue)
- q019: forecast_weekly staleness
- q020: Missing owner_email

**Duplicates**:
- q007: Duplicate of q003 (no ARR deals)

**Out of scope** (not testable):
- q014: MEDDICC definition (rubric question, not data query)
- q015: Multi-deal MEDDICC analysis (requires call analysis)

### Blocked Items

**Cannot run calibration until**:
1. ✗ RAILWAY_API_URL set in .env
2. ✗ CRO Slack agent API deployed and running
3. ✗ /slack/question endpoint accessible

**Once unblocked**:
1. Run: `python scripts/run_calibration.py`
2. Review Correct/Wrong/Unanswerable lists
3. Check fallback rate (<40% threshold)
4. Debug any "wrong" answers
5. Add fast-path handlers for high-fallback questions

---

## Files Modified

1. **config/canonical_questions.yaml**
   - Added verified_value to q002, q008, q009, q010, q011, q012, q013, q016, q019, q020
   - Total questions with verified values: 19 of 21

2. **WAVE_4_STATUS.md**
   - Updated Task 2 status: Complete (10 of 11 answered)
   - Updated Task 3 status: Blocked on API deployment
   - Updated completion criteria tracking

3. **New scripts created**:
   - `answer_pending_canonical_questions.py` - Systematic database querying
   - `get_at_risk_count.py` - At-risk definition extraction

---

## Next Steps

### Immediate
1. Deploy CRO Slack agent to Railway
2. Add RAILWAY_API_URL to .env
3. Test /slack/question endpoint manually
4. Run calibration: `python scripts/run_calibration.py`

### After Calibration
5. Debug q016 query logic (0% win rate issue)
6. Review fallback rate - if >40%, investigate semantic layer
7. Add high-fallback questions to fast-path handlers
8. Implement Trigger 5 (metric_divergence) using verified values
9. Add key metrics to config/metrics.yaml

### Optional
10. Clean up duplicate questions (q007 = q003)
11. Mark out-of-scope questions clearly (q014, q015)
12. Document which questions test semantic layer vs dynamic fallback

---

## Wave 4 Completion Status

- [x] Task 1: Update verified values from debugging session
- [x] Task 2: Get verified values for 11 pending questions (10 of 11)
- [ ] Task 3: Run full calibration (blocked on API deployment)
- [ ] Task 4: Wire Trigger 5 (metric_divergence)

**Overall**: 50% complete (2 of 4 tasks done)
**Blocker**: CRO Slack agent API deployment to Railway
