**# Cross-Quarter Qualification Lookup

## Summary

3 deals (4.2% of total wins) were excluded from conversion_rate_prospective because they were created in one quarter but closed in another. Their qualification snapshots exist in the _prior_ quarter's data, but the original methodology only checked the close quarter.

## The 3 Carry-Over Deals

| Company | Deal ID | Create Date | Close Date | Create Quarter | Close Quarter |
|---------|---------|-------------|------------|----------------|---------------|
| Fellow | TBD | 2025-08-09 | 2025-11-07 | FY2026 Q2 | FY2026 Q3 |
| Yeet! | TBD | 2026-01-27 | 2026-03-02 | FY2026 Q3 | FY2026 Q4 |
| Wellhub | TBD | 2026-04-30 | 2026-05-23 | (boundary) | FY2027 Q1 |

## Problem

Original logic:
```python
# For a deal closed in Q3:
snapshots = get_snapshots(fiscal_quarter='FY2026 Q3', deal_id=deal_id)
```

If the deal was created in Q2, its early snapshots are in Q2's `deals_snapshot` rows, not Q3's. The deal won't be found.

## Solution

New logic:
```python
from scripts.analytics.cross_quarter_qualification import (
    find_qualification_week_cross_quarter
)

# For a deal closed in Q3 but created in Q2:
result = find_qualification_week_cross_quarter(
    supabase,
    deal_id,
    create_date='2025-08-09',  # Q2
    close_date='2025-11-07',   # Q3
    close_quarter='FY2026 Q3',
    excluded_pipelines,
    stage_cfg
)

# Returns: (3, 'FY2026 Q2')
#   - Qualified in week 3
#   - Qualification happened in Q2 (prior quarter)
```

The function:
1. Determines which quarters to check based on `create_date` and `close_quarter`
2. Searches snapshots in chronological order (Q2, then Q3)
3. Returns the _first_ qualified snapshot, regardless of which quarter it came from
4. Includes the qualification quarter in the result

## Implementation

### Core Functions

**`scripts/analytics/cross_quarter_qualification.py`**

```python
def get_fiscal_quarter_for_date(date_str: str) -> Optional[str]:
    """Map a date to its fiscal quarter."""

def get_quarters_to_check(create_date: str, close_quarter: str) -> List[str]:
    """
    Determine which quarters to search for qualification snapshots.

    Returns list in chronological order: ['FY2026 Q2', 'FY2026 Q3']
    """

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
    """
```

### Usage in Conversion Script

**`conversion_by_qualification_week_CROSS_QUARTER.py`**

After processing in-quarter qualifications, checks for carry-overs:

```python
# Get all wins in the quarter
wins = get_wins_in_quarter(quarter_id)

for deal in wins:
    # Skip if already captured
    if deal_id in already_qualified:
        continue

    # Check if created before quarter (carry-over candidate)
    if deal.create_date < quarter_start:
        result = find_qualification_week_cross_quarter(...)

        if result:
            # Add to qualified cohort and wins
            qualification_week, qualification_quarter = result
```

## Impact

**Before (without cross-quarter lookup):**
- Qualified: 376
- Won: 27
- Rate: 7.2%

**After (with cross-quarter lookup):**
- Qualified: 376 + 3 = 379
- Won: 27 + 3 = 30
- Rate: 7.9% (estimated)

The 3 carry-over deals now correctly contribute to:
- Denominator: included in their qualification week cohorts (from prior quarter)
- Numerator: included in their close quarter wins

## Why This Matters

Without cross-quarter lookup:
- Q3 win rate calculation excludes Fellow (closed in Q3 but qualified in Q2)
- Methodologically inconsistent: some Q3 wins are excluded just because they started in Q2
- Underestimates conversion for deals with longer cycles that span quarters

With cross-quarter lookup:
- Complete: all wins closed in Q3 are included if they ever qualified
- Consistent: qualification timing is accurately captured regardless of quarter boundaries
- Fair: long-cycle deals aren't penalized for spanning quarters

## Edge Cases Handled

1. **Deal created and closed in same quarter:** Only checks that quarter (no overhead)
2. **Deal spans 3+ quarters:** Checks all intermediate quarters in order
3. **Deal created before tracking period:** Returns None (can't determine qualification)
4. **Deal closed before created:** Returns None (data quality error)

## Testing

Run the cross-quarter conversion script:

```bash
python conversion_by_qualification_week_CROSS_QUARTER.py
```

Expected output:
- Should show `+3 wins` compared to previous version
- Should identify Fellow, Yeet!, and Wellhub specifically
- Should print: "✓ Cross-quarter lookup working correctly"

## Integration Path

To integrate into production:

1. **Test thoroughly:**
   ```bash
   python conversion_by_qualification_week_CROSS_QUARTER.py
   ```

2. **Verify the 3 deals:**
   - Check logs for "Carry-over deals qualified: 3"
   - Confirm companies are Fellow, Yeet!, Wellhub

3. **Replace existing script:**
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
       value: 0.079  # 30/379 (updated with carry-over deals)
       numerator: 30
       denominator: 379
     computation_script: conversion_by_qualification_week_ALL_QUARTERS_FIXED.py
     note: Includes cross-quarter lookup for carry-over deals (see CROSS_QUARTER_QUALIFICATION_README.md)
   ```

## Alternative: Keep Separate

If you prefer to track carry-over deals separately rather than blend them:

```yaml
conversion_rate_prospective:
  in_quarter_only:
    value: 0.072
    numerator: 27
    denominator: 376

  with_carry_over:
    value: 0.079
    numerator: 30
    denominator: 379

  recommended: with_carry_over
  note: "in_quarter_only excludes 3 carry-over deals (Fellow, Yeet!, Wellhub)"
```

## Related Files

- `scripts/analytics/cross_quarter_qualification.py`: Core logic
- `conversion_by_qualification_week_CROSS_QUARTER.py`: Enhanced conversion script
- `FINAL_45_MISSING_WINS_ROOT_CAUSES.md`: Category 5 documents these 3 deals
- `config/metrics.yaml`: Update verified_result after testing

## Recommendation

**Implement cross-quarter lookup** - it's methodologically more accurate. The 3 deals represent real conversions that shouldn't be excluded just because they span quarter boundaries.

The logic is clean, performant (only checks prior quarters when `create_date < quarter_start`), and handles edge cases gracefully.
