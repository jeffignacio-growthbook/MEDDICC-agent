#!/usr/bin/env python3
"""Check if prior_arr is available for renewal deals."""
from dotenv import load_dotenv
load_dotenv()

import os
from supabase import create_client

supabase_url = os.getenv("SUPABASE_URL")
supabase_key = os.getenv("SUPABASE_SERVICE_KEY")

supabase = create_client(supabase_url, supabase_key)

# Check if prior_arr column exists in deals table
try:
    response = supabase.table("deals") \
        .select("deal_id,company_name,pipeline_id,arr_usd") \
        .eq("pipeline_id", "866608541") \
        .limit(10) \
        .execute()

    print("Available columns in query:")
    if response.data:
        print(f"  {list(response.data[0].keys())}")

    # Try with prior_arr
    response_with_prior = supabase.table("deals") \
        .select("deal_id,company_name,arr_usd,renewal_revenue") \
        .eq("pipeline_id", "866608541") \
        .limit(10) \
        .execute()

    print("\nWith renewal_revenue:")
    if response_with_prior.data:
        print(f"  {list(response_with_prior.data[0].keys())}")

except Exception as e:
    print(f"Error querying deals: {e}")

# Check schema directly
print("\nChecking deals table schema for prior_arr or baseline fields...")
print("Looking in migrations for prior_arr, baseline_arr, or similar...")
