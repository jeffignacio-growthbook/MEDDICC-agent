-- Migration 070: tombstone_deal(), atomic per-deal deletion handling
-- Date: 2026-09-23
-- Depends on: 067_add_deleted_deals.sql (deleted_deals), deals, deals_snapshot
--
-- Generalises the one-off 068 (Inditex ghost) so every sync run can apply
-- HubSpot deletions and merges (scripts/etl_deals.py _apply_deletions, via
-- supabase rpc). One call = one transaction:
--   - deal not in `deals`: no-op, returns 'absent';
--   - otherwise the full `deals` row goes to deleted_deals, and the deal is
--     removed from `deals`.
--   - p_archived_at given (deleted in HubSpot): also remove, and keep in the
--     tombstone, the deals_snapshot rows dated after the deletion day. Those
--     rows claim the deal existed when it didn't; earlier rows are real
--     history and stay.
--   - p_archived_at NULL (merged away): snapshots stay; the record's history
--     was real and continues under the survivor.
-- A tombstone that already exists (deal restored, then deleted again) keeps
-- its earlier removed snapshots and appends the new ones.
--
-- SECURITY INVOKER plus EXECUTE only for service_role: anon/authenticated
-- can't call it, and RLS on deals / deleted_deals applies regardless.

CREATE FUNCTION tombstone_deal(p_deal_id TEXT, p_archived_at TIMESTAMPTZ,
                               p_reason TEXT, p_source TEXT)
RETURNS TEXT
LANGUAGE plpgsql
AS $$
DECLARE
    v_row   JSONB;
    v_snaps JSONB;
    v_cut   DATE;
BEGIN
    SELECT to_jsonb(d) INTO v_row FROM deals d WHERE d.deal_id = p_deal_id FOR UPDATE;
    IF v_row IS NULL THEN
        RETURN 'absent';
    END IF;

    IF p_archived_at IS NOT NULL THEN
        v_cut := (p_archived_at AT TIME ZONE 'UTC')::date + 1;
        SELECT jsonb_agg(to_jsonb(s) ORDER BY s.snapshot_date) INTO v_snaps
          FROM deals_snapshot s
         WHERE s.deal_id = p_deal_id AND s.snapshot_date >= v_cut;
    END IF;

    INSERT INTO deleted_deals (deal_id, hubspot_archived_at, reason, source,
                               deal_row, removed_snapshot_rows, notes)
    VALUES (p_deal_id, p_archived_at, p_reason, p_source, v_row, v_snaps, NULL)
    ON CONFLICT (deal_id) DO UPDATE SET
        hubspot_archived_at   = EXCLUDED.hubspot_archived_at,
        detected_at           = NOW(),
        reason                = EXCLUDED.reason,
        source                = EXCLUDED.source,
        deal_row              = EXCLUDED.deal_row,
        removed_snapshot_rows = CASE
            WHEN EXCLUDED.removed_snapshot_rows IS NULL THEN deleted_deals.removed_snapshot_rows
            ELSE COALESCE(deleted_deals.removed_snapshot_rows, '[]'::jsonb)
                 || EXCLUDED.removed_snapshot_rows END;

    IF v_cut IS NOT NULL THEN
        DELETE FROM deals_snapshot WHERE deal_id = p_deal_id AND snapshot_date >= v_cut;
    END IF;
    DELETE FROM deals WHERE deal_id = p_deal_id;
    RETURN 'tombstoned';
END;
$$;

REVOKE ALL ON FUNCTION tombstone_deal(TEXT, TIMESTAMPTZ, TEXT, TEXT) FROM PUBLIC;
REVOKE ALL ON FUNCTION tombstone_deal(TEXT, TIMESTAMPTZ, TEXT, TEXT) FROM anon, authenticated;
GRANT EXECUTE ON FUNCTION tombstone_deal(TEXT, TIMESTAMPTZ, TEXT, TEXT) TO service_role;

COMMENT ON FUNCTION tombstone_deal(TEXT, TIMESTAMPTZ, TEXT, TEXT) IS
    'Atomically move a HubSpot-deleted/merged deal from deals (and post-deletion snapshots) to deleted_deals.';
