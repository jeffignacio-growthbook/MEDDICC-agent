-- Migration: Fix Remaining 10 Swapped Deal Dates
-- Date: 2026-09-04
--
-- Additional 10 deals with moderate negative cycles (-14d to -67d)
-- that become valid when dates are swapped.

-- Square: -67d → 67d
UPDATE deals SET create_date = '2024-11-25', close_date = '2025-01-31' WHERE deal_id = '32821739117';

-- Action Nederland: -67d → 67d
UPDATE deals SET create_date = '2025-07-11', close_date = '2025-09-16' WHERE deal_id = '43739930533';

-- EDF Energy: -52d → 52d
UPDATE deals SET create_date = '2025-06-18', close_date = '2025-08-09' WHERE deal_id = '41610728003';

-- Make: -41d → 41d
UPDATE deals SET create_date = '2026-01-28', close_date = '2026-03-10' WHERE deal_id = '57909116984';

-- Quizlet: -41d → 41d
UPDATE deals SET create_date = '2026-01-13', close_date = '2026-02-23' WHERE deal_id = '56814175800';

-- pelmorex: -29d → 29d
UPDATE deals SET create_date = '2023-08-29', close_date = '2023-09-27' WHERE deal_id = '15342570867';

-- Quizlet: -24d → 24d
UPDATE deals SET create_date = '2026-01-31', close_date = '2026-02-24' WHERE deal_id = '56896689288';

-- Reach plc: -19d → 19d
UPDATE deals SET create_date = '2025-12-06', close_date = '2025-12-25' WHERE deal_id = '52491158184';

-- Haystack TV Inc: -16d → 16d
UPDATE deals SET create_date = '2025-07-24', close_date = '2025-08-09' WHERE deal_id = '41610727783';

-- Wix / DeviantArt: -14d → 14d
UPDATE deals SET create_date = '2025-09-19', close_date = '2025-10-03' WHERE deal_id = '45144997263';
