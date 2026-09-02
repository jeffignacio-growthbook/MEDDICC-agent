# Migration 047 Required

## Issue

`compute_forecast.py` fails with:
```
postgrest.exceptions.APIError: {'message': "Could not find the 'historical_conversion_high'
column of 'forecast_weekly' in the schema cache", 'code': 'PGRST204'}
```

## Root Cause

Migration 047 adds historical_conversion columns but hasn't been applied yet.

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

## Why Manual

Direct psycopg2 connection fails due to special characters in database password.
The `!` needs URL encoding (%21) but the .env format doesn't support that.

## After Applying

Once migration is applied, compute_forecast.py will write the full forecast range:
- historical_conversion_low (9.2% rate)
- historical_conversion_mid (9.9% trailing average)
- historical_conversion_high (10.5% rate)

These are the bias-corrected forecasts from Wave 1 work.
