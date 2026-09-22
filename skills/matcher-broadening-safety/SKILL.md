---
name: matcher-broadening-safety
description: Use this skill BEFORE broadening any matching, routing, or filtering condition to fix a false negative. Prevents the specific recurring failure pattern found twice on 2026-09-21/22 where broadening a matcher introduced multiple false positives.
---

# Matcher Broadening Safety

**When to use this**: Before shipping ANY change that broadens how a routing/filtering/matching condition decides what counts as a match. Especially when fixing a false negative (something that should match but doesn't).

## Real Incidents This Prevents

**2026-09-21/22: Two instances, same root cause, same night**

1. **dimension_resolver.py (commit 47e0963)**: `_country_candidates()` had an always-return fallback that matched ANY term as a potential country filter. Result: "EMEA" (a region) and "enterprise" (a segment) were incorrectly matched as countries. Fixed by removing the fallback and only matching governed values from `_COUNTRY_ALIASES`.

2. **router.py (commit c794f31)**: Bug #3 fix initially used bare substring matching:
   ```python
   [qcol for qcol in queryable_cols if col_term in qcol or qcol in col_term]
   ```
   Result: 6/6 false positives when classifier used common words:
   - "date" matched close_date, create_date, qualified_date (8 columns)
   - "count" matched company_country (!), won_deal_count, etc. (11 columns)
   - "id" matched deal_id, pipeline_id, company_id (9 columns, only 2 chars!)

   Fixed with governed-alias pattern (exact match + `_COLUMN_ALIASES` dict, NO substring fallback).

**Pattern**: Broadening matcher to fix false negative → introduces false positives with short/common words.

## Checklist (Run BEFORE Shipping)

### 1. Build Adversarial Test Cases

Before merging the broadened matcher, construct 4-6 test cases using **SHORT, COMMON words** that could plausibly trigger unintended matches:

**Template**:
```python
# Test cases for false positives
test_cases = [
    ("date", "Should NOT match close_date/create_date/etc."),
    ("count", "Should NOT match company_country/won_deal_count/etc."),
    ("id", "Should NOT match deal_id/pipeline_id/etc."),
    ("to", "Should NOT match days_to_close/competitor_name/etc."),
    # Add 2-3 more based on your domain
]

for term, expected in test_cases:
    result = your_broadened_matcher(term)
    assert not result, f"FALSE POSITIVE: {term} matched {result}"
```

**Why short/common words**: They appear as substrings everywhere, maximizing false positive risk.

### 2. Check for Existing Governed-Whitelist Pattern

Search the codebase for similar matching problems already solved with governed aliases:

```bash
# Look for alias/whitelist patterns
grep -r "_ALIASES\|_WHITELIST" api/

# Check these proven patterns:
# - api/dimension_resolver.py: _COUNTRY_ALIASES, _REGION_ALIASES
# - api/router.py: _COLUMN_ALIASES (Bug #3 fix)
```

**If found**: Reuse the pattern. Do NOT invent a new matching mechanism for the same class of problem.

**The pattern**:
```python
# 1. Define governed whitelist of known semantic variants
_YOUR_ALIASES = {
    "country": "company_country",  # Question term → actual schema name
    "region": "region",
    # Add known synonym gaps only
}

# 2. Check exact match FIRST
if term in actual_values:
    return term

# 3. Then check governed alias
elif term in _YOUR_ALIASES:
    canonical = _YOUR_ALIASES[term]
    if canonical in actual_values:
        return canonical

# 4. NO substring fallback
return None  # or raise, or return error - never guess
```

### 3. Reject Bare Substring Fallbacks

**NEVER ship**:
```python
# DANGEROUS - bidirectional substring matching
matches = [x for x in collection if term in x or x in term]

# DANGEROUS - always-return fallback
if term in known_aliases:
    return aliases[term]
else:
    return term  # ← This matches EVERYTHING, even wrong terms
```

**Why**: No minimum length check, no context awareness, no similarity score. Short words match everything.

### 4. Run the Structural Gate

Before committing:
```bash
python tests/test_no_bare_substring_matching.py
```

This checks for the EXACT dangerous pattern from tonight's incidents. If it fails, you've reintroduced the anti-pattern.

## Summary

**Before broadening any matcher**:
1. ✅ Build 4-6 adversarial tests with short/common words
2. ✅ Check if governed-alias pattern already exists (reuse it!)
3. ✅ Never ship bare substring/containment checks as fallbacks
4. ✅ Run `test_no_bare_substring_matching.py`

**The right pattern**: Exact match → governed whitelist → honest failure. Never guess.

**Worked examples**: See `dimension_resolver.py` (_COUNTRY_ALIASES, _REGION_ALIASES) or `router.py` (_COLUMN_ALIASES, commit c794f31).
