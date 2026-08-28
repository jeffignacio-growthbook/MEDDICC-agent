-- Add renewal_revenue to deals_snapshot table
-- Added during investigation of renewal pipeline reporting gap (2026-08-28)

ALTER TABLE deals_snapshot
ADD COLUMN IF NOT EXISTS renewal_revenue NUMERIC;

COMMENT ON COLUMN deals_snapshot.renewal_revenue IS
'Point-in-time renewal ARR from HubSpot renewal_revenue property.
UNPOPULATED BY DESIGN: renewal_revenue is already included in deal_value via
compute_deal_value() for renewal pipeline deals (utils.py:197). Waterfall and
forecast analyses read deal_value, not this column. The column was added based
on an unverified inference that historical analyses were wrong; verification
showed they were correct all along. Left applied to avoid production schema
changes, but intentionally NULL everywhere. Do not backfill.';

-- DO NOT backfill this column. Renewal value is already present in deal_value
-- for all historical snapshots via the compute_deal_value() logic that adds
-- incremental + renewal for deals in renewal_pipeline_ids.
