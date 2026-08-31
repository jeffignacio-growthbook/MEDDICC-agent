# V2 Semantic Layer — Overview

**Status:** Parts 1-3 complete and shipped, awaiting field testing
**Last updated:** 2026-08-30

## What V2 Is

V2 replaces "LLM reads everything and guesses" with structured handlers that return typed data. Each metric has a canonical formula, population definition, and verified reference values. The semantic layer prevents wrong answers from reaching users through inline plausibility checks and reconciliation explains.

## Architecture

```
Question
  ↓
Intent Classification (router.py) → handler name
  ↓
Handler (handlers_*.py) → structured data
  ↓
Plausibility Checks (plausibility.py) → block if critical violation
  ↓
Synthesis (router.py) → natural language answer
  ↓
Slack
```

## Five Parts

### Part 1: Intent Classification ✅
**Status:** Complete
**Location:** `api/router.py`

Routes questions to handlers:
- `query_retention_metrics` — GRR, churn, NRR for renewal pipeline
- `query_pipeline_waterfall` — stage-by-stage deal counts
- `query_deal_health` — MEDDICC scores and risk factors
- `query_sdr_metrics` — activity, conversion, velocity
- Dynamic tool — complex questions outside handler scope

### Part 2: Metric Definitions ✅
**Status:** Complete
**Location:** `config/metrics.yaml`, `api/handlers_retention.py`

Each metric includes:
- **Formula** — exact calculation (ported from HubSpot reports)
- **Population** — which deals qualify
- **Freshness** — historical vs current
- **Views** — closed-only vs assume-open-wins
- **Not applicable to** — prevents garbage (e.g., week-3 conversion on renewals)

Example:
```yaml
grr:
  label: Gross Revenue Retention
  formula: SUM(IF(closed_won, renewal_revenue, 0)) / SUM(renewal_revenue)
  population: renewal pipeline only
  freshness: historical
  not_applicable_to: [default pipeline, new business pipeline]
```

### Part 3: Answer Integrity ✅
**Status:** Complete, awaiting field testing
**Location:** `api/plausibility.py`, `api/handlers_retention.py`, `api/router.py`
**Docs:** `docs/V2_PART3_ANSWER_INTEGRITY.md`

Four components:

**3a. Plausibility checks (inline)**
- 5 check types run before synthesis
- Critical violations block synthesis with plain-language message
- Warnings surface in answer with ⚠️  marker

**3b. Population statements (plain language)**
- "44 renewals across FY2027 Q1, FY2027 Q2. 5 don't have an amount recorded yet."
- No internal vocabulary (pipeline IDs, denominator basis, coverage floor)

**3c. Freshness stamps (per-quarter metadata)**
- `is_closed` flag, `quarter_end` date
- `metric_type: historical`, `last_verified` date

**3d. Reconciliation explains (both views, never picks winner)**
- "Handler 111.8% vs verified 107%. Handler includes Lion Studios ($37.5K expansion). Report excludes it. Both are valid views depending on treatment rules."

**Field testing needed:**
- Does plausibility block good answers? (false positives)
- Q3/Q4 with no verified values — does it error or return answer?
- Semantic layer (~650 tokens) — does it shift routing behavior?

### Part 4: Memory ⏳
**Status:** Spec only, not built
**Docs:** `docs/V2_SCOPE.md`

Corrections persist beyond the thread they were made in.

When someone says the agent got something wrong:
1. Ask: is this general or specific to this question?
2. Write proposal to queue with conversation as evidence
3. Agent proposes, human disposes — nothing auto-applies

**Don't build until:** Parts 1-3 field tested and validated.

### Part 5: Monitoring Loop ⏳
**Status:** Spec only, not built
**Docs:** `docs/V2_SCOPE.md`

Nightly pass over substrate that posts to Slack unprompted when thresholds crossed.

Examples:
- Renewals with no amount recorded near close
- Deal committed three weeks running, close date hasn't moved
- MEDDICC scores that shifted materially (and from which call)

Each needs:
- Threshold (when to fire)
- Evidence bar (proof required)
- Suppression window (don't repeat too often)

**Don't build until:** Parts 1-3 field tested and answers are trustworthy.

## Files

| File | Lines | Purpose |
|------|-------|---------|
| `api/router.py` | 2500+ | Intent classification, synthesis |
| `api/handlers_retention.py` | 530 | GRR/churn/NRR with freshness + reconciliation |
| `api/plausibility.py` | 456 | Five inline checks, block messages |
| `config/metrics.yaml` | 189 | Verified values, reconciliation notes |
| `docs/V2_PART3_ANSWER_INTEGRITY.md` | 195 | Part 3 completion summary |

## Testing Protocol

**Who:** User runs questions through Slack (not automated)
**Why:** Needs real user perspective on tone and usefulness, not just technical correctness
**What:** Dozen questions over next few days
**Mix:** Renewals, retention, rep pipeline, deal health, movement
**Watch for:** Blocks on good answers, robotic language, routing changes

## Commits

- `45fc82a` — NRR reconciliation (Lion Studios found, 0.06pp)
- `5dfd262` — Plausibility checks (5 types, blocks on critical)
- `bd2ad99` — Plain-language rewrite (block messages, population statements)
- `93f37f4` — Freshness stamps + reconciliation explains
- `6adf121` — Remove internal vocabulary from synthesis payload

## Next Session

Read this doc first. Then:
1. Ask user for field testing results
2. Fix what broke
3. Decide what's next from observations, not from plan

Don't build memory or monitoring loop until current changes are validated.
