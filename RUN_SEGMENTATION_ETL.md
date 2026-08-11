# Load Segmentation Data - Quick Start

## Problem
The batch associations API is returning 0 results, but the CSV files work perfectly (88% employee count coverage).

## Solution
Run the ETL once with your local CSV files and Supabase credentials.

## One-Time Setup (2 minutes)

### Step 1: Get Supabase credentials

```bash
# View secrets in browser
gh browse --settings

# Or visit: https://github.com/jeffignacio-growthbook/MEDDICC-agent/settings/secrets/actions
```

### Step 2: Run the ETL

```bash
# Set credentials (get actual values from GitHub secrets page)
export SUPABASE_URL="your-supabase-url-here"
export SUPABASE_SERVICE_KEY="your-service-key-here"

# Run ETL with CSV files (takes ~5 seconds)
python scripts/etl_deals.py \
  --mode analytics \
  --file "/Users/jeffignacio/Downloads/all-deals.csv" \
  --companies-file "/Users/jeffignacio/Downloads/all-companies.csv"

# Query results
python scripts/query_segments_simple.py
```

## Alternative: Use the shell script

```bash
# Set credentials first
export SUPABASE_URL="your-url"
export SUPABASE_SERVICE_KEY="your-key"

# Run everything
./scripts/load_segments.sh
```

## Expected Results

After running, you should see:

```
Segment Distribution (Active Deals)
====================================================================
Segment            Count     Total Value    Avg Value
--------------------------------------------------------------------
SMB                 XXX $    X,XXX,XXX $     XX,XXX
Mid-Market          XXX $    X,XXX,XXX $     XX,XXX
Enterprise          XXX $    X,XXX,XXX $     XX,XXX
Unknown             XXX $    X,XXX,XXX $     XX,XXX  (should be ~12%)
--------------------------------------------------------------------
```

## What This Does

1. Loads 1,557 deals from your CSV export
2. Joins with 1,224 companies
3. Calculates segments based on employee count:
   - SMB: ≤250 employees
   - Mid-Market: 251-2,000 employees
   - Enterprise: 2,001+ employees
   - Unknown: no employee data (~12% based on CSV coverage)
4. Writes segmentation data to Supabase:
   - company_id
   - company_employee_count
   - segment
5. Queries and displays the distribution

## Files Created

- `scripts/load_segments.sh` - Wrapper script
- `scripts/query_segments_simple.py` - Query tool
- `scripts/run_csv_etl_interactive.py` - Interactive version if you prefer prompts

## Next Steps

Once this completes successfully with real segment distribution (not 100% Unknown):
- Task 3 is complete ✓
- Ready to proceed to Task 4: compute_pipeline_generation.py
