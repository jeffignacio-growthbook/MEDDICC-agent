-- Coaching hypothesis loop state table.
-- Tracks the lifecycle of each component hypothesis from detection through
-- experiment, with a single human checkpoint (pending_review) before any
-- recommendation reaches a rep.
CREATE TABLE IF NOT EXISTS coaching_hypotheses (
    id              BIGSERIAL PRIMARY KEY,
    component       TEXT NOT NULL,           -- one of the 7 MEDDICC components
    direction       TEXT NOT NULL,           -- 'higher' or 'lower'
    train_p         DOUBLE PRECISION,        -- stratified permutation p (training set)
    train_d         DOUBLE PRECISION,        -- Cohen's d (training set)
    holdout_d       DOUBLE PRECISION,        -- Cohen's d (holdout set)
    run_date        DATE NOT NULL,           -- date this hypothesis was generated
    status          TEXT NOT NULL DEFAULT 'pending_review',
        -- pending_review  → waiting for human approve/reject in Supabase Studio
        -- approved        → human approved; experiment is now tracking
        -- rejected        → human rejected; skip this component going forward
        -- tracking        → experiment is running (crossing rate measured weekly)
        -- completed       → experiment finished; final report written
        -- no_clear        → rule did not clear; logged for audit, no action taken
    proposal        JSONB,                   -- full draft_proposal() output
    experiment      JSONB,                   -- experiment tracking state
    notes           TEXT,                    -- human notes (filled in Studio)
    created_at      TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at      TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS coaching_hypotheses_status_idx
    ON coaching_hypotheses (status);

CREATE INDEX IF NOT EXISTS coaching_hypotheses_run_date_idx
    ON coaching_hypotheses (run_date DESC);

-- Prevent duplicate active rows for the same component
CREATE UNIQUE INDEX IF NOT EXISTS coaching_hypotheses_active_component_idx
    ON coaching_hypotheses (component)
    WHERE status IN ('pending_review', 'approved', 'tracking');
