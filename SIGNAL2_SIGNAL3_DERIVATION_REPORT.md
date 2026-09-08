# Signal 2 & Signal 3 Threshold Derivation Report

## Executive Summary

**Status:** Both Signal 2 and Signal 3 are **DEFERRED** due to insufficient data infrastructure.

**Impact on Q012:** At-risk deal identification cannot use segment-specific thresholds for these signals until data availability improves.

---

## Signal 3: Call Gap (Won vs Lost Separation)

### Status: ⏸️ **DEFERRED**

### Attempted Methodology

Following Signal 2's rigor:
1. Fetch all historical CLOSED deals with call data
2. Calculate gap between consecutive calls (and last call to close_date)
3. Segment by STAGE x SEGMENT (Enterprise/Mid-Market/SMB)
4. Compare won vs lost distributions per cell
5. Set threshold at SEPARATION point between distributions
   - **NOT** just lost median (avoids pandora defect)
   - Use gap between won median and lost 25th percentile
6. Apply min_sample_size >= 5 per cell
7. Fall back to stage-only if insufficient segment-specific sample

### Data Availability

**Closed deals with call data:** 402 of 1,737 (23.1%)

| Outcome | Count | Coverage |
|---------|-------|----------|
| Won deals with calls | 77 | 23.1% of won |
| Lost deals with calls | 325 | 23.1% of lost |

### Critical Methodological Issue

**Problem:** Cannot compare won vs lost within same stage bucket

- Won deals: All in `closed_won` stage bucket (terminal)
- Lost deals: All in `closed_lost` stage bucket (terminal)
- **No overlap** to compute separation between distributions

### Why This Matters

The methodology requires comparing deals at the SAME stage to see:
- "What call gap pattern predicts loss at Discovery stage?"
- "What call gap pattern predicts loss at Technical Evaluation stage?"

But closed deals are no longer in those stages - they're all terminal.

### Revised Approach Options

#### Option 1: Analyze Call Patterns BEFORE Closing ✅ Recommended

Instead of comparing by current stage (terminal), analyze:
1. Maximum gap between calls during entire sales process
2. Average gap between calls during process
3. Last gap before close_date

Compare these aggregate metrics for won vs lost deals.

**Pros:**
- Works with existing data
- Simple, interpretable threshold
- No stage history needed

**Cons:**
- Not stage-specific (but may be acceptable given sample size)
- Global threshold may over-flag SMB, under-flag Enterprise

#### Option 2: Use Active Deals + Historical Outcome

For currently active deals:
1. Compute current call gap
2. Look at historical deals with similar patterns
3. Determine threshold based on historical won/lost rates

**Pros:**
- Stage-specific possible

**Cons:**
- Complex implementation
- Still limited by 23% call coverage

#### Option 3: Stage History Reconstruction

Requires:
1. Accessing stage history (when deal was in each stage)
2. Matching calls to stages at that time
3. Computing gaps per historical stage

**Blockers:**
- `stage_updates` table doesn't exist (see Signal 2 below)
- Heavy computation
- May not be worth it for 23% coverage

### Recommendation

**DEFER Signal 3** until one of these conditions is met:

1. **More call data coverage** (currently 23%, need 50%+)
2. **Revised methodology** (Option 1: global max/avg gap)
3. **Simplified threshold** (hand-picked with explicit "not derived" documentation)

### Files Created

- `scripts/derive_signal3_thresholds.py` - Attempted derivation, found insufficient data
- `signal3_derived_thresholds.json` - Empty result (no thresholds)
- `SIGNAL3_INSUFFICIENT_DATA.md` - Initial documentation
- `SIGNAL2_SIGNAL3_DERIVATION_REPORT.md` - This comprehensive report

---

## Signal 2: Time-in-Stage (Segment-Specific Thresholds)

### Status: ⏸️ **DEFERRED**

### Attempted Methodology

Compute 75th percentile WITHIN each segment's own distribution:

1. For each STAGE x SEGMENT cell, compute 75th percentile of stage duration
2. Use historical WON deals only (success pattern, not failures)
3. Apply min_sample_size per cell (>=5 from Signal 2 config)
4. Fall back to stage-only (drop segment) if insufficient sample

