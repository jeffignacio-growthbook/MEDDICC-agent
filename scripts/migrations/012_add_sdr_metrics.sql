-- SDR metrics tables for Apollo, Salesloft, and Aircall
-- Tracks daily activity metrics per user across dialer/sequencer platforms

-- User mapping table to normalize user IDs across different tools
CREATE TABLE IF NOT EXISTS sdr_users (
  id                        BIGSERIAL PRIMARY KEY,
  tool                      TEXT NOT NULL,
  -- apollo | salesloft | aircall
  tool_user_id              TEXT NOT NULL,
  user_name                 TEXT,
  user_email                TEXT,
  -- Optional: map to internal user identifier
  internal_user_id          TEXT,
  first_seen                TIMESTAMPTZ DEFAULT now(),
  last_seen                 TIMESTAMPTZ DEFAULT now(),
  UNIQUE(tool, tool_user_id)
);

-- Daily SDR metrics per user per tool
CREATE TABLE IF NOT EXISTS sdr_metrics (
  id                        BIGSERIAL PRIMARY KEY,
  tool                      TEXT NOT NULL,
  -- apollo | salesloft | aircall
  tool_user_id              TEXT NOT NULL,
  user_name                 TEXT,
  metric_date               DATE NOT NULL,
  -- Date in reporting timezone (not UTC)

  -- Call metrics (Apollo, Salesloft, Aircall)
  calls_made                INTEGER DEFAULT 0,
  connected_calls           INTEGER DEFAULT 0,
  connect_rate              NUMERIC,
  -- null when calls_made = 0 (data gap)
  voicemails                INTEGER DEFAULT 0,
  no_answers                INTEGER DEFAULT 0,
  missed_calls              INTEGER DEFAULT 0,
  bad_numbers               INTEGER DEFAULT 0,
  avg_duration_seconds      NUMERIC,

  -- Email metrics (Salesloft only)
  emails_sent               INTEGER DEFAULT 0,
  emails_opened             INTEGER DEFAULT 0,
  emails_replied            INTEGER DEFAULT 0,
  open_rate                 NUMERIC,
  -- null when emails_sent = 0 (data gap)
  reply_rate                NUMERIC,
  -- null when emails_sent = 0 (data gap)

  -- Metadata
  data_gap                  BOOLEAN DEFAULT FALSE,
  -- true when key denominators are 0 (no activity)
  etl_run_at                TIMESTAMPTZ DEFAULT now(),

  UNIQUE(tool, tool_user_id, metric_date)
);

-- Indexes for efficient querying
CREATE INDEX IF NOT EXISTS idx_sdr_users_tool
  ON sdr_users(tool);

CREATE INDEX IF NOT EXISTS idx_sdr_users_internal
  ON sdr_users(internal_user_id)
  WHERE internal_user_id IS NOT NULL;

CREATE INDEX IF NOT EXISTS idx_sdr_metrics_tool
  ON sdr_metrics(tool);

CREATE INDEX IF NOT EXISTS idx_sdr_metrics_date
  ON sdr_metrics(metric_date DESC);

CREATE INDEX IF NOT EXISTS idx_sdr_metrics_user_date
  ON sdr_metrics(tool_user_id, metric_date DESC);

CREATE INDEX IF NOT EXISTS idx_sdr_metrics_tool_date
  ON sdr_metrics(tool, metric_date DESC);
