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
