# V2 Semantic Layer Part 3: Answer Integrity

**Status:** Complete
**Date:** 2026-08-30
**Commits:** bd2ad99, 93f37f4

## Overview

Part 3 adds inline plausibility checks, user-facing population statements, freshness stamps, and reconciliation explains to prevent wrong answers from reaching users.

## What Was Built

### 3a. Plausibility Checks (Inline)

**Location:** `api/plausibility.py` (456 lines)
**Integration:** `api/router.py:1900` (before synthesis)

Five check types run before synthesis:
1. **Rate bounds** — catch rates >100% or <0%
2. **Subset relationships** — flag won > closed, qualified > created
3. **Sum consistency** — verify won + lost + open = total
4. **Negative counts** — catch impossible negative deal counts
5. **Metric registry divergence** — compare GRR/NRR to verified values

**Behavior:**
- Critical violations → **block synthesis**, return plain-language message
- Warnings → surface in answer with ⚠️  marker

**Example block message:**
```
I'm not showing GRR for Q1 FY2027 — the number I calculated doesn't
match what we've verified, so I don't trust it. Flagged for Jeff to check.
```

**Test case:**
```bash
python /tmp/test_plausibility_arr_usd.py
```
Forces retention handler to use `arr_usd` instead of `renewal_revenue`, resulting in GRR 100% vs verified 77%. Plausibility check catches the 23pp variance and blocks synthesis.

### 3b. Population Statements

**Location:** `api/handlers_retention.py:151-168`

Plain-language description of what was counted and what was excluded.

**Before (internal vocabulary):**
```
44 renewal deals — pipeline IDs [866608541], grouped by fiscal quarter.
Quarters: FY2027 Q1, FY2027 Q2. Denominator: renewal_revenue (excludes
deals with NULL renewal_revenue). Coverage floor: 50%.
```

**After (plain language):**
```
44 renewals across FY2027 Q1, FY2027 Q2. 5 don't have an amount recorded yet.
```

**Rule applied:** If a sentence contains a word from the codebase (pipeline ID, denominator, tolerance, variance, coverage floor, query), rewrite it.

### 3c. Freshness Stamps

**Location:** `api/handlers_retention.py:171-315`

Per-quarter metadata showing:
- **metric_type:** "historical" (from registry)
- **is_closed:** true for quarters with no open deals
- **quarter_end:** ISO date for quarter end (e.g., "2026-04-30")
- **last_verified:** When registry values were reconciled

**Example metadata:**
```json
{
  "freshness": {
    "metric_type": "historical",
    "last_verified": "2026-08-28",
    "quarters": {
      "FY2027 Q1": {
        "is_closed": true,
        "quarter_end": "2026-04-30",
        "reconciliation": {
          "grr": "Handler 76.7% matches verified 77% (0.32pp variance, within tolerance)",
          "nrr": "Handler 111.8% vs verified 107%. Handler includes Lion Studios..."
        }
      }
    }
  }
}
```

### 3d. Reconciliation Explains

**Location:** `api/handlers_retention.py:360-415`

When handler output differs from verified values:
- Show both views
- Explain the difference
- Never pick a winner

**Example:**
```
NRR: Handler 111.8% vs verified 107%. Handler includes Lion Studios
($37.5K expansion). Report excludes it. Reason unknown. Both are valid
views depending on treatment rules.
```

**Synthesis integration:** `api/router.py:2173` instructs synthesis to surface reconciliation notes in plain language.

## How It Works

### Flow

1. **Handler runs** → returns metrics + freshness + reconciliation
2. **Plausibility checks** → run before synthesis (router:1900)
3. **Critical violation?** → block synthesis, return plain message
4. **Warnings?** → add to tool_results for synthesis awareness
5. **Synthesis** → includes reconciliation notes when present
6. **Verify** → confirms accuracy

### Registry Format

**Location:** `config/metrics.yaml`

```yaml
grr:
  label: Gross Revenue Retention
  freshness: historical
  verified:
    q1_fy2027_closed_only: 0.77
    tolerance: 0.005  # ±0.5pp
    handler_output: 0.7668  # within tolerance
    reconciled_on: 2026-08-28

nrr:
  label: Net Revenue Retention
  freshness: historical
  verified:
    q1_fy2027_closed_only: 1.07
    tolerance: 0.005
    handler_output: 1.1182
    handler_output_excluding_lion_studios: 1.0694
    reconciliation_note: |
      Handler includes Lion Studios ($37.5K expansion).
      Report excludes it. Both are valid views.
```

## Testing

### Plausibility Check Test
```bash
python /tmp/test_plausibility_arr_usd.py
```
**Result:** Catches GRR 100% vs verified 77%, blocks synthesis.

### Freshness Metadata Test
```bash
python -c "
from handlers_retention import query_retention_metrics
from utils import load_client_config
from db import get_supabase

result = query_retention_metrics(get_supabase(), load_client_config(), {'type': 'all'})
print(result['freshness'])
"
```
**Result:** Shows Q1 FY2027 is closed (2026-04-30), includes reconciliation notes.

## What's Next

Part 3 complete. Ready for:
- Part 4: Field lineage (which HubSpot property feeds each metric)
- Part 5: Coverage transparency (% of deals with required fields)

## Files Modified

| File | Lines | Purpose |
|------|-------|---------|
| `api/plausibility.py` | 456 | Five inline checks, block messages |
| `api/handlers_retention.py` | +220 | Freshness stamps, reconciliation notes |
| `api/router.py` | +10 | Plausibility integration, synthesis instructions |
| `config/metrics.yaml` | 189 | Verified values, reconciliation notes |

## Commits

- `bd2ad99` — Remove internal vocabulary from user-facing messages
- `93f37f4` — Add freshness stamps and reconciliation explains

---

**V2 Semantic Layer progress:**
- ✅ Part 1: Intent classification (handler routing)
- ✅ Part 2: Metric definitions (handlers, formulas, population)
- ✅ Part 3: Answer integrity (plausibility, freshness, reconciliation)
- ⏳ Part 4: Field lineage
- ⏳ Part 5: Coverage transparency
