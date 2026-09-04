-- Wave 5 — Memory
-- Three specific things: what was I told, what did I say, what broke.

-- ============================================================================
-- 5b. Answers Given
-- ============================================================================
-- Thread history expires after 24 hours. This persists question, answer,
-- figures cited, and the handler that produced it.
--
-- Example: renewals went $733K → $5.2M → $1.59M over two days.
-- Nobody could reconstruct the sequence because thread history expired.

CREATE TABLE IF NOT EXISTS answers_given (
    id BIGSERIAL PRIMARY KEY,

    question TEXT NOT NULL,
    answer TEXT NOT NULL,

    -- Figures cited in the answer (for reconciliation when numbers change)
    figures_cited JSONB,
    -- e.g. {"total_pipeline": 14800000, "deal_count": 100, "team_attainment": 12.7}

    handler_name TEXT NOT NULL,
    -- Which handler produced this answer (or 'dynamic' for general path)

    -- Thread context
    thread_ts TEXT,
    asked_by TEXT,  -- Slack user_id or 'calibration_runner'

    -- Query metadata
    tables_queried TEXT[],  -- Which tables were accessed
    row_count INTEGER,      -- How many rows were in the result set

    answered_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),

    -- Index for "what did I say about X"
    CONSTRAINT answers_given_thread_ts_idx UNIQUE (thread_ts, answered_at)
);

CREATE INDEX IF NOT EXISTS idx_answers_given_handler
    ON answers_given(handler_name, answered_at DESC);

CREATE INDEX IF NOT EXISTS idx_answers_given_question
    ON answers_given USING gin(to_tsvector('english', question));

COMMENT ON TABLE answers_given IS
    'Wave 5b: Persists answers beyond 24-hour thread expiry. Enables reconciliation when numbers change.';

-- ============================================================================
-- 5c. Failure Resolution
-- ============================================================================
-- fallback_log captures trigger and fast_path_attempted.
-- Add resolution tracking so when a failure gets fixed, we close the loop.

ALTER TABLE fallback_log ADD COLUMN IF NOT EXISTS resolved BOOLEAN DEFAULT FALSE;
ALTER TABLE fallback_log ADD COLUMN IF NOT EXISTS resolved_at TIMESTAMPTZ;
ALTER TABLE fallback_log ADD COLUMN IF NOT EXISTS resolution_type TEXT;
    -- 'handler_added' | 'semantic_fact_added' | 'data_fixed' | 'question_clarified' | 'out_of_scope'
ALTER TABLE fallback_log ADD COLUMN IF NOT EXISTS resolution_notes TEXT;

CREATE INDEX IF NOT EXISTS idx_fallback_log_unresolved
    ON fallback_log(trigger, resolved) WHERE resolved = FALSE;

COMMENT ON COLUMN fallback_log.resolved IS
    'Wave 5c: Marks when a fallback failure was later fixed. Turns log into record of what actually goes wrong.';

-- ============================================================================
-- 5a. Corrections as Evidence
-- ============================================================================
-- The proposals table already exists (migration 036).
-- Add a field to track conversation context for correction proposals.

ALTER TABLE proposals ADD COLUMN IF NOT EXISTS conversation_evidence JSONB;
    -- Thread context showing the correction being made
    -- {"thread_ts": "...", "user_message": "...", "agent_response": "...", "correction": "..."}

COMMENT ON COLUMN proposals.conversation_evidence IS
    'Wave 5a: Conversation context when user corrects agent. Evidence for general vs one-off determination.';
