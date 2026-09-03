-- ETL failure tracking table
-- Records every ETL job failure to enable alerting on consecutive failures

CREATE TABLE IF NOT EXISTS etl_failures (
    id BIGSERIAL PRIMARY KEY,
    job_name TEXT NOT NULL,
    run_id TEXT NOT NULL,
    failed_at TIMESTAMPTZ DEFAULT NOW(),
    consecutive_count INTEGER DEFAULT 1,
    created_at TIMESTAMPTZ DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_etl_failures_job_time
    ON etl_failures(job_name, failed_at DESC);

COMMENT ON TABLE etl_failures IS
'Records ETL job failures. Alert sent when consecutive_count >= 2.
Catches silent failures like the Aug 7 calls ETL breakdown that went
unnoticed for 4 weeks.';

COMMENT ON COLUMN etl_failures.consecutive_count IS
'How many consecutive failures for this job. Resets on success.';
