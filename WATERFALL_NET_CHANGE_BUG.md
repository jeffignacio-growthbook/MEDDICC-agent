# Waterfall Net Change Bug - CONFIRMED

**Date:** 2026-09-08
**Status:** 🐛 BUG CONFIRMED - Requires Fix

---

## Summary

The `net_change` calculation in `compute_waterfall_segmented.py` incorrectly includes `moved_forward_value` and `moved_backward_value`, causing reconciliation mismatches between `beginning_value + net_change` and `ending_value`.

**Impact:** Affects every week's waterfall figures where deals move stages without changing ARR.

---

## Evidence

### Aug 28 EMEA/Enterprise Example

**Waterfall values:**
- Beginning value: $2,200,924
- Ending value: $2,200,924
- Net change: **$97,174** ⚠️

**Movement breakdown:**
- moved_forward_value: $142,174
- moved_backward_value: $45,000
- Difference: $97,174 (matches net_change)

**Reconciliation check:**
- Expected ending: beginning + net_change = $2,200,924 + $97,174 = **$2,298,098**
- Actual ending: **$2,200,924**
- **Mismatch: -$97,174** ❌

**Deal-level verification:**
- 17 EMEA/Enterprise deals in both snapshots
- 17 deals qualified, same deal_ids
- **ZERO ARR changes between Aug 24 and Aug 28**
- Total value identical in both snapshots: $2,200,924

---

## Root Cause

Stage movements (moved_forward/moved_backward) represent deals **re-ordering within the qualified pipeline**, not deals entering or leaving the pipeline.

**Current (buggy) formula** (line 494-501):
```python
wf['net_change'] = (
    wf['new_pipeline_value']
    + wf['newly_qualified_value']
    + wf['moved_forward_value']      # ❌ BUG
    - wf['moved_backward_value']     # ❌ BUG
    - wf['won_value']
    - wf['lost_value']
)
```

**Why this is wrong:**
1. A deal that moves forward in stage stays in qualified pipeline
2. It's counted in BOTH beginning_value (at old stage) and ending_value (at new stage) with same ARR
3. Adding moved_forward to net_change **double-counts** it
4. Result: `beginning + net_change ≠ ending`

**Example:**
- Deal A: $50K, moves from stage 3 → stage 4
- Beginning total: $50K (includes Deal A at stage 3)
- Ending total: $50K (includes Deal A at stage 4)
- moved_forward_value: +$50K
- net_change: +$50K
- Reconciliation: $50K + $50K = $100K, but actual ending is $50K ❌

---

## Correct Formula

```python
wf['net_change'] = (
    wf['new_pipeline_value']       # Deals created (not in prev, in new)
    + wf['newly_qualified_value']  # Deals crossed threshold
    - wf['won_value']              # Deals closed won (removed)
    - wf['lost_value']             # Deals closed lost (removed)
)
```

**Rationale:**
- `new_pipeline`: Adds value (deal wasn't in beginning snapshot)
- `newly_qualified`: Adds value (deal wasn't in qualified pipeline before)
- `won`/`lost`: Removes value (deal exits qualified pipeline)
- `moved_forward`/`moved_backward`: **No net change** (deal stays in pipeline at same ARR)

**Note on ARR changes:**
If a deal's ARR changes while moving stages, that's captured separately in `arr_change_value`. Stage movement and ARR change are orthogonal.

---

## Scope of Impact

**Affected rows:** Every week where deals move stages
- Aug 28 example: -$97K mismatch
- Backfill output showed reconciliation warnings in ~40% of weeks

**Data integrity impact:**
- `net_change` values are inflated/deflated by stage movements
- Synthesis layer may report pipeline "growth" when deals just re-ordered
- Reconciliation check catches it, but data is still written with wrong net_change

**Historical data:**
- All 56 weeks of backfilled data have this bug
- Need to recompute after fixing formula

---

## Fix Required

### 1. Update compute_waterfall_segmented.py

**File:** `scripts/analytics/compute_waterfall_segmented.py`
**Lines:** 494-501

```diff
wf['net_change'] = (
    wf['new_pipeline_value']
    + wf['newly_qualified_value']
-   + wf['moved_forward_value']
-   - wf['moved_backward_value']
    - wf['won_value']
    - wf['lost_value']
)
```

### 2. Update compute_waterfall.py (if still in use)

Same fix needed in the original non-segmented version.

### 3. Recompute Historical Data

After fixing formula:
```bash
python scripts/analytics/compute_waterfall_segmented.py --backfill
```

### 4. Verify Reconciliation

After recompute, confirm zero reconciliation mismatches:
```bash
python scripts/analytics/compute_waterfall_segmented.py --backfill 2>&1 | grep "Reconciliation mismatch"
```

Should return empty (no mismatches).

---

## Design Question: Should moved_forward/backward be tracked at all?

**Current state:** These values are computed and stored, but should NOT affect net_change.

**Options:**
1. **Keep tracking, fix formula** (recommended)
   - moved_forward/backward are useful qualitative signals
   - Show deal velocity/progression through stages
   - Just don't include them in net_change math

2. **Remove tracking entirely**
   - Simplifies logic
   - Loses visibility into stage movement patterns

**Recommendation:** Option 1. Keep tracking for analytics, fix the formula.

---

## Related Patterns

This is the same class of bug caught multiple times this week:
- **Byborg contraction sign mismatch** (expected -$X, got +$X)
- **Q3 100%/100% coincidence** (two independent metrics suspiciously identical)
- **Resolved vs best-case GRR confusion** (two definitions, one label)

**Common pattern:** Internal consistency violations where two figures that should be mathematically related diverge.

**Lesson:** When A + B should equal C by definition, and they don't, that's a real bug worth tracing to the source, not a "plausible edge case."

---

## Next Steps

1. Fix the formula in both compute_waterfall_segmented.py and compute_waterfall.py
2. Recompute historical data (56 weeks)
3. Verify zero reconciliation mismatches
4. Update PENDING_WORK.md
5. Commit with test showing before/after reconciliation

**Priority:** High - affects data integrity across all waterfall reporting

---

## Discovery Credit

**Caught by:** Live Slack test + user scrutiny of synthesis response
**Original flag:** "Enterprise: flat, though net_change shows +$97K"
**User quote:** "Don't accept 'likely an ARR update' as sufficient - trace the actual deals"

This is exactly why production testing matters - the bug was invisible until real queries exposed the internal inconsistency.
