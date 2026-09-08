-- Migration: Add region and segment to deals_snapshot
-- Date: 2026-09-08
-- Purpose: Enable point-in-time enrichment for waterfall reconciliation
--
-- PROBLEM: Waterfall calculations currently load region/segment from current
-- deals table and apply them to ALL historical snapshots. If a deal's
-- region/segment changed over time, waterfall reconciliation fails because
-- deals "teleport" between groups retroactively.
--
-- SOLUTION: Capture region/segment at snapshot time, enabling accurate
-- point-in-time waterfall calculations.

-- Add region column (nullable initially for existing snapshots)
ALTER TABLE deals_snapshot
ADD COLUMN IF NOT EXISTS region TEXT;

-- Add segment column (nullable initially for existing snapshots)
ALTER TABLE deals_snapshot
ADD COLUMN IF NOT EXISTS segment TEXT;

-- Add indexes for waterfall query performance
CREATE INDEX IF NOT EXISTS idx_deals_snapshot_region
ON deals_snapshot(region);

CREATE INDEX IF NOT EXISTS idx_deals_snapshot_segment
ON deals_snapshot(segment);

-- Add composite index for waterfall grouping queries
CREATE INDEX IF NOT EXISTS idx_deals_snapshot_date_pipeline_region_segment
ON deals_snapshot(snapshot_date, pipeline_id, region, segment);

-- Comments
COMMENT ON COLUMN deals_snapshot.region IS
'Sales region at snapshot time: NAM, EMEA, APAC, LATAM, ROW, or UNKNOWN. Point-in-time value enables accurate waterfall reconciliation when deals change regions. NULL for pre-migration snapshots (will be backfilled from property_history if available).';

COMMENT ON COLUMN deals_snapshot.segment IS
'Company size segment at snapshot time: SMB, Mid-Market, Enterprise, or Unknown. Point-in-time value enables accurate waterfall reconciliation when deals change segments. NULL for pre-migration snapshots (will be backfilled from property_history if available).';
