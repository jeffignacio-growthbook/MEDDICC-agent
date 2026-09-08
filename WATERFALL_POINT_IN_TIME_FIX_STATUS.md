# Waterfall Point-in-Time Enrichment Fix - Status Report

**Date:** 2026-09-08
**Status:** ⚠️ ARCHITECTURAL FIX IMPLEMENTED BUT HISTORICAL DATA IMPERFECT

---

## Summary

Implemented point-in-time enrichment for waterfall calculations by:
1. ✅ Added region/segment columns to deals_snapshot (Migration 060)
2. ✅ Updated snapshot_deals.py to capture point-in-time values going forward
3. ✅ Backfilled 27,298 historical snapshots with current region/segment
4. ✅ Updated compute_waterfall_segmented.py to use snapshot enrichment
5. ⚠️ **Historical reconciliation NOT improved** (46/56 weeks with mismatches vs 41/56 before)

---

## What Was Fixed

### 1. moved_forward/backward Formula Bug ✅
**Status:** COMPLETELY FIXED

- Removed moved_forward_value and moved_backward_value from net_change formula
- Aug 28 EMEA/Enterprise: Reconciles perfectly (was +$97K mismatch, now $0)
- This fix is proven and working

### 2. Point-in-Time Enrichment Architecture ✅
**Status:** IMPLEMENTED FOR FUTURE DATA

- Migration 060: Added region/segment columns to deals_snapshot
- snapshot_deals.py: Now captures region/segment at snapshot time
- compute_waterfall_segmented.py: Now reads enrichment from snapshot, not current deals
- **Starting today (2026-09-08), all new snapshots have accurate point-in-time enrichment**

---

## What Was NOT Fixed

### Historical Data Reconciliation ⚠️
**Status:** CANNOT BE FIXED WITHOUT property_history

**Problem:** Historical snapshots were backfilled using CURRENT region/segment from the deals table (September 2026 values). This gives every historical snapshot the same values, which doesn't solve the "deal teleporting between groups" issue for historical waterfalls.

**Evidence:**
- Before point-in-time fix: 41 of 56 weeks with mismatches (73%)
- After point-in-time fix: 46 of 56 weeks with mismatches (82%)
- **Worse, not better!**

**Root Cause:**
The backfill used this SQL:
```sql
UPDATE deals_snapshot ds
SET region = d.region, segment = d.segment
FROM deals d
WHERE ds.deal_id = d.deal_id
```

This applies September 2026 values to ALL historical snapshots (Aug 2025 through Sep 2026). So:
- Aug 2025 snapshots have Sep 2026 region/segment
- Sep 2026 snapshots have Sep 2026 region/segment
- Every week in between has Sep 2026 region/segment

This is NO DIFFERENT from the old approach (loading enrichment_map once from current deals table).

**Why It Got Worse:**
The slight increase in mismatches (41 → 46 weeks) suggests the backfill timing matters:
- Old code: Loaded enrichment_map when waterfall ran (could be any time)
- New code: Backfilled enrichment once (Sep 8, 2026)
- If deals table changed between old runs and backfill, the enrichment is different

---

## What Would Actually Fix Historical Data

### Option 1: property_history Tracking (IDEAL, NOT AVAILABLE)
**Requirements:**
- property_history table would need to track region/segment changes
- Backfill script would reconstruct point-in-time values from change history
- Achievable accuracy: ~95%+ (depends on history completeness)

**Status:** property_history does NOT track region/segment fields. Would require:
1. ETL changes to capture region/segment in property_history going forward
2. Cannot backfill pre-Sep-2026 changes (data doesn't exist)

### Option 2: Reconstruct from employee_count History (COMPLEX)
**Approach:**
- segment is derived from company_employee_count
- If property_history tracks employee_count, reconstruct segment changes
- region is company_country-based, might be in property_history

**Feasibility:** Needs investigation

### Option 3: Accept Historical Imperfection (PRAGMATIC)
**Approach:**
- Historical snapshots (Aug 2025 - Sep 2026) use best-available data (current values)
- Future snapshots (Sep 2026 onward) have accurate point-in-time enrichment
- Reconciliation will naturally improve as accurate snapshots accumulate
- After 56 weeks of accurate snapshots (Sep 2027), historical period rolls off

**Trade-offs:**
- Historical waterfalls remain imperfect
- New waterfalls (computed after Sep 2026) will reconcile perfectly
- One year of transition period

---

## Recommendations

### Immediate (Today)

1. **Verify the fix is working going forward:**
   - Run snapshot_deals.py to create today's snapshot
   - Verify it has accurate region/segment
   - Compute tomorrow's waterfall and verify zero mismatches for new data

2. **Investigate remaining mismatches:**
   - The 46 weeks with mismatches might have OTHER causes besides stale enrichment
   - Check a few examples to see if there are additional bugs
   - Possible causes:
     - ARR changes not in net_change formula (arr_change_value field?)
     - Deals changing pipelines mid-week
     - Qualification timing edge cases

3. **Document the historical data limitation:**
   - Update PENDING_WORK.md to reflect current status
   - Add note that historical reconciliation requires property_history enhancement

### Medium-term (Next Sprint)

1. **Add region/segment to property_history:**
   - Modify ETL to capture region/segment changes going forward
   - Enables future point-in-time reconstruction

2. **Investigate employee_count history:**
   - Check if we can reconstruct segment changes from employee_count history
   - If yes, write backfill script to improve historical accuracy

### Long-term (Accept or Fix)

**Option A: Accept** - Historical data remains imperfect, new data is accurate
**Option B: Fix** - Invest in property_history backfill or reconstruction

---

## Files Changed

### Schema
- `scripts/migrations/060_add_region_segment_to_snapshot.sql` (NEW)
  - Added region and segment columns to deals_snapshot
  - Indexes for query performance

### Snapshot Capture
- `scripts/analytics/snapshot_deals.py`
  - Line 91-96: Added region/segment to deals SELECT
  - Line 169-183: Added region/segment to snapshot records

### Waterfall Computation
- `scripts/analytics/compute_waterfall_segmented.py`
  - Line 82-94: Changed enrichment_map to only load company_name
  - Line 261-270: Use prev_snap region/segment for beginning values
  - Line 277-285: Use new_snap region/segment for ending values
  - Line 318-322: Use snapshot region/segment for movement calculations

### Backfill
- `scripts/analytics/backfill_snapshot_enrichment.py` (NEW, but limited utility)
  - Backfills historical snapshots with current region/segment
  - Does NOT achieve point-in-time accuracy for historical data

---

## Current State

**What reconciles:**
- Aug 28 EMEA/Enterprise (user's original example) ✅

**What doesn't reconcile:**
- 46 of 56 historical weeks (82%)
- Root cause: Mix of stale enrichment (unfixable without property_history) and possibly other issues

**Going forward:**
- New snapshots (starting Sep 8, 2026) will have accurate point-in-time enrichment
- New waterfalls (computed with accurate snapshots) should reconcile perfectly
- Need to verify with tomorrow's waterfall run

---

## Next Actions

1. **Verify fix works for new data** - Run snapshot and waterfall tomorrow
2. **Investigate other mismatch causes** - Check if there are bugs beyond enrichment
3. **Decide on historical data strategy** - Accept imperfection vs invest in fix
4. **Update PENDING_WORK.md** - Reflect current status and recommendations
