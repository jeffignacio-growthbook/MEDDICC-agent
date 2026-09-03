-- Add missing columns to calls table
--
-- Migration 001 declared these columns but they don't exist in the actual table.
-- This caused PGRST204 errors killing every ETL write since August 7.
--
-- Root cause: migrations and live schema diverged. The table was modified
-- outside the migration system, dropping columns that the ETL still writes to.

ALTER TABLE calls ADD COLUMN IF NOT EXISTS duration_minutes NUMERIC;
ALTER TABLE calls ADD COLUMN IF NOT EXISTS formatted_summary TEXT;
ALTER TABLE calls ADD COLUMN IF NOT EXISTS has_feature_gap BOOLEAN DEFAULT FALSE;
ALTER TABLE calls ADD COLUMN IF NOT EXISTS has_objection BOOLEAN DEFAULT FALSE;

COMMENT ON COLUMN calls.duration_minutes IS 'Call duration in minutes';
COMMENT ON COLUMN calls.formatted_summary IS 'Formatted call summary';
COMMENT ON COLUMN calls.has_feature_gap IS 'Whether call mentioned feature gaps';
COMMENT ON COLUMN calls.has_objection IS 'Whether call contained objections';

-- Create indexes for boolean filters (declared in 001 but also missing)
CREATE INDEX IF NOT EXISTS idx_calls_has_feature_gap
  ON calls(has_feature_gap) WHERE has_feature_gap = TRUE;

CREATE INDEX IF NOT EXISTS idx_calls_has_objection
  ON calls(has_objection) WHERE has_objection = TRUE;
