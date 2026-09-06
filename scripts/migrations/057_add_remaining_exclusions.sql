-- Migration: Add Remaining 8 Data Quality Exclusions
-- Date: 2026-09-04
--
-- Minor negative cycles (-1d to -13d) that are too small to fix via swapping
-- but still indicate data quality issues (likely data entry errors).

INSERT INTO data_quality_exclusions (deal_id, reason, cycle_days, create_date, close_date, company_name)
VALUES ('57553779546', 'NEGATIVE_CYCLE', -13, '2026-03-04', '2026-02-19', 'BESTSECRET');

INSERT INTO data_quality_exclusions (deal_id, reason, cycle_days, create_date, close_date, company_name)
VALUES ('54276667418', 'NEGATIVE_CYCLE', -4, '2026-01-21', '2026-01-17', 'VSCO');

INSERT INTO data_quality_exclusions (deal_id, reason, cycle_days, create_date, close_date, company_name)
VALUES ('34494802963', 'NEGATIVE_CYCLE', -4, '2025-03-10', '2025-03-06', 'Dribbleup');

INSERT INTO data_quality_exclusions (deal_id, reason, cycle_days, create_date, close_date, company_name)
VALUES ('32821623700', 'NEGATIVE_CYCLE', -1, '2025-01-31', '2025-01-30', '7shifts');

INSERT INTO data_quality_exclusions (deal_id, reason, cycle_days, create_date, close_date, company_name)
VALUES ('32820089374', 'NEGATIVE_CYCLE', -1, '2025-01-31', '2025-01-30', 'Breeze Airways');

INSERT INTO data_quality_exclusions (deal_id, reason, cycle_days, create_date, close_date, company_name)
VALUES ('32821623440', 'NEGATIVE_CYCLE', -1, '2025-01-31', '2025-01-30', '7shifts');

INSERT INTO data_quality_exclusions (deal_id, reason, cycle_days, create_date, close_date, company_name)
VALUES ('53441920789', 'NEGATIVE_CYCLE', -1, '2026-01-08', '2026-01-07', 'Fortis Games');

INSERT INTO data_quality_exclusions (deal_id, reason, cycle_days, create_date, close_date, company_name)
VALUES ('45489233443', 'NEGATIVE_CYCLE', -1, '2025-10-09', '2025-10-08', 'lendable');
