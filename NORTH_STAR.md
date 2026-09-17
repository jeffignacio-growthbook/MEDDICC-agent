# North Star: GrowthBook RevOps Agent Architecture

## Core Principles

### 1. Primitives Over Handlers
Build reusable, composable primitives that multiple handlers can call, rather than duplicating logic across handlers. Every aggregation, filter, or calculation should have ONE canonical implementation.

### 2. Trustworthy Over Fast
A slow, correct answer is better than a fast, wrong answer. Every primitive must be **provably correct** before shipping:
- Unit tests with planted failures that prove the trap springs
- Integration tests on real handlers showing end-to-end protection
- Verification gates that catch corruption before it reaches users

### 3. Honest Failures
When verification fails, return an honest error rather than corrupted data. Silent wrong answers are worse than no answer - they erode trust permanently.

### 4. Data-Grounded Thresholds
Never guess thresholds. Every classification boundary (at-risk, stale, overdue) must be derived from actual historical data or explicitly flagged as provisional until data exists.

---

## Current Phase: Aggregation Correctness (Phase 1)

**Goal**: Eliminate hand-rolled aggregation bugs in dedicated handlers by replacing with governed primitives + verification.

### Phase 1a+ ✅ COMPLETE (2026-09-16)
**Pattern Established**: Deduplication + Verification

**Delivered**:
- `aggregate_results()` primitive: Single source of truth for group-by aggregations with automatic deduplication
- `verify_structured_aggregations()`: Deterministic validation of handler outputs against raw data
- Wired into `query_pipeline` with planted failure tests proving trap springs
- Both deduplication AND verification protection in production

**Key Artifacts**:
- `scripts/aggregate_results.py` - Deduplication primitive
- `api/structured_verification.py` - Verification primitive
- `PRIMITIVE_CHECKLIST.md` - Documentation of tradeoffs (hard error vs caveated partial)

### Phase 1b 🔄 IN PROGRESS
**Goal**: Apply proven deduplication + verification pattern to remaining dedicated handlers

**Priority Order** (one at a time, full cycle per handler):
1. **query_pipeline_movement** (CURRENT) - Had 2 real bugs this session, highest priority
2. query_stale_deals
3. query_waterfall
4. query_at_risk
5. query_win_loss
6. query_rep_pipeline
7. query_team_leaderboard
8. query_sdr_metrics, query_sdr_pipeline_sourced

**Per-Handler Process**:
1. **Audit**: Identify hand-rolled aggregations, rate severity (LOW/MEDIUM/HIGH)
2. **Baseline**: Capture current output for 3-5 realistic questions
3. **Refactor**: Replace manual loops with `aggregate_results()`
4. **Verify**: Wire `verify_structured_aggregations()` + plant discrepancy test
5. **Ship**: Full suite, commit, push, CI confirmation

**Do NOT** batch handlers or skip steps to save time. Report after each handler completes before starting next.

---

## Primitive Roadmap - Reasoning Layer

**Context**: Aggregation correctness (Phase 1) protects data integrity. The reasoning layer interprets PATTERNS across that data to answer "why" and "what should we do" questions. Each primitive below represents a cross-cutting analytical capability motivated by real user questions.

**Source**: Audited from query_cost_log (300 recent questions, 2026-09-17) and conversation history. Questions marked with ✓ were answered; ✗ indicates partial/failed attempts.

### Priority 1: Cross-Rep Trend Analysis

**Real Questions**:
- ✓ "Show me win rate by segment for Q3"
- ✗ "How's Scott's call quality been this month?"
- ✗ "How many meetings has Jake Stangl's SDR pipeline generated this quarter"

