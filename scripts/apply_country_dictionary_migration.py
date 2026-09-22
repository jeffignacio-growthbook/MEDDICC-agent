#!/usr/bin/env python3
"""Apply migration 066: Register company_country and region in data_dictionary."""
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent.parent / "api"))

from dotenv import load_dotenv
load_dotenv(Path(__file__).parent.parent / ".env")

from db import get_supabase

def main():
    sb = get_supabase()

    # Read migration SQL
    migration_sql = (Path(__file__).parent / "migrations" /
                     "066_register_company_country_in_dictionary.sql").read_text()

    print("Applying migration 066: Register company_country in data_dictionary...")

    # Execute via RPC (since postgrest doesn't support raw SQL)
    # We'll do the inserts via the Supabase client directly

    # Insert company_country
    try:
        result1 = sb.table("data_dictionary").upsert({
            "supabase_table": "deals",
            "supabase_column": "company_country",
            "data_type": "text",
            "description": "Company country from HubSpot Company.country property. Populated via one-time enrichment pull from HubSpot. Used for region classification and geographic analysis. Example values: United States, United Kingdom, Germany, India, etc.",
            "is_queryable": True,
            "hubspot_name": "Company.country",
            "source": "hubspot"
        }, on_conflict="supabase_table,supabase_column").execute()
        print("✅ company_country registered")
    except Exception as e:
        print(f"❌ company_country registration failed: {e}")
        return False

    # Insert region
    try:
        result2 = sb.table("data_dictionary").upsert({
            "supabase_table": "deals",
            "supabase_column": "region",
            "data_type": "text",
            "description": "Sales region computed from company_country: NAM (North America), EMEA (Europe/Middle East/Africa), APAC (Asia-Pacific), LATAM (Latin America), ROW (Rest of World), or UNKNOWN (no geography data). Derived from HubSpot Company.country via config/regions.yaml mappings. Use for regional pipeline analysis.",
            "is_queryable": True,
            "enum_values": ["NAM", "EMEA", "APAC", "LATAM", "ROW", "UNKNOWN"],
            "source": "computed"
        }, on_conflict="supabase_table,supabase_column").execute()
        print("✅ region registered")
    except Exception as e:
        print(f"❌ region registration failed: {e}")
        return False

    # Verify
    check = sb.table("data_dictionary").select("supabase_column").eq(
        "supabase_table", "deals"
    ).in_("supabase_column", ["company_country", "region"]).eq(
        "is_queryable", True
    ).execute()

    if len(check.data) == 2:
        print(f"✅ Verification passed: {len(check.data)} columns registered and queryable")
        print("✅ BUG #3 FIX APPLIED: company_country and region now in data_dictionary")
        return True
    else:
        print(f"❌ Verification failed: only {len(check.data)} of 2 columns found")
        return False

if __name__ == "__main__":
    success = main()
    sys.exit(0 if success else 1)
