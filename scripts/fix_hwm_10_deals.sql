-- FIX 3: Correct highest_stage_order_reached for HWM=10 deals
-- Phase D Task 0 - Ordinal Semantics Investigation
-- Generated: 2026-08-11

-- PART A: Fix 252 Disqualified deals (HWM should be 9, not 10)
-- These deals went through normal stages then landed in Disqualified (order=9)
-- HWM=10 is impossible since max configured order is 9

UPDATE deals
SET highest_stage_order_reached = 9
WHERE highest_stage_order_reached = 10
  AND stage = '68509551'  -- Disqualified
  AND deal_id != '58169341204';  -- Exclude Yoto (needs history check)

-- PART B: Yoto deal (58169341204) - CONDITIONAL FIX
-- DO NOT RUN until stage history is checked via HubSpot API
--
-- Once history is fetched:
-- 1. Map each historical stage_id to its order via config/client.yaml
-- 2. Take MAX of those orders (excluding exclude_from_progression stages)
-- 3. Run:
-- UPDATE deals
-- SET highest_stage_order_reached = <calculated_max>
-- WHERE deal_id = '58169341204';

-- Expected outcomes:
-- - 252 rows updated (Disqualified deals: HWM 10→9)
-- - 1 row pending (Yoto: awaiting history analysis)
