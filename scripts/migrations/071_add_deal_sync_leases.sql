-- Migration 071: deal_sync_leases, so deal sync runs never write at once
-- Date: 2026-09-23
-- Depends on: none
--
-- Every scripts/etl_deals.py run that writes Supabase (the hourly
-- incremental, the ~12h full sync, and the manual analytics workflows) first
-- takes the lease for job 'deals' (scripts/deal_sync.py SyncLease). Without
-- it, an incremental run writing while a full sync is in progress can have
-- its newer values overwritten by the full sync's stale ones, and makes the
-- full sync's reconciliation fail on deals created after its listing.
-- A GitHub Actions concurrency group alone didn't cover the manual
-- workflows, and a newly queued run in a group cancels the pending one.
--
-- One row per job while held. expires_at bounds how long a crashed runner
-- can block others; a live run renews it before its write phase.
-- Each function is one statement, so acquire is atomic: INSERT ... ON
-- CONFLICT takes the row lock, and the WHERE only lets the holder, or anyone
-- once the lease has expired, overwrite it.
-- Name checked free before creating (see the 069 collision note); plain
-- CREATE, so a collision fails loudly.

CREATE TABLE deal_sync_leases (
    job          TEXT PRIMARY KEY,
    holder       TEXT NOT NULL,
    mode         TEXT,
    acquired_at  TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    expires_at   TIMESTAMPTZ NOT NULL
);
ALTER TABLE deal_sync_leases ENABLE ROW LEVEL SECURITY;
COMMENT ON TABLE deal_sync_leases IS
    'Write lease for the deal sync (etl_deals.py). Held row = a run is writing deals; see scripts/deal_sync.py SyncLease.';

-- Returns {acquired, holder, mode, expires_at} for whoever holds it now.
CREATE FUNCTION acquire_deal_sync_lease(p_job TEXT, p_holder TEXT, p_mode TEXT,
                                        p_ttl_seconds INTEGER)
RETURNS JSONB
LANGUAGE sql
AS $$
    WITH taken AS (
        INSERT INTO deal_sync_leases AS l (job, holder, mode, acquired_at, expires_at)
        VALUES (p_job, p_holder, p_mode, NOW(), NOW() + make_interval(secs => p_ttl_seconds))
        ON CONFLICT (job) DO UPDATE SET
            holder      = EXCLUDED.holder,
            mode        = EXCLUDED.mode,
            acquired_at = EXCLUDED.acquired_at,
            expires_at  = EXCLUDED.expires_at
        WHERE l.expires_at <= NOW() OR l.holder = EXCLUDED.holder
        RETURNING l.holder, l.mode, l.expires_at
    )
    SELECT jsonb_build_object('acquired', true, 'holder', holder, 'mode', mode,
                              'expires_at', expires_at)
      FROM taken
    UNION ALL
    SELECT jsonb_build_object('acquired', false, 'holder', holder, 'mode', mode,
                              'expires_at', expires_at)
      FROM deal_sync_leases
     WHERE job = p_job AND NOT EXISTS (SELECT 1 FROM taken)
    LIMIT 1;
$$;

-- True if the caller still holds it (expiry extended); false if lost.
CREATE FUNCTION renew_deal_sync_lease(p_job TEXT, p_holder TEXT, p_ttl_seconds INTEGER)
RETURNS BOOLEAN
LANGUAGE sql
AS $$
    WITH r AS (
        UPDATE deal_sync_leases
           SET expires_at = NOW() + make_interval(secs => p_ttl_seconds)
         WHERE job = p_job AND holder = p_holder
        RETURNING 1
    )
    SELECT EXISTS (SELECT 1 FROM r);
$$;

-- Deletes only the caller's own lease.
CREATE FUNCTION release_deal_sync_lease(p_job TEXT, p_holder TEXT)
RETURNS BOOLEAN
LANGUAGE sql
AS $$
    WITH d AS (
        DELETE FROM deal_sync_leases WHERE job = p_job AND holder = p_holder RETURNING 1
    )
    SELECT EXISTS (SELECT 1 FROM d);
$$;

REVOKE ALL ON FUNCTION acquire_deal_sync_lease(TEXT, TEXT, TEXT, INTEGER) FROM PUBLIC, anon, authenticated;
REVOKE ALL ON FUNCTION renew_deal_sync_lease(TEXT, TEXT, INTEGER) FROM PUBLIC, anon, authenticated;
REVOKE ALL ON FUNCTION release_deal_sync_lease(TEXT, TEXT) FROM PUBLIC, anon, authenticated;
GRANT EXECUTE ON FUNCTION acquire_deal_sync_lease(TEXT, TEXT, TEXT, INTEGER) TO service_role;
GRANT EXECUTE ON FUNCTION renew_deal_sync_lease(TEXT, TEXT, INTEGER) TO service_role;
GRANT EXECUTE ON FUNCTION release_deal_sync_lease(TEXT, TEXT) TO service_role;
