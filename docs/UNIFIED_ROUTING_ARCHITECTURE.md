# Unified Routing Architecture

**Status:** 🛑 **DO NOT START WITHOUT JEFF'S GO-AHEAD**

This is a real, deliberate initiative to eliminate a demonstrated bug class by converging handler routing into the dynamic query loop's existing tool-selection mechanism.

**Created:** 2026-09-18
**Context:** Phase 1b handler audits revealed three separate bugs traced to the classifier-based routing mechanism. This proposes converging to a single, proven-reliable routing system.

---

## Current State: Dual Routing Systems

### Classifier-Based Handler Routing (router.py)

**How it works:**
1. Separate LLM call (Sonnet 4.5 classifier) evaluates user question
2. Scores confidence for each handler using HANDLER_DESCRIPTIONS text
3. If confidence >= 0.80, route to dedicated handler
4. If confidence < 0.80, fall back to dynamic_query loop

**Demonstrated fragility this session (Phase 1b):**

1. **max_tokens truncation (1 month of silent corruption)**
   - Classifier configured with max_tokens=300
   - Handler descriptions expanded over time → truncation mid-description
   - ALL handlers potentially unreachable, discovered only accidentally
   - Issue: Classifier-specific configuration parameter silently broke routing

2. **Circular redirect chains (query_pipeline → query_waterfall → query_pipeline_movement)**
   - Handler A's description said "use handler B for X"
   - Handler B's description said "use handler C for X"
   - Loop required manual redirect graph analysis to detect
   - Issue: Cross-handler coordination in HANDLER_DESCRIPTIONS is brittle

3. **Routing ambiguities (query_win_loss vs query_waterfall)**
   - Two handlers claimed overlapping question patterns
   - Required manual description strengthening to disambiguate
   - Issue: Confidence scoring doesn't guarantee mutual exclusivity

**Additional complexity:**
- Separate code path for handler vs dynamic routing
- Different error handling for each path
- Schema params extracted by classifier but not visible to dynamic loop
- params["question"] injection required for handlers (discovered as bug during Phase 1b)

---

## Proposed Design: Unified Tool-Based Routing

### Fold Handlers Into Dynamic Query Loop

**Core concept:** Handlers register as callable tools in the dynamic query loop, same pattern already proven with `assess_deal_risk` and other functions.

**How it would work:**

1. **Handler registration:** Each handler registered as a tool with:
   ```python
   {
       "name": "query_pipeline",
       "description": HANDLER_DESCRIPTIONS["query_pipeline"],  # Reuse existing text
       "parameters": HANDLER_PARAMS["query_pipeline"],
       "function": handlers.query_pipeline
   }
   ```

2. **First-iteration routing:** Dynamic loop's existing tool-selection mechanism (same LLM, same context) decides whether a handler fits the question.

