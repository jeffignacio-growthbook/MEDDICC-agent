-- Add missing columns to calls table
--
-- The competitors_mentioned column was in 001_initial_schema.sql but
-- is missing from the actual table, causing PGRST204 errors in daily ETL.

-- Add competitors_mentioned if it doesn't exist
DO $$
BEGIN
    IF NOT EXISTS (
        SELECT 1 FROM information_schema.columns
        WHERE table_name = 'calls' AND column_name = 'competitors_mentioned'
    ) THEN
        ALTER TABLE calls ADD COLUMN competitors_mentioned TEXT;
        COMMENT ON COLUMN calls.competitors_mentioned IS 'Comma-separated list of competitors mentioned in call';
    END IF;
END $$;
