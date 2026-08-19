-- Rename Fireflies-specific names to be source-agnostic
-- Part of Phase 5: CI Adapter Abstraction

-- Rename column: fireflies_call_id → call_recording_id
ALTER TABLE meetings
RENAME COLUMN fireflies_call_id TO call_recording_id;

-- Drop old index
DROP INDEX IF EXISTS meetings_fireflies_call_idx;

-- Create new index with updated name
CREATE INDEX IF NOT EXISTS meetings_call_recording_idx
    ON meetings(call_recording_id);

-- Update column comment to reflect new confidence value
COMMENT ON COLUMN meetings.held_confidence IS 'Source of held inference: call_recording_match (matched to transcript from any CI source), hs_outcome (HubSpot field), or null (unknown)';

-- No data migration needed - confidence values updated by code changes in etl_meetings.py
