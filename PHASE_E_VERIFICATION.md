# Phase E Enrichment - Verification Steps

## ⚠️ JEFF: Run migration 008 in SQL Editor FIRST

Before any Python code runs, execute `scripts/migrations/008_add_enrichment_tables.sql`
in the Supabase SQL editor.

### Step 1: Run Migration

Copy and paste the contents of `scripts/migrations/008_add_enrichment_tables.sql` into
the SQL editor and execute.

### Step 2: Verify Schema

Run these queries in SQL editor:

```sql
-- Verify feature_gaps table exists
SELECT column_name FROM information_schema.columns
WHERE table_name = 'feature_gaps'
ORDER BY ordinal_position;

-- Verify objections table extensions
SELECT column_name FROM information_schema.columns
WHERE table_name = 'objections'
AND column_name IN ('category','verbatim_quote','deal_id','company_name','extracted_at')
ORDER BY column_name;

-- Verify calls table dedup columns
SELECT column_name FROM information_schema.columns
WHERE table_name = 'calls'
AND column_name IN ('objections_scanned_at','feature_gaps_scanned_at')
ORDER BY column_name;
```

Expected output:
- feature_gaps: All columns from migration should be present
- objections: Should show all 5 columns listed
- calls: Should show both timestamp columns

### Step 3: Refresh PostgREST Schema Cache

```sql
SELECT pg_notify('pgrst', 'reload schema');
```

### Step 4: Verify PostgREST Sees New Tables

Test via curl (or similar):

```bash
curl -X PATCH \
  -H "apikey: YOUR_SUPABASE_KEY" \
  -H "Authorization: Bearer YOUR_SUPABASE_KEY" \
  -H "Content-Type: application/json" \
  -d '{"id": 9999999}' \
  "https://htgvkqycrwesdysustxd.supabase.co/rest/v1/feature_gaps?id=eq.9999999"
```

Should return error about no matching row (NOT "table not found" or "column not found").

## After Migration is Verified

### Step 5: Dry-Run Both Scripts

```bash
# Test objections extraction
python scripts/enrichment/extract_objections.py --dry-run

# Test feature gaps extraction
python scripts/enrichment/extract_feature_gaps.py --dry-run
```

Expected: List of calls that would be scanned, with cost estimate.

### Step 6: Run Both Scripts with --limit 5

```bash
# Extract objections from 5 calls
python scripts/enrichment/extract_objections.py --limit 5 --yes

# Extract feature gaps from 5 calls
python scripts/enrichment/extract_feature_gaps.py --limit 5 --yes
```

### Step 7: Verify Data Written

```sql
-- Check objections
SELECT category, count(*)
FROM objections
GROUP BY category
ORDER BY count DESC;

-- Check feature gaps
SELECT category, count(*)
FROM feature_gaps
GROUP BY category
ORDER BY count DESC;

-- Verify dedup stamps
SELECT COUNT(*) as scanned_for_objections
FROM calls
WHERE objections_scanned_at IS NOT NULL;

SELECT COUNT(*) as scanned_for_feature_gaps
FROM calls
WHERE feature_gaps_scanned_at IS NOT NULL;
```

## Status Checklist

- [ ] Migration 008 run in SQL editor
- [ ] Schema verified via information_schema queries
- [ ] PostgREST schema cache refreshed
- [ ] PostgREST PATCH test passed
- [ ] Both scripts pass --dry-run
- [ ] Both scripts run successfully with --limit 5
- [ ] Data verified in objections and feature_gaps tables
- [ ] Dedup timestamps confirmed in calls table
- [ ] Ready to commit and push to phase-e-enrichment branch
