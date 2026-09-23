-- Migration 068: remove the Inditex ghost deal (29591984407)
-- Date: 2026-09-23
-- Depends on: 067_add_deleted_deals.sql
--
-- Deal 29591984407 ("Inditex - 2025 renewal (should expand)", renewal
-- pipeline, stage 1297321618 Upcoming Renewal) was deleted in HubSpot at
-- 2026-08-11T23:26:35.181Z. That's confirmed: it appears in
-- GET /crm/v3/objects/deals?archived=true, and a normal GET returns 404 (probe
-- runs 35899912562 / 35900066388). Its `deals` row was last written
-- 2026-08-11 20:03Z and stayed deal_status='active' from then on. It has $0 in
-- every value field, so no dollar total moved, but it was counted as a deal:
--   - 12 deals_snapshot rows dated after the deletion (2026-08-17 .. 09-21)
--     assert it was an open renewal on days it didn't exist;
--   - Slack answers on 2026-09-02 and 2026-09-06 (x2) named it, as a past-due
--     $0 renewal and as "the 1 active deal missing an owner".
--
-- Snapshots: the 12 post-deletion rows are removed, not annotated. A snapshot
-- claims "this was HubSpot's state on that date", and for these rows that
-- claim is false. Consumers (pipeline movement, waterfall, renewal movement)
-- read rows, not notes, so an annotation wouldn't reach them. With the rows
-- gone, the snapshot diff shows the deal exiting in the week it was actually
-- deleted, which is the truth. The 54 rows dated before the deletion are
-- correct history and stay. Every removed row is kept verbatim in
-- deleted_deals.removed_snapshot_rows.
--
-- Atomic: runs as one migration transaction. The deletes only happen once
-- the tombstone row (with both backups) exists.

INSERT INTO deleted_deals (deal_id, hubspot_archived_at, reason, source,
                           deal_row, removed_snapshot_rows, notes)
SELECT d.deal_id,
       TIMESTAMPTZ '2026-08-11 23:26:35.181+00',
       'deleted_in_hubspot',
       'migration_068_manual_2026-09-23',
       to_jsonb(d),
       (SELECT jsonb_agg(to_jsonb(s) ORDER BY s.snapshot_date)
          FROM deals_snapshot s
         WHERE s.deal_id = d.deal_id AND s.snapshot_date >= DATE '2026-08-12'),
       'Ghost: deleted in HubSpot 2026-08-11, still active in deals until 2026-09-23. '
       'Found by the incremental-sync audit (Supabase-vs-HubSpot id diff).'
  FROM deals d
 WHERE d.deal_id = '29591984407'
ON CONFLICT (deal_id) DO NOTHING;

DELETE FROM deals_snapshot
 WHERE deal_id = '29591984407'
   AND snapshot_date >= DATE '2026-08-12'
   AND EXISTS (SELECT 1 FROM deleted_deals t
                WHERE t.deal_id = '29591984407' AND t.removed_snapshot_rows IS NOT NULL);

DELETE FROM deals
 WHERE deal_id = '29591984407'
   AND EXISTS (SELECT 1 FROM deleted_deals t WHERE t.deal_id = '29591984407');