### Rationale for Segment-Specific

- Enterprise deals naturally sit in stages longer than SMB deals
- Global percentile would systematically:
  - Over-flag SMB (their normal duration < global 75th percentile)
  - Under-flag Enterprise (their normal duration > global 75th percentile)

### Data Infrastructure Gap

**Critical blocker:** No stage history table exists

#### Tables Available
- ✅ `deals` table - has current stage, create_date, close_date
- ✅ `calls` table - has call records
- ❌ `stage_updates` table - **DOES NOT EXIST**
- ❌ `stage_history` table - does not exist
- ❌ `deal_stage_history` table - does not exist

#### Fields in Deals Table

Available date fields:
- `create_date` - when deal was created
- `close_date` - when deal closed
- `qualified_date` - when deal was qualified (mostly NULL)
- `updated_at` - Supabase record update timestamp
- `created_at` - Supabase record creation timestamp

**Missing:**
- No `last_activity_date` field
- No `stage_entry_date` field
- No historical stage progression data

### What This Means

**Cannot compute:**
- How long each deal spent in Discovery stage
- How long each deal spent in Technical Evaluation stage
- Duration in any specific historical stage

**Can only compute:**
- Total cycle time (close_date - create_date) ✅ Done in Q016
- Days since deal creation (today - create_date) ✅ Currently used for stale deals

### Current Implementation

The existing "stale deals" handler (api/handlers.py) uses a **proxy approach**:

```python
# Stale deals: deals in same stage longer than threshold
stale_days = params.get("stale_days", 21)  # Default: 21 days
stale_cutoff = (today - timedelta(days=stale_days)).isoformat()

# Filter deals where updated_at < stale_cutoff
# Proxy: updated_at as "last activity in current stage"
```

**Limitations:**
- `updated_at` is Supabase record update, not deal activity
- Not segment-specific (same 21 days for Enterprise and SMB)
- Hand-picked threshold, not derived

### Recommendation

**DEFER Signal 2** until one of these conditions is met:

1. **Stage history table created** - requires HubSpot ETL enhancement to capture stage transitions
2. **Alternative approach** - use global time-in-stage threshold (not segment-specific) with explicit documentation
3. **Proxy refinement** - enhance `updated_at` logic to better represent deal activity

### Comparison to Signal 1

**Signal 1 (MEDDICC scores):** Also DEFERRED
- Reason: Nightly MEDDICC agent writes scores back to HubSpot
- But CRO Slack Agent doesn't yet read those scores
- Integration pending

**Signal 2 (time-in-stage):** DEFERRED
- Reason: No stage history data infrastructure
- Alternative: Use global threshold with documentation

**Signal 3 (call gap):** DEFERRED
- Reason: Insufficient call data coverage (23.1%)
- Alternative: Analyze aggregate call patterns (Option 1)

---

## Impact on Q012 Implementation

### Current Q012 Definition

**Question:** "Which of those are at risk?"

**Definition:** Deals where any MEDDICC component required at the current stage is below the threshold band to advance.

**Current status:** Placeholder logic, marked "until Ryan defines"

### Available Signals for Q012

| Signal | Status | Can Use? | Notes |
|--------|--------|----------|-------|
| **Signal 1:** MEDDICC scores | ⏸️ Deferred | ❌ No | Scores written by nightly agent, not yet read by CRO agent |
| **Signal 2:** Time-in-stage | ⏸️ Deferred | ⚠️ Proxy only | Can use global threshold (21 days default), not segment-specific |
| **Signal 3:** Call gap | ⏸️ Deferred | ❌ No | Only 23% call coverage, methodology issue |
| **Other signals:** Deal value, stage, owner | ✅ Available | ✅ Yes | Full data available in deals table |

### Recommendation for Q012

**Option A: Defer Q012 until Signals 1-3 available** ❌ Not recommended
- Would block Q012 indefinitely
- No timeline for data infrastructure improvements

