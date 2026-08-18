-- Alter user_personas to use email as primary key instead of slack_user_id
-- This allows lazy binding of Slack IDs on first message

-- Drop existing constraints and indexes
ALTER TABLE user_personas
DROP CONSTRAINT IF EXISTS user_personas_pkey CASCADE;

ALTER TABLE user_personas
DROP CONSTRAINT IF EXISTS user_personas_slack_user_id_key CASCADE;

DROP INDEX IF EXISTS idx_user_personas_slack_id;
DROP INDEX IF EXISTS idx_user_personas_persona;

-- Add new columns if they don't exist
ALTER TABLE user_personas
ADD COLUMN IF NOT EXISTS name TEXT,
ADD COLUMN IF NOT EXISTS role TEXT,
ADD COLUMN IF NOT EXISTS role_group TEXT,
ADD COLUMN IF NOT EXISTS title TEXT,
ADD COLUMN IF NOT EXISTS last_seen_at TIMESTAMPTZ DEFAULT now();

-- Make email the primary key
ALTER TABLE user_personas
ADD PRIMARY KEY (email);

-- Make slack_user_id nullable and unique (instead of required)
ALTER TABLE user_personas
ALTER COLUMN slack_user_id DROP NOT NULL;

ALTER TABLE user_personas
ADD CONSTRAINT user_personas_slack_user_id_unique UNIQUE (slack_user_id);

-- Make persona nullable (will be populated from role_group if needed)
ALTER TABLE user_personas
ALTER COLUMN persona DROP NOT NULL;

-- Recreate indexes
CREATE INDEX IF NOT EXISTS user_personas_slack_user_id_idx
    ON user_personas(slack_user_id) WHERE slack_user_id IS NOT NULL;

CREATE INDEX IF NOT EXISTS user_personas_role_group_idx
    ON user_personas(role_group);

CREATE INDEX IF NOT EXISTS user_personas_role_idx
    ON user_personas(role);

-- Update source default to 'hubspot'
ALTER TABLE user_personas
ALTER COLUMN source SET DEFAULT 'hubspot';

COMMENT ON TABLE user_personas IS
  'User personas seeded from HubSpot Users API. Slack IDs added lazily on first message via email lookup.';

COMMENT ON COLUMN user_personas.email IS
  'Primary key. Always known from HubSpot.';

COMMENT ON COLUMN user_personas.slack_user_id IS
  'Added lazily when user sends first Slack message. Nullable until then.';

COMMENT ON COLUMN user_personas.role IS
  'Specific role: ae, sdr, vp_revops, cro, etc. Inferred from deal ownership or config overrides.';

COMMENT ON COLUMN user_personas.role_group IS
  'Persona group for voice routing: ic, sales_leadership, operational, executive, other.';
