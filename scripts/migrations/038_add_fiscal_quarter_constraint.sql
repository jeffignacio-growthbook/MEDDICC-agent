-- Migration 038: Add NOT NULL constraint to fiscal_quarter
--
-- Context: fiscal_quarter was added to deals_snapshot but without NOT NULL constraint.
-- This allows orphan rows (fiscal_quarter=NULL) that escape cleanup filters like
-- fiscal_quarter = 'FY2027 Q3', contaminating analyses.
--
-- Prerequisites: Run backfill_null_fiscal_quarters.py first to eliminate existing NULLs
--
-- Effect: Future snapshot writers must set fiscal_quarter or fail loudly instead of
-- creating orphan rows.

-- Verify no NULL values exist before adding constraint
DO $$
DECLARE
    null_count INT;
BEGIN
    SELECT COUNT(*) INTO null_count
    FROM deals_snapshot
    WHERE fiscal_quarter IS NULL;

    IF null_count > 0 THEN
        RAISE EXCEPTION '% rows have fiscal_quarter=NULL - run backfill_null_fiscal_quarters.py first', null_count;
    END IF;

    RAISE NOTICE 'Verified: 0 rows with fiscal_quarter=NULL';
END $$;

-- Add NOT NULL constraint
ALTER TABLE deals_snapshot
ALTER COLUMN fiscal_quarter SET NOT NULL;

-- Verify constraint was added
DO $$
BEGIN
    -- Test that NULL values are rejected
    BEGIN
        INSERT INTO deals_snapshot (deal_id, snapshot_date, fiscal_quarter)
        VALUES ('test_null_constraint', '2099-12-31', NULL);

        RAISE EXCEPTION 'NOT NULL constraint was not added - NULL was accepted';
    EXCEPTION
        WHEN not_null_violation THEN
            RAISE NOTICE '✓ NOT NULL constraint verified - NULL values rejected';
            -- Constraint is working, this is expected
    END;
END $$;
