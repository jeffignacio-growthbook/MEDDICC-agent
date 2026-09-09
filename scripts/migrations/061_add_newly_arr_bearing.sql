-- Add newly_arr_bearing columns to waterfall_weekly
-- These track deals that crossed the ARR-bearing threshold ($0→value with stage progression)

ALTER TABLE waterfall_weekly
ADD COLUMN IF NOT EXISTS newly_arr_bearing_value NUMERIC DEFAULT 0,
ADD COLUMN IF NOT EXISTS newly_arr_bearing_count INTEGER DEFAULT 0;

COMMENT ON COLUMN waterfall_weekly.newly_arr_bearing_value IS 'Value of deals that crossed ARR-bearing threshold this week ($0→value with stage_order progression)';
COMMENT ON COLUMN waterfall_weekly.newly_arr_bearing_count IS 'Count of deals that crossed ARR-bearing threshold this week';