**Option B: Implement Q012 with available signals only** ✅ Recommended
- Use stage progression logic (stage order, forecast category)
- Use global time-in-stage proxy (21 days default)
- Document explicitly what's missing
- Add TODO for Signal 1/3 integration

**Option C: Simplified Signal 2/3** ⚠️ Compromise
- Signal 2: Use global 21-day threshold with "not segment-specific" note
- Signal 3: Implement Option 1 (global max/avg gap) if needed
- Document as simplified implementation

### Proposed Q012 Implementation

```yaml
q012:
  question: "Which of those are at risk?"
  definition: "Deals showing risk signals based on available data"

  signals_available:
    - stage_progression: "Deals not advancing through pipeline"
    - time_in_stage: "Deals in same stage > 21 days (global threshold)"
    - forecast_category: "Deals in PIPELINE/OMIT vs COMMIT/BEST_CASE"
    - close_date_risk: "Deals past close date or closing within 7 days"

  signals_deferred:
    - meddicc_scores: "Pending CRO agent integration with nightly scores"
    - call_gap: "Insufficient call data coverage (23%), methodology issue"
    - segment_specific_thresholds: "No stage history data, using global thresholds"

  verification_status: "internally_consistent_with_documented_gaps"

  notes: |
    At-risk logic uses available signals only. Signal 1 (MEDDICC) and
    Signal 3 (call gap) deferred due to data limitations. Signal 2
    (time-in-stage) uses global threshold, not segment-specific.

    When data infrastructure improves (stage history, call coverage),
    refine to include deferred signals.
```

---

## Template-Portable Pattern

### Lesson: Data Infrastructure Drives Methodology

**Discovery process:**
1. Define desired methodology (segment-specific, won vs lost separation)
2. Check data availability BEFORE writing code
3. Document gaps explicitly
4. Provide fallback options
5. Don't force derived thresholds when data insufficient

### Explicit Gap Documentation

Following Q016 pattern:
- Don't silently fall back to hand-picked numbers
- Document what's missing and why
- Provide alternatives when data improves
- Mark as "deferred" not "failed"

### Consistent Treatment

**Signal 1, 2, 3 all deferred** - different reasons, same treatment:
- Explicit documentation of gap
- No forcing of numbers without empirical basis
- Can be refined in later waves when data improves

---

## Next Steps

### Immediate (Q012 Implementation)

1. **Implement Q012 with available signals** (stage, time proxy, forecast)
2. **Document deferred signals explicitly** in canonical_questions.yaml
3. **Add TODO markers** for Signal 1/3 integration
4. **Verify internally consistent** (code agrees with itself)

### Wave 6 (Data Infrastructure Improvements)

1. **Stage history capture** - enhance HubSpot ETL to track stage transitions
2. **Call data improvement** - investigate why only 23% coverage
3. **MEDDICC score integration** - connect nightly agent output to CRO agent
4. **Segment-specific refinement** - once stage history available

### Future Enhancements

1. **Signal 3 Option 1** - global max/avg call gap analysis
2. **Alternative time-in-stage proxy** - use deal activities, not just updated_at
3. **Multi-signal scoring** - combine available signals into risk score

---

## Files Created During Investigation

### Signal 3 Derivation
- `scripts/derive_signal3_thresholds.py` (262 lines)
- `signal3_derived_thresholds.json` (empty result)
- `SIGNAL3_INSUFFICIENT_DATA.md` (initial findings)

### Signal 2 Derivation
- `scripts/derive_signal2_segment_specific.py` (311 lines)
- Errored on: `table 'public.stage_updates' not found`

### Documentation
- `SIGNAL2_SIGNAL3_DERIVATION_REPORT.md` (this file)

---

## Sign-Off

**Date:** 2026-09-06

**Investigation:** Wave 4 calibration - Signal 2/3 threshold derivation

**Findings:**
- Signal 2: No stage history infrastructure ⏸️ DEFERRED
- Signal 3: Insufficient call coverage (23%), terminal stage issue ⏸️ DEFERRED

**Recommendation:** Implement Q012 with available signals, document gaps explicitly

**Next:** Proceed with Q012 implementation using stage progression, global time threshold, and forecast category signals.

---

**END OF REPORT**
