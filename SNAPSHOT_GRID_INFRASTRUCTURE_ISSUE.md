# Snapshot Grid Infrastructure Issue

**Status:** Critical data quality issue blocking conversion methodology
**Impact:** Cannot compute cohort-by-qualification-week analysis
**Priority:** High - affects primary revenue forecasting metric

---

## Summary

The `deals_snapshot` table has pervasive data incompleteness across all quarters, preventing reliable cohort-by-qualification-week analysis. Initially believed to be a Q3/Q4-specific gap, investigation shows Q1 is also affected.

---

## Symptoms

### 1. Q3/Q4 Snapshot Grid Gaps (Initially Identified)

| Quarter | Date Range | Expected Weeks | Actual Weeks Available |
|---------|------------|----------------|------------------------|
| FY2026 Q3 | 2025-11-01 to 2026-01-31 | 1-13 | **1-2 only** (missing 3-13) |
| FY2026 Q4 | 2026-02-01 to 2026-04-30 | 1-13 | **4-13 only** (missing 1-3) |
| FY2027 Q1 | 2026-05-01 to 2026-07-31 | 1-13 | **1-13** (claimed complete) |

### 2. Q1 Data Quality Issue (Subsequently Discovered)

Despite "complete weeks 1-13" availability claim, Q1 data shows:

```
Qual Week | Qualified | Won  | Rate
Week 1    |    61     |  4   | 6.6%
Week 2    |     9     |  1   | 11.1%
Week 3    |     0     |  0   | 0.0%  ← IMPOSSIBLE
Week 4-13 |     0     |  0   | 0.0%  ← IMPOSSIBLE
```

**Total deals with qualification weeks: 70**
**Total wins in Q1 (from `deals` table): 29**

**Discrepancy:** Only 5 of 29 Q1 wins appear in qualification-week cohorts. **24 wins missing** (82.8%).

**Week-3 contradiction:**
- Earlier analysis: 5 wins from week-3 cohort
- Qualification-week analysis: 0 deals qualified in week-3

This pattern (all qualification in weeks 1-2, then nothing) suggests systematic data capture failure, not actual business behavior.

---

## Root Cause Hypotheses

### Hypothesis A: Snapshot Job Not Running Consistently

**Evidence:**
- Q3: Captured weeks 1-2, then stopped
- Q4: Started capturing at week 4 (missed weeks 1-3)
- Q1: Shows qualification only in weeks 1-2, despite having 13 weeks of snapshot rows

**Implication:** Snapshot job may be running intermittently or failing silently.

### Hypothesis B: Deals Created Already Qualified

**Evidence:**
- 61 deals qualified in week 1 (unusually high)
- No deals qualifying in weeks 3-13 (statistically improbable)

**Implication:** If deals enter the pipeline in qualified stages (no "Meeting Set" → "Qualified" transition), they would only appear in first snapshot taken. This would be captured once, then never marked as "newly qualified" in later weeks.

**Counter-evidence:** We know from `analyze_qualification_timing.py` that 83.3% of eventual wins qualified AFTER week-3. If Q1 shows 0 deals qualifying after week-2, the data doesn't reflect reality.

### Hypothesis C: Snapshot Logic Error

**Evidence:**
- 1000 snapshot rows for Q1 (481 unique deals)
- Only 70 deals marked as qualified across all weeks
- Week-3 cohort exists in earlier queries but shows 0 here

**Implication:** The snapshot table may be populated, but the logic for determining "first qualification week" may be flawed or incomplete.

---

## Impact on Methodology

### Blocked Analyses

1. **Cohort-by-qualification-week conversion rates**
   Cannot track when deals qualify → cannot compute timing-based decay curve

2. **Week-3 validation**
   Cannot verify whether week-3 cutoff is reasonable vs alternatives

3. **Segment timing patterns**
   Cannot determine if SMB qualification gap is timing artifact or hygiene problem

### Current Workaround

Using **fixed week-3 snapshot** as cohort cutoff:
- Q3: 3 wins from week-3 cohort / 21 total wins = 14.3%
- Q4: 4 wins from week-3 cohort / 22 total wins = 18.2%
- Q1: 5 wins from week-3 cohort / 29 total wins = 17.2%
- **Pooled: 12/72 wins = 16.7%**

This methodology excludes 83.3% of eventual wins from the denominator, causing systematic undercount.

---

## Investigation Steps

### Step 1: Validate Snapshot Job Status

```sql
-- Check snapshot row distribution by quarter and week
SELECT
    fiscal_quarter,
    week_of_quarter,
    COUNT(*) as snapshot_rows,
    COUNT(DISTINCT deal_id) as unique_deals
FROM deals_snapshot
WHERE pipeline_id = 'default'
GROUP BY fiscal_quarter, week_of_quarter
ORDER BY fiscal_quarter, week_of_quarter;
```

