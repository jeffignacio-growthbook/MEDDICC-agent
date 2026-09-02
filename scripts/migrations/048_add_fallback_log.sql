-- Fallback logging table
-- Captures every use of the general fallback path for learning and roadmap building

CREATE TABLE IF NOT EXISTS fallback_log (
    id BIGSERIAL PRIMARY KEY,
    question TEXT NOT NULL,
    trigger TEXT NOT NULL,  -- budget_exhausted, discarded_answer, plausibility_block, below_floor, handler_raised
    fast_path_attempted TEXT,  -- handler name or 'dynamic'
    fast_path_failure TEXT,  -- what went wrong
    queries_run JSONB,  -- [{table, columns, filters, rows_returned, execution_time_ms}, ...]
    answered BOOLEAN DEFAULT FALSE,
    answer_excerpt TEXT,  -- first 200 chars of answer for quick review
    tokens_used INTEGER,
    latency_ms INTEGER,
    created_at TIMESTAMPTZ DEFAULT NOW()
);

-- Index for weekly review grouping
CREATE INDEX IF NOT EXISTS idx_fallback_log_question_pattern
    ON fallback_log USING gin(to_tsvector('english', question));

-- Index for trigger analysis
CREATE INDEX IF NOT EXISTS idx_fallback_log_trigger
    ON fallback_log(trigger, created_at DESC);

-- Index for fast path failure analysis
CREATE INDEX IF NOT EXISTS idx_fallback_log_fast_path
    ON fallback_log(fast_path_attempted, answered);

COMMENT ON TABLE fallback_log IS
'Every use of the general fallback path. queries_run column is the raw material for handlers.';

COMMENT ON COLUMN fallback_log.queries_run IS
'Worked example of how to answer this question: [{table, columns, filters, rows_returned}, ...].
This is the specification for a handler if the same question pattern recurs 3+ times.';

COMMENT ON COLUMN fallback_log.trigger IS
'Why the fast path failed: budget_exhausted, discarded_answer (has_answer=True but returned failure),
plausibility_block, below_floor, handler_raised. discarded_answer indicates control-flow bug.';
