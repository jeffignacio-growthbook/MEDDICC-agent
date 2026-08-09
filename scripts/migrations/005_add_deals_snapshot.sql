-- Migration 005: Add deals snapshot table for point-in-time historical analysis
-- Daily snapshots of deal state for trending and retrospective analysis

CREATE TABLE IF NOT EXISTS deals_snapshot (
    id BIGSERIAL PRIMARY KEY,
    snapshot_date DATE NOT NULL,
    deal_id TEXT NOT NULL,
    company_slug TEXT NOT NULL,
    stage_id TEXT NOT NULL,
    stage_name TEXT,
    pipeline_id TEXT,
    pipeline_name TEXT,
    amount NUMERIC(15,2),
    close_date DATE,
    owner_id TEXT,
    overall_score INTEGER CHECK (overall_score >= 0 AND overall_score <= 100),
    health_status TEXT CHECK (health_status IN ('red', 'yellow', 'green')),
    days_in_current_stage INTEGER,
    days_since_created INTEGER,
    created_at TIMESTAMPTZ DEFAULT NOW(),
    UNIQUE(deal_id, snapshot_date)
);

CREATE INDEX idx_deals_snapshot_date ON deals_snapshot(snapshot_date DESC);
CREATE INDEX idx_deals_snapshot_deal ON deals_snapshot(deal_id);
CREATE INDEX idx_deals_snapshot_slug ON deals_snapshot(company_slug);
CREATE INDEX idx_deals_snapshot_stage ON deals_snapshot(stage_id);

COMMENT ON TABLE deals_snapshot IS 'Daily snapshots of deal state for historical trending and waterfall analysis';
COMMENT ON COLUMN deals_snapshot.snapshot_date IS 'Date of snapshot (typically nightly ETL run date)';
