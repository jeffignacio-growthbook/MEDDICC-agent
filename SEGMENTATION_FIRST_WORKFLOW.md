# Segmentation-First Workflow: Template-Portable Pattern

## Core Principle

**Define cohorts FIRST, compute within them SECOND.**

Never compute on blended populations and explain contamination after the fact.

---

## Three-Layer Segmentation Hierarchy

### 1. ERA: Major Process/System Changes
**Rule:** NEVER blend across ERA boundaries - different business motion

**Example:** Pre-2023 vs 2023+ (renewal pipeline introduction)
- Pre-2023: All deals in "default" pipeline (no renewal tracking)
- 2023+: Renewal pipeline introduced (pipeline_id='866608541')
- **Action:** Compute separately, report only 2023+ for current-process metrics

### 2. EVENT: Bulk Operations
**Rule:** EXCLUDE event-driven outcomes - not organic sales results

**Example:** Bulk cleanup months (478 deals across 10 months)
- Detection: >10 deals/month with blank lost_reason
- Months: 2023-08, 2024-11, 2026-01 through 2026-08
- **Action:** Exclude ALL bulk cleanup deals, compute only on organic cohort

### 3. MOTION: Variance Within Clean Cohort
**Rule:** Segment if cycle times/win rates differ significantly across groups

**Example:** SMB vs Mid-Market vs Enterprise
- Mid-Market: 52% of organic won deals
- SMB: 30%
- Enterprise: 17%
- **Action:** Report variance, consider sub-segmentation if needed

---

## GrowthBook Q016 Example

### Original Blended Approach (WRONG)
```python
# Computed on ALL default pipeline deals
default_deals = [d for d in all_deals if pipeline_id == "default"]
lost_deals = [d for d in default_deals if deal_status == "lost"]
win_rate = won / (won + lost)
# Result: 3.7% (23/629) - suspiciously low
```

**Problems:**
- Blended 2023+ organic (128 lost) + bulk cleanup (478 lost) + pre-2023 (22 lost)
- 81.8% contamination undetected until retroactive investigation
- False narrative: "default pipeline might be junk"

### Segmentation-First Approach (CORRECT)
```python
# STEP 1: Define ERA cohort
ERA_CUTOFF = datetime(2023, 1, 1, tzinfo=timezone.utc)
default_2023_plus = [
    d for d in all_deals
    if pipeline_id == "default" and create_date >= ERA_CUTOFF
]

# STEP 2: Identify and exclude EVENT contamination
bulk_cleanup_months = detect_bulk_cleanup(default_2023_plus)  # 10 months, 478 deals
organic_cohort = [
    d for d in default_2023_plus
    if not is_bulk_cleanup(d, bulk_cleanup_months)
]

# STEP 3: Compute within clean cohort
won = [d for d in organic_cohort if is_won(stage)]  # 23
lost = [d for d in organic_cohort if deal_status == "lost"]  # 128
win_rate = len(won) / (len(won) + len(lost))
# Result: 15.2% (23/151) - validates as legitimate new business ✅
```

---

## Enhanced Plausibility Check Integration

### Automated Blocking

```python
# Before finalizing ANY population metric:
passed = run_enhanced_plausibility_check(
    population_description="Default pipeline deals",
    deals=default_deals,
    metric_name="cycle_time",
    metric_value=52
)

if not passed:
    # BLOCKS finalization - requires segmentation first
    exit(1)
```

### Check Results

**On Blended Population:**
- ✅ ERA Boundary: PASS (all 2023+)
- 🚫 EVENT Contamination: **BLOCK** (478 bulk cleanup deals, 78.9%)
- Exit code: 1 (error - cannot finalize)

**On Clean Cohort (2023+, organic only):**
- ✅ ERA Boundary: PASS
- ✅ EVENT Contamination: PASS
- ✅ Cross-Metric Consistency: PASS
- Exit code: 0 (success - safe to finalize)

---

## Business Events Registry

Maintained in `config/business_events_registry.yaml`:

```yaml
pipeline_scheme_changes:
  - date: "2023-01-01"
    event: "Renewal pipeline introduced"
    segmentation_rule: "Exclude pre-2023 from current-process metrics"

bulk_cleanup_events:
  - event_type: "recurring_bulk_cleanup"
    pattern: ">10 deals/month with blank lost_reason"
    months_detected: [2023-08, 2024-11, 2026-01, ...]
    segmentation_rule: "Exclude ALL bulk cleanup months from win rate/cycle time"
```

---

## Detection Patterns

### Bulk Cleanup Detection
```sql
SELECT
  DATE_TRUNC('month', close_date) as month,
  COUNT(*) as blank_lost_reason_count
FROM deals
WHERE deal_status = 'lost'
  AND lost_reason IS NULL
GROUP BY month
HAVING COUNT(*) > 10
ORDER BY month DESC
```

Each row with count > 10 = potential bulk cleanup event.

