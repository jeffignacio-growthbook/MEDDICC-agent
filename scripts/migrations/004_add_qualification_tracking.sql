-- Migration 004: Add qualification tracking columns to deals table
-- Adds lost_reason and stage_source for waterfall analysis

ALTER TABLE deals ADD COLUMN IF NOT EXISTS lost_reason TEXT;
ALTER TABLE deals ADD COLUMN IF NOT EXISTS stage_source TEXT;

COMMENT ON COLUMN deals.lost_reason IS 'Reason deal was lost (from Closed Lost dropdown or analysis)';
COMMENT ON COLUMN deals.stage_source IS 'How deal entered current stage (manual, automation, import, etc)';

-- Index for filtering by lost reason
CREATE INDEX IF NOT EXISTS idx_deals_lost_reason ON deals(lost_reason) WHERE lost_reason IS NOT NULL;
