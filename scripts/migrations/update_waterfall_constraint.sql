-- Migration: Update waterfall_weekly to segmented grain
-- Date: 2026-09-08
-- Purpose: Support new grain (week_ending, pipeline_id, region, segment)
--
-- IMPORTANT: This truncates existing data and requires full historical backfill
-- Run: python scripts/analytics/compute_waterfall_segmented.py --backfill

-- Step 1: Truncate existing unsegmented rows
-- All 84 existing rows have NULL region/segment and will be regenerated
-- with proper segmentation via backfill
TRUNCATE TABLE waterfall_weekly;

-- Step 2: Make region and segment NOT NULL (required for primary key)
ALTER TABLE waterfall_weekly
ALTER COLUMN region SET NOT NULL;

ALTER TABLE waterfall_weekly
ALTER COLUMN segment SET NOT NULL;

-- Step 3: Drop old unique constraint (if exists)
ALTER TABLE waterfall_weekly
DROP CONSTRAINT IF EXISTS waterfall_weekly_week_ending_pipeline_id_key;

-- Drop old primary key if exists
ALTER TABLE waterfall_weekly
DROP CONSTRAINT IF EXISTS waterfall_weekly_pkey;

-- Step 4: Add new primary key with region and segment
ALTER TABLE waterfall_weekly
ADD CONSTRAINT waterfall_weekly_pkey
PRIMARY KEY (week_ending, pipeline_id, region, segment);

-- Comment
COMMENT ON CONSTRAINT waterfall_weekly_pkey ON waterfall_weekly IS
'Primary key for segmented waterfall: week + pipeline + region + segment. Enables granular pipeline movement tracking by geography and company size. Requires backfill after migration.';
