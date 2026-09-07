-- Migration: Add stage_at_analysis to analyses table
-- Date: 2026-09-07
--
-- Purpose: Capture deal stage at time of MEDDICC analysis for future empirical
-- derivation of stage-relative scoring expectations. Currently, analyses table
-- doesn't record stage context, making it impossible to derive stage-relative
-- expectations (e.g., "EB-red acceptable in Discovery but concerning in Proposal").
--
-- This column stores the HubSpot stage ID or label at analysis time, enabling:
-- 1. Stage × component × band outcome analysis (per derive_stage_meddicc_expectations.py)
-- 2. Re-derivation of hand-picked expectations once sufficient data accumulates
-- 3. Validation that stage-relative coaching rules match actual win/loss patterns
--
-- Rationale: Same discipline as Signal 2 empirical derivation - derive from data
-- when possible (n≥5 per cell), hand-pick with honest labeling when insufficient,
-- set re-derivation trigger once data structure supports it.

ALTER TABLE analyses ADD COLUMN IF NOT EXISTS
  stage_at_analysis TEXT;
  -- HubSpot stage ID (e.g., '1297321623') or canonical name (e.g., 'appointmentscheduled')
  -- NULL for historical analyses (backfill not possible without timeline inference)
  -- Populated going forward by insert_analysis() callers

-- Index for stage-relative queries (derivation script groups by stage × component × band)
CREATE INDEX IF NOT EXISTS idx_analyses_stage_at_analysis
  ON analyses(stage_at_analysis);

-- Combined index for common derivation query pattern
CREATE INDEX IF NOT EXISTS idx_analyses_stage_outcome
  ON analyses(stage_at_analysis, deal_id);
