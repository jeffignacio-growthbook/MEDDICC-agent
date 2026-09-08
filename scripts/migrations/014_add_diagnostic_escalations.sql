-- Migration 014: Add diagnostic_escalations table for Phase 2b
-- Purpose: Track backtest non-convergences to trigger classifier re-derivation

CREATE TABLE IF NOT EXISTS diagnostic_escalations (
    id SERIAL PRIMARY KEY,
    escalated_at TIMESTAMP DEFAULT NOW(),

    -- Metric info
    metric_name TEXT NOT NULL,
    metric_type TEXT NOT NULL,  -- sum_dollars, median_days, percentage

    -- Convergence results
    naive_value NUMERIC,
    final_value NUMERIC,
    target_value NUMERIC,
    improvement_pct NUMERIC,
    remaining_gap_pct NUMERIC,

    -- Classification
    classifier_type TEXT,  -- missing_rule, impossible_target, partial_progress
    classifier_confidence TEXT,  -- high, medium, low

    -- Human feedback (for re-derivation)
    human_reviewed BOOLEAN DEFAULT FALSE,
    human_classification TEXT,  -- missing_rule, impossible_target, partial_progress, other
    human_notes TEXT,
    reviewed_at TIMESTAMP,
    reviewed_by TEXT,

    -- Audit trail
    rules_tried TEXT[],
    iterations_count INTEGER,
    converged BOOLEAN DEFAULT FALSE
);

-- Index for counting escalations
CREATE INDEX IF NOT EXISTS idx_escalation_count ON diagnostic_escalations(escalated_at);

-- Index for human-reviewed cases (used by re-derivation trigger)
CREATE INDEX IF NOT EXISTS idx_human_reviewed ON diagnostic_escalations(human_reviewed, escalated_at);

-- Index for querying by metric type
CREATE INDEX IF NOT EXISTS idx_metric_type ON diagnostic_escalations(metric_type, escalated_at);

COMMENT ON TABLE diagnostic_escalations IS 'Tracks backtest non-convergences for diagnostic classifier re-derivation (Phase 2b)';
COMMENT ON COLUMN diagnostic_escalations.human_reviewed IS 'True when human has reviewed and classified this escalation (required for re-derivation)';
COMMENT ON COLUMN diagnostic_escalations.human_classification IS 'Human-determined classification (ground truth for re-tuning thresholds)';
