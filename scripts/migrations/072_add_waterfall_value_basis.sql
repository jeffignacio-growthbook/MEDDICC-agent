-- Migration 072: waterfall_weekly.value_basis (which dollar basis a row uses)
-- Date: 2026-09-24
-- Depends on: waterfall_weekly
--
-- compute_waterfall_segmented.py values a week on incremental_arr()
-- (new_arr + expansion_arr, the governed basis query_waterfall's headline
-- uses) once its earlier snapshot is on or after 2026-09-11, the first
-- deals_snapshot that carries those fields. Earlier weeks can only be valued
-- on deal_value (Incremental ARR, or HubSpot amount where none was
-- recorded). The row records which, so query_waterfall can state the basis
-- per week instead of mixing them silently.
--
-- Every row that exists when this runs was computed on deal_value.
-- Name checked free before creating (see the 069 collision note).

ALTER TABLE waterfall_weekly ADD COLUMN value_basis TEXT
    CHECK (value_basis IN ('deal_value', 'incremental_arr'));
UPDATE waterfall_weekly SET value_basis = 'deal_value' WHERE value_basis IS NULL;
COMMENT ON COLUMN waterfall_weekly.value_basis IS
    'Dollar basis of this row: deal_value (weeks before 2026-09-11) or incremental_arr (new_arr + expansion_arr).';

-- Register it so the dynamic query loop's schema context shows it
-- (data_dictionary, not information_schema, is what the model sees; see 062).
INSERT INTO data_dictionary
  (source, supabase_table, supabase_column, data_type, description, is_queryable)
VALUES
  ('supabase', 'waterfall_weekly', 'value_basis', 'text',
   'Dollar basis of this row''s *_value fields: incremental_arr (new_arr + '
   'expansion_arr, renewal base excluded; weeks whose earlier snapshot is on or '
   'after 2026-09-11) or deal_value (Incremental ARR, or HubSpot amount where '
   'none was recorded; earlier weeks). Each row is ONE region/segment slice: '
   'sum the slices of a week_ending for a company-wide figure.',
   true);
