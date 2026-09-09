# Waterfall arr_delta Integration - Complete Results

**Date:** 2026-09-08
**Status:** ✅ COMPLETE - 99.8% reconciliation achieved

---

## Executive Summary

Integrated `arr_delta` function into waterfall computation and fixed 5 distinct bugs discovered during investigation. Achieved 99.8% reconciliation (952 of 954 group/week combinations). The 2 remaining mismatches (0.2%) are caused by a separate snapshot ETL bug, not waterfall logic issues.

---

## Bugs Fixed

### 1. Won/Lost Detection Defaulting to 'Active'
**Issue:** Deals closing won/lost were not detected, silently defaulting to 'active' status
**Fix:** Implemented hybrid detection using property_history first, close_date + stage fallback
**Impact:** $830K+ of won/lost deals now properly detected

### 2. Net_change Formula Double-Counting
**Issue:** moved_forward/moved_backward included in net_change despite not affecting pipeline value
**Fix:** Removed from net_change formula (they're timing movements, not value changes)
**Impact:** Multiple reconciliation failures resolved

### 3. Point-in-Time Enrichment Missing
**Issue:** Region/segment values were current (Sep 2026), not historical snapshot values
**Fix:** Added region/segment to deals_snapshot, backfilled 27,298 snapshots to 85-95% enrichment
**Impact:** Eliminated boundary crossing mismatches

### 4. Precedence Masking Bug
**Issue:** Movements treated as mutually exclusive (if won, don't check ARR change)
**Fix:** Removed precedence system, all movements tracked independently
**Impact:** 32 cases of masked ARR changes now properly tracked

### 5. ARR Delta Using VALUE Instead of DELTA
**Issue:** arr_change_value stored deal value instead of change amount
**Fix:** Created arr_delta() function to track actual deltas, added newly_arr_bearing category
**Impact:** 50+ cases of incorrect ARR tracking fixed

---

## Final Results

**Reconciliation Status:**
- Total group/week combinations: 954
- Perfect reconciliation: 952 (99.8%)
- Mismatches: 2 (0.2%)

**Remaining Mismatches (Snapshot ETL Bug):**

1. **Case 1: ROW/SMB week 2026-04-13** (-$20K mismatch)
   - Beginning value: $37,871 (2 deals)
   - Lost value: $17,871 (deal 16895554409 closed lost 04-06, **correctly tracked**)
   - Expected ending: $20,000
   - Actual ending: $0
   - **True phantom exit:** Deal 38816659085 ($20K)
     - Present in 2026-04-06 snapshot, missing from 2026-04-13, reappears in 2026-04-20
     - Closes won on 2026-04-27 (so was active during 04-13 week)
   - Note: Deal 16895554409 appears in phantom exit tracking but was properly detected as lost

2. **Case 2: EMEA/Mid-Market week 2026-05-25** (-$40K mismatch)
   - **Phantom exit:** Deal 59860100786 ($40K)
   - Present in 2026-05-18 snapshot, missing from 2026-05-25
   - Eventually closes won in August (so was active during 05-25 week)

**Root Cause:** Snapshot ETL (scripts/snapshot_deals.py) occasionally excludes active deals from specific snapshot dates. Deals then reappear in subsequent snapshots, creating "phantom exits" that waterfall cannot reconcile.

---

## Code Changes

### New Files Created:
- `scripts/analytics/arr_delta.py` - Standalone function for ARR delta calculation with explicit edge case handling
- `scripts/migrations/061_add_newly_arr_bearing.sql` - Database migration for new tracking category
- `test_exclusion_rules.py` - Verification that movement categories are mutually exclusive
- `test_arr_delta_real_deals.py` - Tests against real deals from investigation

### Modified Files:
- `scripts/analytics/compute_waterfall_segmented.py`:
  - Integrated arr_delta() function
  - Removed precedence system
  - Updated net_change formula
  - Added newly_arr_bearing tracking
  - Enhanced reconciliation check to enumerate specific deal IDs causing mismatches

- `PENDING_WORK.md`:
  - Removed old waterfall reconciliation item (5 bugs fixed)
  - Added new item: "Snapshot ETL Phantom Exits Bug"

---

## Reconciliation Check Enhancement

The reconciliation check now:
- ✅ Remains STRICT (correctly fails on phantom exits)
- ✅ Enumerates specific deal_ids causing mismatches
- ✅ Tracks phantom exits per group/week
- ✅ Reports deal IDs and values in error output

**Example Output:**
```
default/ROW/SMB week 2026-04-13:
  Expected: $20,000.00
  Actual:   $0.00
  Diff:     $-20,000.00
  Phantom exits: 2 deals, $37,871
    - Deal 16895554409: $17,871
    - Deal 38816659085: $20,000
```

**Note on "Phantom Exits" Reporting:**
The tracking currently flags all deals that disappeared from snapshots, including those properly tracked in won_value/lost_value. For Case 1, deal 16895554409 ($17,871) was correctly tracked as lost, so the true phantom exit is only deal 38816659085 ($20K). The -$20K mismatch figure traces to this single untracked deal. The phantom exit list is diagnostic (showing what disappeared) rather than definitional (not all are untracked).

---

## Testing Performed

### Isolated Function Testing:
- arr_delta() function: 12/12 tests pass
- Exclusion Rule 1 (newly_arr_bearing vs arr_change): PASS
- Exclusion Rule 2 (won/lost vs arr_change): PASS (after fix)

### Real-World Verification:
- NAM/Mid-Market week 2025-10-06: -$52,725 correctly calculated
- Deal #4 (61149585726): Correctly classified as newly_arr_bearing
- ARR increases: Correctly calculated on multiple real deals

### Full Backfill:
- 56 weeks computed (2025-08-11 to 2026-08-28)
- 954 group/week combinations
- 952 perfect reconciliations (99.8%)

---

## Next Steps

### Immediate:
- ✅ Integration complete and tested
- ✅ Reconciliation check enhanced with deal ID tracking
- ✅ PENDING_WORK.md updated with snapshot ETL bug

### Future Work:
1. **Audit snapshot_deals.py ETL** (tracked in PENDING_WORK.md)
   - Investigate why deals occasionally missing from single snapshot
   - Check for race conditions, API pagination issues, HubSpot filters
   - Add completeness check between consecutive snapshots
   - Re-backfill affected weeks once fixed

2. **Monitor Future Waterfalls**
   - Check if new phantom exits appear
   - Verify reconciliation check continues to catch issues
   - Document any new patterns discovered

---

## Documentation

**Investigation Files:**
- All trace scripts created during investigation (trace_case_2_emea.py, check_disappeared_deals.py, etc.)
- This summary document

**Related Docs:**
- PENDING_WORK.md (updated)
- arr_delta.py (comprehensive docstrings and test cases)

---

## Conclusion

The waterfall computation is now correct. All 5 originally identified bugs have been fixed through systematic investigation and isolated testing. The arr_delta integration successfully tracks ARR changes, newly ARR-bearing deals, and won/lost movements as independent categories.

The 2 remaining mismatches (0.2%) are caused by a separate snapshot ETL bug where active deals are occasionally missing from specific snapshot dates. This is tracked in PENDING_WORK.md as its own item to be investigated and fixed separately.

**The reconciliation check remains strict and correctly identifies these data quality issues, as designed.**