3. **Fast-path preservation:** If handler called and returns successful result, treat as final answer immediately (same speed as today's direct routing).

4. **Seamless fallback:** If no handler fits, loop continues with primitives (filter_table, aggregate_results, etc.) - no separate "fallback" step needed.

5. **Single reliability standard:** One routing mechanism, one LLM call, one set of tool descriptions. All tools (handlers + primitives) compete equally.

**What changes:**
- Handler routing moves from separate classifier call into first iteration of dynamic loop
- HANDLER_DESCRIPTIONS become tool descriptions (no format change)
- params["question"] no longer needed (loop already has full question context)
- Redirect logic unnecessary (loop handles multi-step reasoning natively)

**What stays the same:**
- Handler implementations unchanged
- Handler return formats unchanged
- HANDLER_DESCRIPTIONS text unchanged (just used as tool descriptions)
- Structured verification unchanged
- Baseline outputs unchanged (same handler called for same questions)

---

## Why This Is Better, Not Just Different

### Eliminates Demonstrated Bug Class

**Classifier-specific fragility goes away:**
- No max_tokens parameter to misconfigure (loop uses standard token limits)
- No confidence scoring ambiguities (loop's reasoning is explicit in logs)
- No redirect chains (loop handles multi-step natively)
- No separate schema extraction (loop's tool calling handles params)

**Single source of reliability:**
- The dynamic loop handled complex multi-step queries reliably all session
- It reasoned through filters, aggregations, enrichments without fragility
- It logged every decision explicitly ([LOOP iter=N] traces)
- Why maintain TWO routing systems when one is proven more reliable?

### Reduces Maintenance Surface

**One fewer mechanism to tune:**
- HANDLER_DESCRIPTIONS already exist, just reuse them as tool descriptions
- No separate classifier prompt to maintain
- No confidence threshold to tune (0.80 was arbitrary)
- No redirect graph to audit

**Simpler debugging:**
- One log stream ([LOOP iter=N]) for all routing decisions
- Handler call appears alongside primitive calls in same trace
- No separate [INTENT] logs to cross-reference

---

## Real Risks To Scope Before Building

### 1. Latency/Cost Impact

**MEASURED (2026-09-18):**

Current classifier approach:
- Input: ~7,200 tokens (handler descriptions + JSON schema + semantic context)
- Output: ~175 tokens (JSON with handler + params)
- Cost per query: ~$0.024

Proposed loop-with-handlers approach:
- Input: ~8,400 tokens (primitives + schema + semantic context + ALL handler descriptions as tools)
- Output: ~250 tokens (tool reasoning + params)
- Cost per query: ~$0.029

**Delta: +$0.005 per query (+21%), or ~$5/month per 1,000 questions**

**Latency impact:** +0.2-0.5 seconds per question (loop first iteration slightly larger than classifier)

**Break-even analysis (for reference, not justification):**
- Cost increase: $5/month per 1,000 questions
- Cost to diagnose + fix routing bug: 2-4 engineer hours = $150-600
- Theoretical break-even: 0.8-3 bugs per month

**Phase 1b found:** 3 distinct routing bugs in one session - a backlog of latent bugs discovered through systematic audit, not a confirmed ongoing recurrence rate.

**Actual decision rationale:** $5/month is negligible regardless of exact bug frequency. The cost is justified by eliminating a demonstrated fragility class (classifier-specific configuration, redirect chains, confidence ambiguities) with explicit reasoning + single-mechanism simplicity. The break-even math is directionally supportive but not the primary justification.

### 2. Baseline Re-Verification For Converged Handlers

**6 handlers already have baselines from Phase 1b:**
- query_waterfall
- query_deals_at_risk
- query_win_loss
- query_rep_pipeline
- query_pipeline_movement
- query_stale_deals

**Risk:** Routing change might alter which handler gets called for edge-case questions.

**Mitigation required:**
- Re-run all baseline captures under new routing
- Verify byte-exact match on handler invoked + output structure
- Document any questions that route differently (and why)

**Likely outcome:** Identical routing for clear-cut questions, potentially BETTER routing for ambiguous questions (loop's reasoning is more explicit).

### 3. Structured Verification Impact

**Current:** verify_structured_aggregations() wired at handler return (query_pipeline, query_waterfall, query_rep_pipeline, etc.)

**Proposed:** Same - handler implementations don't change, just how they're invoked.

**Risk:** Loop might handle handler results differently than direct returns.

**Mitigation required:**
- Verify [STRUCTURED_VERIFY] logs still fire
- Verify planted bugs still get caught
- Confirm loop treats handler exceptions correctly

**Likely outcome:** No impact (verification happens inside handler, before return), but confirm.

### 4. Handler-Specific Features

**entity_scoped routing (deal_ids injection):**
- Currently: Classifier detects entity mentions, injects deal_ids param
- Proposed: Loop's existing entity extraction handles this naturally

**time_window resolution:**
- Currently: Classifier extracts time_window param
- Proposed: Loop already has time_resolver tool, handlers can call it or accept param

**Redirect chains (intentional):**
- Currently: query_waterfall can redirect to query_pipeline_movement
- Proposed: Loop reasons through this naturally ("I need pipeline movement data, so I'll call query_pipeline_movement")

**Risk:** Feature parity needs explicit verification.

---

## Rough Phasing: Proof of Concept First

### Phase 1: Single Handler Migration (query_pipeline_movement)

**Why query_pipeline_movement (NOT query_pipeline):**
- **query_pipeline never exhibited any of the 3 bugs** - it routed reliably, no circular redirects, no ambiguities
- **query_pipeline_movement HAD the actual circular-redirect bug** - query_waterfall → query_pipeline_movement redirect chain
- Migrating it proves the loop eliminates the specific bug class we're targeting (redirects become structurally impossible)
- Has 4 baseline captures from Phase 1b (movement, composition, curve, stage_deals views)
- Complex multi-view routing logic tests tool-selection reasoning

**Pilot proves:** Eliminating demonstrated bug (not just clean migration of unaffected handler)

**Steps:**
1. Register query_pipeline_movement as a tool in dynamic loop (alongside existing primitives)
2. Disable classifier routing for query_pipeline_movement only (other handlers use old path)
3. Capture new baselines for all 4 test questions
4. Compare byte-exact against Phase 1b baselines
5. Verify [LOOP iter=1] logs show explicit tool-selection reasoning
6. Measure latency/cost delta

**Success criteria:**
- Baselines match exactly (same handler called, same output structure)
- [LOOP iter=1] logs show clear reasoning for selecting query_pipeline_movement
- No circular redirect possible (structural property of loop)
- Latency delta <500ms
- Cost delta within 25% of current

### Phase 2: Full Migration

**Only if Phase 1 succeeds:**
1. Migrate remaining handlers one-by-one
2. Re-verify baselines for each
3. Remove classifier routing entirely
4. Remove HANDLER_DESCRIPTIONS dict (use tool descriptions directly)
5. Remove redirect logic (loop handles multi-step natively)

**Success criteria:**
- All handlers route correctly
- All baselines match
- No increase in fallback rate
- Measurable reduction in routing bugs (by definition: classifier bugs eliminated)

---

## Decision Points For Jeff

**Before starting Phase 1:**
1. Is eliminating classifier fragility worth the migration risk?
2. What's the acceptable latency/cost delta threshold?
3. Should we measure current classifier reliability first (establish baseline failure rate)?
4. Any other architectural constraints to consider?

**This is documented for review, not implementation.** Do not proceed without explicit go-ahead.

---

## References

**Related bugs fixed this session:**
- max_tokens truncation: Commit ffae344
- Circular redirects: Documented in /tmp/redirect_analysis.md
- Routing ambiguities: Commit 4cca990

**Related pattern:**
- assess_deal_risk callable tool: api/router.py lines 3500-3520 (example of handler-as-tool)
- Dynamic loop tool calling: api/router.py lines 1800-2100 (proven reliable mechanism)

**Baseline captures:** /tmp/baseline_*.log (8 captures across 4 handlers from Phase 1b)
