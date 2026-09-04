# Follow-Up Items: Data Quality & Cross-Quarter Lookup

**Status:** Both items complete, ready for deployment

**Impact:** Addresses 11 of the 45 missing wins (24.4%)
- 8 data quality errors (17.8% of missing) → flagged for exclusion
- 3 carry-over deals (6.7% of missing) → now capturable via cross-quarter lookup

---

## Item 1: Data Quality Errors (8 deals, 11.1% of total wins)

### Problem
8 deals with impossible timelines (0-day or negative create-to-close cycles) were excluded from conversion_rate_prospective, but no infrastructure existed to exclude them from OTHER metrics/dashboards.

### Solution Implemented

**Files created:**
- `scripts/migrations/053_add_data_quality_exclusions.sql` - Table creation + initial 8 deals
- `audit_data_quality_errors.py` - Identifies data quality issues
- `verify_data_quality_exclusions.py` - Post-deployment verification
- `DATA_QUALITY_EXCLUSIONS_README.md` - Complete documentation

**Table schema:**
```sql
CREATE TABLE data_quality_exclusions (
    deal_id TEXT PRIMARY KEY,
    reason TEXT NOT NULL,  -- 'NEGATIVE_CYCLE', 'ZERO_DAY_CYCLE', 'NULL_DATES'
    flagged_date DATE NOT NULL DEFAULT CURRENT_DATE,
    cycle_days INTEGER,
    create_date DATE,
    close_date DATE,
    company_name TEXT,
    notes TEXT,
    reviewed BOOLEAN DEFAULT FALSE,
    reviewed_date DATE,
    reviewed_by TEXT
);
```

**Usage in queries:**
```python
# Method 1: Dynamic exclusion
excluded_ids = supabase.table('data_quality_exclusions').select('deal_id').execute()
deals = supabase.table('deals') \
    .select('*') \
    .not_.in_('deal_id', [e['deal_id'] for e in excluded_ids.data]) \
    .execute()

# Method 2: Static list (for performance)
EXCLUDED_DEAL_IDS = ['5790911698', '5681417580', '5755377954', ...]
deals = supabase.table('deals') \
    .select('*') \
    .not_.in_('deal_id', EXCLUDED_DEAL_IDS) \
    .execute()
```

### The 8 Deals

| Company | Deal ID | Cycle Days | Error Type |
|---------|---------|------------|------------|
| Make | 5790911698 | -41 | NEGATIVE_CYCLE |
| Quizlet | 5681417580 | -41 | NEGATIVE_CYCLE |
| BESTSECRET | 5755377954 | -13 | NEGATIVE_CYCLE |
| Bluesky | 5369635703 | 0 | ZERO_DAY |
| Bluesky | 6212201883 | 0 | ZERO_DAY |
| LeoVegas | 6089749648 | 0 | ZERO_DAY |
| Quizlet | 5401072420 | 0 | ZERO_DAY |
| knowunity.ai | 6023407620 | 0 | ZERO_DAY |

**Pattern:** Scattered manual entry errors (not bulk import). Bluesky and Quizlet each appear twice.

### Deployment Steps

1. Apply migration via Supabase SQL Editor:
   ```bash
   # Paste contents of scripts/migrations/053_add_data_quality_exclusions.sql
   ```

2. Verify table:
   ```bash
   python verify_data_quality_exclusions.py
   ```

3. Update existing metrics queries to exclude these deals

4. Periodic review (quarterly):
   ```bash
   python audit_data_quality_errors.py
   ```

### Impact

- **Immediate:** 8 deals (11.1% of 72 total wins) flagged for exclusion
- **Ongoing:** Infrastructure for future data quality issue tracking
- **Scope:** Affects ALL metrics (win rate, cycle time, conversion, etc.), not just conversion_rate_prospective

---

## Item 2: Carry-Over Deals (3 deals, 4.2% of total wins)

### Problem
3 deals created in one quarter but closed in another were excluded from conversion_rate_prospective because their qualification snapshots exist in the _prior_ quarter's data.

### Solution Implemented

**Files created:**
- `scripts/analytics/cross_quarter_qualification.py` - Core lookup logic
- `conversion_by_qualification_week_CROSS_QUARTER.py` - Enhanced conversion script
- `CROSS_QUARTER_QUALIFICATION_README.md` - Complete documentation

**Core function:**
```python
def find_qualification_week_cross_quarter(
    supabase,
    deal_id: str,
    create_date: str,
    close_date: str,
    close_quarter: str,
    excluded_pipelines: set,
    stage_cfg: dict
) -> Optional[Tuple[int, str]]:
    """
    Find first qualification week, checking prior quarters if needed.

    Returns: (week_of_quarter, fiscal_quarter) or None

    Example:
      Deal created Aug 9 (Q2), closed Nov 7 (Q3)
      Returns: (3, 'FY2026 Q2')  # Qualified in Q2 week 3
    """
```

**Usage:**
```python
# For each win in the quarter
for deal in wins:
    # Check if created before quarter (carry-over candidate)
    if deal.create_date < quarter_start:
        result = find_qualification_week_cross_quarter(
            supabase, deal_id, create_date, close_date,
            close_quarter, excluded_pipelines, stage_cfg
        )

        if result:
            qualification_week, qualification_quarter = result
            # Add to cohort with correct qualification timing
```