### ERA Boundary Detection
```sql
SELECT
  MIN(create_date) as earliest_deal,
  MAX(create_date) as latest_deal
FROM deals
WHERE <population_filter>
```

If earliest < ERA_CUTOFF AND latest >= ERA_CUTOFF:
- Population spans ERA boundary
- BLOCK and require segmentation

---

## GrowthBook Results (After Segmentation)

### Target Cohort Definition
**Population:** Default pipeline, 2023+, organic closures only
- Closed deals: 151 (23 won, 128 lost)
- Excluded: 478 bulk cleanup + 22 pre-2023 = 500 deals (76.8% of original)

### Metrics (Within Clean Cohort)
- **Win rate:** 15.2% ✅ (validates as legitimate new business, expected 15-30%)
- **Cycle time:** 52 days median (n=22, adequate sample)
- **Active vs historical:** 2.5x ratio (58 active incremental vs 23 historical won) - balanced

### Segment Distribution (MOTION variance)
- Mid-Market: 52%
- SMB: 30%
- Enterprise: 17%

No further segmentation needed (cohort is reasonably homogeneous).

---

## Template-Portable Checklist

Before computing ANY historical metric on ANY client:

- [ ] **Check ERA boundaries** - Does population span pipeline scheme change, CRM migration, or other major process shift?
  - If YES → Segment by ERA, compute separately
  - If NO → Proceed

- [ ] **Check EVENT contamination** - Does population include bulk operations (cleanup, migration, admin actions)?
  - Detect: >10 deals/month with blank lost_reason (or other bulk patterns)
  - If YES → Exclude EVENT deals, compute only on organic cohort
  - If NO → Proceed

- [ ] **Check MOTION variance** - Within clean cohort, are there multiple segments/deal types with different characteristics?
  - If YES → Report variance, consider sub-segmentation
  - If NO → Compute on unified cohort

- [ ] **Log segmentation decisions** - Document which cohorts were created and why

- [ ] **Verify results** - Do metrics computed within clean cohort validate against cross-metric plausibility checks?

---

## Scripts Created

### Segmentation Workflow
1. **segment_and_compute.py** - Define segments FIRST, compute within them
2. **enhanced_plausibility_check.py** - BLOCKS blended populations, requires segmentation
3. **test_clean_cohort_check.py** - Verify clean cohort passes check

### Business Events
4. **config/business_events_registry.yaml** - Registry of dated ERA/EVENT boundaries

### Reusable Patterns
All scripts are template-portable - work with any client's data by:
- Updating ERA_CUTOFF dates in registry
- Adjusting bulk cleanup threshold (default: >10 deals/month)
- Adding client-specific EVENT patterns

---

## Key Insight: Why This Matters

**Before (Blended Approach):**
- Computed 3.7% win rate (23/629)
- Spent hours investigating "why is default pipeline junk?"
- Found 81.8% contamination retroactively
- Narratives kept shifting as contamination was discovered piecemeal

**After (Segmentation-First):**
- Define clean cohort: 2023+, organic, exclude bulk cleanup
- Compute 15.2% win rate (23/151) - immediately validates
- Clear conclusion: legitimate new business pipeline
- No retroactive explanation needed - cohort was clean from the start

**Time saved:** Hours of investigation avoided
**Accuracy gained:** Metrics computed on apples-to-apples cohort
**Confidence increased:** Plausibility check blocks contaminated populations automatically

---

## Next Steps for GrowthBook

1. ✅ Q016 cycle_time validated at 52 days (clean cohort: 2023+, organic, won, n=22)
2. ✅ Win rate validated at 15.2% (confirms legitimate new business)
3. ✅ Cross-metric consistency acceptable (2.5x active vs historical ratio)
4. ⏳ Safe to finalize in canonical_questions.yaml with segmentation documented
5. ⏳ Apply same segmentation-first pattern to other historical metrics (win rate, velocity, etc.)

---

## Template for Other Clients

```python
# 1. Load business events registry
with open("config/business_events_registry.yaml") as f:
    events = yaml.safe_load(f)

# 2. Define ERA cohort
era_cutoff = events["pipeline_scheme_changes"][0]["date"]
post_era = [d for d in deals if d.create_date >= era_cutoff]

# 3. Detect and exclude EVENT contamination
bulk_months = detect_bulk_cleanup(post_era, threshold=10)
organic = exclude_bulk_cleanup(post_era, bulk_months)

# 4. Check for MOTION variance
segments = analyze_segments(organic)
if has_variance(segments):
    # Compute separately by segment
    for segment in segments:
        compute_metrics(segment)
else:
    # Compute on unified cohort
    compute_metrics(organic)

# 5. Run enhanced plausibility check
passed = run_enhanced_plausibility_check(
    population=organic,
    metric_name="...",
    metric_value=...
)

if not passed:
    raise ValueError("Segmentation required - see plausibility_checks.log")
```

This pattern applies to **every client**, not just GrowthBook.
