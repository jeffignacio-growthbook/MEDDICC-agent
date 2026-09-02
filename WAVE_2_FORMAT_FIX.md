# Wave 2 Format Normalization Fix

## Problem

Forecast queries were returning 0 rows due to fiscal_quarter format mismatch:
- **Stored format**: `FY2027 Q3` (with space)
- **Query format**: `FY2027Q3` (no space)
- **Root cause**: Model occasionally omits the space despite format instructions in field_semantics.yaml

Example from logs:
```
[TOOL] filter_table fiscal_quarter=eq.FY2027Q3 ← no space
Result: 0 rows (but 16 quarters exist in forecast_weekly)
```

This caused:
- 3 wasted loop iterations
- Budget exhaustion (20K token limit hit)
- User frustration ("What do you forecast for the quarter?" → "No matching data found")

## Solution

### Fix 1: Auto-correct fiscal_quarter format at tool boundary

**File**: `api/tools.py` (lines 82-93)

Added format normalization in `filter_table()` before building the query:

```python
# Normalize fiscal_quarter format: FY2027Q3 → FY2027 Q3
if col == "fiscal_quarter" and isinstance(val, str):
    import re
    # Match FY<year>Q<quarter> without space
    if re.match(r'^FY\d{4}Q\d$', val):
        normalized = val[:6] + " " + val[6:]  # Insert space before Q
        print(f"[FILTER] Auto-corrected fiscal_quarter: '{val}' → '{normalized}'", flush=True)
        processed_filters.append((op, col, normalized))
    else:
        processed_filters.append((op, col, val))
else:
    processed_filters.append((op, col, val))
```

**Why this approach**:
- More robust than expecting the model to reproduce format exactly
- Catches the error at the boundary where it matters (query construction)
- Logs the correction for observability
- Generalizes to other structured columns in the future

**Test results**:
```
✓ 'FY2027Q3' → 'FY2027 Q3' (normalized=True)
✓ 'FY2027 Q3' → 'FY2027 Q3' (normalized=False)
✓ 'FY2028Q1' → 'FY2028 Q1' (normalized=True)
```

### Fix 2: Tighten row cap to prevent context bloat

**File**: `api/tools.py` (lines 46-51)

Changed from:
```python
max_limit = 50 if table == "analyses" else 200
```

To:
```python
# Hard cap at 50 rows to prevent synthesis context bloat.
# 100 rows was producing 27,969 chars — too large for synthesis.
# Entity extraction happens separately and preserves full populations.
max_limit = 50
```

**Why**:
- 100 rows returned 27,969 chars into synthesis → budget exhaustion
- Entity extraction preserves full populations separately (no cap needed)
- Synthesis needs concise summaries, not full datasets

## Impact

Before:
- Query: `fiscal_quarter=eq.FY2027Q3` → 0 rows → 3 iterations wasted → budget exhausted
- Dynamic loop hitting 100-row limits → 27,969 chars → synthesis context bloated

After:
- Query: `fiscal_quarter=eq.FY2027Q3` → auto-corrects to `FY2027 Q3` → returns data on first iteration
- Hard cap at 50 rows → max ~14K chars → synthesis stays within budget
- Logged corrections make format mismatches observable

## Verification

Format normalization logic tested with unit tests (all passing):
- `FY2027Q3` correctly normalizes to `FY2027 Q3`
- `FY2027 Q3` (already correct) passes through unchanged
- Invalid formats don't match and pass through unchanged
- Logging fires when normalization occurs

## Related

- **Wave 2 Semantic Gaps**: field_semantics.yaml now documents format (lines 250-269)
- **Wave 2 Bug 1**: Entity extraction no longer caps at 20 (separate fix)
- **Dynamic query direct dispatch**: Bypasses handler dispatch to reduce budget waste

## Commit

```
7b59c44 Fix fiscal_quarter format normalization and row cap
```
