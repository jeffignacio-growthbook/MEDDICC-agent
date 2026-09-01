# Fix: Apply Pipeline Exclusion in forecast_analyses.py (Read Time, Not Write Time)

## Problem

`forecast_analyses.py` computes week-3 conversion rates **per pipeline** including renewals:

```python
# Line 267-275
def _qualified_in_own_pipeline(stage_id, pipeline_id):
    # ... with the pooled pipeline-exclusion NEUTRALISED (empty set)
    return is_deal_in_analytics_scope(
        str(stage_id), pipeline_id, set(), stage_cfg)
        #                             ^^^^ BUG: should be excl_pipelines
```

This counts renewal deals in week-3 denominators starting in Q1 FY2027 (when renewal stages started being captured), breaking QoQ comparison:

- Q3/Q4 FY2026: 0 renewal stages → denominators clean
- Q1+ FY2027: 1,300+ renewal stages → denominators contaminated

Result: 13.5% trailing average pools incompatible quarters.

---

## Why Not Delete Renewal Rows from deals_snapshot?

From `point_in_time.py` lines 14-22:

> "Scoping the write would have dropped 221 of 376 rows and broken a consumer nobody was thinking about, unrecoverably without a refetch. **Scope on read, never on write**."

**GRR/NRR need renewal rows** even though not currently implemented. Architecture explicitly preserves them:

```python
# config/client.yaml (renewal pipeline)
analyze: false  # MEDDICC agent skips
# BUT analytics INCLUDES for GRR/NRR
```

Deleting 4,500+ renewal snapshot rows would be irreversible and break future retention analysis.

---

## Correct Fix

**Apply pipeline exclusion at read time** in `forecast_analyses.py`:

### Before (Bug)
```python
def _qualified_in_own_pipeline(stage_id, pipeline_id):
    if stage_id is None or not str(stage_id).strip():
        return False
    return is_deal_in_analytics_scope(
        str(stage_id), pipeline_id, set(), stage_cfg)
        #                             ^^^^ neutralizes pipeline exclusion
```

### After (Fixed)
```python
def _qualified_in_own_pipeline(stage_id, pipeline_id):
    if stage_id is None or not str(stage_id).strip():
        return False
    # Apply full scope filter INCLUDING pipeline exclusion
    return is_deal_in_analytics_scope(
        str(stage_id), pipeline_id, excl_pipelines, stage_cfg)
        #                            ^^^^^^^^^^^^^^ uses loaded exclusions
```

This excludes renewal pipeline (866608541) from new-business conversion denominators while preserving renewal rows in snapshots for GRR/NRR.

---

## Impact

**Before fix**:
- Q1 week-3 denominator: 247 (240 default + 7 renewal)
- Q2 week-3 denominator: 255 (119 default + 136 renewal)
- Trailing average: 13.5% (meaningless — pools incompatible quarters)

**After fix**:
- Q1 week-3 denominator: 240 (default only)
- Q2 week-3 denominator: 119 (default only)
- Recomputed rates on consistent population

**Expected**: Tight 9-10.5% band holds across Q3 FY2026 through Q2 FY2027 once data is consistent.

---

## Implementation

### File to Change
`scripts/analytics/forecast_analyses.py`

### Line to Fix
Line 275 (inside `query_week3_conversion`)

### Change
```diff
  def _qualified_in_own_pipeline(stage_id, pipeline_id):
-     # The shared stage rule (qualified order, not an excluded stage),
-     # with the pooled pipeline-exclusion NEUTRALISED (empty set) so each
-     # pipeline is scored on its own stages. A null stage is not qualified
-     # and so is not in a starting-pipeline denominator.
+     # The shared stage rule (qualified order, not an excluded stage),
+     # WITH pipeline exclusion applied (renewal pipeline excluded from
+     # new-business conversion analysis). A null stage is not qualified.
      if stage_id is None or not str(stage_id).strip():
          return False
      return is_deal_in_analytics_scope(
-         str(stage_id), pipeline_id, set(), stage_cfg)
+         str(stage_id), pipeline_id, excl_pipelines, stage_cfg)
```

### Test
```bash
# Before fix: Should show renewal pipeline with conversion rate
python scripts/analytics/forecast_analyses.py

# After fix: Should show ONLY default pipeline with conversion rate
python scripts/analytics/forecast_analyses.py

# Verify renewal rows still in snapshots (GRR/NRR needs them)
python check_snapshot_scope_consistency.py
# Should still show 1,300+ renewal rows per quarter
```

---

## Why the Original Code Neutralized Exclusion

Comment said: "so each pipeline is scored on its own stages"

**Intent**: Compute per-pipeline conversion rates (new business separate from renewal).

**Problem**: Code computed rates but then **pooled them** for trailing average. If you want separate rates, report them separately. If you want a pooled rate, filter to one population first.

**Correct approach**:
- For **new-business forecast**: Exclude renewals, compute rate on default pipeline only
- For **renewal forecast** (future): Compute separately on renewal pipeline only
- **Never pool** incompatible populations

---

## Validation

After fix, recompute conversion rates:

```bash
python scripts/analytics/compute_week3_conversion.py \
  --quarters "FY2026 Q3,FY2026 Q4,FY2027 Q1,FY2027 Q2"
```

**Expected per-quarter rates** (default pipeline only):
- Q3 FY2026: ~10.5%
- Q4 FY2026: ~10.0%
- Q1 FY2027: ~9.2%
- Q2 FY2027: Check if still outlier on clean data

**If Q2 still outlier**: Investigate further (real or different measurement issue).

**If Q2 normalizes**: Was artifact of scope contamination, 9-10.5% band holds.

**Update** `config/metrics.yaml` with verified rates and consistent range.

---

## Summary

✅ **Keep renewal rows in deals_snapshot** (GRR/NRR needs them)
✅ **Fix forecast_analyses.py** to exclude renewals at read time
✅ **Recompute conversion rates** on consistent population
✅ **Update metrics.yaml** with verified rates

❌ **Do NOT delete renewal snapshot rows** (irreversible, breaks future retention)
