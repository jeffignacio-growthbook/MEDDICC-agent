-- Migration: Add Data Quality Exclusions
-- Date: 2026-09-04
--
-- Root cause: Field confusion between created_at (Supabase ETL timestamp) and
-- create_date (HubSpot deal creation date) led to false identification of issues.
--
-- After correction, 20 deals remain with genuine data quality issues:
-- - 9 truly broken negative cycles (close before create, not fixable by swapping)
-- - 11 suspicious zero-day won deals (zero ARR or large same-day closes)
--
-- These deals should be excluded from conversion analysis as they:
-- - Cannot have valid qualification_week
-- - Distort cycle time metrics
-- - Indicate data entry errors or bulk retroactive imports

-- Create data_quality_exclusions table if not exists
CREATE TABLE IF NOT EXISTS data_quality_exclusions (
    deal_id TEXT PRIMARY KEY,
    reason TEXT NOT NULL,
    cycle_days INTEGER,
    create_date DATE,
    close_date DATE,
    company_name TEXT,
    notes TEXT,
    flagged_date DATE NOT NULL DEFAULT CURRENT_DATE,
    reviewed BOOLEAN DEFAULT FALSE
);

-- Insert truly broken negative cycles (9 deals)
INSERT INTO data_quality_exclusions (deal_id, reason, cycle_days, create_date, close_date, company_name)
VALUES ('41609744055', 'NEGATIVE_CYCLE', -682, '2025-08-09', '2023-09-27', 'Fellow');

INSERT INTO data_quality_exclusions (deal_id, reason, cycle_days, create_date, close_date, company_name)
VALUES ('41609747117', 'NEGATIVE_CYCLE', -658, '2025-08-09', '2023-10-21', 'Netthandelsgruppen');

INSERT INTO data_quality_exclusions (deal_id, reason, cycle_days, create_date, close_date, company_name)
VALUES ('57856036766', 'NEGATIVE_CYCLE', -580, '2026-03-10', '2024-08-07', 'Refurbed Marketplace GmbH');

INSERT INTO data_quality_exclusions (deal_id, reason, cycle_days, create_date, close_date, company_name)
VALUES ('41609744944', 'NEGATIVE_CYCLE', -442, '2025-08-09', '2024-05-24', 'SymplaTeste');

INSERT INTO data_quality_exclusions (deal_id, reason, cycle_days, create_date, close_date, company_name)
VALUES ('57539418520', 'NEGATIVE_CYCLE', -417, '2026-03-05', '2025-01-12', 'patreon');

INSERT INTO data_quality_exclusions (deal_id, reason, cycle_days, create_date, close_date, company_name)
VALUES ('57856098205', 'NEGATIVE_CYCLE', -406, '2026-03-10', '2025-01-28', 'Make');

INSERT INTO data_quality_exclusions (deal_id, reason, cycle_days, create_date, close_date, company_name)
VALUES ('57856099977', 'NEGATIVE_CYCLE', -402, '2026-03-11', '2025-02-02', 'Joyteractive');

INSERT INTO data_quality_exclusions (deal_id, reason, cycle_days, create_date, close_date, company_name)
VALUES ('41610727759', 'NEGATIVE_CYCLE', -402, '2025-08-09', '2024-07-03', 'kununu GmbH');

INSERT INTO data_quality_exclusions (deal_id, reason, cycle_days, create_date, close_date, company_name)
VALUES ('56906140802', 'NEGATIVE_CYCLE', -388, '2026-02-23', '2025-01-31', 'Quizlet');

-- Insert suspicious zero-day won deals (11 deals)
INSERT INTO data_quality_exclusions (deal_id, reason, cycle_days, create_date, close_date, company_name)
VALUES ('51249962302', 'ZERO_DAY_WON', 0, '2025-12-03', '2025-12-03', 'Avaaz');

INSERT INTO data_quality_exclusions (deal_id, reason, cycle_days, create_date, close_date, company_name)
VALUES ('54223525305', 'ZERO_DAY_WON', 0, '2026-01-21', '2026-01-21', 'AgencyAnalytics');

INSERT INTO data_quality_exclusions (deal_id, reason, cycle_days, create_date, close_date, company_name)
VALUES ('62122018837', 'ZERO_DAY_WON', 0, '2026-07-07', '2026-07-07', 'Bluesky');

INSERT INTO data_quality_exclusions (deal_id, reason, cycle_days, create_date, close_date, company_name)
VALUES ('16791240492', 'ZERO_DAY_WON', 0, '2024-01-03', '2024-01-03', 'Khan Academy');

INSERT INTO data_quality_exclusions (deal_id, reason, cycle_days, create_date, close_date, company_name)
VALUES ('38680235576', 'ZERO_DAY_WON', 0, '2025-06-09', '2025-06-09', 'Lease a Bike');

INSERT INTO data_quality_exclusions (deal_id, reason, cycle_days, create_date, close_date, company_name)
VALUES ('60897496484', 'ZERO_DAY_WON', 0, '2026-06-05', '2026-06-05', 'LeoVegas');

INSERT INTO data_quality_exclusions (deal_id, reason, cycle_days, create_date, close_date, company_name)
VALUES ('18654043745', 'ZERO_DAY_WON', 0, '2024-04-15', '2024-04-15', 'Square');

INSERT INTO data_quality_exclusions (deal_id, reason, cycle_days, create_date, close_date, company_name)
VALUES ('41705593737', 'ZERO_DAY_WON', 0, '2025-08-11', '2025-08-11', 'Uzum');

INSERT INTO data_quality_exclusions (deal_id, reason, cycle_days, create_date, close_date, company_name)
VALUES ('53696357034', 'ZERO_DAY_WON', 0, '2026-01-12', '2026-01-12', 'Bluesky');

INSERT INTO data_quality_exclusions (deal_id, reason, cycle_days, create_date, close_date, company_name)
VALUES ('14195068446', 'ZERO_DAY_WON', 0, '2023-07-17', '2023-07-17', 'Inditex');

INSERT INTO data_quality_exclusions (deal_id, reason, cycle_days, create_date, close_date, company_name)
VALUES ('54010724204', 'ZERO_DAY_WON', 0, '2026-01-15', '2026-01-15', 'Quizlet');
