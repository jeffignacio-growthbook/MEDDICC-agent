-- Migration 047: Add historical conversion forecast columns to forecast_weekly
-- Adds low/mid/high forecasts based on measured week-3 conversion rates

ALTER TABLE forecast_weekly
  ADD COLUMN IF NOT EXISTS historical_conversion_low  NUMERIC DEFAULT 0,
  ADD COLUMN IF NOT EXISTS historical_conversion_mid  NUMERIC DEFAULT 0,
  ADD COLUMN IF NOT EXISTS historical_conversion_high NUMERIC DEFAULT 0;

COMMENT ON COLUMN forecast_weekly.historical_conversion_low IS
  'Forecast using 9.2% conversion rate (FY2027 Q1 measured)';

COMMENT ON COLUMN forecast_weekly.historical_conversion_mid IS
  'Forecast using 13.5% conversion rate (4-quarter trailing average)';

COMMENT ON COLUMN forecast_weekly.historical_conversion_high IS
  'Forecast using 24.4% conversion rate (FY2027 Q2 outlier — denominator halved while wins rose, cause TBD)';
