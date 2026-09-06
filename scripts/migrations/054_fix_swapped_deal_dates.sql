-- Migration: Fix Swapped Deal Dates
-- Date: 2026-09-04
--
-- Root cause: 15 deals have create_date and close_date swapped in source data.
-- When swapped, these deals have valid cycles (100-360 days).
-- This recovers real deals instead of excluding them from analysis.

-- Haystack TV Inc: -359d → 359d
UPDATE deals SET create_date = '2024-08-15', close_date = '2025-08-09' WHERE deal_id = '41610727774';

-- Opera: -345d → 345d
UPDATE deals SET create_date = '2024-08-29', close_date = '2025-08-09' WHERE deal_id = '41609747244';

-- Asana: -335d → 335d
UPDATE deals SET create_date = '2025-04-04', close_date = '2026-03-05' WHERE deal_id = '57601552421';

-- Fellow: -311d → 311d
UPDATE deals SET create_date = '2024-10-02', close_date = '2025-08-09' WHERE deal_id = '41609744165';

-- BESTSECRET: -307d → 307d
UPDATE deals SET create_date = '2025-05-01', close_date = '2026-03-04' WHERE deal_id = '57553470314';

-- Make: -300d → 300d
UPDATE deals SET create_date = '2025-05-14', close_date = '2026-03-10' WHERE deal_id = '57856036981';

-- Asana: -236d → 236d
UPDATE deals SET create_date = '2024-04-04', close_date = '2024-11-26' WHERE deal_id = '29586293533';

-- lendable: -223d → 223d
UPDATE deals SET create_date = '2025-02-20', close_date = '2025-10-01' WHERE deal_id = '45092404555';

-- Refurbed Marketplace GmbH: -215d → 215d
UPDATE deals SET create_date = '2025-08-07', close_date = '2026-03-10' WHERE deal_id = '57856160781';

-- TSH: -189d → 189d
UPDATE deals SET create_date = '2025-02-01', close_date = '2025-08-09' WHERE deal_id = '41609747284';

-- Space Neobank: -184d → 184d
UPDATE deals SET create_date = '2025-02-06', close_date = '2025-08-09' WHERE deal_id = '41610727939';

-- MasterClass: -158d → 158d
UPDATE deals SET create_date = '2025-10-03', close_date = '2026-03-10' WHERE deal_id = '57856036663';

-- facile.it: -155d → 155d
UPDATE deals SET create_date = '2025-10-01', close_date = '2026-03-05' WHERE deal_id = '57553731729';

-- lendable: -119d → 119d
UPDATE deals SET create_date = '2025-06-04', close_date = '2025-10-01' WHERE deal_id = '45002408375';

-- Which?: -102d → 102d
UPDATE deals SET create_date = '2025-04-29', close_date = '2025-08-09' WHERE deal_id = '41609747354';
