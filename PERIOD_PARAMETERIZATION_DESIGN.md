# Period Parameterization Design

**Date:** 2026-09-08
**Status:** Design approved, ready for implementation
**Goal:** Make conversion_rate_prospective and cycle_time reusable building blocks

---

## Architecture Principle

**All period types reduce to date ranges.**

Instead of:
```python
# BAD: Special cases per period type
conversion_rate_prospective(quarter="Q1 2026")
cycle_time(window_mode="rolling", rolling_months=12)
cycle_time(window_mode="all_time")
```

Use:
```python
# GOOD: Single uniform interface
conversion_rate_prospective(period={"start": "2026-01-01", "end": "2026-03-31"})
cycle_time(period={"start": "2026-01-01", "end": "2026-03-31"})
cycle_time(period={"start": None, "end": None})  # all_time
```

**Rationale:**
- all_time, rolling_12mo, Q1_2026, arbitrary ranges are all just {start, end} pairs
- No special-case code paths per period type
- Makes metrics reusable for ANY future composite metric
- Date boundary is the ONLY thing parameterized (hygiene rules unchanged)

---

## Function Signatures

### conversion_rate_prospective

```python
def conversion_rate_prospective(
    period: dict = None,  # {"start": date, "end": date} or None for all_time
    pipeline_id: str = "default",
    exclude_renewals: bool = True,
    exclude_invalid_cycles: bool = True
) -> dict:
    """
    Compute prospective conversion rate for a given period.

    Args:
        period: Date range {"start": "YYYY-MM-DD", "end": "YYYY-MM-DD"}
                If None or {"start": None, "end": None}, computes all_time
        pipeline_id: Which pipeline to analyze (default: "default")
        exclude_renewals: Apply is_renewal_base hygiene rule (default: True)
        exclude_invalid_cycles: Apply is_valid_cycle_deal hygiene rule (default: True)

    Returns:
        {
            "rate": float,  # win_rate as decimal (0.072 = 7.2%)
            "numerator": int,  # won deals
            "denominator": int,  # qualified deals
            "period": {"start": date, "end": date},
            "exclusions": {"renewals": int, "invalid_cycles": int, "data_quality": int}
        }
    """
```

### cycle_time

```python
def cycle_time(
    period: dict = None,  # {"start": date, "end": date} or None for all_time
    pipeline_id: str = "default",
    exclude_renewals: bool = True,
    exclude_invalid_cycles: bool = True,
    aggregation: str = "median"  # median or mean
) -> dict:
    """
    Compute sales cycle time for won deals in a given period.

    Args:
        period: Date range {"start": "YYYY-MM-DD", "end": "YYYY-MM-DD"}
                If None or {"start": None, "end": None}, computes all_time
        pipeline_id: Which pipeline to analyze (default: "default")
        exclude_renewals: Apply is_renewal_base hygiene rule (default: True)
        exclude_invalid_cycles: Apply is_valid_cycle_deal hygiene rule (default: True)
        aggregation: "median" or "mean" (default: median)

    Returns:
        {
            "days": float,  # median or mean cycle time
            "sample_size": int,  # deals in calculation
            "period": {"start": date, "end": date},
            "distribution": {"p25": float, "p50": float, "p75": float},
            "exclusions": {"renewals": int, "invalid_cycles": int}
        }
    """
```

---

## Period Construction Helpers

**Utility functions** to construct {start, end} from various period types:

```python
def period_all_time():
    """All-time period (no date filter)."""
    return {"start": None, "end": None}

def period_rolling(months: int, as_of: str = None):
    """Rolling N-month window from as_of date (default: today)."""
    as_of_date = datetime.fromisoformat(as_of) if as_of else datetime.now()
    start_date = as_of_date - timedelta(days=months * 30)
    return {
        "start": start_date.strftime("%Y-%m-%d"),
        "end": as_of_date.strftime("%Y-%m-%d")
    }

def period_quarter(quarter: str):
    """Fiscal quarter (e.g., 'Q1 2026', 'FY2027 Q3')."""
    # Parse quarter string and return date range
    # Q1 2026 → Jan 1 - Mar 31, 2026
    # FY2027 Q3 → Aug 1 - Oct 31, 2026 (based on fiscal calendar)
    ...
    return {"start": start_date, "end": end_date}

def period_custom(start: str, end: str):
    """Custom date range."""
    return {"start": start, "end": end}
```

