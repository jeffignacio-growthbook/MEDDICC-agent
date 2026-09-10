-- Migration: Register deals_snapshot.region and deals_snapshot.segment in
-- data_dictionary so the dynamic query loop can see they exist.
--
-- ROOT CAUSE (found 2026-09-11, budget-exhaustion investigation): migration
-- 060 added region/segment directly to deals_snapshot via ALTER TABLE, and
-- scripts/analytics/snapshot_deals.py has written real values into both
-- columns ever since. But 060 never added corresponding data_dictionary
-- rows, and data_dictionary — not information_schema — is what
-- api/schema_context.py's get_schema_context() reads to build the model's
-- view of "queryable columns" for the dynamic query loop.
--
-- Consequence: every "which deals changed stage in EMEA/Enterprise"
-- question caused the model to query deals_snapshot WITHOUT region/segment
-- (it wasn't told they existed), then state — correctly, given what it was
-- shown, incorrectly given the real table — "the snapshot data doesn't
-- include segment or region columns," and burn an extra iteration
-- re-querying deals for them, when deals_snapshot already had the exact
-- point-in-time values needed and could have filtered on them in the very
-- first query. That extra iteration was the direct, most avoidable cause
-- of the token growth pushing this query shape into budget exhaustion.
--
-- This migration only adds data_dictionary rows for two columns that
-- already exist in Postgres (per migration 060) and are already populated
-- (per snapshot_deals.py) — no schema change to deals_snapshot itself.

INSERT INTO data_dictionary
  (source, supabase_table, supabase_column, data_type, description, is_queryable)
VALUES
  ('supabase', 'deals_snapshot', 'region', 'text',
   'Sales region AS OF this snapshot date: NAM, EMEA, APAC, LATAM, ROW, or '
   'UNKNOWN. Point-in-time value captured at snapshot time — filter on this '
   'directly for region-scoped point-in-time comparisons. Do NOT join to '
   'deals.region for a historical snapshot; a deal''s current region can '
   'differ from what it was at that snapshot date.',
   true),
  ('supabase', 'deals_snapshot', 'segment', 'text',
   'Company size segment AS OF this snapshot date: SMB, Mid-Market, '
   'Enterprise, or Unknown. Point-in-time value captured at snapshot time — '
   'filter on this directly for segment-scoped point-in-time comparisons. '
   'Do NOT join to deals.segment for a historical snapshot; a deal''s '
   'current segment can differ from what it was at that snapshot date.',
   true)
ON CONFLICT (supabase_table, supabase_column) DO UPDATE SET
  data_type    = EXCLUDED.data_type,
  description  = EXCLUDED.description,
  is_queryable = EXCLUDED.is_queryable,
  last_refreshed = now();
