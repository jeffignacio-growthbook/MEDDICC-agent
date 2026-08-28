-- Add renewal_revenue to deals_snapshot table
-- Required for historical renewal pipeline analysis (waterfall, forecast, coverage)

ALTER TABLE deals_snapshot
ADD COLUMN IF NOT EXISTS renewal_revenue NUMERIC;

COMMENT ON COLUMN deals_snapshot.renewal_revenue IS
'Point-in-time renewal ARR from HubSpot renewal_revenue property.
Required for accurate renewal pipeline value in historical analyses.
Without this, all renewal deals showed $0 in waterfall/forecast/coverage.';

-- Note: After running this migration, regenerate all snapshots via:
--   python scripts/analytics/snapshot_deals.py --backfill
-- to populate renewal_revenue for all historical snapshot dates.
