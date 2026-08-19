-- Add SDR/BDR attribution field to deals table
-- Stores the email of the SDR who sourced the deal, regardless of current owner
-- Enables tracking SDR-sourced pipeline post-handoff to AEs

ALTER TABLE deals
ADD COLUMN IF NOT EXISTS sdr_owner_email TEXT;

CREATE INDEX IF NOT EXISTS deals_sdr_owner_email_idx
ON deals(sdr_owner_email);

COMMENT ON COLUMN deals.sdr_owner_email IS
  'Email of SDR/BDR who sourced this deal. Populated from HubSpot attribution field configured in client.yaml (e.g., bdr_owner). Used for SDR pipeline contribution tracking.';
