-- Migration 067: deleted_deals tombstone table
-- Date: 2026-09-23
-- Depends on: deals, deals_snapshot
--
-- Why: nothing in the ETL learns about deals deleted in HubSpot. deals/search
-- never returns archived records, so a deleted deal's row stays in `deals`
-- forever, still 'active'. The first known case, Inditex 29591984407, was
-- deleted 2026-08-11 23:26Z and was still counted six weeks later (see 068).
--
-- Why a tombstone table instead of a status flag on `deals`: consumers filter
-- deal_status in different ways. query_upcoming_renewals uses
-- `neq won` + `neq lost`, the snapshot writer (scripts/analytics/
-- snapshot_deals.py) doesn't filter on status at all, and dynamic queries are
-- written by the model. A 'deleted' flag would still pass all of those.
-- Moving the row out keeps `deals` = "deals that exist in HubSpot" for every
-- consumer at once, and keeps the full original row for audit and restore.
--
-- The incremental-sync deletion handling (PENDING_WORK: "Incremental deal
-- sync") writes here too. If HubSpot restores a deal, the next analytics
-- ETL upsert simply re-creates it in `deals`; the tombstone stays as history.

CREATE TABLE IF NOT EXISTS deleted_deals (
    deal_id               TEXT PRIMARY KEY,
    hubspot_archived_at   TIMESTAMPTZ,            -- archivedAt from HubSpot, when known
    detected_at           TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    reason                TEXT NOT NULL,          -- e.g. 'deleted_in_hubspot', 'merged_away'
    source                TEXT NOT NULL,          -- what removed it (manual fix, incremental sync, ...)
    deal_row              JSONB NOT NULL,         -- the `deals` row as it was when removed
    removed_snapshot_rows JSONB,                  -- deals_snapshot rows removed with it (post-deletion dates)
    notes                 TEXT
);

-- Same posture as deals / deals_snapshot: RLS on, service role bypasses it.
ALTER TABLE deleted_deals ENABLE ROW LEVEL SECURITY;

COMMENT ON TABLE deleted_deals IS
    'Tombstones for deals deleted/merged away in HubSpot: removed from deals (and post-deletion '
    'deals_snapshot rows) and kept here in full. deals must only hold deals that exist in HubSpot.';
