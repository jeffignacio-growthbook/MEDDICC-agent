# Signal 2 Threshold Derivation: Insufficient Data Infrastructure

## Current Status: **DEFERRED** ⏸️

Matching Signal 1 and Signal 3 treatment - explicit gap documentation rather than forcing a number.

---

## Data Infrastructure Gap

**Critical blocker:** No stage history table exists in the database.

### Tables Checked
- ✅ `deals` - exists (current stage only)
- ✅ `calls` - exists
- ❌ `stage_updates` - **NOT FOUND**
- ❌ `stage_history` - not found
- ❌ `deal_stage_history` - not found
- ❌ `stage_changes` - not found
- ❌ `activities` - not found

### Fields Available in Deals Table

**Date fields:**
- `create_date` - when deal was created
- `close_date` - when deal closed
- `qualified_date` - when deal was qualified (mostly NULL)
- `updated_at` - Supabase record update timestamp (not deal activity)
- `created_at` - Supabase record creation timestamp

**Stage fields:**
- `stage` - current stage name/ID
- `highest_stage_order_reached` - integer (max progression)

**Missing:**
- ❌ No `last_activity_date`
- ❌ No `stage_entry_date`
- ❌ No historical stage transitions
- ❌ No stage duration data

---

## What Cannot Be Computed

Without stage history data:
- ❌ How long each deal spent in Discovery stage
- ❌ How long each deal spent in Technical Evaluation stage
- ❌ Duration in any specific historical stage
- ❌ Stage-by-stage progression analysis
- ❌ 75th percentile per STAGE x SEGMENT cell

---

## Methodology That Cannot Be Applied

**Intended approach (segment-specific):**

1. For each STAGE x SEGMENT cell, compute 75th percentile of stage duration
2. Use historical WON deals only (success pattern)
3. Apply min_sample_size >= 5 per cell
4. Fall back to stage-only if insufficient segment-specific sample

**Why segment-specific matters:**
- Enterprise deals naturally sit in stages longer (larger ACV, more stakeholders)
- SMB deals move faster (smaller ACV, fewer stakeholders)
- Global threshold would systematically over-flag SMB, under-flag Enterprise

**Blocker:** Requires stage_updates or similar table with stage entry/exit timestamps.

---

## Current Proxy Implementation

The existing "stale deals" handler uses a simplified approach:

```python
# From api/handlers.py - query_stale_deals()
stale_days = params.get("stale_days", 21)  # Default: 21 days
stale_cutoff = (today - timedelta(days=stale_days)).isoformat()

# Filters deals where updated_at < stale_cutoff
# Proxy: Supabase updated_at as "last activity in current stage"
```

**Limitations:**
1. `updated_at` is Supabase record update, not deal activity date
2. Not segment-specific (same 21 days for Enterprise and SMB)
3. Hand-picked threshold (21 days), not derived from won/lost distributions
4. Not stage-specific (same threshold for all stages)

---

## Alternative Approaches

### Option 1: Use Total Cycle Time Instead ✅ Done in Q016

**What:** Compute total deal lifecycle (close_date - create_date)

**Status:** Already computed in Q016 (52 days median for new business)

**Pros:**
- Data available
- Verified and signed off

**Cons:**
- Doesn't tell you if deal is stuck in CURRENT stage
- Only useful for closed deals, not active pipeline

### Option 2: Global Time-in-Stage Proxy ⚠️ Current Implementation

**What:** Use updated_at as proxy for stage entry

**Status:** Currently implemented with 21-day default

**Pros:**
- Simple, works with existing data
- Better than nothing

**Cons:**
- Not segment-specific
- updated_at may not reflect actual deal activity
- Hand-picked threshold

### Option 3: Enhanced HubSpot ETL ✅ Recommended for Wave 6

**What:** Capture stage_update events from HubSpot

**Requirements:**
1. Modify ETL to query HubSpot deal property history
2. Create stage_updates table with (deal_id, old_stage, new_stage, updated_at)
3. Backfill historical data where available
4. Run derive_signal2_segment_specific.py with real data

**Pros:**
- Enables proper segment-specific thresholds
- Enables won vs lost duration comparison
- Template-portable for all clients

**Cons:**
- Requires ETL enhancement
- HubSpot API rate limits may slow backfill

---

## Comparison to Other Signals

| Signal | Status | Reason | Alternative |
|--------|--------|--------|-------------|
| **Signal 1** | ⏸️ Deferred | Nightly agent writes scores, CRO agent doesn't read them yet | Integration pending |
| **Signal 2** | ⏸️ Deferred | No stage history data | Global 21-day proxy |
| **Signal 3** | ⏸️ Deferred | 23% call coverage, terminal stage issue | Aggregate call pattern analysis |

All three signals deferred for different reasons - consistent treatment with explicit gap documentation.

---

## Recommendation

**DEFER Signal 2 segment-specific thresholds** until one of these conditions is met:

1. **Stage history table created** - via enhanced HubSpot ETL (recommended)
2. **Alternative proxy improved** - better than updated_at for activity tracking
3. **Simplified global threshold documented** - use 21 days with explicit "not segment-specific" note

**For Q012 implementation:**
- Use available signals (stage progression, forecast category, close date risk)
- Document Signal 2 as deferred with global proxy fallback
- Add TODO for segment-specific refinement in Wave 6

---

## Files Created

- `scripts/derive_signal2_segment_specific.py` - Attempted derivation, found no stage_updates table
- `SIGNAL2_INSUFFICIENT_DATA.md` - This documentation
- `SIGNAL2_SIGNAL3_DERIVATION_REPORT.md` - Comprehensive analysis of both signals

---

## Next Steps (If Proceeding with Q012)

If must implement at-risk logic despite insufficient Signal 2 data:

1. **Use global time-in-stage proxy** (21 days default from handlers.py)
2. **Document explicitly:** "Not segment-specific due to lack of stage history"
3. **Mark for refinement:** Wave 6 with proper stage_updates table
4. **Verify internally consistent:** Code agrees with its own logic

**But preferred:** DEFER segment-specific implementation until Wave 6 with proper data infrastructure.

---

## Sign-Off

**Date:** 2026-09-06

**Investigation:** Wave 4 calibration - Signal 2 threshold derivation

**Finding:** No stage history infrastructure available

**Status:** ⏸️ DEFERRED pending stage_updates table creation

**See also:** `SIGNAL2_SIGNAL3_DERIVATION_REPORT.md` for comprehensive analysis

---

**END OF DOCUMENTATION**
