# Sales Velocity Composition Test - Architectural Gap

**Date:** 2026-09-08
**Status:** 🚫 BLOCKED - Building blocks not parameterizable
**Test Type:** Phase 2 Dogfood Test #2 (Composition)

---

## Test Objective

Build Sales Velocity as composite metric to test whether:
1. Already-validated metric **METHODOLOGY** (not cached values) can be reused as building blocks
2. Registry hygiene rules compose cleanly when nested
3. Unit/dimensional consistency holds across composition layers

**Formula:**
```
New Business Sales Velocity (quarter X) =
  (# opportunities reaching qualified stage in X)
  × (avg deal size, WON new-business deals in X)
  × (win rate, new-business in X - conversion_rate_prospective methodology)
  / (cycle time, new-business in X - cycle_time methodology)

Expansion Sales Velocity (quarter X) =
  (# deals with expansion_arr > 0 in X)
  × (avg deal size, WON expansion deals in X)
  × (win rate, expansion in X)
  / (cycle time, expansion in X)
```

---

## Critical Architectural Requirement

**Per Jeff's specification:**
> "CRITICAL ARCHITECTURAL TEST: Check whether win_rate (conversion_rate_prospective) and cycle_time's DEFINITIONS in config/metrics.yaml / field_semantics.yaml are structured as **re-parameterizable functions** (population filter + period parameter) or hardcoded to the all-time window."

**Translation:** Both building blocks must accept a **period parameter** (e.g., "Q1 2026", "Q2 2026") to be usable in Sales Velocity formula.

---

## Finding: Building Blocks NOT Parameterizable

### conversion_rate_prospective

**Status:** ❌ NOT PARAMETERIZABLE

**Current Implementation:**
- **Definition:** "In-quarter close rate for deals cohorted by the week-of-quarter in which each deal FIRST reached a qualified stage"
- **Verified result:** 0.072 = 27 won / 376 qualified across **[FY2026 Q3, FY2026 Q4, FY2027 Q1]**
- **Computation script:** `conversion_by_qualification_week_FINAL_CLEAN.py`
- **Hardcoded quarters:** Lines 31-35 define 3 specific quarters, loops through all, returns aggregated result

**Evidence from code:**
```python
FISCAL_QUARTERS = [
    ('FY2026 Q3', '2025-11-01', '2026-01-31'),
    ('FY2026 Q4', '2026-02-01', '2026-04-30'),
    ('FY2027 Q1', '2026-05-01', '2026-07-31'),
]

# Loops through all quarters, aggregates:
all_qualified = []
all_wins = []

for quarter_id, start_date, end_date in FISCAL_QUARTERS:
    # ... compute qualified and wins for this quarter
    all_qualified.extend(...)
    all_wins.extend(...)

# Returns POOLED rate across all 3 quarters
```

**What's missing:**
- No `quarter` parameter to compute rate for a single specific quarter
- Returns single global rate (7.2%), not per-quarter rates
- Cannot invoke as `conversion_rate_prospective(quarter="Q1 2026")`

**Note:** The definition structure **implies** it could be refactored to be per-quarter (numerator and denominator are both quarter-scoped), but **implementation is currently pooled**.

---

### cycle_time

**Status:** ❌ NOT PARAMETERIZABLE

**Current Implementation:**
- **Definition:** "MEDIAN((close_date - create_date).days) WHERE days >= 0"
- **Config:** `window_mode: "all_time"` or `rolling_window_months: 12`
- **Verified result:** 52 days (all_time, 22 deals)
- **Current value:** 52 days (all_time window)

**Evidence from config/metrics.yaml lines 722-726:**
```yaml
config:
  window_mode: "all_time"  # Options: "all_time", "rolling"
  rolling_window_months: 12  # Used when window_mode = "rolling"
  min_sample_size: 20
  fallback_to_all_time: true
```

**What's missing:**
- No `quarter` parameter to compute cycle time for a specific quarter
- Window modes are time-based (all_time, rolling N months), not period-based (Q1, Q2, Q3)
- Cannot invoke as `cycle_time(quarter="Q1 2026")`

**Note:** Could be refactored to accept period parameter alongside window_mode, but **not currently implemented**.

---

## Refactoring Path

### Option A: Make Building Blocks Parameterizable (Recommended)

**Conversion Rate:**
1. Refactor `conversion_by_qualification_week_FINAL_CLEAN.py` to accept `quarter` parameter
2. Instead of looping all quarters and pooling, compute for single specified quarter
3. Update metrics.yaml to document parameter: `conversion_rate_prospective(quarter)`
4. Preserve pooled calculation as separate metric: `conversion_rate_prospective_pooled`

