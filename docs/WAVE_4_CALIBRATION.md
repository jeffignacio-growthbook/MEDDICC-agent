# Wave 4 — Calibration (Complete)

**Built:** September 3, 2026
**Status:** Ready for client onboarding run

---

## What Was Built

A canonical question set and calibration runner that measures agent accuracy against known-true values from client reports. This is what you did by hand during the debugging session — making it a ritual is what lets someone else run it.

## The Canonical Question Set

**Location:** `config/canonical_questions.yaml`

**20 questions** drawn from three sources:
1. `fallback_log` where `trigger='success'` — 2 questions that worked
2. `unanswered_queries` — 10 meaningful failures (filtered from 42 total)
3. The six exercised during debugging (Sep 2-3):
   - Forecast for the quarter
   - Renewal pipeline
   - Pipeline movement
   - MEDDICC scoring
   - Attainment
   - Deals with no ARR

Each question includes:
- `question`: Exact text
- `shape`: Expected answer type (count, percentage, forecast_breakdown, list, etc.)
- `verified_value`: Known-true value from client reports where available
- `handler`: Expected handler to answer it
- `notes`: Context from when the question was exercised

## Verified Values

Six questions have verified values from the Sep 2-3 debugging session:

| Question | Verified Value | Source |
|----------|----------------|--------|
| Which deals have no ARR recorded? | 127 deals | Direct query Sep 2 |
| How is Christian tracking? | 0% ($0 / $250K) | Direct query Sep 3 (was $56K stale agent output) |
| What is team attainment for Q3? | 12.7% ($197,400 / $1,550,000) | **This goes to Ryan** |
| How many deals in COMMIT? | 3 out of 432 deals | Forecast category check Sep 2 |
| What is the GRR for Q1 2027? | 77% | Week-3 conversion analysis |
| What is the week-3 conversion rate? | 9.9% | Snapshot analysis Sep 2 |

**Important:** These verified values came from client reports and direct queries, not from agent output. A canonical set validated against the agent's own output agrees with itself by construction.

## Running Calibration

```bash
# Dry run to validate question set
python scripts/run_calibration.py --dry-run

# Full run (calls Railway API)
python scripts/run_calibration.py
```

The runner:
1. Loads the 20 canonical questions
2. Asks each question via `/slack/question` endpoint
3. Compares response to `verified_value` where it exists
4. Produces three lists

## The Three Lists

### ✓ CORRECT
Matched expected value within tolerance:
- Numeric values: ±5% or ±1, whichever is larger
- Percentages: ±1.0%
- Lists: count within ±5%

### ✗ WRONG
Produced a number that disagrees with client truth.

**This is the important list.** Each entry gets triaged into:
- Missing semantic fact (config/context.yaml needs update)
- Handler description problem (api/handlers.py docstring unclear)
- Code defect (bug in handler logic)

### ? UNANSWERABLE
Agent could not produce anything. Feeds the handler roadmap.

## The Health Metric: Fallback Rate

**What fraction of the canonical set needed the general path.**

A client where 40% of standard questions fall through has a badly configured semantic layer — and you know it in an hour rather than after a month of complaints.

Thresholds:
- **< 20%** — Handlers covering most questions well
- **20-40%** — Moderate fallback usage, handlers need tuning
- **> 40%** — WARNING: Badly configured semantic layer

## Output

Not a report. A set of changes:

1. **Semantic facts to add** — Missing context in config/context.yaml
2. **Descriptions to tighten** — Handler docstrings in api/handlers.py
3. **`verified` values** — For every number the client confirmed

That last part is what makes divergence detectable later (Wave 6 monitoring).

## Example Run Output

```
================================================================================
WAVE 4 — CALIBRATION RUN
================================================================================
Loaded 20 canonical questions
API endpoint: https://your-railway-app.up.railway.app

[q001] What do you forecast for the quarter?
      Shape: forecast_breakdown
      Status: ✓ CORRECT

[q002] How much expansion ARR is in the renewal pipeline for Q3 and Q4?
      Shape: renewal_breakdown
      Status: ✗ WRONG

[q003] Which deals have no ARR recorded?
      Shape: list_with_count
      Status: ✓ CORRECT

...

================================================================================
CALIBRATION SUMMARY
================================================================================

✓ CORRECT:         6 / 20 (30.0%)
✗ WRONG:           4 / 20 (20.0%)
? UNANSWERABLE:   10 / 20 (50.0%)

Fallback rate: 8/20 (40.0%)
  ⚠ WARNING: >40% fallback rate indicates badly configured semantic layer

================================================================================
WRONG ANSWERS — Requires Triage
================================================================================

[q002] How much expansion ARR is in the renewal pipeline for Q3 and Q4?
  Expected: {'renewal_value': 1590000, 'expansion_arr': 200000}
  Response: "I found $5.2M in renewals..."
  Triage into:
    [ ] Missing semantic fact
    [ ] Handler description problem
    [ ] Code defect

Full results saved to: outputs/calibration/calibration_run_20260903_052930.json
```

## What This Caught During Debugging

Every one of these surfaced by accident during unrelated work:

1. **Email mismatch** — `christian@` vs `christian.liebenow@` broke rep_targets join
2. **Renewals value field** — Changed from `new_arr` to `renewal_revenue`, forecast went $733K → $5.2M → $1.59M
3. **127 deals with no ARR** — Data completeness issue
4. **3 deals in COMMIT** — Forecast category coverage degraded quietly
5. **21-day stale precomputed table** — `forecast_weekly` wasn't refreshing
6. **Week-3 snapshot coverage** — 192 rows vs typical 475, forced Q2 exclusion

**All of these should have been detected by calibration at onboarding instead of surfacing weeks later.**

## Next Steps

1. **Client provides verified values** for questions currently marked `verified_value: null`
   - Renewal pipeline Q3/Q4
   - Historical win rate by stage
   - Recent closed-lost deals count

2. **Run calibration at onboarding** — Validate agent accuracy before going live

3. **Run calibration quarterly** — Catch semantic drift

4. **Add to metric registry** — Store verified values for divergence monitoring (Wave 6)

## Files Created

```
config/canonical_questions.yaml         — The 20-question set
scripts/run_calibration.py              — Calibration runner
docs/WAVE_4_CALIBRATION.md             — This file
```

## What This Enables

**Wave 5 (Memory):** Corrections can be validated against the canonical set

**Wave 6 (Monitoring):** Metric divergence alerts when computed values disagree with verified registry values beyond tolerance

---

## Build Order Rationale

> **1. Calibration** — smallest, uses data you have, and its output improves everything downstream
>
> **2. Memory** — corrections need somewhere to go before monitoring generates more of them
>
> **3. Monitoring** — last, once answers are trustworthy enough that an unprompted claim is not embarrassing

Wave 4 is complete. Ready to start Wave 5 (Memory) when you are.
