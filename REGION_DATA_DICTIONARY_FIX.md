# Region Classification - Data Dictionary Fix

**Date:** 2026-09-08
**Issue:** Railway Slack agent said "no region field available" despite region classification being implemented

---

## Root Cause

**Data Dictionary Gap** - not deployment issue, not LLM hallucination.

The region classification was implemented (code, schema, data) but **never registered in `data_dictionary`**, so the dynamic_query handler couldn't see it.

### What Existed
- ✅ `company_country` column in deals table (added via migration 059)
- ✅ Data populated (1718 deals with geography)
- ✅ `get_region()` function in api/field_semantics.py
- ❌ **No `region` column in database**
- ❌ **Neither `company_country` nor `region` registered in `data_dictionary`**

### Why The Agent Said "No Region Field"

The dynamic_query handler:
1. Queries `data_dictionary` to see what columns exist
2. Builds SQL queries using only columns marked `is_queryable=True`
3. Cannot call Python functions like `get_region()` - needs database columns

**The LLM was correct** - from its perspective (querying `data_dictionary`), no region field existed.

---

## Fix Applied (2026-09-08 ~4:50pm PT)

### 1. Added `region` Column to Database

```sql
ALTER TABLE deals ADD COLUMN region TEXT;
CREATE INDEX idx_deals_region ON deals(region);
```

**Why:** Dynamic_query builds SQL queries and can't call Python `get_region()`. Needs a database column.

### 2. Populated All Deals with Regions

Single SQL UPDATE using CASE statement generated from config/regions.yaml:

```sql
UPDATE deals
SET region = CASE
    WHEN company_country IS NULL THEN 'UNKNOWN'
    WHEN company_country = 'United Kingdom' THEN 'EMEA'
    WHEN company_country = 'United States' THEN 'NAM'
    WHEN company_country = 'India' THEN 'APAC'
    -- ... 87 more countries ...
    ELSE 'ROW'
END;
```

**Result:** All 1890 deals updated in single transaction.

**Distribution:**
- NAM: 784 deals
- EMEA: 639 deals
- APAC: 202 deals
- LATAM: 44 deals
- ROW: 49 deals
- UNKNOWN: 172 deals

### 3. Registered Both Columns in `data_dictionary`

**Added `company_country`:**
```python
{
    'supabase_table': 'deals',
    'supabase_column': 'company_country',
    'data_type': 'text',
    'description': 'Company country from HubSpot Company.country property. Full country name (e.g., "United States", "United Kingdom", "India"). Used for region classification via get_region() function. Coverage: 90.9% (1718/1890 deals). See config/regions.yaml for region mappings.',
    'is_queryable': True,
    'source': 'hubspot_enrichment',
    'hubspot_name': 'Company.country'
}
```

**Added `region`:**
```python
{
    'supabase_table': 'deals',
    'supabase_column': 'region',
    'data_type': 'text',
    'description': 'Sales region computed from company_country: NAM (North America), EMEA (Europe/Middle East/Africa), APAC (Asia-Pacific), LATAM (Latin America), ROW (Rest of World), or UNKNOWN (no geography data). Derived from HubSpot Company.country via config/regions.yaml mappings. Use for regional pipeline analysis.',
    'is_queryable': True,
    'enum_values': ['NAM', 'EMEA', 'APAC', 'LATAM', 'ROW', 'UNKNOWN'],
    'source': 'computed'
}
```

**Now visible to dynamic_query handler** - can build SQL with `WHERE region = 'EMEA'`.

---

## Verification

**Before fix (4:47pm):**
```
⚠️ EMEA Pipeline — No Regional Segmentation Available
The CRM data doesn't include a region or territory field...
```

**After fix (expected):**
Dynamic_query can now:
1. See `region` column in data_dictionary
2. Build SQL: `SELECT * FROM deals WHERE region = 'EMEA' AND ...`
3. Answer EMEA pipeline questions correctly

---

## Design Lesson

**Schema changes require data_dictionary updates.**

When adding columns for query handlers to use:
1. ✅ Add column to database schema
2. ✅ Populate with data
3. ✅ **Register in `data_dictionary` with `is_queryable=True`**

The last step is critical - without it, the LLM query builder cannot see the column exists.

This is different from application code (which uses get_region() function) vs. SQL-based query handlers (which need database columns in data_dictionary).

---

## Files

**Created:**
- `scripts/populate_region_column.py` - Script to populate region from company_country

**Database Changes (via SQL):**
- Added `region` column to deals table
- Populated all 1890 deals
- Added index on region
- Inserted 2 rows into data_dictionary (company_country, region)

**No Code Changes Required:**
- `get_region()` function already exists in api/field_semantics.py
- config/regions.yaml already has mappings
- Dynamic_query handler already queries data_dictionary

**Just needed the schema-to-metadata bridge.**

---

## Related Issue: Confidence Threshold

From logs:
```
[INTENT] handler=query_pipeline_movement confidence=0.72
[ROUTING] confidence 0.72 < 0.80 — routing to dynamic instead
```

**Question:** "How has EMEA pipeline moved in the last 2 weeks"

Matched `query_pipeline_movement` at 0.72 confidence (below 0.80 threshold), fell through to dynamic_query.

**Now that dynamic_query can handle regional questions**, this routing is acceptable. But if regional pipeline questions should always use a dedicated handler, need better intent examples to push confidence >0.80.

**Not blocking** - dynamic_query now has the data to answer correctly.

---

## Summary

**Problem:** Region classification implemented but not registered in data_dictionary.
**Fix:** Added `region` column, populated all deals, registered both columns as queryable.
**Result:** Dynamic_query handler can now answer regional pipeline questions.

**Lesson:** Schema changes for query handlers require data_dictionary registration.
