-- User personas table for voice-aware CRO agent responses
-- Captures role, experience level, and preferred communication style
-- Used by api/router.py to adapt Sonnet voice and detail level

CREATE TABLE IF NOT EXISTS user_personas (
  id                        BIGSERIAL PRIMARY KEY,
  slack_user_id             TEXT NOT NULL UNIQUE,
  -- U12345ABC format from Slack
  email                     TEXT,
  display_name              TEXT,

  -- Persona classification (from DM intake or admin seed)
  persona                   TEXT NOT NULL,
  -- executive | sales_leadership | operational | ic | other

  -- Metadata for adaptive responses
  preferred_detail_level    TEXT DEFAULT 'standard',
  -- brief | standard | detailed
  wants_metrics_context     BOOLEAN DEFAULT true,
  -- true: include "why this matters" framing
  -- false: just the numbers

  -- Registration tracking
  registered_at             TIMESTAMPTZ DEFAULT now(),
  updated_at                TIMESTAMPTZ DEFAULT now(),
  source                    TEXT DEFAULT 'dm_intake'
  -- dm_intake | admin_seed
);

-- Index for fast Slack user lookup
CREATE INDEX IF NOT EXISTS idx_user_personas_slack_id
  ON user_personas(slack_user_id);

CREATE INDEX IF NOT EXISTS idx_user_personas_persona
  ON user_personas(persona);
