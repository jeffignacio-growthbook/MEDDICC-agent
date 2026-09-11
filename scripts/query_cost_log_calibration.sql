-- ============================================================
-- Cost-aware planner calibration queries for query_cost_log
-- (migration 063_add_query_cost_log.sql)
-- ============================================================
-- Last run: 2026-09-11, against the full query_cost_log table (13 rows
-- at the time — this week's own testing, not a week of organic
-- production traffic). Results were used to calibrate
-- resolve_execution_cost_estimate() in api/router.py — see that
-- function's own module-level comment (_COST_BASE_ITERATIONS,
-- _COST_BASE_TOKENS, _COST_DELTAS) for exactly which numbers came from
-- which query below, and the sample-size caveat that applies to all of
-- them. Re-run this file (or query_cost_log directly) and update those
-- constants once meaningfully more traffic has accumulated — there is
-- no automated recalibration; this is a manual, occasional pass.

-- A. Overall cost distribution by outcome bucket.
-- Tells us: does answered_cleanly cost meaningfully less than
-- answered_after_resynthesis / budget_exhausted, and by how much?
SELECT
  outcome,
  COUNT(*) AS n,
  ROUND(AVG(final_iteration_count)::numeric, 2) AS avg_iterations,
  PERCENTILE_CONT(0.5) WITHIN GROUP (ORDER BY final_iteration_count) AS median_iterations,
  PERCENTILE_CONT(0.9) WITHIN GROUP (ORDER BY final_iteration_count) AS p90_iterations,
  MAX(final_iteration_count) AS max_iterations,
  ROUND(AVG(final_tokens_used)::numeric, 0) AS avg_tokens,
  PERCENTILE_CONT(0.5) WITHIN GROUP (ORDER BY final_tokens_used) AS median_tokens,
  PERCENTILE_CONT(0.9) WITHIN GROUP (ORDER BY final_tokens_used) AS p90_tokens,
  MAX(final_tokens_used) AS max_tokens
FROM query_cost_log
GROUP BY outcome
ORDER BY n DESC;


-- B. Per-primitive marginal cost breakdown (fired=true vs fired=false).
-- This is the core calibration input: for each feature the estimator
-- could detect ahead of time (snapshot_anchor_injected = "mentions a
-- comparison timeframe", dimension_resolver_matched = "mentions
-- dimension terms", enrichment_shortcut_fired = "needed an enrichment
-- lookup on top of a base query"), how much extra does it typically
-- cost when it fires?
WITH primitive_keys AS (
  SELECT unnest(ARRAY[
    'snapshot_anchor_injected','dimension_resolver_matched',
    'enrichment_shortcut_fired','scratchpad_rejection_fired',
    'aggregation_mismatch_caught','forced_anchor_fetch_fired',
    'snapshot_diff_computed','diff_company_name_backfill_fired',
    'false_partial_claim_caught','aggregation_mismatch_unresolved_after_retry',
    'ambiguous_dimension_term_flagged','snapshot_date_labeling_unverified',
    'finalize_scratchpad_caught','ambiguous_dimension_unaddressed',
    'zero_rows_suspicion_flagged','zero_rows_suspicion_unresolved'
  ]) AS key
)
SELECT
  pk.key AS primitive,
  COALESCE((qcl.primitives_fired->>pk.key)::boolean, false) AS fired,
  COUNT(*) AS n,
  ROUND(AVG(qcl.final_iteration_count)::numeric, 2) AS avg_iterations,
  PERCENTILE_CONT(0.5) WITHIN GROUP (ORDER BY qcl.final_iteration_count) AS median_iterations,
  PERCENTILE_CONT(0.9) WITHIN GROUP (ORDER BY qcl.final_iteration_count) AS p90_iterations,
  ROUND(AVG(qcl.final_tokens_used)::numeric, 0) AS avg_tokens,
  PERCENTILE_CONT(0.5) WITHIN GROUP (ORDER BY qcl.final_tokens_used) AS median_tokens,
  PERCENTILE_CONT(0.9) WITHIN GROUP (ORDER BY qcl.final_tokens_used) AS p90_tokens,
  MAX(qcl.final_tokens_used) AS max_tokens
FROM primitive_keys pk
CROSS JOIN query_cost_log qcl
GROUP BY pk.key, fired
ORDER BY pk.key, fired;


-- C. Recent rows in full, to identify and validate the specific known
-- question shapes from this week (simple lookup, snapshot comparison
-- with enrichment, the EMEA/Enterprise/Jake composite question). Widen
-- LIMIT or add a created_at filter if this week's traffic is more than
-- 200 rows.
SELECT
  id, created_at, question, outcome, reason_tag, answered,
  final_iteration_count, final_tokens_used,
  primitives_fired, resolved_dimension_terms
FROM query_cost_log
ORDER BY created_at DESC
LIMIT 200;


-- D. Convenience keyword search for the composite question specifically
-- (adjust keywords if the actual wording differs).
SELECT
  id, created_at, question, outcome, reason_tag,
  final_iteration_count, final_tokens_used, primitives_fired
FROM query_cost_log
WHERE question ILIKE '%EMEA%'
  AND question ILIKE '%enterprise%'
  AND question ILIKE '%jake%'
ORDER BY created_at DESC;
