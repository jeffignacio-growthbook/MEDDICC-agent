-- Add new_arr and expansion_arr to deals_snapshot, registered in
-- data_dictionary in this SAME migration (per the region/segment
-- registration-gap lesson: migration 060 added region/segment to
-- deals_snapshot without registering them in data_dictionary, and the
-- gap wasn't caught until migration 062, after it had already caused a
-- real budget-exhaustion incident — see 062's own comment. This
-- migration does not repeat that mistake.
--
-- WHY: compute_forecast.py's week-3 average-deal-size fallback
-- (scripts/analytics/forecast_analyses.py's sibling, compute_forecast.py)
-- could only read deals_snapshot.deal_value, not the two raw components
-- that make it up. config/client.yaml's own value_field comment
-- documents a real, verified hazard: HubSpot's own combined
-- "Incremental ARR" calculated field nulls out when EITHER New ARR or
-- Expansion ARR is individually blank, even when the other is a real
-- known value. The `deals` table has carried the two raw, independently-
-- reliable components since migration 007 specifically to avoid that
-- hazard (summing them directly instead of trusting the combined
-- field); deals_snapshot never did, so its one dollar-weighted
-- fallback could not recompute the same way and had to fall back to
-- null-propagating the combined deal_value field instead (see
-- PENDING_WORK.md Low Priority #11).
--
-- POINT-IN-TIME, NOT BACKFILLED: per the exact lesson already learned
-- from region/segment (scripts/analytics/backfill_snapshot_enrichment.py
-- backfilled historical rows with CURRENT values, an acknowledged
-- imperfect approximation since a deal's region/segment can change over
-- time) — new_arr/expansion_arr are NOT backfilled here. A deal's
-- current New ARR/Expansion ARR does not necessarily reflect what was
-- true at a past snapshot date; a wrong number is worse than an honest
-- unknown. Existing historical rows get these columns as NULL and stay
-- NULL — they genuinely don't have this data and never will.
-- scripts/analytics/snapshot_deals.py is updated in the same change to
-- populate both going forward, starting from the next snapshot run.

ALTER TABLE deals_snapshot
  ADD COLUMN IF NOT EXISTS new_arr NUMERIC,
  ADD COLUMN IF NOT EXISTS expansion_arr NUMERIC;

COMMENT ON COLUMN deals_snapshot.new_arr IS
'Point-in-time New ARR from HubSpot new_revenue property, captured at
snapshot time. NULL for snapshots taken before this column existed
(migration 064) — intentionally not backfilled, since a deal''s current
New ARR does not reflect what was true at a past date. Use alongside
expansion_arr to recompute Incremental ARR directly (New ARR +
Expansion ARR) rather than reading deal_value, which can be affected by
a NULL-out hazard in HubSpot''s own combined calculated field when
either component is individually blank — see config/client.yaml''s
value_field comment.';

COMMENT ON COLUMN deals_snapshot.expansion_arr IS
'Point-in-time Expansion ARR from HubSpot expansion_revenue property,
captured at snapshot time. NULL for snapshots taken before this column
existed (migration 064) — intentionally not backfilled, same rationale
as new_arr. Use alongside new_arr to recompute Incremental ARR
directly.';

INSERT INTO data_dictionary
  (source, supabase_table, supabase_column, data_type, description, is_queryable)
VALUES
  ('supabase', 'deals_snapshot', 'new_arr', 'number',
   'New ARR AS OF this snapshot date, from HubSpot''s new_revenue '
   'property. Point-in-time value captured at snapshot time — sum with '
   'expansion_arr for Incremental ARR at that date. NULL for snapshots '
   'taken before this column existed (2026-09-11) and intentionally not '
   'backfilled; do NOT join to deals.new_arr for a historical snapshot, '
   'a deal''s current New ARR can differ from what it was at that date.',
   true),
  ('supabase', 'deals_snapshot', 'expansion_arr', 'number',
   'Expansion ARR AS OF this snapshot date, from HubSpot''s '
   'expansion_revenue property. Point-in-time value captured at '
   'snapshot time — sum with new_arr for Incremental ARR at that date. '
   'NULL for snapshots taken before this column existed (2026-09-11) '
   'and intentionally not backfilled; do NOT join to deals.expansion_arr '
   'for a historical snapshot, a deal''s current Expansion ARR can '
   'differ from what it was at that date.',
   true)
ON CONFLICT (supabase_table, supabase_column) DO UPDATE SET
  data_type    = EXCLUDED.data_type,
  description  = EXCLUDED.description,
  is_queryable = EXCLUDED.is_queryable,
  last_refreshed = now();
