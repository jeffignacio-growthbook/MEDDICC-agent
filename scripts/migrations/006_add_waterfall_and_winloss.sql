-- Migration 006: Add waterfall metrics and win/loss narrative tracking
-- Weekly aggregated waterfall + win/loss reason capture

-- Stage transitions for waterfall analysis
CREATE TABLE IF NOT EXISTS stage_transitions (
    id BIGSERIAL PRIMARY KEY,
    deal_id TEXT NOT NULL,
    company_slug TEXT NOT NULL,
    from_stage_id TEXT,
    from_stage_name TEXT,
    to_stage_id TEXT NOT NULL,
    to_stage_name TEXT,
    transition_date TIMESTAMPTZ NOT NULL,
    days_in_previous_stage INTEGER,
    transition_type TEXT CHECK (transition_type IN ('forward', 'backward', 'skip', 'resurrection')),
    overall_score_at_transition INTEGER,
    created_at TIMESTAMPTZ DEFAULT NOW()
);

CREATE INDEX idx_stage_transitions_deal ON stage_transitions(deal_id);
CREATE INDEX idx_stage_transitions_date ON stage_transitions(transition_date DESC);
CREATE INDEX idx_stage_transitions_to_stage ON stage_transitions(to_stage_id);

-- Weekly waterfall metrics by stage
CREATE TABLE IF NOT EXISTS waterfall_weekly (
    id BIGSERIAL PRIMARY KEY,
    week_start_date DATE NOT NULL,
    week_end_date DATE NOT NULL,
    stage_id TEXT NOT NULL,
    stage_name TEXT NOT NULL,
    stage_order INTEGER NOT NULL,
    deals_created_count INTEGER DEFAULT 0,      -- NEW deals created this week
    deals_qualified_count INTEGER DEFAULT 0,     -- Deals that reached qualified stage
    deals_entered INTEGER DEFAULT 0,             -- Deals that entered this stage
    deals_advanced INTEGER DEFAULT 0,            -- Deals that advanced to next stage
    deals_stalled INTEGER DEFAULT 0,             -- Deals stuck in stage
    deals_regressed INTEGER DEFAULT 0,           -- Deals that moved backward
    deals_lost INTEGER DEFAULT 0,                -- Deals lost from this stage
    avg_days_in_stage NUMERIC(10,2),
    conversion_rate NUMERIC(5,2),
    calculated_at TIMESTAMPTZ DEFAULT NOW(),
    UNIQUE(week_start_date, week_end_date, stage_id)
);

CREATE INDEX idx_waterfall_weekly_date ON waterfall_weekly(week_start_date, week_end_date);
CREATE INDEX idx_waterfall_weekly_stage ON waterfall_weekly(stage_id);

-- Win/loss narratives
CREATE TABLE IF NOT EXISTS win_loss_narratives (
    id BIGSERIAL PRIMARY KEY,
    deal_id TEXT NOT NULL,
    company_slug TEXT NOT NULL,
    outcome TEXT CHECK (outcome IN ('won', 'lost')) NOT NULL,
    stated_reason TEXT,                          -- Reason from rep (dropdown or notes)
    analyzed_reason TEXT,                        -- AI-extracted reason from calls
    competitor_mentioned TEXT,
    close_date DATE,
    deal_value NUMERIC(15,2),
    sales_cycle_days INTEGER,
    stage_at_close TEXT,
    overall_score_at_close INTEGER,
    created_at TIMESTAMPTZ DEFAULT NOW(),
    UNIQUE(deal_id)
);

CREATE INDEX idx_win_loss_narratives_outcome ON win_loss_narratives(outcome);
CREATE INDEX idx_win_loss_narratives_date ON win_loss_narratives(close_date DESC);
CREATE INDEX idx_win_loss_narratives_competitor ON win_loss_narratives(competitor_mentioned) WHERE competitor_mentioned IS NOT NULL;

COMMENT ON TABLE stage_transitions IS 'Individual deal movements between stages for waterfall analysis';
COMMENT ON TABLE waterfall_weekly IS 'Weekly aggregated pipeline metrics by stage';
COMMENT ON COLUMN waterfall_weekly.deals_created_count IS 'Count of NEW deals created this week (entered pipeline)';
COMMENT ON COLUMN waterfall_weekly.deals_qualified_count IS 'Count of deals that reached qualified stage this week';
COMMENT ON TABLE win_loss_narratives IS 'Win/loss reasons and analysis for closed deals';
COMMENT ON COLUMN win_loss_narratives.stated_reason IS 'Reason provided by sales rep (from CRM field or notes)';
