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

**Source (2026-09-19 revision)**: This ordering was built from Jeff's
direct domain expertise — what a CRO, and separately what a marketing/
RevOps lead (Lyndsie), actually asks in the role — **not** from a
query_cost_log audit. It replaces the earlier version of this section,
which was sourced from a 300-question query_cost_log sample
(2026-09-17). A query_cost_log/learning_log audit against real usage is
still recommended as a future validation step to confirm or reorder
this list (see "Real-Usage Cross-Check" below for a first pass at
that, done against the *prior* version of this list) — but this
ordering is the working plan until that validation happens.

### CRO-facing primitives, in priority order

1. **Forecast trustworthiness** — "how much should I believe this
   quarter's number." Built and verified (2026-09-19):
   `scripts/forecast_trust.py::assess_forecast_trust()` composes
   `assess_deal_risk()` (run directly on the current quarter's own
   COMMIT+MOST_LIKELY cohort, not the COMMIT-only scope
   `assess_deal_risk` was originally scoped for) with a pooled,
   week-indexed historical calibration baseline
   (`query_commit_ml_calibration_by_week()`, `forecast_analyses.py`) —
   a moving comparison against whichever week the current quarter is
   actually in, never a fixed anchor. Gated below week 3 (reps
   structurally don't tag Commit/Most-Likely with real forecasting
   intent that early). See the 2026-09-19 Decision Log entry below for
   the full design.
2. **Pipeline health/coverage** — Built and verified (2026-09-19):
   `scripts/pipeline_coverage.py::assess_pipeline_coverage()`. Audited
   first: `query_pipeline()`/`query_coverage()` already compute a
   coverage ratio, so this was NOT a from-scratch gap — but
   `query_coverage()` is confirmed broken in production (8,000%+
   nonsense), and neither weights pipeline by historical stage-level
   close rate or reports gap-to-goal against a real target. New+
   Expansion-ARR-only, qualified-pipeline-only (reusing the existing
   split and qualification boundary exactly), stage-weighted (fresh
   `query_stage_close_rate()` — no per-stage close-rate primitive
   existed to reuse), compared against a REAL current-quarter
   quota+stretch target (`config/targets.yaml`), always phrased
   gap-to-goal, never a bare ratio. A HEURISTIC historical coverage
   curve (2x-prior-year-actual proxy — confirmed live that no complete
   historical quarter ever had a real target) is shown for context
   only, permanently labeled as such. See the 2026-09-19 Decision Log
   entry below for the full design.
3. **Deal risk/likelihood to close** — covered by `assess_deal_risk()`,
   cycle-length signal only. This is the gap that started this whole
   thread of work.
