-- Add forecast analysis fields to deals_snapshot
-- Part of Phase 2: Snapshot Schema for Forecast Analyses
--
-- Enables week-3 conversion analysis, category churn tracking, and
-- commit calibration analysis in Phase 3.

ALTER TABLE deals_snapshot
  ADD COLUMN IF NOT EXISTS forecast_category TEXT,
    -- COMMIT | BEST_CASE | PIPELINE | OMITTED (client vocabulary varies)
    -- Backfillable if fetch-property-history.yml captured it
  ADD COLUMN IF NOT EXISTS fiscal_quarter TEXT,
    -- e.g. 'FY2027-Q3', from get_fiscal_quarter()
    -- Derivable from snapshot_date + fiscal config - backfillable for ALL rows
  ADD COLUMN IF NOT EXISTS week_of_quarter INTEGER;
    -- 1-13, computed at snapshot time from fiscal calendar
    -- Derivable from snapshot_date + fiscal config - backfillable for ALL rows

-- Index for forecast analyses (category churn, commit calibration, week-3 conversion)
CREATE INDEX IF NOT EXISTS idx_snapshot_category
  ON deals_snapshot(fiscal_quarter, week_of_quarter, forecast_category);

-- Index for anchor week analysis (per-week snapshots)
CREATE INDEX IF NOT EXISTS idx_snapshot_fiscal_week
  ON deals_snapshot(fiscal_quarter, week_of_quarter);
