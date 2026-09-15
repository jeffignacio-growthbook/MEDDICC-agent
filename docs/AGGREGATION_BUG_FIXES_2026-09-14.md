# Aggregation Verification Bug Fixes — 2026-09-14

**Status:** FIXED and VERIFIED
**Priority:** URGENT — Production data corruption prevented
**Test Coverage:** 14 tests (10 existing + 4 new) all passing

---

## Executive Summary

Two critical bugs in AGGREGATION_VERIFY were discovered and fixed:

1. **Extraction Bug (FIXED):** Regex matched wrong numbers (years, counts) instead of dollar totals
2. **Substitution Bug (FIXED):** Corrected totals placed in wrong location (attached to company names instead of summary lines)

**Impact:** Both bugs caused production incidents with wrong dollar figures shipping to real users. The substitution bug specifically attached a $6.89M total to a single company (Creative CX) instead of a $50K deal amount.

---

## Bug 1: Extraction Bug

### Root Cause

The `_AMOUNT_RE` regex in `aggregation_verification.py` had an optional `$` sign (`\$?`), causing it to match ANY bare number, not just dollar amounts.

**Example:**
```
Text: "EMEA Closed Won — Jan 2025 to Date... Total: $6.89M"
Expected extraction: 6890000.0
Actual extraction: 2025.0 (the year!)
```

### Live Incidents

Across three separate questions, AGGREGATION_VERIFY extracted:
- 8.0 (deal count)
- 2025.0 (year)
- 2025.0 (year)

None of these were plausible dollar totals, yet the verification logic compared them against real totals, creating false mismatches.

### The Fix

**File:** `api/aggregation_verification.py`

**Change:** Two-phase extraction strategy

```python
# Phase 1: Look for explicit dollar amounts ($ sign REQUIRED)
_AMOUNT_WITH_DOLLAR_RE = re.compile(
    r"([+-]?)\$([\d][\d,]*(?:\.\d+)?)\s*([KkMm])?\s*(won|lost)?", re.IGNORECASE
)

# Phase 2: ONLY if no $ amount found, check for bare number with strong context
# (e.g., "Total: 1500000" or "Total is 1.5M")
context_match = re.search(
    r'\btotal\b(?:[^.!?:]*?)(?::|is|was|of)\s*([+-]?[\d][\d,]*(?:\.\d+)?)\s*([KkMm])?\b',
    sentence,
    re.IGNORECASE
)
```

**Result:** Extraction now prioritizes explicit `$` amounts and only falls back to bare numbers when they appear immediately after "total" + connector words.

### Test Coverage

**File:** `tests/test_aggregation_extraction_bug.py` (NEW)

- Test 1: Year in title, dollar total in body → extracts $6.89M (not 2025)
- Test 2: Deal count mentioned, then dollar total → extracts $1.2M (not 8)
- Test 3: Bare number in same sentence → extracts $500K (not 2025)
- Test 4: Full extraction with categories → extracts $1.5M correctly

**Status:** ✅ All 4 tests passing

---

## Bug 2: Substitution Corruption Bug

### Root Cause

When AGGREGATION_VERIFY detected a mismatch, it sent a correction message giving the model the RIGHT VALUE ($6.89M) but NO GUIDANCE on WHERE to put it. The model was free to splice the corrected total anywhere.

**Production Incident:**
```
Question: EMEA closed won/lost deals
- 354 rows, actual total: $6.89M
- Model's first answer: "Total: $50,000" (wrong)
- Correction sent: "Replace with $6,890,371.78"
- Model's retry: Replaced Creative CX's individual $50K line item with $6.89M
- Result: Wrong $6.89M figure attached to Creative CX, shipped to production
```

### The Fix (Two-Part)

**Part 1: Explicit Prompt Guidance**

**File:** `api/router.py` — `_aggregation_correction_message()`

**Change:** Added explicit location guidance to correction message:

