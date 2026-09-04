# Data Quality Exclusions

## Summary

8 deals identified with impossible timelines (0-day or negative create-to-close cycles) that should be excluded from ALL metrics calculations, not just conversion_rate_prospective.

## The 8 Deals

| Company | Deal ID | Create Date | Close Date | Cycle Days | Error Type |
|---------|---------|-------------|------------|------------|------------|
| Make | 5790911698 | 2026-03-10 | 2026-01-28 | -41 | NEGATIVE_CYCLE |
| Quizlet | 5681417580 | 2026-02-23 | 2026-01-13 | -41 | NEGATIVE_CYCLE |
| BESTSECRET | 5755377954 | 2026-03-04 | 2026-02-19 | -13 | NEGATIVE_CYCLE |
| Bluesky | 5369635703 | 2026-01-12 | 2026-01-12 | 0 | ZERO_DAY |
| Bluesky | 6212201883 | 2026-07-07 | 2026-07-07 | 0 | ZERO_DAY |
| LeoVegas | 6089749648 | 2026-06-05 | 2026-06-05 | 0 | ZERO_DAY |
| Quizlet | 5401072420 | 2026-01-15 | 2026-01-15 | 0 | ZERO_DAY |
| knowunity.ai | 6023407620 | 2026-05-13 | 2026-05-13 | 0 | ZERO_DAY |

## Root Cause

Scattered manual entry errors, not a systematic import:
- No timestamp clustering (not bulk import)
- No source fields populated
- Bluesky and Quizlet each appear twice (repeat pattern)

Negative cycles are physically impossible data corruption. Zero-day cycles likely represent backdated entries where only one date was known.

## Infrastructure Created

### Migration: `scripts/migrations/053_add_data_quality_exclusions.sql`

Creates `data_quality_exclusions` table and pre-populates with the 8 deals.

**To apply:**
1. Go to Supabase project → SQL Editor
2. Paste contents of `scripts/migrations/053_add_data_quality_exclusions.sql`
3. Execute
4. Run `verify_data_quality_exclusions.py` to confirm

### Verification: `verify_data_quality_exclusions.py`

Checks that:
- Table exists
- All 8 deals are present
- Queries correctly exclude these deals

## Usage in Queries

**All metrics queries should exclude these deals:**

```python
# Method 1: Subquery exclusion
deals = supabase.table('deals') \
    .select('*') \
    .not_.in_('deal_id', [
        # Query exclusions dynamically
        supabase.table('data_quality_exclusions').select('deal_id').execute().data
    ]) \
    .execute()

# Method 2: Manual list (for performance)
EXCLUDED_DEAL_IDS = [
    '5790911698',  # Make (negative cycle)
    '5681417580',  # Quizlet (negative cycle)
    '5755377954',  # BESTSECRET (negative cycle)
    '5369635703',  # Bluesky (zero-day)
    '6212201883',  # Bluesky (zero-day, 2nd)
    '6089749648',  # LeoVegas (zero-day)
    '5401072420',  # Quizlet (zero-day, 2nd)
    '6023407620',  # knowunity.ai (zero-day)
]

deals = supabase.table('deals') \
    .select('*') \
    .not_.in_('deal_id', EXCLUDED_DEAL_IDS) \
    .execute()
```

**SQL:**
```sql
SELECT *
FROM deals
WHERE deal_id NOT IN (SELECT deal_id FROM data_quality_exclusions)
```

## Why This Matters

These 8 deals represent 11.1% of total wins (72). If not excluded:
- Conversion rate denominators include impossible data
- Win rate calculations are polluted
- Time-to-close metrics include negative values
- Segment analysis includes corrupt records

**Impact on conversion_rate_prospective:** Already excluded (captured in analysis as data_quality_errors category). This table extends that exclusion to ALL metrics queries.

## Periodic Review

Check for new data quality issues quarterly:

```bash
python audit_data_quality_errors.py
```

If new deals appear with same pattern, add to `data_quality_exclusions` table.

## Fields in data_quality_exclusions Table

- `deal_id` (PK): HubSpot deal ID
- `reason`: ERROR_TYPE (NEGATIVE_CYCLE, ZERO_DAY_CYCLE, NULL_DATES)
- `cycle_days`: Days between create and close
- `create_date`, `close_date`, `company_name`: Reference data
- `notes`: Human-readable explanation
- `reviewed`: Boolean flag for manual review status
- `reviewed_date`, `reviewed_by`: Audit trail

## Related Files

- `audit_data_quality_errors.py`: Identifies data quality issues
- `scripts/migrations/053_add_data_quality_exclusions.sql`: Table creation + initial data
- `verify_data_quality_exclusions.py`: Post-migration verification
- `FINAL_45_MISSING_WINS_ROOT_CAUSES.md`: Category 2 documents these 8 deals
