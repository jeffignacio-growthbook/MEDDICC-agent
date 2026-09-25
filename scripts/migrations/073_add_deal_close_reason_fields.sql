-- Migration 073: add the close-reason enrichment columns to deals and
-- register them in data_dictionary (2026-09-25).
--
-- Context: HubSpot's closed_lost_reason is ~100% populated on closed-lost
-- deals, but deals.lost_reason read 0% populated because DEAL_SYNC_PROPERTIES
-- never fetched it (see PENDING_WORK "DATA BUG (confirmed 2026-09-25)"). The
-- ETL now fetches closed_lost_reason (-> existing deals.lost_reason column)
-- plus three enrichment properties that had no home:
--   closed_lost_from   the stage a deal was in immediately before Closed Lost
--   dq_reason          the disqualification reason
--   closed_won_reason  the reason a deal was won
--
-- lost_reason already exists and is already registered in data_dictionary, so
-- only the three new columns are added here. Additive, nullable text columns —
-- no data loss, safe to re-run (IF NOT EXISTS / ON CONFLICT).

ALTER TABLE deals ADD COLUMN IF NOT EXISTS closed_lost_from text;
ALTER TABLE deals ADD COLUMN IF NOT EXISTS dq_reason text;
ALTER TABLE deals ADD COLUMN IF NOT EXISTS closed_won_reason text;

INSERT INTO data_dictionary
  (source, supabase_table, supabase_column, data_type, description, is_queryable, hubspot_name)
VALUES
  ('supabase', 'deals', 'closed_lost_from', 'text',
   'The pipeline stage the deal was in immediately before it moved to Closed '
   'Lost (HubSpot Deal.closed_lost_from). Names where a loss actually came '
   'from, e.g. "Meeting Set", "Scoping". Empty for won/active deals.',
   true, 'closed_lost_from'),
  ('supabase', 'deals', 'dq_reason', 'text',
   'Disqualification reason (HubSpot Deal.dq_reason), e.g. "Pro deal", set '
   'when a deal is disqualified. Empty when not disqualified.',
   true, 'dq_reason'),
  ('supabase', 'deals', 'closed_won_reason', 'text',
   'Reason a deal was won (HubSpot Deal.closed_won_reason). The won-side '
   'counterpart to lost_reason. Empty for lost/active deals.',
   true, 'closed_won_reason')
ON CONFLICT (supabase_table, supabase_column) DO UPDATE SET
  data_type    = EXCLUDED.data_type,
  description  = EXCLUDED.description,
  is_queryable = EXCLUDED.is_queryable,
  hubspot_name = EXCLUDED.hubspot_name,
  last_refreshed = now();

DO $$
DECLARE registered INTEGER;
BEGIN
  SELECT COUNT(*) INTO registered FROM data_dictionary
   WHERE supabase_table = 'deals'
     AND supabase_column IN ('closed_lost_from', 'dq_reason', 'closed_won_reason')
     AND is_queryable = true;
  IF registered <> 3 THEN
    RAISE EXCEPTION 'close-reason column registration failed: % of 3', registered;
  END IF;
  RAISE NOTICE '✅ closed_lost_from, dq_reason, closed_won_reason registered in data_dictionary';
END $$;