**Primitive**: `compute_cohort_performance_trends(dimension, metric, time_window)`
- **What it does**: Compute metric (win rate, call quality, meeting generation) grouped by dimension (segment, rep, region) over time window, with statistical significance flags for outliers
- **Why it's hard**: Need historical baseline, variance calculation, multi-dimensional grouping
- **Status**: **PARTIAL** - Individual metrics exist (win_rate in query_win_loss, sdr_metrics per rep) but no cross-cohort comparison or trend detection
- **Blocks**: Rep coaching prioritization (can't identify "who's struggling" without cohort context), forecast confidence (can't assess rep-level reliability)

### Priority 2: Win/Loss Attribution

**Real Questions**:
- ✓ "What was the closed won/lost split in EMEA last quarter?"
- ✓ "Why wasn't this deal included in the German closed won calculations?"
- Current: competitive_intel exists but only searches mentions, doesn't attribute outcomes

**Primitive**: `attribute_outcome_to_factors(deal_id, outcome, candidate_factors)`
- **What it does**: For a won/lost deal, rank contributing factors (competitor mentioned, missing champion, pricing objection, segment, cycle time variance) by attribution weight
- **Why it's hard**: Causation vs correlation, sparse data (only 327 historical wins), need multi-factor modeling
- **Status**: **PARTIAL** - win_loss_narratives table exists, competitive_intel searches mentions, but no attribution model or factor ranking
- **Blocks**: Competitive intel (can't answer "lost 5 deals to Statsig due to X"), rep coaching (can't identify which competency gaps matter most)

### Priority 3: Competitive Loss Patterns

**Real Questions**:
- ✗ "Which competitors keep coming up?" (answered via search, not pattern analysis)
- No direct "we lost N deals to X in segment Y citing reason Z" questions in log yet

**Primitive**: `analyze_competitive_loss_patterns(competitor_name=None, segment=None)`
- **What it does**: Cross-reference competitor mentions in objections/feature_gaps/win_loss_narratives with deal outcomes to find: frequency of competitor by segment, win rate when X mentioned, common objection themes when losing to X
- **Why it's hard**: Unstructured text extraction (competitor names not always in competitor_mentioned field), need to link mentions → outcomes → patterns
- **Status**: **PARTIAL** - competitive_intel searches mentions, win_loss_narratives exist, but no outcome correlation or pattern detection
- **Depends on**: Win/loss attribution (need causal model, not just search)

### Priority 4: Rep Coaching Prioritization

**Real Questions**:
- Current: coaching_priorities exists but per-deal flagging only, no cross-rep trends
- No "which reps struggle with X competency" questions in log yet (coaching questions route to deal-level flags)

**Primitive**: `prioritize_coaching_needs(rep_email=None, competency=None)`
- **What it does**: Rank reps by competency gaps (champion identification, pain discovery, objection handling) weighted by: frequency of gap, deal value at risk, historical improvement rate after coaching
- **Why it's hard**: Need historical coaching→outcome tracking (not instrumented yet), competency must correlate with win/loss (unproven for this client per 2026-09-16 MEDDICC decision)
- **Status**: **PARTIAL** - coaching_priorities flags deals with low component scores, but no cross-rep ranking, no competency-to-outcome correlation, no coaching effectiveness tracking
- **Depends on**: Cohort performance trends (need rep-level benchmarks), win/loss attribution (need to prove competency X predicts outcome Y)
- **Blocker**: MEDDICC data insufficient (only 4 of 327 won deals scored) - shelved until ≥30 scored wins exist

### Priority 5: Forecast Confidence Scoring

**Real Questions**:
- ✗ "Show me forecast confidence" (not in log - aspirational primitive)
- Current: query_pipeline returns coverage ratio but no confidence assessment

**Primitive**: `score_forecast_confidence(pipeline_snapshot, target, time_window)`
- **What it does**: For a given pipeline snapshot and target, compute confidence score (0-100) based on: historical close rate by stage, rep reliability (forecast vs actual), deal age distribution, MEDDICC maturity distribution
- **Why it's hard**: Need historical forecast→actual tracking (not instrumented yet), stage-specific close rates need ≥50 deals per stage, rep reliability needs ≥6 months history
- **Status**: **NOT STARTED** - no historical forecast snapshots, no close rate by stage computation, no rep reliability tracking
- **Depends on**: Cohort performance trends (need rep-level close rate history), deal risk assessment (partially exists but shelved due to MEDDICC data gap)

### Priority 6: Root Cause Drill-Down

**Real Questions**:
- ✓ "Which deals are stale in Discovery stage?" (answered, but no root cause analysis)
- ✓ "Which deals haven't moved in 30 days?" (flagging only, no "why stale" reasoning)

**Primitive**: `explain_cohort_anomaly(cohort_definition, metric, threshold)`
- **What it does**: For a cohort showing anomalous metric (12 deals stale in Discovery, win rate dropped 20% in EMEA), drill down to shared factors (same rep, same competitor, same objection, same missing competency) and rank by frequency
- **Why it's hard**: Anomaly detection needs baseline (see Priority 1), root cause needs multi-dimensional correlation (see Priority 2)
- **Status**: **NOT STARTED** - flagging handlers exist (stale_deals, coaching_priorities) but no cross-deal pattern extraction
- **Depends on**: Win/loss attribution (factor ranking), cohort performance trends (anomaly detection)

---

## Reasoning Layer: Decision Criteria

**When to build a reasoning primitive** (vs adding another handler):
1. **Cross-cutting**: Primitive serves 3+ question types (e.g., win/loss attribution helps competitive intel, coaching priorities, forecast confidence)
2. **Causal inference**: Question asks "why" or "what predicts" - needs more than aggregation
3. **Data sufficiency**: Historical data exists to validate the model (≥30 examples for binary classification, ≥50 per group for cohort analysis)
4. **Action-oriented**: Output directly informs a decision (which rep to coach, which competitor to counter, whether forecast is trustworthy)

**When NOT to build** (keep as handler or defer):
- Only 1-2 questions motivate it (not cross-cutting)
- Data insufficient to validate (see MEDDICC decision log 2026-09-16)
- Pure retrieval/flagging suffices (existing handlers already answer well)

**Review cadence**: Before proposing a new reasoning primitive, check this roadmap first. If question shape matches an existing primitive's motivation, expand that primitive rather than adding a new one.

---

## Future Phases (Roadmap)

### Phase 2: Dynamic Query Loop Tooling
**Goal**: Make primitives reachable by `dynamic_query_loop` for novel phrasings, not just dedicated handlers

**Gaps Identified**:
- Primitives like `deal_risk_assessor` only accessible via keyword-match handlers
- `api/tools.py` registration pattern needed for dynamic query loop access
- Need to close "handler-only, dynamic_query can't reach it" gap

### Phase 3: Convergence
**Goal**: Eliminate duplicate implementations of same logical concept

**Known Duplicates**:
- `compute_at_risk_deals` vs `deal_risk_assessor` (two separate "at-risk" definitions)
- Multiple handlers doing their own dimension resolution
- Need to identify and converge, not just add more handlers

### Phase 4: Data Quality Gates
**Goal**: Surface data gaps and quality issues proactively, not as silent failures

**Examples**:
- Missing MEDDICC scores on closed-won deals (only 4 of 327 have scores)
- Stale snapshots (deals_snapshot behind by N days)
- Uncategorized deals (no renewal_revenue, new_arr, or expansion_arr)

---

## Anti-Patterns to Avoid

### ❌ Don't Guess Thresholds
**Bad**: "Let's set the stale threshold to 14 days because it feels right"
**Good**: "Closed-won deals have scores within 7 days on average, so 14 days (2x) is the staleness bar"

### ❌ Don't Ship Unproven Protections
**Bad**: Writing verification code and assuming it works
**Good**: Plant a deliberate wrong total, prove the trap catches it, THEN ship

### ❌ Don't Optimize Before Correctness
**Bad**: "This aggregation is slow, let's cache it"
**Good**: "This aggregation is slow but correct - verify it, THEN optimize if needed"

### ❌ Don't Add Features During Bug Fixes
**Bad**: "While fixing this handler, let's also add 3 new views"
**Good**: "Fix the bug, verify the fix, ship. New features are separate work."

### ❌ Don't Batch Unrelated Changes
**Bad**: "Let's refactor 5 handlers in one commit"
**Good**: "One handler per commit, full cycle (audit → verify → ship), report between"

---

## Decision Log

### 2026-09-16: deal_risk_assessor MEDDICC Signal Deferred
**Context**: MEDDICC scores on closed-won deals (N=4) show no discrimination vs at-risk deals. Won deals score the same or LOWER on 6 of 7 components.

**Decision**: Drop MEDDICC from risk assessment until sufficient historical data (≥30 won deals with scores) exists to validate framework.

**Rationale**: Abstract Red/Yellow/Green bands don't predict outcomes for this client. Using unvalidated thresholds would create false alarms. Cycle-length signal (days past benchmark) is well-grounded in 327 historical wins - ship that alone.

**Status**: deal_risk_assessor shelved pending data. Focus returns to Phase 1b (query_pipeline_movement).

---

## How to Use This Document

1. **Before starting any work**: Read the current phase section
2. **Map your proposed work** to a specific phase/item
3. **If it doesn't map**: Stop and confirm it's actually the priority
4. **After 3+ technical exchanges**: Surface this document explicitly, zoom out

This is a living document. Update it when phases complete, decisions are made, or priorities shift.