**Cycle Time:**
1. Add `period` parameter to cycle_time computation
2. Filter deals by `close_date.in_period(X)` before computing median
3. Update config to support: `window_mode: "period"` alongside existing "all_time"/"rolling"
4. Preserve all_time as default when no period specified

**Benefits:**
- Tests true composition (reusing methodology across periods)
- Enables quarter-over-quarter comparisons
- Makes metrics more generally useful beyond Sales Velocity

**Risks:**
- Small sample sizes per quarter (Q1 had 22 non-renewal wins all-time, would be ~7-8 per quarter)
- May hit min_sample_size thresholds and need fallback logic

---

### Option B: Build Sales Velocity Without Refactoring (Workaround)

**Approach:**
1. Manually compute win_rate and cycle_time per quarter in Sales Velocity script
2. Reuse **hygiene rules** from registry (exclude_renewals, exclude_invalid_cycle_time)
3. Do NOT reuse conversion_rate_prospective or cycle_time functions directly

**Benefits:**
- Faster to implement (no refactoring of existing metrics)
- Still tests hygiene rule composition

**Drawbacks:**
- Does NOT test methodology reuse (the primary goal of Test #2)
- Duplicates logic instead of reusing it
- Not a real composition test

---

## Decision Required

**Question for Jeff:** Which path to take?

**Option A (Refactor first, then test composition):**
- Longer upfront work
- Tests true composition
- Makes metrics more flexible for other use cases

**Option B (Build Sales Velocity standalone):**
- Faster to implement
- Tests hygiene rule composition only
- Doesn't test methodology reuse

---

## What's Already Parameterizable

### Hygiene Rules ✅

From `config/field_semantics.yaml` known_hygiene_rules (lines 759-834):
- `is_valid_cycle_deal()` - excludes negative cycle time
- `is_renewal_base()` - excludes renewal pipeline
- `is_fresh_pipeline_deal()` - excludes stale deals >180 days

**These are functional checks** that can be applied to any deal set, regardless of period. They compose cleanly.

### GRR ✅

From `config/metrics.yaml` grr section (lines 46-247):
- Takes period parameter: `close_date.in_period(X)`
- Proven across Q1 2026 and Q2 2026
- Already validated for composition

---

## Recommendation

**Proceed with Option A** (refactor building blocks first):

**Rationale:**
1. The whole point of Test #2 is to test **methodology reuse**, not just hygiene rule composition
2. If we can't reuse conversion_rate_prospective and cycle_time methodologies, we're not actually testing composition
3. Parameterization is valuable beyond Sales Velocity (enables quarter-over-quarter analysis)
4. Small sample size risk is manageable with proper fallback logic (already present in cycle_time)

**Estimated work:**
- Refactor conversion_rate_prospective: 1-2 hours
- Refactor cycle_time: 30 min - 1 hour
- Build Sales Velocity composite: 1-2 hours
- Run backtest against Jeff's ground truth: 1 hour
- **Total: ~4-6 hours**

**Alternative if Jeff wants faster path:**
- Proceed with Option B (standalone Sales Velocity)
- Document as "hygiene rule composition test" instead of "methodology reuse test"
- **Total: ~2-3 hours**

---

## Blocked Status

**BLOCKED ON:**
1. Decision: Refactor building blocks (Option A) vs. standalone implementation (Option B)
2. If Option A: Which quarters to use for backtest (Q1 or Q2 2026 - both closed)
3. If Option A: Get Jeff's ground truth Sales Velocity values before computing

**CANNOT PROCEED** until building blocks are parameterizable or we accept Option B's limitations.

---

## Files Examined

**Metrics definitions:**
- `config/metrics.yaml` lines 478-551 (conversion_rate_prospective)
- `config/metrics.yaml` lines 714-965 (cycle_time)
- `config/field_semantics.yaml` lines 759-834 (known_hygiene_rules)

**Computation scripts:**
- `conversion_by_qualification_week_FINAL_CLEAN.py` (hardcoded quarters, pooled result)
- No dedicated cycle_time computation script found (computed inline in handlers)

**Evidence:**
- conversion_rate_prospective: VERIFIED 0.072 pooled across 3 quarters (27 won / 376 qualified)
- cycle_time: VERIFIED 52 days all_time (22 non-renewal won deals)
- Both metrics currently global/pooled, not per-quarter parameterizable
