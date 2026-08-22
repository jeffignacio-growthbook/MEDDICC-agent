-- Store raw call transcripts in the substrate (STORE_AND_BACKFILL_TRANSCRIPTS).
--
-- NormalizedCall already carries raw_transcript, but to_row() drops it — the
-- adapter contract says transcripts belong in the substrate and the write path
-- quietly diverged. This table closes that gap so coaching / deal-prep read the
-- actual conversation, and the highest-value artifact stops living only inside
-- a vendor's API (Fireflies today, Gong tomorrow).
--
-- SEPARATE TABLE, not a column on calls: ~20 handlers read `calls`, several
-- paging 1000 rows at a time; a 45-min transcript is 40-60KB. Putting that on a
-- hot table changes the cost of every existing query. Keep `calls` lean.
--
-- FK note: calls.call_id is TEXT PRIMARY KEY (migrations/001). We keep a FK with
-- ON DELETE CASCADE so a transcript never outlives its call. Migration 010
-- dropped call FKs on objections/feature_gaps because those are written from the
-- ANALYSIS path where the parent call row may not exist yet; transcripts are
-- written from the INGESTION path (alongside the call upsert) and the backfill
-- only iterates existing calls, so the parent always exists here.

CREATE TABLE IF NOT EXISTS call_transcripts (
  call_id             TEXT PRIMARY KEY REFERENCES calls(call_id) ON DELETE CASCADE,
  source              TEXT NOT NULL,            -- 'fireflies' | 'apollo' | 'gong'
  transcript          TEXT,                     -- assembled, readable; NULL if unavailable
  transcript_quality  TEXT NOT NULL
    CHECK (transcript_quality IN ('full', 'partial', 'fragments_only', 'unavailable')),
  unavailable_reason  TEXT,                     -- why NULL, when it is NULL
  char_count          INTEGER,
  fetched_at          TIMESTAMPTZ NOT NULL DEFAULT now(),

  -- NULL, never an empty string or placeholder (matches the codebase's
  -- null-handling discipline). A call with no transcript is 'unavailable' + a
  -- reason, not "".
  CONSTRAINT call_transcripts_no_empty_string
    CHECK (transcript IS NULL OR transcript <> ''),
  -- If there is no transcript text, it must be explicitly marked unavailable
  -- and carry a reason — so a NULL is always an accounted-for absence.
  CONSTRAINT call_transcripts_null_is_unavailable
    CHECK (transcript IS NOT NULL
           OR (transcript_quality = 'unavailable' AND unavailable_reason IS NOT NULL))
);

CREATE INDEX IF NOT EXISTS idx_call_transcripts_source
  ON call_transcripts(source, transcript_quality);