```python
"CRITICAL: These corrected totals belong in your SUMMARY/TOTAL "
"line(s) ONLY. Do NOT alter any individual deal amounts, "
"per-week figures, or line-item breakdowns — those are already "
"correct. Replace ONLY the wrong summary total(s) named above "
"with the exact corrected number(s), verbatim."
```

**Part 2: Structural Verification**

**File:** `api/router.py` — `_check_suspicious_total_substitution()` (NEW)

**Change:** After retry, check if corrected value appears in suspicious contexts:

```python
# Pattern 1: Company name + corrected value
# (e.g., "Creative CX: $6.89M" — SUSPICIOUS!)
# BUT: Exclude total-indicator phrases like "Total", "Grand total", "Overall"

pattern = rf'([A-Z][A-Za-z0-9\s&]+)(?::|\s—|\s-)\s*\$?{re.escape(fmt_val)}'
match = re.search(pattern, answer_text)
if match:
    label = match.group(1).strip().lower()
    TOTAL_INDICATORS = {"total", "overall", "grand total", "grand_total", "sum", "net"}
    if not any(indicator in label for indicator in TOTAL_INDICATORS):
        return "⚠️ SUSPICIOUS: Corrected total appears next to company/entity name..."
```

If suspicious, escalate to "couldn't verify" instead of shipping corrupted data.

### Test Coverage

**File:** `tests/test_aggregation_substitution_corruption.py` (NEW)

- Test 1: Wrong answer states low total ($50K vs actual $6.89M)
- Test 2: Verification detects mismatch
- Test 3: CORRUPTED retry (Creative CX = $6.89M) → flagged as suspicious ✅
- Test 4: CORRECT retry (Total = $6.89M, Creative CX still $50K) → NOT flagged ✅

**Status:** ✅ All 4 tests passing

---

## Supporting Changes

### New Helper Function

**File:** `api/aggregation_verification.py`

```python
def _format_agg_number(value: float) -> str:
    """Format a number with commas and appropriate decimal places."""
    if value == int(value):
        return f"{value:,.0f}"  # Whole number
    else:
        return f"{value:,.2f}"  # Decimals
```

Used by `_check_suspicious_total_substitution()` to match various formatted representations of corrected values.

---

## Regression Testing

**File:** `tests/test_aggregation_retry_hands_correct_value.py` (EXISTING)

All 10 existing aggregation tests continue to pass:
- Format number tests (whole vs fractional)
- Incident reproduction tests (both incidents)
- Correction message tests (single/multiple discrepancies)
- End-to-end tests (retry, escalation, caveat)

**Status:** ✅ All 10 tests passing

---

## Total Test Coverage

| Test File | Tests | Status |
|-----------|-------|--------|
| test_aggregation_extraction_bug.py | 4 | ✅ All passing |
| test_aggregation_substitution_corruption.py | 4 | ✅ All passing |
| test_aggregation_retry_hands_correct_value.py | 10 | ✅ All passing |
| **TOTAL** | **14** | **✅ 100% passing** |

---

## Deployment Checklist

- [x] Both bugs identified and reproduced
- [x] Fixes implemented in production code
- [x] Test coverage added (8 new tests)
- [x] Regression tests passing (10 existing tests)
- [x] Documentation complete (this file)
- [ ] Deploy to production
- [ ] Monitor next 48 hours for any edge cases

---

## Related Documentation

- `api/aggregation_verification.py` — Core verification logic
- `api/router.py` — Retry mechanism and suspicious detection
- `docs/HANDLER_PRIMITIVE_CONVERGENCE.md` — Broader architectural context
- `tests/test_aggregation_*.py` — Test coverage

---

## Key Takeaways

1. **Extraction must be strict:** Optional `$` sign is too permissive. Prefer explicit $ amounts, only fallback with strong context.

2. **LLM guidance must be explicit:** "Replace the wrong total" is not enough. Must specify WHERE (summary lines only, not individual items).

3. **Structural checks are mandatory:** Prompt guidance alone isn't enough. Code-level verification catches when model doesn't follow instructions.

4. **Test real incidents:** Both bugs were reproduced with exact production scenarios, ensuring fixes target the real failure modes.

---

**End of Document**
