# Snapshot Scope Fix Plan

## Problem Statement

Renewal stages started being captured in Q1 FY2027 snapshots, breaking quarter-over-quarter consistency:

| Quarter | Renewal Stages in Snapshots |
|---------|------------------------------|
| Q3 FY2026 | 0 |
| Q4 FY2026 | 0 |
| **Q1 FY2027** | **1,319** ← boundary |
| Q2 FY2027 | 1,784 |
| Q3 FY2027 | 1,419 |

**Blast Radius**: Every snapshot-based analysis crossing the Q4→Q1 boundary is contaminated:
- Week-3 conversion rates (Q1-Q2 pooled 13.5% is meaningless)
- Waterfall qualified pipeline (Q1+ counts include renewals, Q3-Q4 don't)
- Coverage curves
- Any QoQ comparison using `deals_snapshot`

## Definitional Choice

**Decision required**: Should renewals be counted as "qualified" pipeline?

### Option 1: Renewals NEVER Qualified (RECOMMENDED)

**Rationale**:
- Qualification is a **new-business concept** — a deal crossing threshold from unqualified to qualified
- Renewals exist because customer **already bought**. No qualification gate.
- Aligns with "renewal waterfall is a design gap" finding — renewals are a different motion

**Impact**:
- Exclude renewal pipeline from all snapshot analytics
- Q3-Q4 FY2026 behavior (0 renewal stages) becomes the **standard**

**Implementation**:
1. Update snapshot generation to exclude renewal pipeline:
   ```python
   # In snapshot generation logic
   excluded_pipelines = config.get('pipeline', {}).get('excluded', [])
   renewal_pipeline_ids = config.get('pipeline', {}).get('value_field', {}).get('renewal_pipeline_ids', [])

   # Combine both exclusions
   all_excluded = set(excluded_pipelines) | set(renewal_pipeline_ids)

   # Filter deals before snapshotting
   snapshot_deals = [d for d in deals if d.get('pipeline_id') not in all_excluded]
   ```

2. **Backfill Q1-Q3 FY2027** snapshots:
   - Regenerate snapshots excluding renewal pipeline (866608541)
   - Keeps Q3-Q4 FY2026 as-is (already clean)
   - All quarters now consistent

3. **Verify clean data**:
   ```sql
   SELECT fiscal_quarter, pipeline_id, COUNT(*)
   FROM deals_snapshot
   WHERE pipeline_id = '866608541'
   GROUP BY 1, 2;
   ```
   Should return **0 rows** for all quarters after fix.

**Pros**:
- ✅ Simpler mental model (new business = qualified, renewals = separate)
- ✅ Less data to snapshot and analyze
- ✅ Current Q1 analysis already assumes this (renewal exclusion built in)
- ✅ Minimal backfill (only 3 quarters vs 2 if going the other way)

**Cons**:
- ❌ Can't compute renewal-specific conversion rates from snapshots (but we established renewal waterfall is a design gap anyway)

### Option 2: Renewals ALWAYS Qualified

**Rationale**:
- Renewal stages (Engaged, Pricing Presented) represent progression similar to new business
- Want unified view of all qualified pipeline

**Impact**:
- Include renewal pipeline uniformly across all quarters
- Q1+ behavior becomes the standard

**Implementation**:
- **Backfill Q3-Q4 FY2026** to include renewal pipeline with proper stage mapping

**Pros**:
- ✅ Comprehensive view of all in-flight deals

**Cons**:
- ❌ Mixes two different motions (qualification vs renewal progression)
- ❌ Larger snapshot data volume
- ❌ Doesn't align with "renewals are separate" philosophy already established

---

## Recommended Fix Sequence

### Step 1: Implement Scope Filter (renewals never qualified)

**File**: `scripts/analytics/snapshot_generator.py` (or wherever snapshots are created)

```python
# At the top of snapshot generation
from analytics.point_in_time import load_scope_config

excluded_pipelines, stage_cfg = load_scope_config(config)

# Get renewal pipeline IDs
renewal_pipeline_ids = set(
    config.get('pipeline', {}).get('value_field', {}).get('renewal_pipeline_ids', [])
)

# Combine exclusions
all_excluded_pipelines = excluded_pipelines | renewal_pipeline_ids

# Filter deals before creating snapshots
snapshot_candidates = [
    d for d in all_active_deals
    if d.get('pipeline_id') not in all_excluded_pipelines
]
```

### Step 2: Backfill Q1-Q3 FY2027 Snapshots

**Command** (to be created):
```bash
python scripts/analytics/backfill_snapshots.py \
  --quarters "FY2027 Q1,FY2027 Q2,FY2027 Q3" \
  --exclude-renewals \
  --dry-run  # verify first
```

**Expected changes**:
- Q1 FY2027: Remove 1,319 renewal stage rows
- Q2 FY2027: Remove 1,784 renewal stage rows
- Q3 FY2027: Remove 1,419 renewal stage rows

### Step 3: Verify Consistency

```bash
python check_snapshot_scope_consistency.py
```

Should show:
```
Quarter         Pipeline           Total  Renewal-Stgs
----------------------------------------------------
FY2026 Q3       866608541              0             0  ✓
FY2026 Q4       866608541              0             0  ✓
FY2027 Q1       866608541              0             0  ✓ (after backfill)
FY2027 Q2       866608541              0             0  ✓ (after backfill)
FY2027 Q3       866608541              0             0  ✓ (after backfill)
```

### Step 4: Recompute Conversion Rates on Clean Data

Once snapshots are consistent:

```bash
python scripts/analytics/compute_week3_conversion.py \
  --quarters "FY2026 Q3,FY2026 Q4,FY2027 Q1,FY2027 Q2"
```

**Expected**:
- Check if tight 9-10.5% band holds across all four quarters
- If Q2 still outlier, diagnose (now on clean data)
- Update `config/metrics.yaml` with verified rates

### Step 5: Re-enable Historical Conversion Forecast

Once rates are recomputed on clean data:

```bash
python scripts/analytics/compute_forecast.py
```

Historical conversion will use:
- Clean week-3 counts (renewals excluded)
- Verified conversion rate (probably 9-10.5% range)
- Won-deal average $37,662 (bias-corrected)

---

## Business Finding for Ryan (Separate from Forecast)

**Deal-size bias is systematic**, not driven by whale losses:

| Metric | Won Deals | Pipeline | Bias |
|--------|-----------|----------|------|
| **Mean** | $37,662 | $47,809 | **-21.2%** |
| **Median** | $20,000 | $25,625 | **-22.0%** |

**Finding**: Smaller deals win consistently. We **systematically over-qualify large deals**.

**Questions for Ryan**:
1. Are large deals being qualified too early (not truly ready)?
2. Do reps struggle to close larger deals (different motion needed)?
3. Should ICP/qualification criteria tighten for deals >$50K?

This is **actionable business intelligence**, independent of forecasting methodology.

---

## Timeline

| Step | Owner | Effort | Blocker |
|------|-------|--------|---------|
| 1. Implement scope filter | Eng | 1 hour | Need snapshot generation code location |
| 2. Backfill Q1-Q3 FY2027 | Eng | 2 hours | Step 1 complete |
| 3. Verify consistency | Eng | 15 min | Step 2 complete |
| 4. Recompute conversion rates | Eng | 30 min | Step 3 complete |
| 5. Re-enable historical conversion | Auto | 5 min | Step 4 complete |

**Total**: ~4 hours engineering time + validation.

---

## Rollback Plan

If backfill fails or produces unexpected results:

1. Snapshots are versioned by `snapshot_date` — old data remains
2. Queries filter to specific snapshot dates — point to pre-backfill dates
3. Regenerate if needed (snapshots are idempotent from `deals` table)

No data loss risk.
