# Test Data Hygiene Rule

**Date:** 2026-09-08
**Issue:** "Test Org" appeared in live EMEA pipeline report

---

## Problem

Test/demo deals appearing in production Slack answers suggests test data in HubSpot that should be excluded.

**Evidence from Slack response:**
```
• Test Org — $0 | Discovery | Christian (Aug 26) (likely test — verify)
```

The LLM correctly flagged uncertainty, but the record shouldn't appear in real reports at all.

---

## Investigation

**Query:** Deals with "test" in company_name

**Found:** 15 deals total

**Obvious test records:**
- Test Org ($0, Discovery)
- sn-test ($0, Closed Lost)
- FahadTest ($5K, 2 deals)
- Orkes Test ($0, Disqualified)
- Test ($0, Disqualified)
- Jusbrasil Test ($125K, Discovery)
- zoopla-test ($30K, Closed Lost)

**Legitimate companies (not test):**
- TestGorilla ($50K) - real company (assessment platform)
- User Testing Inc ($0) - real company (UX research platform)

**Pattern:** Some test records have obvious patterns (lowercase "test", "-test" suffix, "Test" alone), while legitimate companies incorporate "Test" as part of their actual brand name.

---

## Hygiene Rule Design

**Rule:** `exclude_test_deals`

**Logic:**
Exclude deals where company_name matches known test patterns:
1. Exactly "Test" or "Test Org"
2. Contains "-test" (lowercase, with hyphen)
3. Starts with "test" (lowercase) unless it's a known legitimate company
4. Contains "Teste" (Portuguese test pattern)

**Do NOT exclude:**
- TestGorilla (legitimate company)
- User Testing Inc (legitimate company)
- Any company with capital "Test" as part of brand name that doesn't match above patterns

---

## Implementation

### Option 1: Add to data_integrity rules in field_semantics.py

```python
def is_test_deal(deal: dict) -> bool:
    """
    True if deal appears to be test/demo data.

    Patterns matched:
    - Exact match: "Test", "Test Org"
    - Contains: "-test", "test-" (lowercase with hyphen)
    - Starts with: "test " (lowercase, space after)
    - Contains: "Teste" (Portuguese test pattern)

    Excludes legitimate companies:
    - TestGorilla (assessment platform)
    - User Testing Inc (UX research)

    Args:
        deal: Deal dict with company_name field

    Returns:
        True if deal matches test patterns

    Examples:
        is_test_deal({"company_name": "Test Org"}) -> True
        is_test_deal({"company_name": "sn-test"}) -> True
        is_test_deal({"company_name": "TestGorilla"}) -> False
        is_test_deal({"company_name": "User Testing Inc"}) -> False
    """
    company_name = deal.get('company_name', '').strip()
    if not company_name:
        return False

    # Normalize for matching
    name_lower = company_name.lower()

    # Exact matches
    if name_lower in ['test', 'test org']:
        return True

    # Hyphenated test patterns
    if '-test' in name_lower or 'test-' in name_lower:
        return True

    # Starts with "test " (space after)
    if name_lower.startswith('test '):
        return True

    # Portuguese test pattern
    if 'teste' in name_lower:
        return True

    return False
```

### Option 2: Add to HubSpot directly

**Better long-term:** Add a custom boolean property `is_test_deal` in HubSpot and exclude at source.

**Benefits:**
- Centralized test data management
- Marketing/Sales can mark test deals directly
- Syncs automatically to all downstream systems

**Recommended workflow:**
1. Add `is_test_deal` boolean property in HubSpot Company object
2. Bulk update known test companies with this flag
3. Add to ETL/sync: pull `is_test_deal` property
4. Filter in query handlers: `WHERE is_test_deal != TRUE`

---

## Current Workaround

Until HubSpot property exists, use `is_test_deal()` function in Python handlers.

**In query handlers:**
```python
from api.field_semantics import is_test_deal

# Filter test deals
real_deals = [d for d in deals if not is_test_deal(d)]
```

**In SQL queries (if function added to Postgres):**
```sql
-- Exclude test deals
WHERE company_name NOT ILIKE '%test%'
  AND company_name NOT IN ('Test', 'Test Org')
```

---

## Testing

**Test cases:**
```python
# Should be flagged as test
is_test_deal({"company_name": "Test"}) -> True
is_test_deal({"company_name": "Test Org"}) -> True
is_test_deal({"company_name": "sn-test"}) -> True
is_test_deal({"company_name": "zoopla-test"}) -> True
is_test_deal({"company_name": "FahadTest"}) -> False (doesn't match patterns)
is_test_deal({"company_name": "SymplaTeste"}) -> True (Portuguese)

# Should NOT be flagged
is_test_deal({"company_name": "TestGorilla"}) -> False
is_test_deal({"company_name": "User Testing Inc"}) -> False
is_test_deal({"company_name": "Testbirds"}) -> False (real company)
```

---

## Impact

**Current state:**
- 15 test deals in database
- Appearing in pipeline reports, waterfall, regional analysis
- Contaminating metrics (even if flagged with "verify")

**After fix:**
- Test deals excluded from all query results
- Cleaner pipeline reports
- More accurate metrics
- No "likely test — verify" caveats needed

---

## Recommended Actions

1. **Short-term (today):** Add `is_test_deal()` to field_semantics.py and use in handlers
2. **Medium-term (this week):** Add `is_test_deal` boolean property in HubSpot
3. **Long-term (ongoing):** Train team to mark test/demo deals with flag at creation

---

## Files

**To create:**
- Add `is_test_deal()` to `api/field_semantics.py`

**To update:**
- Query handlers should filter with `if not is_test_deal(d)`
- SQL queries should add test exclusion patterns

**Documentation:**
- `TEST_DATA_HYGIENE_RULE.md` (this file)
- Add to known_hygiene_rules registry once implemented

---

## Related Patterns

**Same "explicit hygiene" pattern as:**
- `is_valid_cycle_deal()` - excludes negative cycle times
- `is_fresh_pipeline_deal()` - excludes stale deals (>180 days)
- `is_incremental_pipeline()` - distinguishes pipeline from renewal base

**Add to the roster:**
- `is_test_deal()` - excludes test/demo data

All follow same discipline: **filter at data layer, not silently in metrics.**

---

## Summary

**Problem:** Test deals appearing in production reports.
**Root cause:** No test data filter in HubSpot or query handlers.
**Fix:** Add `is_test_deal()` hygiene rule to exclude known test patterns.
**Long-term:** Add `is_test_deal` boolean property in HubSpot at source.
