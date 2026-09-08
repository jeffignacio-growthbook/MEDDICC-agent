-- Migration: Add region and segment to waterfall_weekly
-- Date: 2026-09-08
-- Purpose: Change grain from (week_ending, pipeline_id) to
--          (week_ending, pipeline_id, region, segment)

-- Add region column (nullable initially for existing rows)
ALTER TABLE waterfall_weekly
ADD COLUMN IF NOT EXISTS region TEXT;

-- Add segment column (nullable initially for existing rows)
ALTER TABLE waterfall_weekly
ADD COLUMN IF NOT EXISTS segment TEXT;

-- Add indexes for query performance
CREATE INDEX IF NOT EXISTS idx_waterfall_weekly_region
ON waterfall_weekly(region);

CREATE INDEX IF NOT EXISTS idx_waterfall_weekly_segment
ON waterfall_weekly(segment);

-- Add composite index for common queries (week + region + segment)
CREATE INDEX IF NOT EXISTS idx_waterfall_weekly_week_region_segment
ON waterfall_weekly(week_ending, region, segment);

-- Comment on columns
COMMENT ON COLUMN waterfall_weekly.region IS
'Sales region: NAM, EMEA, APAC, LATAM, ROW, or UNKNOWN. Derived from deals.region (company geography). NULL for pre-backfill rows (will be populated during historical backfill).';

COMMENT ON COLUMN waterfall_weekly.segment IS
'Company size segment: SMB, Mid-Market, Enterprise, or Unknown. Derived from deals.segment (employee count bands). NULL for pre-backfill rows (will be populated during historical backfill).';
