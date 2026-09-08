# Signal 3 Threshold Derivation: Insufficient Data

## Current Status: **DEFERRED** ⏸️

Matching Signal 1 treatment - explicit gap documentation rather than forcing a number.

---

## Data Availability

**Closed deals with call data:** 402 of 1,737 (23.1%)

### By Outcome
- **Won deals with calls:** 77 deals
- **Lost deals with calls:** 325 deals

### Coverage Issue

**Problem:** Sample size too small after stage x segment splits

**Cells examined:** 7 stage x segment cells
**Cells with sufficient data:** 0

---

## Methodological Issue

**Cannot compare won vs lost within same stage bucket:**
- Won deals: All in `closed_won` bucket (terminal stage)
- Lost deals: All in `closed_lost` bucket (terminal stage)

**No overlap** to compute separation between distributions.

---

## Revised Approach Needed

### Option 1: Analyze Call Patterns BEFORE Closing

Instead of comparing by current stage (terminal), analyze:
1. Maximum gap between calls during sales process
2. Average gap between calls
3. Last gap before close_date

Compare these metrics for won vs lost deals.

### Option 2: Use Active Deals + Historical Outcome

For currently active deals:
1. Compute current call gap
2. Look at historical deals with similar patterns
3. Determine threshold based on historical won/lost rates

### Option 3: Stage History Reconstruction

Requires:
1. Accessing stage history (when deal was in each stage)
2. Matching calls to stages at that time
3. Computing gaps per historical stage
4. Heavy computation, may not be worth it for 23% coverage

---

## Recommendation

**DEFER Signal 3** until one of these conditions is met:

1. **More call data coverage** (currently 23%, need 50%+)
2. **Revised methodology** (Option 1 or 2 above)
3. **Simplified threshold** (hand-picked with explicit "not derived" documentation)

Consistent with Signal 1 treatment:
- Documented gap explicitly
- Not forcing a number without empirical basis
- Can be refined in Wave 6 with more data

---

## Comparison to Signal 2

**Signal 2 (time-in-stage):** Successfully derived
- Stage history available via `stage_updates` table
- Can compute stage durations for won vs lost
- Sufficient sample sizes per stage x segment

**Signal 3 (call gap):** Cannot derive yet
- Call data sparse (23% coverage)
- Stage at time of call not easily determined
- Terminal stages don't provide comparison basis

---

## Next Steps (If Proceeding)

If must implement Signal 3 despite insufficient data:

1. **Use simplified metric:** Maximum call gap (not stage-specific)
2. **Compute global threshold:** Won vs lost across all stages
3. **Document explicitly:** "Not segment-specific due to sample size"
4. **Flag for refinement:** Wave 6 with more data

**But preferred:** DEFER until Wave 6 with proper methodology.

---

## Files Created

- `scripts/derive_signal3_thresholds.py` - Attempted derivation, found insufficient data
- `signal3_derived_thresholds.json` - Empty result (no thresholds)
- `SIGNAL3_INSUFFICIENT_DATA.md` - This documentation
- `SIGNAL2_SIGNAL3_DERIVATION_REPORT.md` - Comprehensive analysis of both Signal 2 and Signal 3

**Status:** ⏸️ DEFERRED pending more call data or revised methodology

**See also:** `SIGNAL2_SIGNAL3_DERIVATION_REPORT.md` for complete analysis including impact on Q012
