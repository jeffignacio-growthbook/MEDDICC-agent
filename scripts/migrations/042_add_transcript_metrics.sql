-- Conversation metrics on call_transcripts (STORE_AND_BACKFILL_TRANSCRIPTS).
--
-- Both sources carry per-utterance timestamps (Fireflies in seconds, Apollo in
-- milliseconds — normalised to seconds at the adapter boundary), so talk time,
-- question rate, and monologue length are computable DURING the one backfill
-- pass while we hold the raw payload. Computing later would mean re-fetching all
-- ~2,742 calls, because the stored `transcript` is assembled "[speaker]: line"
-- text with no timestamps. Hence: compute once, store.
--
-- Per-speaker maps are keyed on the most STABLE speaker id per source (Apollo
-- participant_id; Fireflies has only speaker_name) with a `speakers` name
-- lookup alongside — storing the raw per-speaker split can't be wrong by
-- construction, whereas a single rep-vs-other ratio would bake in a speaker→rep
-- attribution guess we'd have to re-fetch to undo. Rep ratio is derived later
-- from talk_time_seconds[rep] once host/organizer→roster attribution is settled.

ALTER TABLE call_transcripts ADD COLUMN IF NOT EXISTS talk_time_seconds JSONB;
  -- {speaker_key: seconds} — seconds of speech per speaker
ALTER TABLE call_transcripts ADD COLUMN IF NOT EXISTS question_count JSONB;
  -- {speaker_key: n} — utterances ending in '?' per speaker (a punctuation
  -- floor: ASR may under-punctuate questions)
ALTER TABLE call_transcripts ADD COLUMN IF NOT EXISTS speakers JSONB;
  -- {speaker_key: display_name} — name lookup for the keys above
ALTER TABLE call_transcripts ADD COLUMN IF NOT EXISTS total_speech_seconds NUMERIC;
  -- sum of utterance durations (denominator for any talk ratio)
ALTER TABLE call_transcripts ADD COLUMN IF NOT EXISTS longest_monologue_seconds NUMERIC;
  -- longest single-speaker continuous run. "Continuous" = interruptions from
  -- other speakers totalling < 3s between a speaker's utterances are treated as
  -- backchannel ("mm-hmm", "right") and do NOT break the run, nor count toward
  -- its length; 3s or more of other-speaker speech ends the run.
ALTER TABLE call_transcripts ADD COLUMN IF NOT EXISTS longest_monologue_speaker TEXT;
  -- display name of the speaker who held the longest monologue
ALTER TABLE call_transcripts ADD COLUMN IF NOT EXISTS sentence_count INTEGER;
  -- utterances parsed (0 when unavailable)