**Usage:**
```python
# All equivalent invocations for Q1 2026:
conversion_rate_prospective(period=period_quarter("Q1 2026"))
conversion_rate_prospective(period={"start": "2026-01-01", "end": "2026-03-31"})

# Rolling 12 months:
cycle_time(period=period_rolling(months=12))

# All-time:
conversion_rate_prospective(period=period_all_time())
conversion_rate_prospective(period=None)  # default
```

---

## Implementation Plan

### Phase 1: Create Parameterized Functions

**Files to create:**
- `scripts/metrics/conversion_rate.py` - New parameterized implementation
- `scripts/metrics/cycle_time.py` - New parameterized implementation
- `scripts/metrics/period_utils.py` - Period construction helpers

**Key changes:**
1. **Date filtering:** Apply period filter to close_date (for both metrics)
2. **Hygiene rules:** Unchanged - still call is_renewal_base(), is_valid_cycle_deal()
3. **Single code path:** No if/else per period type - just filter on date range
4. **Return full context:** Include numerator/denominator, sample_size, exclusions

### Phase 2: Regression Check

**Verify existing all_time values reproduce exactly:**

```python
# Test 1: conversion_rate_prospective all_time
result = conversion_rate_prospective(period=None)
assert result["rate"] == 0.072  # 7.2%
assert result["numerator"] == 27
assert result["denominator"] == 376
print("✓ conversion_rate_prospective all_time: EXACT MATCH")

# Test 2: cycle_time all_time
result = cycle_time(period=None)
assert result["days"] == 52
assert result["sample_size"] == 22
print("✓ cycle_time all_time: EXACT MATCH")
```

**Script:** `scripts/verify_period_parameterization.py`

**If mismatch:** Debug until exact match achieved (regression gate)

### Phase 3: Update Metrics Registry

**Update config/metrics.yaml:**

```yaml
conversion_rate_prospective:
  label: Prospective Conversion Rate
  formula: |
    parameterized_function(period={start, end})

    Population: deals that FIRST reached qualified stage within period,
                filtered by close_date within same period

    Period types (all reduce to date ranges):
    - all_time: period=None or {"start": None, "end": None}
    - quarter: period=period_quarter("Q1 2026")
    - rolling: period=period_rolling(months=12)
    - custom: period={"start": "2026-01-01", "end": "2026-03-31"}

  verified:
    all_time:
      rate: 0.072
      numerator: 27
      denominator: 376
      period: {"start": null, "end": null}
      verified_date: "2026-09-04"
      computation_method: "parameterized_function(period=None)"

cycle_time:
  label: Sales Cycle Time
  formula: |
    parameterized_function(period={start, end})

    MEDIAN((close_date - create_date).days) WHERE days >= 0
    Filtered to won deals with close_date in period

    Period types (all reduce to date ranges):
    - all_time: period=None
    - rolling: period=period_rolling(months=12)
    - quarter: period=period_quarter("Q1 2026")

  verified:
    all_time:
      days: 52
      sample_size: 22
      period: {"start": null, "end": null}
      verified_date: "2026-09-06"
      computation_method: "parameterized_function(period=None)"
```

### Phase 4: Test Per-Quarter Calculations

**Verify Q1 and Q2 2026 separately:**

```python
# Q1 2026
q1_conversion = conversion_rate_prospective(period=period_quarter("Q1 2026"))
q1_cycle = cycle_time(period=period_quarter("Q1 2026"))

# Q2 2026
q2_conversion = conversion_rate_prospective(period=period_quarter("Q2 2026"))
q2_cycle = cycle_time(period=period_quarter("Q2 2026"))

# Validate sample sizes reasonable (not too thin)
assert q1_conversion["denominator"] >= 10  # min evidence threshold
assert q1_cycle["sample_size"] >= 5
```

**Expected behavior:**
- Q1 + Q2 combined should NOT equal all_time (because all_time includes Q3, Q4, etc.)
- Per-quarter rates should be in reasonable range (not wildly different from pooled)
- Sample sizes may trigger warnings if below threshold (expected)

---

