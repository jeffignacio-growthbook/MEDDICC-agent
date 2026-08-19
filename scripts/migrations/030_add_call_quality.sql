-- Migration 030: Call Quality Assessment Table
-- Stores discovery quality scores extracted from call summaries
-- Based on gb-drill-discovery framework from GrowthBook coaching skills

CREATE TABLE IF NOT EXISTS call_quality (
    id                  BIGSERIAL PRIMARY KEY,
    call_id             TEXT REFERENCES calls(call_id),
    deal_id             TEXT,
    company_name        TEXT,
    owner_email         TEXT,
    call_date           DATE,

    -- Discovery scoring (1-10 each, null if not assessable)
    -- Based on gb-drill-discovery rubric
    quantification_score    INTEGER,  -- Did they leave with numbers?
    incumbent_picture_score INTEGER,  -- Cost, contract end, what's wrong with it
    technical_picture_score INTEGER,  -- Warehouse, SDK, who runs tests
    decision_process_score  INTEGER,  -- Who decides, threshold, timeline
    question_quality_score  INTEGER,  -- Open, one at a time, followed up

    overall_quality_score   INTEGER,  -- Average of above, 1-10

    -- What was found / missing
    numbers_obtained    JSONB,   -- which of the 5 discovery numbers were captured
    numbers_missing     JSONB,   -- which were not
    blocker_type        TEXT,    -- technical | resourcing | cultural | commercial | none
    blocker_identified  BOOLEAN, -- did rep correctly identify the blocker type

    -- Evidence
    strongest_moment    TEXT,    -- verbatim quote or description
    weakest_moment      TEXT,
    pattern_flags       TEXT[],  -- ['no_followup', 'pitched_early',
                                 --  'accepted_vague_answer', 'no_number']

    -- Metadata
    assessed_at         TIMESTAMPTZ DEFAULT now(),
    assessment_source   TEXT DEFAULT 'llm'  -- 'llm' | 'human'
);

CREATE INDEX IF NOT EXISTS call_quality_deal_id_idx
    ON call_quality(deal_id);
CREATE INDEX IF NOT EXISTS call_quality_owner_email_idx
    ON call_quality(owner_email);
CREATE INDEX IF NOT EXISTS call_quality_call_date_idx
    ON call_quality(call_date);