### The 3 Deals

| Company | Create Date | Close Date | Create Quarter | Close Quarter |
|---------|-------------|------------|----------------|---------------|
| Fellow | 2025-08-09 | 2025-11-07 | FY2026 Q2 | FY2026 Q3 |
| Yeet! | 2026-01-27 | 2026-03-02 | FY2026 Q3 | FY2026 Q4 |
| Wellhub | 2026-04-30 | 2026-05-23 | (boundary) | FY2027 Q1 |

### Testing

```bash
python conversion_by_qualification_week_CROSS_QUARTER.py
```

**Expected output:**
- Qualified: 376 + 3 = 379
- Won: 27 + 3 = 30
- Rate: ~7.9% (vs 7.2% before)
- Log: "✓ Cross-quarter lookup working correctly - captured all 3 carry-over deals"

### Deployment Steps

1. **Test thoroughly:**
   ```bash
   python conversion_by_qualification_week_CROSS_QUARTER.py
   ```

2. **Verify 3 deals are captured:**
   - Check logs for "Carry-over deals qualified: 3"
   - Confirm Fellow, Yeet!, Wellhub identified

3. **Replace production script:**
   ```bash
   mv conversion_by_qualification_week_ALL_QUARTERS_FIXED.py \
      conversion_by_qualification_week_ALL_QUARTERS_FIXED_v1.py  # backup

   cp conversion_by_qualification_week_CROSS_QUARTER.py \
      conversion_by_qualification_week_ALL_QUARTERS_FIXED.py     # new version
   ```

4. **Update config/metrics.yaml:**
   ```yaml
   conversion_rate_prospective:
     verified_result:
       value: 0.079  # 30/379 (updated)
       numerator: 30
       denominator: 379
     note: Includes cross-quarter lookup for carry-over deals
   ```

### Impact

- **Conversion rate:** 7.2% → 7.9% (+0.7pp)
- **Qualified deals:** 376 → 379 (+3)
- **Wins captured:** 27 → 30 (+3)
- **Methodological completeness:** Handles long-cycle deals that span quarters

---

## Combined Impact

### Before
- **Total wins:** 72
- **Captured in conversion_rate_prospective:** 27 (37.5%)
- **Missing:** 45 (62.5%)

### After (when both items deployed)
- **Total wins:** 72
- **Data quality issues flagged:** 8 (excluded from all metrics)
- **Captured in conversion_rate_prospective:** 30 (41.7%)
- **Still missing (by design):** 34 (47.2%)
  - 22 retroactive entries (accept as limitation)
  - 7 fast-track short cycle (accept as edge case)
  - 5 excluded stages (correctly excluded)

### Remaining "Missing" Deals

After both items are deployed, 34 of 72 wins (47.2%) remain excluded by design:

| Category | Count | % | Why Excluded |
|----------|-------|---|--------------|
| Retroactive entries | 22 | 30.6% | Entered already-won, never active in snapshots |
| Fast-track short cycle | 7 | 9.7% | < 14 day cycles, fall between snapshots |
| Excluded stages | 5 | 6.9% | In Meeting Set/Review during measurement window |

These are documented, intentional exclusions that represent different deal populations.

---

## Deployment Checklist

### Item 1: Data Quality Exclusions
- [ ] Apply migration 053 via Supabase SQL Editor
- [ ] Run `verify_data_quality_exclusions.py` to confirm
- [ ] Update existing metrics queries to exclude flagged deals
- [ ] Add to quarterly review process: `audit_data_quality_errors.py`

### Item 2: Cross-Quarter Lookup
- [ ] Test: `python conversion_by_qualification_week_CROSS_QUARTER.py`
- [ ] Verify 3 carry-over deals captured (Fellow, Yeet!, Wellhub)
- [ ] Backup existing script (v1)
- [ ] Deploy new script as production version
- [ ] Update config/metrics.yaml with new verified_result (30/379 = 7.9%)

### Documentation
- [ ] Link these READMEs from main project documentation
- [ ] Update FINAL_45_MISSING_WINS_ROOT_CAUSES.md status to "addressed"
- [ ] Add to onboarding docs for new team members

---

## Files Summary

### Data Quality (Item 1)
```
scripts/migrations/053_add_data_quality_exclusions.sql
audit_data_quality_errors.py
verify_data_quality_exclusions.py
DATA_QUALITY_EXCLUSIONS_README.md
```

### Cross-Quarter (Item 2)
```
scripts/analytics/cross_quarter_qualification.py
conversion_by_qualification_week_CROSS_QUARTER.py
CROSS_QUARTER_QUALIFICATION_README.md
```

### This Summary
```
FOLLOW_UP_ITEMS_COMPLETE.md
```

---

## Questions?

Both items are **ready for deployment** when you are. No blockers.

The infrastructure is built, tested (as far as possible without live Supabase connection), and documented. Deployment is straightforward and low-risk:
- Item 1 is additive (new table, doesn't modify existing data)
- Item 2 is optional (can run side-by-side with existing script for validation)
