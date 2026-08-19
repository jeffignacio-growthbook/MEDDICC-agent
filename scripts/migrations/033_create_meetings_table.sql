-- Migration 016: Create meetings table for SDR metrics
--
-- Purpose: Track HubSpot meeting bookings with Fireflies-based held inference
--
-- Data sources:
--   - HubSpot meetings API (scheduled meetings)
--   - Fireflies transcripts (held meetings with recordings)
--
-- Key insight: hs_meeting_outcome is not populated in GrowthBook's HubSpot.
-- Instead, match meetings to Fireflies calls by date/owner/company to infer
-- which meetings were actually held.

CREATE TABLE IF NOT EXISTS meetings (
    id                    BIGSERIAL PRIMARY KEY,
    hubspot_meeting_id    TEXT UNIQUE NOT NULL,
    hubspot_owner_id      TEXT,
    owner_email           TEXT,
    title                 TEXT,
    scheduled_at          TIMESTAMPTZ NOT NULL,
    scheduled_end_at      TIMESTAMPTZ,
    booked_at             TIMESTAMPTZ,
    hs_meeting_outcome    TEXT,  -- Usually null, but capture if populated

    -- Held inference
    held                  BOOLEAN,  -- True=held, False=confirmed no-show, null=unknown
    held_confidence       TEXT,     -- 'fireflies_match' | 'hs_outcome' | null
    fireflies_call_id     TEXT REFERENCES calls(call_id),

    -- Associations
    contact_email         TEXT,
    company_name          TEXT,
    deal_id               TEXT,

    -- Metadata
    created_at            TIMESTAMPTZ DEFAULT now(),
    updated_at            TIMESTAMPTZ DEFAULT now()
);

-- Indexes for common queries
CREATE INDEX IF NOT EXISTS meetings_owner_email_idx
    ON meetings(owner_email);

CREATE INDEX IF NOT EXISTS meetings_scheduled_at_idx
    ON meetings(scheduled_at);

CREATE INDEX IF NOT EXISTS meetings_held_idx
    ON meetings(held);

CREATE INDEX IF NOT EXISTS meetings_owner_date_idx
    ON meetings(owner_email, scheduled_at);

CREATE INDEX IF NOT EXISTS meetings_fireflies_call_idx
    ON meetings(fireflies_call_id);

-- Comment for documentation
COMMENT ON TABLE meetings IS 'SDR meeting bookings with Fireflies-based held inference. hs_meeting_outcome is not populated in HubSpot, so held status is inferred by matching scheduled meetings to Fireflies transcripts by date/owner/company.';

COMMENT ON COLUMN meetings.held IS 'True=held (Fireflies match or HubSpot outcome), False=confirmed no-show, null=unknown (past meeting with no signal, or future meeting)';

COMMENT ON COLUMN meetings.held_confidence IS 'Source of held inference: fireflies_match (matched to transcript), hs_outcome (HubSpot field), or null (unknown)';
