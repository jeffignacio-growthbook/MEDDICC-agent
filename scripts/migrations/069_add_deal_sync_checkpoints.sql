-- Migration 069: deal_sync_checkpoints (incremental deal sync checkpoint)
-- Date: 2026-09-23
-- Depends on: none
--
-- One row per sync job. watermark_ms is an epoch-millisecond
-- hs_lastmodifieddate value taken from HubSpot's own clock. It is written only
-- by scripts/deal_sync.py CheckpointStore.advance(), after a fully successful
-- run: never on a partial one, never with the runner's "now". The next run
-- reads deals modified at or after (watermark_ms - overlap). See PENDING_WORK
-- "Incremental deal sync".
--
-- NAME COLLISION, recorded: this was first applied as `etl_checkpoints` with
-- CREATE TABLE IF NOT EXISTS. That table already existed (the SDR metrics
-- ETL's checkpoint: tool / last_run_at / last_success_date, 1 row, not
-- created by any migration file), so the CREATE silently did nothing while
-- the trigger, RLS and comment were applied to the SDR table. The trigger
-- sets NEW.advanced_at, a column that table doesn't have, so it would have
-- broken the SDR ETL's next checkpoint write. It was reverted about a minute
-- later (Supabase migrations 069_revert_trigger_on_existing_etl_checkpoints
-- and 069_restore_sdr_etl_checkpoints_state; RLS restored to off like its
-- sibling sdr_* tables). Nothing wrote to that table in between: the SDR ETL
-- only runs by manual dispatch, and its row's last_run_at is still
-- 2026-08-18. Hence the new name. There is deliberately no IF NOT EXISTS
-- below, so a collision fails loudly.

CREATE TABLE deal_sync_checkpoints (
    job           TEXT PRIMARY KEY,
    watermark_ms  BIGINT NOT NULL CHECK (watermark_ms >= 1000000000000 AND watermark_ms < 10000000000000),
    run_id        TEXT,
    fetched       INTEGER,
    upserted      INTEGER,
    advanced_at   TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

-- advanced_at must reflect every advance, not just the first insert
CREATE FUNCTION deal_sync_checkpoints_touch() RETURNS trigger AS $$
BEGIN
    NEW.advanced_at := NOW();
    RETURN NEW;
END;
$$ LANGUAGE plpgsql;

CREATE TRIGGER deal_sync_checkpoints_touch BEFORE INSERT OR UPDATE ON deal_sync_checkpoints
    FOR EACH ROW EXECUTE FUNCTION deal_sync_checkpoints_touch();

ALTER TABLE deal_sync_checkpoints ENABLE ROW LEVEL SECURITY;

COMMENT ON TABLE deal_sync_checkpoints IS
    'Incremental deal sync checkpoints (epoch ms, HubSpot clock). Advanced only after a fully successful run.';