## Hygiene Rules: Unchanged

**These rules apply BEFORE date filtering:**

1. **is_renewal_base()** - Exclude renewal pipeline deals
2. **is_valid_cycle_deal()** - Exclude negative cycle time
3. **data_quality_exclusions** - Exclude flagged deals (conversion_rate only)

**Logic:**
```python
# 1. Load all deals (no date filter yet)
all_deals = fetch_deals(pipeline_id=pipeline_id)

# 2. Apply hygiene rules (population filter)
clean_deals = [
    deal for deal in all_deals
    if (not exclude_renewals or not is_renewal_base(deal))
    and (not exclude_invalid_cycles or is_valid_cycle_deal(deal))
]

# 3. Apply period filter (date boundary)
if period and period.get("start"):
    clean_deals = [d for d in clean_deals if d.close_date >= period["start"]]
if period and period.get("end"):
    clean_deals = [d for d in clean_deals if d.close_date <= period["end"]]

# 4. Compute metric on filtered population
```

**Key principle:** Hygiene rules are population filters. Period is a date boundary. Both are independent dimensions.

---

## Sales Velocity Composition (After Refactor)

**Once parameterization complete, Sales Velocity becomes:**

```python
def new_business_sales_velocity(period: dict) -> dict:
    """
    Sales Velocity = (Opps) × (Deal Size) × (Win Rate) / (Cycle Time)
    """
    # Count opportunities reaching qualified stage in period
    opps = count_qualified_deals(period=period)

    # Average deal size of WON deals in period
    won_deals = fetch_won_deals(period=period, exclude_renewals=True)
    avg_deal_size = mean([d.incremental_arr for d in won_deals])

    # Win rate using parameterized conversion_rate_prospective
    win_rate_result = conversion_rate_prospective(
        period=period,
        pipeline_id="default",
        exclude_renewals=True
    )
    win_rate = win_rate_result["rate"]

    # Cycle time using parameterized cycle_time
    cycle_result = cycle_time(
        period=period,
        pipeline_id="default",
        exclude_renewals=True
    )
    cycle_days = cycle_result["days"]

    # Velocity calculation
    velocity = (opps * avg_deal_size * win_rate) / cycle_days

    return {
        "velocity": velocity,
        "period": period,
        "components": {
            "opportunities": opps,
            "avg_deal_size": avg_deal_size,
            "win_rate": win_rate,
            "cycle_time": cycle_days
        },
        "building_blocks": {
            "conversion_rate": win_rate_result,
            "cycle_time": cycle_result
        }
    }
```

**This is true composition** - reusing validated methodologies with their hygiene rules intact.

---

## Regression Gate

**Before considering refactor complete:**

```bash
python scripts/verify_period_parameterization.py
```

**Must output:**
```
=================================================================
PERIOD PARAMETERIZATION REGRESSION CHECK
=================================================================

Testing conversion_rate_prospective(period=None)...
  Expected: 0.072 (27/376)
  Actual:   0.072 (27/376)
  ✓ EXACT MATCH

Testing cycle_time(period=None)...
  Expected: 52 days (22 deals)
  Actual:   52 days (22 deals)
  ✓ EXACT MATCH

=================================================================
✅ REGRESSION CHECK PASSED
=================================================================

All existing all_time values reproduce exactly.
Refactor did not change already-trusted behavior.
```

**If ANY mismatch:** Debug and fix before proceeding to Sales Velocity.

---

## Benefits of This Design

1. **True reusability** - Works for ANY future composite metric, not just Sales Velocity
2. **No special cases** - All period types reduce to same {start, end} interface
3. **Hygiene rules intact** - Only date boundary parameterized, exclusion logic unchanged
4. **Regression safe** - Existing all_time values must reproduce exactly
5. **Template portable** - Other clients can use same pattern

---

## Next Steps

1. ✅ Design approved
2. ⏳ Implement Phase 1 (create parameterized functions)
3. ⏳ Implement Phase 2 (regression check)
4. ⏳ Implement Phase 3 (update registry)
5. ⏳ Implement Phase 4 (test per-quarter)
6. ⏳ Build Sales Velocity using parameterized building blocks
7. ⏳ Run backtest against Jeff's ground truth

**Estimated time:** 4-6 hours total
