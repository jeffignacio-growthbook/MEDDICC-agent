-- Migration 003: Add methodology-agnostic component scores table
-- Replaces hardcoded MEDDICC columns with flexible component tracking

CREATE TABLE IF NOT EXISTS qualification_components (
    id BIGSERIAL PRIMARY KEY,
    deal_id TEXT NOT NULL,
    company_slug TEXT NOT NULL,
    component_name TEXT NOT NULL,
    component_score INTEGER CHECK (component_score >= 0 AND component_score <= 10),
    evidence TEXT,
    analyzed_at TIMESTAMPTZ DEFAULT NOW(),
    UNIQUE(deal_id, component_name, analyzed_at)
);

CREATE INDEX idx_qualification_components_deal ON qualification_components(deal_id);
CREATE INDEX idx_qualification_components_slug ON qualification_components(company_slug);
CREATE INDEX idx_qualification_components_analyzed ON qualification_components(analyzed_at DESC);

COMMENT ON TABLE qualification_components IS 'Component scores for any methodology (MEDDICC, SPICED, BANT, etc)';
COMMENT ON COLUMN qualification_components.component_name IS 'E.g. champion, metrics, situation, pain, budget, etc';
