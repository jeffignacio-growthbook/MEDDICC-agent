-- Migration 076: plan_feedback and plan_templates tables
-- Supports Piece 7 of the compositional layer (api/plan_feedback.py).
--
-- plan_feedback: one row per user feedback event (confirmed / rejected).
--   Deduplication for confirmation counting is done in application code via
--   distinct question_hash values — DB stores raw events.
--
-- plan_templates: promoted plan structures, flagged for handler review.
--   Contains structure only (sub_parts / primitives). Stored answer values
--   are never served; callers always re-run Execute/Verify fresh.

-- Feedback log
CREATE TABLE IF NOT EXISTS plan_feedback (
    id              BIGSERIAL PRIMARY KEY,
    plan_signature  TEXT        NOT NULL,
    question_hash   TEXT        NOT NULL,
    question_text   TEXT        NOT NULL,
    thread_id       TEXT        NOT NULL,
    confirmed       BOOLEAN     NOT NULL,
    created_at      TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_plan_feedback_signature
    ON plan_feedback (plan_signature);

CREATE INDEX IF NOT EXISTS idx_plan_feedback_sig_confirmed
    ON plan_feedback (plan_signature, confirmed);

-- Promoted plan templates
CREATE TABLE IF NOT EXISTS plan_templates (
    plan_signature          TEXT        PRIMARY KEY,
    plan_json               TEXT        NOT NULL,
    confirmation_count      INTEGER     NOT NULL DEFAULT 0,
    flagged_for_handler_review BOOLEAN  NOT NULL DEFAULT FALSE,
    created_at              TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at              TIMESTAMPTZ NOT NULL DEFAULT NOW()
);