**Expected:** Roughly consistent row counts per week (±20%)
**If found:** Sharp drops or gaps indicate job failures

### Step 2: Check Deal Creation vs Qualification Timing

```sql
-- Compare deal create_date to first snapshot appearance
SELECT
    d.deal_id,
    d.create_date,
    MIN(ds.snapshot_date) as first_snapshot_date,
    MIN(ds.week_of_quarter) as first_snapshot_week,
    (MIN(ds.snapshot_date) - d.create_date::date) as days_to_first_snapshot
FROM deals d
LEFT JOIN deals_snapshot ds ON d.deal_id = ds.deal_id
WHERE d.pipeline_id = 'default'
  AND d.create_date >= '2026-05-01'
  AND d.create_date <= '2026-07-31'
GROUP BY d.deal_id, d.create_date
ORDER BY first_snapshot_week;
```

**Expected:** Deals appear in snapshots shortly after creation
**If found:** All deals appear in week 1-2 snapshots, created weeks earlier → snapshot job started late

### Step 3: Audit Stage Transitions via HubSpot

**Already attempted:** HubSpot property history API returned empty results (not feasible)

**Alternative:** Check if stage transitions are logged in HubSpot timeline/activity feed
- May require different API endpoint
- May not be programmatically accessible

### Step 4: Cross-Reference with `deals` Table

```sql
-- Find deals that closed won in Q1 but don't appear in qualification cohorts
SELECT
    d.deal_id,
    d.company_name,
    d.create_date,
    d.close_date,
    d.stage,
    COUNT(ds.deal_id) as snapshot_appearances
FROM deals d
LEFT JOIN deals_snapshot ds ON d.deal_id = ds.deal_id
    AND ds.fiscal_quarter = 'FY2027 Q1'
WHERE d.pipeline_id = 'default'
  AND d.stage IN (/* won stage IDs */)
  AND d.close_date >= '2026-05-01'
  AND d.close_date <= '2026-07-31'
GROUP BY d.deal_id, d.company_name, d.create_date, d.close_date, d.stage
HAVING COUNT(ds.deal_id) = 0;
```

**Expected:** 0 rows (all wins appear in snapshots)
**If found:** 24+ deals → confirms snapshot grid missing most deals

---

## Recommended Fixes

### Short-term: Document Limitations

1. **Update metrics registry** to note week-3 methodology captures only 16.7% of eventual wins
2. **Flag conversion rates** as "provisional - denominator systematically undercount"
3. **Caveat all segment-specific rates** due to small n and methodology issues

### Medium-term: Fix Snapshot Job

1. **Root cause snapshot grid gaps** (see Investigation Steps above)
2. **Ensure snapshot job runs consistently** every week for all quarters
3. **Backfill missing weeks** if source data (HubSpot history) available
   - Q3 weeks 3-13
   - Q4 weeks 1-3
   - Validate Q1 weeks 3-13 (rows exist but data quality suspect)

### Long-term: Alternative Methodology

If snapshot grid cannot be reliably fixed:

**Option 1: Use `create_date` as proxy for qualification timing**
- Assumes deals qualify shortly after creation
- Introduces unverified assumption (this session spent eliminating such assumptions)

**Option 2: Track qualification in `deals` table directly**
- Add `first_qualified_date` column
- Populate via HubSpot webhook or nightly ETL
- More reliable than retroactive snapshot reconstruction

**Option 3: Abandon cohort-by-qualification-week**
- Revert to "qualified at any point in quarter" as denominator
- Simpler, but loses timing-based insight
- Cannot distinguish early vs late qualification patterns

---

## Owner & Timeline

**Owner:** Data Engineering / RevOps Infra
**Timeline:**
- Investigation: 1 week
- Fix implementation: 2 weeks
- Backfill (if feasible): 1 week
- Validation: 1 week

**Total:** ~5 weeks to resolution

**Interim state:** Use fixed week-3 methodology with documented caveats

---

## Related Files

- `conversion_by_qualification_week.py` - Initial implementation (blocked by data gaps)
- `conversion_by_qualification_week_q1.py` - Q1-only attempt (revealed data quality issue)
- `test_hubspot_history_feasibility.py` - HubSpot API backfill attempt (failed)
- `reconcile_all_quarters_correct.py` - Win count reconciliation (revealed 83.3% exclusion)
- `analyze_qualification_timing.py` - Initial attempt (incomplete data)

---

## Decision Log

**2026-09-04:** Attempted cohort-by-qualification-week methodology
**2026-09-04:** Discovered Q3/Q4 snapshot grid gaps
**2026-09-04:** Tested HubSpot property history API backfill → Not feasible
**2026-09-04:** Attempted Q1-only analysis → Revealed Q1 data quality issues
**2026-09-04:** **DECISION: Document issue, flag for infra team, proceed with fixed week-3 methodology with caveats**

---

## Status: OPEN

Awaiting infra team investigation and resolution.
