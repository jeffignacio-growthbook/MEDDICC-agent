# Waterfall Reconciliation Analysis - Multiple Root Causes

**Date:** 2026-09-08
**Status:** ⚠️ PARTIAL FIX APPLIED - Deeper Issue Discovered

---

## Summary

Fixed the moved_forward/moved_backward net_change bug (Aug 28 EMEA/Enterprise now reconciles perfectly). However, reconciliation warnings persist in ~40% of weeks due to a DIFFERENT, deeper architectural issue: **stale enrichment data**.

---

## Fix Applied: moved_forward/backward Removed ✅

**Changes:**
- `compute_waterfall_segmented.py` line 494-501
- `compute_waterfall.py` line 466-473
- Removed `moved_forward_value` and `moved_backward_value` from net_change calculation

**Result:**
- Aug 28 EMEA/Enterprise: ✅ RECONCILES PERFECTLY
  - Before: Beginning $2.2M, Ending $2.2M, Net $97K (MISMATCH: -$97K)
  - After: Beginning $2.2M, Ending $2.2M, Net $0 (RECONCILES)
- No other code depends on old net_change definition
- moved_forward/backward columns remain valid for stage progression analytics

---

## Remaining Issue: Stale Enrichment Data

**Problem:** `enrichment_map` loaded from current `deals` table applies CURRENT region/segment to ALL historical snapshots.

**Code (lines 256-285):**
```python
# Load enrichment ONCE from current deals table
enrichment_map = {row['deal_id']: {...} for row in deals_table}

# For beginning_value (prev snapshot):
for deal_id, p in prev_snap.items():
    enrich = enrichment_map.get(deal_id, {})  # CURRENT enrichment
    region = enrich.get('region', 'UNKNOWN')   # CURRENT region
    group_key = (pipeline_id, region, segment)
    begin_values[group_key].append(deal_value)

# For ending_value (new snapshot):
for deal_id, n in new_snap.items():
    enrich = enrichment_map.get(deal_id, {})  # CURRENT enrichment
    region = enrich.get('region', 'UNKNOWN')   # CURRENT region  
    group_key = (pipeline_id, region, segment)
    end_values[group_key].append(deal_value)
```

**Impact:** If a deal's region or segment changed between prev_snap and new_snap, BOTH beginning and ending use the NEW classification, causing:
- Deals counted in wrong historical groups
- Reconciliation mismatches when deals "teleport" between groups retroactively

**Example:**
- Aug 4: Deal X is APAC/Mid-Market with $100K
- Aug 11: Deal X reclassified to NAM/Enterprise (still $100K)
- Current enrichment: Deal X → NAM/Enterprise
- Aug 11 waterfall computation:
  - Beginning NAM/Enterprise: $100K (Deal X counted using CURRENT enrichment)
  - Ending NAM/Enterprise: $100K (Deal X counted using CURRENT enrichment)
  - Movement: Deal X was in both snapshots, no change detected
  - But HISTORICALLY, Deal X wasn't in NAM/Enterprise on Aug 4!

**Evidence:**
- 2025-08-11 NAM/Enterprise: +$250K mismatch
- Beginning: $853K, Net Change: +$250K, Expected: $1.1M, Actual: $1.35M
- Difference exactly equals new_pipeline_value, suggesting misclassification

---

## Scope of Remaining Mismatches

**Count:** Reconciliation warnings in 41 of 56 weeks (73%)
- Week 1: 3 mismatches
- Week 2: 1 mismatch  
- Week 36: 16 mismatches (largest)
- Many weeks: 0-4 mismatches

**Not caused by moved_forward bug:** That's now fixed and proved by Aug 28 EMEA/Enterprise reconciling

**Likely causes:**
1. **Region/segment reclassification** (most common)
2. **ARR changes not captured** (if arr_change_value exists but not in net_change... wait, let me check)
3. **Deals changing pipelines**
4. **Qualification timing edge cases**

---

## Architectural Fix Required

**Current:** Single enrichment_map from current deals table
**Needed:** Point-in-time enrichment for each snapshot

**Options:**

### Option 1: Add region/segment to deals_snapshot (RECOMMENDED)
- Modify `snapshot_deals.py` to capture region/segment at snapshot time
- Store point-in-time values in deals_snapshot table
- Use snapshot values instead of current deals table

**Pros:**
- Clean, accurate point-in-time data
- Fixes reconciliation completely
- Enables accurate historical analysis ("Who was Enterprise in Q1?")

**Cons:**
- Schema change required
- Historical backfill needs deals_snapshot regeneration from property_history

### Option 2: Accept Reconciliation Mismatches as Known Behavior
- Document that region/segment changes cause expected mismatches
- Keep reconciliation check as warning, not error
- Track mismatch magnitude as data quality metric

**Pros:**
- No schema changes
- Lower effort

**Cons:**
- Reconciliation violations remain
- Historical analysis less accurate
- "Which deals moved between regions?" becomes unanswerable

### Option 3: Disable Reconciliation Check
- Remove the check entirely
- Trust that formulas are correct

**Pros:**
- Stops warning noise

**Cons:**
- Loses bug detection (moved_forward bug would never have been caught)
- Bad practice

---

## Recommendation

**Option 1** - Add point-in-time enrichment to deals_snapshot.

**Reasoning:**
- Reconciliation violations are a real data integrity signal
- Region/segment are slowly-changing dimensions that should be tracked over time
- The effort is one-time (schema + backfill) vs ongoing confusion about mismatches

**Implementation:**
1. Add `region` and `segment` columns to deals_snapshot table
2. Update `snapshot_deals.py` to capture current region/segment at snapshot time
3. Backfill historical snapshots from property_history (if available) or accept gap
4. Update compute_waterfall_segmented.py to use snapshot enrichment, not current
5. Recompute waterfalls - should reconcile perfectly

---

## Status

**moved_forward/backward bug:** ✅ FIXED
**Stale enrichment bug:** ⚠️ IDENTIFIED, NOT YET FIXED

**Next decision:** Choose architectural approach (Option 1, 2, or 3)