4. **Rep performance and coaching signal** — Built and verified
   (2026-09-19): `scripts/rep_coaching.py::assess_rep_coaching()`
   composes three coaching criteria over the most recent
   transcript-scored call. Hard transcript gate (short-circuits if zero
   transcript-scored calls present). Permanent coverage disclosure
   (unconditional fleet-wide transcript availability sentence). Three
   criteria: (A) MEDDICC component advancement (did rep advance
   weak-and-concerning components at this stage), (B) discovery-question
   mapping via LLM (did rep ask stage-appropriate questions from
   `stage_focus_questions`), (C) talk-time diagnostic (Apollo only —
   internal vs prospect speaking ratio; Fireflies/Gong limitation is
   permanent and source-level, not a pending fix — those APIs provide no
   equivalent to Apollo's exact participant-ID match). Registered as
   `query_rep_coaching` handler with proper ambiguity handling (errors
   when company name matches multiple deals, not silent picking).
5. **Win/loss pattern reasoning** — `query_win_loss` exists as a
   lookup, not yet a reasoning primitive (no synthesis over WHY, just
   what).
6. **Territory/segment/region performance comparison** — dimension
   resolution exists, no comparative-reasoning layer on top.

### Marketing/RevOps-lead-facing primitives (Lyndsie), in priority order

1. **Pipeline generation by source/channel** — no primitive exists.
2. **Country/segment/region breakdown** — a real question was asked
   live (the EMEA country-breakdown thread); not yet a governed
   dimension the way region/segment/owner already are.
3. **Conversion rate by stage/source** (MQL-to-SQL-style) — no
   primitive exists.
4. **Data hygiene/attribution quality as a queryable signal** —
   currently only surfaces as an aside in prose answers, never directly
   queryable.

### Real-Usage Cross-Check (2026-09-19 full-history audit)

**This does not replace the domain-expertise ordering above** — it's a
second, independent signal sitting alongside it: what `query_cost_log`
(every `dynamic_query_loop` invocation) and `learning_log` (assessor
correctness signals) actually show across the FULL available history
(166 + 517 rows respectively). It was run against the *prior* version
of this section's list, before this revision — the mapping below is to
the current (CRO/Marketing) list. Full methodology, consolidated
frequency table, and caveats are in `PENDING_WORK.md`'s "EVIDENCE
AUDIT: What primitive to build next" entry.

- **Deal risk/likelihood to close** (CRO #3 — the gap that started this
  whole thread): **strongest standing signal in real usage**,
  unaffected by tonight's routing/truncation fixes. Real usage and
  domain expertise **agree** here — it's the one place both lists point
  the same direction. Already has `assess_deal_risk()` scoped and
  partially built (`scripts/deal_risk_assessor.py`), not a
  from-scratch ask.
- **Pipeline health/coverage** (CRO #2): raw-dominant in the logs (65%
  of all non-clean evidence, under the old "pipeline movement/
  snapshot" framing), but mostly a Phase 1b routing/handler-existence
  problem tonight's unified-routing migration and synthesis-truncation
  fix already closed, not a reasoning-layer gap. **Not a new-primitive
  priority** — worth a live spot-check for recurrence, not a build
  target.
- **Rep performance/coaching (CRO #4), win/loss pattern reasoning (CRO
  #5), country/segment/region breakdown (Marketing #2), data hygiene
  (Marketing #4)**: present in real usage but low-volume — consistent
  with, not contradicting, where they sit on the lists above. The
  country/segment/region evidence directly corroborates Marketing #2's
  own stated example (the EMEA country-breakdown thread is in the
  audited evidence).
- **Forecast trustworthiness (CRO #1)** — ranked #1 by domain expertise
  — shows only **1 raw hit** in the full-history real-usage audit.
  Can't tell from log data alone whether that means genuinely rare so
  far, or that people haven't learned to ask the agent for it yet.
- **Territory/segment/region performance comparison (CRO #6), pipeline
  generation by source/channel (Marketing #1), and conversion rate by
  stage/source (Marketing #3)**: no clear corresponding evidence found
  in the audited history at all — not contradicted, simply unconfirmed
  either way.

**The one thing worth stating plainly**: real usage *confirms* deal
risk/likelihood as a top priority — both lists agree, and it's ranked
#3 here only because forecast trustworthiness and pipeline health sit
above it by domain reasoning, not because usage ranks it lower. It does
**not yet confirm** forecast trustworthiness as urgent from real usage,
even though it's ranked #1 here on domain judgment. That gap between
domain judgment and observed usage is itself worth tracking over time,
not a reason to resolve by picking one list over the other now.

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

### 2026-09-19: Forecast Trustworthiness (CRO Priority #1) Built and Verified
**Context**: audited whether a quarter-level "how much should I trust this quarter's number" signal was computable on top of `assess_deal_risk()`. Historical COMMIT-only tagging was too sparse (peak 6-16 deals/week per quarter, all below `min_evidence_count=30`); pooling COMMIT+MOST_LIKELY across the 4 complete quarters cleared the floor (n=176 "ever tagged," n=74-104 per fixed week). Point-in-time integrity confirmed: `deals.forecast_category` (live) must never be used to judge a past quarter — 62.6% of checked historical-vs-current comparisons mismatched; only `deals_snapshot` is point-in-time-correct.

**Decisions**:
- Scope is COMMIT+MOST_LIKELY, not COMMIT alone (COMMIT-only's historical sample is too thin at any granularity).
- Below week 3 of the current quarter: hard `insufficient_data`/`too_early` gate — reps structurally don't produce honest Commit/Most-Likely tags in the coverage-building phase (Jeff's domain read, corroborated but not independently proven by the pooled win-rate-delta data).
- Comparison is a MOVING lookup against the historical win rate at whatever week the current quarter is actually in — never a fixed anchor. Week 10 (the most stable, best-evidenced point on the curve, n=104) is cited only as calibration evidence that the underlying approach is real, never as the live comparison point.
- Stability bands from the pooled week-by-week table: weeks 3-6 "forming" (lower confidence), 7-10 "settled" (highest confidence), 11-13 "late_quarter" (`lost` collapses toward zero by then — comparison answers a narrower question).
- New primitive (`scripts/forecast_trust.py`), not a mode on `assess_deal_risk()` or `forecast_analyses.py` — neither had the other's logic (per-deal risk vs. population-level calibration), so composition was the only structurally correct option.
- Composes against `assess_deal_risk()` directly, not via `get_at_risk_deals()` — that convenience wrapper hardcodes COMMIT-only and would silently drop MOST_LIKELY-tagged, non-late-stage deals from the cohort. Regression-tested directly (Step D).

**Rationale**: same standard as deal_risk_assessor's own MEDDICC deferral — no fabricated probabilities, no signal shipped below its evidence floor, every gate and band grounded in real pooled data rather than assumed.

**Status**: shipped and registered (`api/handlers.py::query_forecast_trust`, `api/router.py` intent map, `api/evaluator.py::STRUCTURED_HANDLERS`). Full Steps A-E build cycle complete: baseline tests (3), planted-discrepancy test proving the week-lookup is genuinely dynamic (not hardcoded/cached — verified by planting that exact bug and confirming the test caught it), and the MOST_LIKELY-only regression test (verified the same way — also confirmed the deal-presence assertion alone would NOT have caught a reintroduced COMMIT-only bug; only the query-shape assertion does). Live CI (`gate-tests.yml`, run [35451944255](https://github.com/jeffignacio-growthbook/MEDDICC-agent/actions/runs/35451944255)): 33/33 executed steps passed, 0 failures.

### 2026-09-19: Pipeline Coverage (CRO Priority #2) Built and Verified
**Context**: audited whether "pipeline health/coverage" was a genuine gap before scoping anything. `query_pipeline()` and a dedicated `query_coverage()` handler already compute a coverage-ratio — not a from-scratch primitive. But `query_coverage()` is confirmed broken live (divides one unscoped total pipeline figure against each individual rep's own target, producing 8,000%+ nonsense), and neither weights pipeline by historical stage performance or ever reports a real gap-to-goal.

**Decisions**:
- Scope: New+Expansion ARR only (`is_incremental_pipeline()`), renewal pipeline excluded — the existing split, reused exactly, never re-derived.
- Qualified pipeline only: `highest_stage_order_reached >= qualified_stage_order` — the exact existing boundary `query_pipeline()`/`query_coverage()` already use.
- Stage-level weighting is built fresh (`forecast_analyses.query_stage_close_rate()`) — no existing per-stage close-rate primitive to reuse (only `SEGMENT_CYCLE_BENCHMARKS`, segment-keyed not stage-keyed). Pools deal-week observations by `stage_order` across the complete quarters, gated by `min_evidence_count`; a deal at an ungated stage is excluded from the weighted total, never defaulted to a 1.0 weight.
- The goal for the current quarter (FY2027 Q3) = the REAL stated quota (`rep_targets` team total, $1.55M) + a manually-set $2.1M stretch figure — a real, explicit GrowthBook business decision (2x YoY growth target current headcount can't organically support), NOT computed. Lives in `config/targets.yaml` (`targets.fy2027_q3.stretch_target`/`stretch_note`), documented there with the full WHY. The stretch figure is read directly from that config file at call time (not seeded into the live `rep_targets` table — doing so would require a live write this build didn't perform); the quota component is read from the live table, matching `query_pipeline()`'s own precedent.
- Every pipeline-vs-target comparison is phrased gap-to-goal ("$X short of target"/"$X over target"), never a bare ratio.
- The historical coverage-TARGET curve cannot be built from real historical targets: confirmed live that NONE of the 4 complete historical quarters (FY2026 Q3/Q4, FY2027 Q1/Q2) ever had a real target in `rep_targets`, in any label format (zero rows). The curve instead uses a proxy: target = 2x the SAME quarter's actual closed-won incremental ARR from the PRIOR YEAR. Further checked: none of the 4 prior-year bases (FY2025 Q3/Q4, FY2026 Q1/Q2 — 9-17 deals each) clear `min_evidence_count=30` — confirmed this is a **permanent structural ceiling** (monotonic 8-quarter growth trend, HubSpot history doesn't extend further back), not a fixable gap. The curve is therefore permanently labeled a **HEURISTIC** — the literal word, not "directional" or "approximate" — everywhere it appears in output text, explicitly distinguished from the real current-quarter target (never labeled a heuristic).

**Rationale**: same standard as the forecast-trustworthiness build — never fabricate a signal past its real evidence floor, and never let a smooth-looking curve substitute for checking the reliability of its own inputs.

**Status**: shipped and registered (`api/handlers.py::query_pipeline_coverage`, `api/router.py` intent map — disambiguated from the legacy, confirmed-broken `query_coverage`, `api/evaluator.py::STRUCTURED_HANDLERS`). Full Steps A-E build cycle complete: baseline tests (scope exclusion, stage weighting, gap-to-goal phrasing in both directions, HEURISTIC-vs-real-target labeling) plus two planted-discrepancy proofs — the HEURISTIC label requirement and the renewal-pipeline exclusion were each verified by actually planting the regression in `scripts/pipeline_coverage.py`, confirming the relevant test genuinely failed, then restoring and confirming a clean pass. Two new structural tests added to `scripts/test_forecast_analyses.py` for the underlying `query_stage_close_rate()`/`query_coverage_proxy_target_by_week()` functions. Wired into `gate-tests.yml` (TEST 0bf). Along the way, promoting the audit-script logic into `scripts/analytics/forecast_analyses.py` tripped two of this codebase's own existing correctness ratchets in `eval_reconstruction.py` — a null-coalescing violation (`_qualified_pipeline_at_week()` was coalescing a null `deal_value` to 0 in a dollar sum) and a missing `OUTCOME-READ` marker (`_actual_incremental_closed_won()`'s terminal-outcome read of `stage`) — both real findings, fixed by null-propagating (exclude-and-count, matching `compute_waterfall.py`'s established pattern) and adding the marker respectively. Live CI (`gate-tests.yml`, run [35457724659](https://github.com/jeffignacio-growthbook/MEDDICC-agent/actions/runs/35457724659)): 39/39 executed steps passed, 0 failures (TEST 3's live smoke test skipped by design, gated behind an explicit opt-in input).

### 2026-09-19: Rep Coaching (CRO Priority #4) Built and Verified
**Context**: per-deal coaching assessment composing three criteria over the most recent transcript-scored call. Identified need for: (A) MEDDICC component advancement (did rep advance weak components), (B) discovery-question mapping (did rep ask stage-appropriate questions), (C) talk-time diagnostic (speaking ratio).

**Decisions**:
- Hard transcript gate: short-circuits with `insufficient_data` if deal has zero transcript-scored calls (`call_scores.text_source='transcript'`). No fabricated assessment when underlying data doesn't exist.
- Permanent coverage disclosure: unconditional fleet-wide transcript availability sentence (`query_coaching_transcript_coverage()`) in BOTH gated and ungated paths — never omitted, matching HEURISTIC label pattern from pipeline-coverage primitive.
- Shared Step 0 (weak component identification): stage bucketing (`stage_bucket()`), stage-specific `concerning_threshold` lookup (`stage_scoring_expectations`), pre-call baseline via `roll_up()`, band labeling (`band_label()`) and concerning-threshold comparison. Zero weak components returns empty list (not error) — "nothing to advance" is a valid coaching state.
- Criterion A (MEDDICC component advancement): checks if target call improved weak component bands vs. pre-call baseline. Returns per-component advancement status with evidence.
- Criterion B (discovery-question mapping): LLM (Haiku/assessor) reads transcript against `stage_focus_questions[bucket][component]`. Champion-specific: checks `genuine_champion.signals` for champion-elicitation attempts. Graceful LLM failure (question_asked=None with error note, doesn't crash). Transcript limit: 100,000 chars (12.5% of Haiku's 800k capacity) — initial 8,000-char PREFIX truncation was caught as critical bug (dropped 74.5% of avg 31,404-char transcript, silently cutting late-call champion elicitation, documented in `scripts/CRITERION_B_TRUNCATION_FIX.md`).
- Criterion C (talk-time diagnostic): Apollo-sourced calls return diagnostic numbers (internal_talk_ratio, internal_question_share) via `coaching_talk_ratio.py::assess_call_talk_ratio()`. Fireflies/Gong return explicit `source_not_supported` with reason (never silently omitted) — those APIs provide no equivalent to Apollo's exact participant-ID matching (`participant_identities`), permanent source-level limitation not a pending fix.
- Handler ambiguity handling: when company name resolves to multiple deals, returns explicit error listing deals (company, stage, owner) and asks user to disambiguate — no silent picking of first match.

**Rationale**: same standard as forecast-trustworthiness and pipeline-coverage — gate on data availability, never fabricate signals past their evidence floor, explicit labeling of limitations (Fireflies/Gong not silently absent).

**Status**: shipped and registered (`scripts/rep_coaching.py::assess_rep_coaching()`, `api/handlers.py::query_rep_coaching`, `api/router.py` intent map, `api/evaluator.py::STRUCTURED_HANDLERS`). Full Steps 2-6 plus A-E build cycle complete: hard transcript gate tests (2), coverage disclosure tests (2), Criterion A tests (3), Criterion B tests (4), Criterion C tests (3), integration tests (4 baseline scenarios), planted-discrepancy test (verifies no corruption/omission in combined output), ambiguity-handling tests (2). Total: 21 tests pass locally. Live CI (`gate-tests.yml`, runs [35476559151](https://github.com/jeffignacio-growthbook/MEDDICC-agent/actions/runs/35476559151) and [35477162917](https://github.com/jeffignacio-growthbook/MEDDICC-agent/actions/runs/35477162917) post-ambiguity-fix): 40/40 executed steps passed, 0 failures.

---

## How to Use This Document

1. **Before starting any work**: Read the current phase section
2. **Map your proposed work** to a specific phase/item
3. **If it doesn't map**: Stop and confirm it's actually the priority
4. **After 3+ technical exchanges**: Surface this document explicitly, zoom out

This is a living document. Update it when phases complete, decisions are made, or priorities shift.
