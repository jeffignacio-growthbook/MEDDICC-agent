-- Per-call MEDDICC scores (PROGRESSIVE_SCORING_SPEC, Phase 1).
--
-- The batch scorer reads every call for a deal and emits seven scores in one
-- pass, nightly, from scratch — which has no provenance (a 5 comes from
-- nowhere), re-litigates unchanged deals, and lets the most ambiguous
-- component absorb the pass's noise. This table is the substrate for the
-- replacement: score ONE call at a time, store what THAT call established, and
-- roll deal scores up as the most-recent-non-null per component.
--
-- SEPARATE TABLE keyed by call_id (mirrors call_transcripts/041): one scoring
-- of record per call; a re-score upserts. deal_id is denormalized here for
-- roll-up convenience but is NULLABLE on purpose — calls.deal_id is only
-- populated by the manual resolve_calls.py step, so a scored call may not yet
-- be linked. The roll-up tolerates that; it never invents a deal_id.
--
-- NULL score is a first-class value and the COMMON case: a technical call
-- establishes nothing about procurement. Null means "this call said nothing
-- about this component" — never zero, never a guess. Every non-null score
-- carries evidence from that call; nulls carry none.

CREATE TABLE IF NOT EXISTS call_scores (
  call_id                  TEXT PRIMARY KEY REFERENCES calls(call_id) ON DELETE CASCADE,
  deal_id                  TEXT,                 -- denormalized; NULL until resolve_calls links it
  call_date                DATE,                 -- the ordering key for the roll-up

  -- Seven MEDDICC components, canonical bare keys matching component_scores
  -- (migrations/003) and _PIN_COMPONENTS in meddicc_agent.py. NULLABLE: null =
  -- this call said nothing about the component.
  metrics_score            SMALLINT,
  economic_buyer_score     SMALLINT,
  decision_criteria_score  SMALLINT,
  decision_process_score   SMALLINT,
  pain_score               SMALLINT,
  champion_score           SMALLINT,
  competition_score        SMALLINT,

  -- Evidence per non-null component: {"champion": "quote/fact from THIS call", ...}.
  -- A null-scored component has no key here.
  evidence                 JSONB,

  -- Provenance of what was actually scored and how.
  text_source              TEXT NOT NULL         -- 'transcript' | 'summary'
    CHECK (text_source IN ('transcript', 'summary')),
  model                    TEXT NOT NULL,        -- e.g. claude-sonnet-4-6
  scorer_version           TEXT NOT NULL,        -- bump to invalidate stale rows on re-backfill
  scored_at                TIMESTAMPTZ NOT NULL DEFAULT now(),

  -- Scores are 0-10 or NULL. Never an out-of-range number.
  CONSTRAINT call_scores_range CHECK (
    (metrics_score           IS NULL OR metrics_score           BETWEEN 0 AND 10) AND
    (economic_buyer_score    IS NULL OR economic_buyer_score    BETWEEN 0 AND 10) AND
    (decision_criteria_score IS NULL OR decision_criteria_score BETWEEN 0 AND 10) AND
    (decision_process_score  IS NULL OR decision_process_score  BETWEEN 0 AND 10) AND
    (pain_score              IS NULL OR pain_score              BETWEEN 0 AND 10) AND
    (champion_score          IS NULL OR champion_score          BETWEEN 0 AND 10) AND
    (competition_score       IS NULL OR competition_score       BETWEEN 0 AND 10)
  )
);

-- Roll-up reads all of a deal's call scores ordered by date, so index the pair.
CREATE INDEX IF NOT EXISTS idx_call_scores_deal_date
  ON call_scores(deal_id, call_date);

CREATE INDEX IF NOT EXISTS idx_call_scores_scorer_version
  ON call_scores(scorer_version);
