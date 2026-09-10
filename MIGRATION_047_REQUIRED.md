# Migration 047 — APPLIED ✓

## Issue (RESOLVED)

`compute_forecast.py` was failing with:
```
postgrest.exceptions.APIError: {'message': "Could not find the 'historical_conversion_high'
column of 'forecast_weekly' in the schema cache", 'code': 'PGRST204'}
```

## Root Cause

Migration 047 adds historical_conversion columns but hadn't been applied yet.

## Fix

Apply this SQL in Supabase SQL Editor:

```sql
ALTER TABLE forecast_weekly
  ADD COLUMN IF NOT EXISTS historical_conversion_low  NUMERIC DEFAULT 0,
  ADD COLUMN IF NOT EXISTS historical_conversion_mid  NUMERIC DEFAULT 0,
  ADD COLUMN IF NOT EXISTS historical_conversion_high NUMERIC DEFAULT 0;
```

## Steps

1. Go to Supabase Dashboard → SQL Editor
2. Paste the SQL above
3. Run it
4. Re-run `python scripts/analytics/compute_forecast.py` to verify

## Resolution (2026-09-01)

Applied successfully via a direct Postgres connection using
`SUPABASE_DB_URL`, with the password URL-encoded (`!` → `%21`).

**⚠️ 2026-09-11: this section previously contained the literal database
password in plaintext.** It has been removed from this file, but it was
committed to git history on 2026-09-06 and may still be exposed there.
Rotate that database password if it hasn't been rotated since, and see
PENDING_WORK.md for the git-history remediation this still needs.

## Verification

`compute_forecast.py` now runs successfully:
```
✓ Won-deal average: $37,662 (n=222)
✓ FY2027 Q3: hist-conv=$1,793,448 [$1,666,639-$1,902,142]
✓ Wrote 23 forecast rows for 2026-09-01
```

Historical conversion forecast converges with stage-weighted ($1.9M), confirming bias correction works.

## Columns Added

- historical_conversion_low (9.2% rate, FY2027 Q1)
- historical_conversion_mid (9.9% trailing 3Q average)
- historical_conversion_high (10.5% rate, FY2026 Q3)

These are the bias-corrected forecasts from Wave 1 work (use won-deal avg, not pipeline avg).
