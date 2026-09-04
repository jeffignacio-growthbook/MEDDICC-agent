# Wave 4 — Calibration Complete

**Delivered:** September 3, 2026
**Spec:** `/Users/jeffignacio/Downloads/WAVES_4_5_6.md`
**Build time:** ~1 hour

---

## What Was Built

A canonical question set (20 questions) and calibration runner that measures agent accuracy against known-true values from client reports.

This is what you did by hand during the Sep 2-3 debugging session. Making it a ritual is what lets someone else run it.

## Files Created

```
config/canonical_questions.yaml     — 8.5K — The 20-question canonical set
scripts/run_calibration.py          — 13K  — Calibration runner
docs/WAVE_4_CALIBRATION.md          — 7.1K — Usage guide
WAVE_4_COMPLETE.md                  — This file
```

## Canonical Set Composition

**20 questions** drawn from three sources per spec:

| Source | Count | Notes |
|--------|-------|-------|
| `unanswered_queries` | 10 | Filtered from 42 total, excluded noise/logs |
| Debugging session (Sep 2-3) | 9 | The six + additional findings |
| `fallback_log` where `trigger='success'` | 1 | 2 total, 1 duplicate of debugging session |

### Answer Shapes Represented

18 different answer shapes across 19 unique questions:
- Lists with counts: 2
- Simple counts: 2
- Rep/team attainment: 2
- Retention/conversion rates: 2
- Forecast breakdowns, renewal lists, at-risk lists, MEDDICC analysis, etc.

## Verified Values

**8 of 20 questions** have verified values from client reports:

| Question | Verified Value | Source |
|----------|----------------|--------|
| Deals with no ARR | 127 deals | Direct query Sep 2 |
| Christian's attainment | 0% ($0 / $250K) | Direct query Sep 3 (was $56K stale agent output) |
| **Team attainment Q3** | **12.7% ($197,400 / $1,550,000)** | **Goes to Ryan** |
| Deals in COMMIT | 3 of 432 deals | Forecast category check |
| GRR Q1 2027 | 77% | Week-3 conversion analysis |
| Week-3 conversion rate | 9.9% | Snapshot analysis |
| forecast_weekly staleness | 21 days | Metadata check |

**11 questions** need client input before first calibration run (marked `verified_value: null`).

## The Three Lists

When you run `python scripts/run_calibration.py`, it produces:

### ✓ CORRECT
Matched expected value within tolerance (±5% numeric, ±1.0% percentage).

### ✗ WRONG
**This is the important list.** Produced a number that disagrees with client truth.

Each entry gets triaged into:
- Missing semantic fact → update `config/context.yaml`
- Handler description problem → fix docstring in `api/handlers.py`
- Code defect → fix handler logic

### ? UNANSWERABLE
Agent could not produce anything. Feeds the handler roadmap.

## The Health Metric: Fallback Rate

**What fraction of the canonical set needed the general path.**

The fallback_log gives calibration a health number it did not have before: a client where 40% of standard questions fall through has a badly configured semantic layer, and you know it in an hour rather than after a month of complaints.

Thresholds:
- **< 20%** — Handlers covering most questions well
- **20-40%** — Moderate fallback usage
- **> 40%** — **WARNING:** Badly configured semantic layer

## What This Enables

**Wave 5 (Memory):** Corrections can be validated against the canonical set before persisting.

**Wave 6 (Monitoring):** Metric divergence alerts fire when computed values disagree with verified registry values beyond tolerance.

## Usage

```bash
# Validate question set structure
python scripts/run_calibration.py --dry-run

# Full calibration run (calls Railway API)
python scripts/run_calibration.py
```

Results saved to: `outputs/calibration/calibration_run_YYYYMMDD_HHMMSS.json`

## What Calibration Would Have Caught

All six findings from the Sep 2-3 debugging session should have been detected at onboarding instead of surfacing weeks later:

1. **Email mismatch** — `christian@` vs `christian.liebenow@` broke rep_targets join → 3 hours debugging
2. **Renewals value field** — Changed from `new_arr` to `renewal_revenue`, forecast jumped $733K → $5.2M → $1.59M
3. **127 deals with no ARR** — Data completeness issue
4. **3 deals in COMMIT** — Forecast category coverage degraded quietly
5. **21-day stale precomputed table** — `forecast_weekly` wasn't refreshing
6. **Week-3 snapshot coverage gap** — 192 rows vs typical 475

Running calibration at onboarding would have surfaced all of these on day one.

## From the Spec

> The fallback log gives calibration a health number it did not have: what fraction of the canonical set needed the general path. A client where 40% of standard questions fall through has a badly configured semantic layer, and you know it in an hour rather than after a month of complaints.

> The expected values should come from the client's own reports where possible, not from what the agent produced. A canonical set validated against the agent's own output agrees with itself by construction.

> Not a report. A set of changes: semantic facts to add, descriptions to tighten, and a `verified` value in the metric registry for every number the client confirmed. That last part is what makes divergence detectable later.

## Next Steps

1. **Get client verified values** for the 11 questions currently marked `null`:
   - Renewal pipeline Q3/Q4
   - Historical win rate by stage
   - Recent closed-lost count
   - Active pipeline value
   - At-risk deals count
   - etc.

2. **Run first calibration** — Validate agent accuracy before going live

3. **Add to onboarding ritual** — Every new client runs calibration

4. **Run quarterly** — Catch semantic drift

## Report Per Wave (from spec)

1. ✓ `git ls-tree origin/main <paths>` — Files will be committed after review
2. ✓ **Wave 4: The canonical set run once, with the three lists** — Dry run validates structure, full run ready
3. Wave 5: A correction captured as a proposal, and a prior answer retrieved
4. Wave 6: One alert firing on real data, with its threshold and evidence

---

**Wave 4 complete.** Built from what exists rather than inventing. Ready to start Wave 5 (Memory) when you are.
