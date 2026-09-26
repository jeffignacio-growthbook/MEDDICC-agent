-- Migration 074: rename pipeline_generation_weekly -> pipeline_generation_quarterly
-- Date: 2026-09-26
-- Depends on: 015_create_pipeline_generation_weekly.sql

-- ROOT CAUSE (2026-09-26, "how much pipeline did we generate this week" live
-- failure): the LLM table-classifier (api/table_classifier.py) routes purely
-- on fuzzy name/description match with zero grain-awareness. Its description
-- for this table — "New pipeline created each week" — is a near-verbatim
-- match for a week-grained question, but the table has NO week column at
-- all: it is keyed on (fiscal_quarter, pipeline_id, segment), one row per
-- quarter. The question landed here instead of on the genuinely weekly
-- waterfall_weekly, the model faked a week filter against the write
-- timestamp (last_updated), got 0 rows, and fell back to "could not find
-- anything." Compounding it: this table's own writer
-- (scripts/analytics/compute_pipeline_generation.py) is wired into no
-- workflow, so all 77 rows were frozen at 2026-08-11 — a second frozen
-- artifact alongside the qualified_date bug fixed earlier tonight.
--
-- This table is NOT a duplicate of waterfall_weekly at a coarser grain: it
-- computes in_quarter_contribution_value/rollover_value (created-and-closed
-- same quarter vs. rolling into a later one), a genuinely quarter-level
-- question waterfall_weekly does not answer. So the fix is to rename it to
-- match what it actually is — quarterly — not to delete it, and to make the
-- classifier's descriptions grain-explicit so a week-grained question can
-- never again land on a quarter-grained table by name-collision alone (see
-- api/table_classifier.py and tests/test_classifier_grain_descriptions.py).

ALTER TABLE pipeline_generation_weekly RENAME TO pipeline_generation_quarterly;

ALTER INDEX IF EXISTS idx_pipeline_gen_quarter    RENAME TO idx_pipeline_generation_quarterly_quarter;
ALTER INDEX IF EXISTS idx_pipeline_gen_segment    RENAME TO idx_pipeline_generation_quarterly_segment;
ALTER INDEX IF EXISTS idx_pipeline_gen_composite  RENAME TO idx_pipeline_generation_quarterly_composite;

-- Carry the data_dictionary rows over to the new table name, and correct
-- their descriptions: the live rows (registered via
-- scripts/backfill_data_dictionary.py, not a checked-in migration — see
-- config/data_dictionary_exclusions.yaml's note on this) described the
-- grain as weekly ("number of new deals generated during the week"),
-- which is what let this collision happen in the first place.
UPDATE data_dictionary
   SET supabase_table = 'pipeline_generation_quarterly'
 WHERE supabase_table = 'pipeline_generation_weekly';

UPDATE data_dictionary SET description =
  'Stores the fiscal quarter identifier (e.g. "FY2027 Q3") this row aggregates. '
  'This table is QUARTER-grained — one row per (fiscal_quarter, pipeline_id, '
  'segment) — never weekly; for week-level pipeline generation use '
  'waterfall_weekly.new_pipeline_value / newly_qualified_value by week_ending.'
  , last_refreshed = now()
 WHERE supabase_table = 'pipeline_generation_quarterly' AND supabase_column = 'fiscal_quarter';

UPDATE data_dictionary SET description =
  'Total value of deals created within this fiscal QUARTER (not week) for this '
  '(pipeline_id, segment). Not comparable to waterfall_weekly.new_pipeline_value, '
  'which is week-grained and keyed on qualified_date, not create_date.'
  , last_refreshed = now()
 WHERE supabase_table = 'pipeline_generation_quarterly' AND supabase_column = 'generated_value';

UPDATE data_dictionary SET description =
  'Count of deals created within this fiscal QUARTER (not week) for this '
  '(pipeline_id, segment). Counts a deal even if it has since won/lost.'
  , last_refreshed = now()
 WHERE supabase_table = 'pipeline_generation_quarterly' AND supabase_column = 'deal_count';

UPDATE data_dictionary SET description =
  'Portion of this quarter''s generated_value from deals BOTH created and '
  'closed within the same fiscal quarter (fast-cycle segments contribute a '
  'higher share here than slow-cycle ones).'
  , last_refreshed = now()
 WHERE supabase_table = 'pipeline_generation_quarterly' AND supabase_column = 'in_quarter_contribution_value';

UPDATE data_dictionary SET description =
  'Portion of an EARLIER quarter''s generated_value whose deals are still '
  'active and closing in the CURRENT quarter (rollover pipeline), attributed '
  'to the closing quarter''s row.'
  , last_refreshed = now()
 WHERE supabase_table = 'pipeline_generation_quarterly' AND supabase_column = 'rollover_value';

UPDATE data_dictionary SET description =
  'HubSpot pipeline this row''s deals belong to (e.g. "default"). Segments '
  'generation totals by pipeline, not by rep or owner.'
  , last_refreshed = now()
 WHERE supabase_table = 'pipeline_generation_quarterly' AND supabase_column = 'pipeline_id';

UPDATE data_dictionary SET description =
  'Company-size segment (SMB, Mid-Market, Enterprise, or Unknown) this row '
  'aggregates within the fiscal quarter.'
  , last_refreshed = now()
 WHERE supabase_table = 'pipeline_generation_quarterly' AND supabase_column = 'segment';

UPDATE data_dictionary SET description =
  'Timestamp this row was last (re)computed by scripts/analytics/'
  'compute_pipeline_generation.py. This is a write timestamp, not a week or '
  'quarter boundary — never filter on it to answer a "this week" question.'
  , last_refreshed = now()
 WHERE supabase_table = 'pipeline_generation_quarterly' AND supabase_column = 'last_updated';

UPDATE data_dictionary SET description =
  'Auto-incrementing row identifier. Internal bookkeeping only.'
  , last_refreshed = now()
 WHERE supabase_table = 'pipeline_generation_quarterly' AND supabase_column = 'id';

-- Verification queries (run after migration):
--
-- 1. Old name gone, new name present:
--    SELECT table_name FROM information_schema.tables
--    WHERE table_name IN ('pipeline_generation_weekly','pipeline_generation_quarterly');
--
-- 2. data_dictionary rows carried over:
--    SELECT supabase_table, supabase_column, description FROM data_dictionary
--    WHERE supabase_table = 'pipeline_generation_quarterly' ORDER BY supabase_column;
