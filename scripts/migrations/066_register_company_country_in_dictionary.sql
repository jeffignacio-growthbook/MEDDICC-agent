-- Register company_country and region columns in data_dictionary
-- (Bug #3 fix: ensures classifier can see these columns exist)
--
-- Root cause: Commit 3e4b094 documented this registration but executed
-- it via "direct SQL" instead of a migration file, causing test/CI
-- environments to be out of sync with production.
--
-- This migration makes the registration idempotent and portable.

INSERT INTO data_dictionary (
  supabase_table,
  supabase_column,
  data_type,
  description,
  is_queryable,
  enum_values,
  hubspot_name,
  source
) VALUES (
  'deals',
  'company_country',
  'text',
  'Company country from HubSpot Company.country property. Populated via one-time enrichment pull from HubSpot. Used for region classification and geographic analysis. Example values: United States, United Kingdom, Germany, India, etc.',
  true,
  NULL,
  'Company.country',
  'hubspot'
)
ON CONFLICT (supabase_table, supabase_column) DO UPDATE SET
  description = EXCLUDED.description,
  is_queryable = EXCLUDED.is_queryable,
  hubspot_name = EXCLUDED.hubspot_name,
  source = EXCLUDED.source;

INSERT INTO data_dictionary (
  supabase_table,
  supabase_column,
  data_type,
  description,
  is_queryable,
  enum_values,
  hubspot_name,
  source
) VALUES (
  'deals',
  'region',
  'text',
  'Sales region computed from company_country: NAM (North America), EMEA (Europe/Middle East/Africa), APAC (Asia-Pacific), LATAM (Latin America), ROW (Rest of World), or UNKNOWN (no geography data). Derived from HubSpot Company.country via config/regions.yaml mappings. Use for regional pipeline analysis.',
  true,
  ARRAY['NAM', 'EMEA', 'APAC', 'LATAM', 'ROW', 'UNKNOWN'],
  NULL,
  'computed'
)
ON CONFLICT (supabase_table, supabase_column) DO UPDATE SET
  description = EXCLUDED.description,
  is_queryable = EXCLUDED.is_queryable,
  enum_values = EXCLUDED.enum_values,
  source = EXCLUDED.source;

-- Verify registration
DO $$
DECLARE
  country_count INTEGER;
  region_count INTEGER;
BEGIN
  SELECT COUNT(*) INTO country_count
  FROM data_dictionary
  WHERE supabase_table = 'deals'
    AND supabase_column = 'company_country'
    AND is_queryable = true;

  SELECT COUNT(*) INTO region_count
  FROM data_dictionary
  WHERE supabase_table = 'deals'
    AND supabase_column = 'region'
    AND is_queryable = true;

  IF country_count = 0 THEN
    RAISE EXCEPTION 'company_country registration failed';
  END IF;

  IF region_count = 0 THEN
    RAISE EXCEPTION 'region registration failed';
  END IF;

  RAISE NOTICE '✅ company_country and region successfully registered in data_dictionary';
END $$;
