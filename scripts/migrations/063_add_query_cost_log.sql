-- Structured cost logging for every dynamic_query_loop invocation.
--
-- 2026-09-11: the loop's token/iteration ceiling (DYNAMIC_LOOP_TOKEN_BUDGET
-- = 200_000, DYNAMIC_LOOP_MAX_ITERATIONS = 12) was deliberately set generous
-- rather than tuned further against any single incident — see the
-- 2026-09-11 "Reframe the fix" commit. Deciding whether 200K is actually
-- generous enough, too generous, or still not enough for some undiscovered
-- question shape needs a real distribution of real usage, not another
-- guess. This table is that distribution: one row per invocation,
-- independent of whether it succeeded, hit budget, or failed any other way
-- (Railway/console logs capture the same events but aren't easily
-- queryable for pattern analysis across a week of traffic).
--
-- Distinct from fallback_log, which only gets a row from specific give-up/
-- success call sites (not every exit path, and with no iteration/token/
-- primitive breakdown) — this is a uniform, always-fires log.

CREATE TABLE IF NOT EXISTS query_cost_log (
    id BIGSERIAL PRIMARY KEY,
    question TEXT NOT NULL,
    final_iteration_count INTEGER,
    -- 0-indexed iteration number reached when the loop exited (NULL if it
    -- never entered the main iteration loop at all).
    final_tokens_used INTEGER,
    -- Actual measured tokens across every client.complete() call made
    -- during this invocation (main loop iterations + any finalize-path
    -- synthesis/resynthesis calls) — not the loop's own pre-call
    -- projection, which is a budget-check estimate, not a measurement.
    primitives_fired JSONB,
    -- {"snapshot_anchor_injected": bool, "dimension_resolver_matched": bool,
    --  "enrichment_shortcut_fired": bool, "scratchpad_rejection_fired": bool,
    --  "aggregation_mismatch_caught": bool, "forced_anchor_fetch_fired": bool,
    --  "snapshot_diff_computed": bool}
    resolved_dimension_terms JSONB,
    -- The actual terms the proactive dimension resolver matched in the
    -- question (e.g. ["EMEA", "enterprise"]), for correlating which
    -- question shapes trigger which primitives.
    reason_tag TEXT,
    -- The internal give-up/finalize reason (budget_exhausted, no_progress,
    -- duplicate_tool_call, id_scoped_enrichment_lookup,
    -- scratchpad_prose_rejected, aggregation_mismatch_unresolved,
    -- iterations_exhausted, ...) — NULL when the model answered directly
    -- on its first attempt with no finalize/give-up path involved at all.
    -- Never shown to the user; internal telemetry only, same discipline as
    -- everywhere else this tag is used.
    outcome TEXT NOT NULL,
    -- One of: answered_cleanly | answered_after_resynthesis |
    -- budget_exhausted | other_fallback | exception
    answered BOOLEAN NOT NULL DEFAULT FALSE,
    created_at TIMESTAMPTZ DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_query_cost_log_outcome
    ON query_cost_log(outcome, created_at DESC);

CREATE INDEX IF NOT EXISTS idx_query_cost_log_created_at
    ON query_cost_log(created_at DESC);

-- GIN index for question-pattern grouping, same convention as
-- fallback_log.idx_fallback_log_question_pattern.
CREATE INDEX IF NOT EXISTS idx_query_cost_log_question_pattern
    ON query_cost_log USING gin(to_tsvector('english', question));

-- GIN index for querying "which requests fired primitive X"
-- (e.g. WHERE primitives_fired @> '{"scratchpad_rejection_fired": true}').
CREATE INDEX IF NOT EXISTS idx_query_cost_log_primitives_fired
    ON query_cost_log USING gin(primitives_fired);

COMMENT ON TABLE query_cost_log IS
'One row per dynamic_query_loop invocation, regardless of outcome. The
basis for deciding whether the 200K-token/12-iteration ceiling is
correctly sized, and for a future cost-aware planner''s estimates, using
real distributions instead of guesses.';
