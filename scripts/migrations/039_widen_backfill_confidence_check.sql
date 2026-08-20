-- Migration 039: widen the backfill_confidence CHECK to the redefined vocabulary.
--
-- Migration 017 defined:
--   CHECK (backfill_confidence IN
--     ('exact','interpolated','inferred','unknown','excluded_mismatch'))
--
-- The Phase 1 relabel redefined confidence to reflect history COVERAGE:
--   'exact'       stage history covers the date (a true point-in-time read)
--   'pre_history' the deal existed but history does not reach this date (null, not guessed)
--   'no_history'  no stage history for the deal at all
-- It updated the code but NOT this constraint, so a write of 'pre_history' /
-- 'no_history' fails with 23514. This widens the allowed set to the new
-- vocabulary while keeping the old values so any legacy rows still validate.
--
-- Apply path: PostgREST cannot run ALTER TABLE, so run this in the Supabase
-- SQL editor or via a direct psycopg2 connection (SUPABASE_DB_URL). It is
-- idempotent — DROP IF EXISTS then ADD.

ALTER TABLE deals_snapshot
  DROP CONSTRAINT IF EXISTS deals_snapshot_backfill_confidence_check;

ALTER TABLE deals_snapshot
  ADD CONSTRAINT deals_snapshot_backfill_confidence_check
  CHECK (backfill_confidence IN (
    'exact', 'pre_history', 'no_history',           -- redefined vocabulary
    'interpolated', 'inferred', 'unknown', 'excluded_mismatch'  -- legacy, kept for back-compat
  ));

DO $$
BEGIN
  RAISE NOTICE 'Migration 039: backfill_confidence CHECK widened to include pre_history / no_history';
END $$;
