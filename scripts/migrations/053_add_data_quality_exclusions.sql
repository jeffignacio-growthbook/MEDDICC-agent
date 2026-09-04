-- Migration 014: Data Quality Exclusions Table
--
-- Track deals with data quality issues (impossible timelines, suspect data)
-- that should be excluded from all metrics calculations.

CREATE TABLE IF NOT EXISTS data_quality_exclusions (
    deal_id TEXT PRIMARY KEY,
    reason TEXT NOT NULL,
    flagged_date DATE NOT NULL DEFAULT CURRENT_DATE,
    cycle_days INTEGER,
    create_date DATE,
    close_date DATE,
    company_name TEXT,
    notes TEXT,
    reviewed BOOLEAN DEFAULT FALSE,
    reviewed_date DATE,
    reviewed_by TEXT
);

-- Index for quick lookups in WHERE clauses
CREATE INDEX IF NOT EXISTS idx_data_quality_exclusions_deal_id
ON data_quality_exclusions(deal_id);

-- Insert the 8 known data quality issues
INSERT INTO data_quality_exclusions (deal_id, reason, cycle_days, create_date, close_date, company_name, notes)
VALUES
    -- Negative cycles (physically impossible)
    ('5790911698', 'NEGATIVE_CYCLE', -41, '2026-03-10', '2026-01-28', 'Make', 'Closed 41 days before created - data corruption'),
    ('5681417580', 'NEGATIVE_CYCLE', -41, '2026-02-23', '2026-01-13', 'Quizlet', 'Closed 41 days before created - data corruption'),
    ('5755377954', 'NEGATIVE_CYCLE', -13, '2026-03-04', '2026-02-19', 'BESTSECRET', 'Closed 13 days before created - data corruption'),

    -- Zero-day cycles (suspicious - same create and close date)
    ('5369635703', 'ZERO_DAY_CYCLE', 0, '2026-01-12', '2026-01-12', 'Bluesky', 'Created and closed same day - likely data entry error'),
    ('6212201883', 'ZERO_DAY_CYCLE', 0, '2026-07-07', '2026-07-07', 'Bluesky', 'Created and closed same day - likely data entry error (2nd occurrence)'),
    ('6089749648', 'ZERO_DAY_CYCLE', 0, '2026-06-05', '2026-06-05', 'LeoVegas', 'Created and closed same day - likely data entry error'),
    ('5401072420', 'ZERO_DAY_CYCLE', 0, '2026-01-15', '2026-01-15', 'Quizlet', 'Created and closed same day - likely data entry error (2nd occurrence)'),
    ('6023407620', 'ZERO_DAY_CYCLE', 0, '2026-05-13', '2026-05-13', 'knowunity.ai', 'Created and closed same day - likely data entry error')
ON CONFLICT (deal_id) DO NOTHING;

COMMENT ON TABLE data_quality_exclusions IS
'Deals with data quality issues that should be excluded from all metrics calculations.
Use in queries: WHERE deal_id NOT IN (SELECT deal_id FROM data_quality_exclusions)';
