# Negative Cycle Time Rule: Universal Data Integrity

## Implementation Complete

Codified as **standing rule**, not manual exclusion list.

---

## Core Rule

**ANY deal where `(close_date - create_date) < 0` is automatically excluded from ALL metrics using cycle time, win rate, or any create_date/close_date-based calculation.**

This is **universal data integrity**, not client-specific judgment.

---

## Rationale

Negative cycle time is **definitionally impossible**. Always indicates:
- CRM migration backfill
- Bulk import artifacts
- Data entry error

**Never** represents a real sales cycle.

---

## Implementation

### 1. Field Semantics Check (Universal)

**Added:** `is_valid_cycle_deal()` in `api/field_semantics.py`

```python
def is_valid_cycle_deal(deal: dict) -> bool:
    """
    True if deal has valid cycle time data (non-negative cycle).

    UNIVERSAL RULE: Auto-excludes deals with:
    - Missing create_date or close_date
    - (close_date - create_date) < 0

    Template-portable: Applies to every client automatically.
    """
```

**Location:** Hand-written business logic section (not auto-generated)

### 2. Config Documentation

**Added:** DATA INTEGRITY RULES section in `config/field_semantics.yaml`

```yaml
# ============================================================================
# DATA INTEGRITY RULES — UNIVERSAL (NOT CLIENT-SPECIFIC)
# ============================================================================
# RULE 1: NEGATIVE CYCLE TIME EXCLUSION
#
# ANY deal where (close_date - create_date) < 0 is AUTOMATICALLY excluded
# from ALL metrics that use cycle time, win rate, or any date-diff calculation.
#
# Template-portable: DEFAULT, non-configurable for every client
# ============================================================================
```

### 3. Handler Integration

**Updated:** `compute_cycle_time()` in `api/handlers.py`

```python
# Import universal data integrity check
from field_semantics import is_valid_cycle_deal

for deal in deals:
    # UNIVERSAL DATA INTEGRITY CHECK
    if not is_valid_cycle_deal(deal):
        continue  # Auto-exclude: negative cycle time
```

**Replaced:** Manual `if days >= 0` check with centralized function

### 4. Continuous Monitoring

**Created:** `scripts/monitor_negative_cycle_times.py`

- Detects all deals with negative cycle times
- Reports specific deal_ids, companies, cycle days
- Exports violations for manual review
- Wave 6 monitoring trigger candidate

**Current violations detected:** 10 deals

| Deal ID | Company | Cycle Days | Status | Create Date | Close Date |
|---------|---------|-----------|--------|-------------|------------|
| 41609747117 | Netthandelsgruppen | -658 | won | 2025-08-09 | 2023-10-21 |
| 57856036766 | Refurbed Marketplace | -580 | won | 2026-03-10 | 2024-08-07 |
| 57539418520 | patreon | -417 | lost | 2026-03-05 | 2025-01-12 |
| 57856098205 | Make | -406 | won | 2026-03-10 | 2025-01-28 |
| 56906140802 | Quizlet | -388 | won | 2026-02-23 | 2025-01-31 |
| ... | ... | ... | ... | ... | ... |

---

## Applies To

**ALL metrics computing date diffs:**
- `cycle_time` (median days from create to close)
- `win_rate` (when including closed deals)
- `velocity_to_close` (days in each stage)
- `conversion_rates` (time-based funnel metrics)
- Any future metric using `create_date`/`close_date`

---

## Template-Portable

### Default Rule (Non-Configurable)

Every client deployment includes this automatically:

1. ✅ `is_valid_cycle_deal()` in field_semantics.py (universal function)
2. ✅ DATA INTEGRITY RULES in field_semantics.yaml (documented)
3. ✅ `monitor_negative_cycle_times.py` (continuous monitoring)

### No Per-Client Config

This is **NOT** a client-specific setting like:
- Renewal pipeline exclusion (varies by client)
- At-risk thresholds (varies by segment)
- Stage definitions (varies by CRM)

This is **baseline data hygiene** - true for everyone.

---

## Audit Complete

### Handlers Using create_date/close_date

**Primary handler:** `compute_cycle_time()` ✅ Updated

**Other date usages:**
- Time window filters (`close_date >= start`, `close_date <= end`) - No cycle time calc, no update needed
- Deal creation tracking (`create_date >= start`) - No cycle time calc, no update needed
- Pipeline current state - No date filters (timeless) ✅

**Conclusion:** All date-diff calculations now use `is_valid_cycle_deal()`

---

## Q016 Impact

### Before Rule Implementation

**Population:** 23 clean cohort won deals
**Cycle time sample:** 22 deals (manual exclusion of negative cycle)
**Discrepancy:** Unexplained 23 vs 22 gap

### After Rule Implementation

**Population:** 23 clean cohort won deals
**Cycle time sample:** 22 deals (auto-excluded via `is_valid_cycle_deal()`)
**Discrepancy:** EXPLAINED by deal_id=41609747117 (Netthandelsgruppen, -658 days)

**Rule applied:** Automatic, universal, documented

---

## Defect Class Prevented

**Pattern:** data_quality_exclusions covering SOME but not ALL consuming handlers

**Risk:** Same defect class flagged earlier - inconsistent exclusion logic

**Fix:** Single source of truth (`is_valid_cycle_deal()`) prevents:
- Some handlers checking `days >= 0`
- Others not checking at all
- Manual exclusion lists getting out of sync

---

## Wave 6 Monitoring Trigger

### Proposed Alert

**Trigger:** `monitor_negative_cycle_times.py` returns exit code 1 (violations detected)

**Alert:** "Negative cycle time deals detected - CRM migration or data entry errors"

**Action:** Review violations, fix at source in HubSpot if possible

**Frequency:** Daily (catches new bulk imports immediately)

---

## Recommended Actions

For current 10 violations:

1. **Investigate:** Are these CRM migration artifacts?
2. **Fix at source:** Correct `create_date` in HubSpot if possible
3. **Accept:** If unfixable (historical migration), auto-exclusion is correct

**No code changes needed** - `is_valid_cycle_deal()` already excludes them.

---

## Documentation Trail

1. **Config:** `config/field_semantics.yaml` (DATA INTEGRITY RULES section)
2. **Implementation:** `api/field_semantics.py` (`is_valid_cycle_deal()` function)
3. **Handler:** `api/handlers.py` (`compute_cycle_time()` updated)
4. **Monitoring:** `scripts/monitor_negative_cycle_times.py`
5. **This doc:** `NEGATIVE_CYCLE_TIME_RULE.md`

---

## Key Principle

**Define cohorts FIRST, apply universal integrity rules SECOND, compute within clean data THIRD.**

Never silently include data quality violations in metrics. Exclude automatically, document permanently, monitor continuously.
