#!/usr/bin/env python3
"""Compare renewal population between deals and deals_snapshot."""
from dotenv import load_dotenv
load_dotenv()

import os
from supabase import create_client

supabase_url = os.getenv("SUPABASE_URL")
supabase_key = os.getenv("SUPABASE_SERVICE_KEY")

supabase = create_client(supabase_url, supabase_key)

# Count renewal deals in deals table
deals_response = supabase.table("deals") \
    .select("deal_id", count="exact") \
    .eq("pipeline_id", "866608541") \
    .execute()

deals_count = deals_response.count

# Count renewal deals in deals_snapshot (latest snapshot)
snapshot_response = supabase.table("deals_snapshot") \
    .select("snapshot_date", count="exact") \
    .order("snapshot_date", desc=True) \
    .limit(1) \
    .execute()

latest_snapshot_date = snapshot_response.data[0]['snapshot_date'] if snapshot_response.data else None

if latest_snapshot_date:
    snapshot_deals_response = supabase.table("deals_snapshot") \
        .select("deal_id", count="exact") \
        .eq("snapshot_date", latest_snapshot_date) \
        .eq("pipeline_id", "866608541") \
        .execute()

    snapshot_count = snapshot_deals_response.count

    print(f"Renewal pipeline (866608541) population comparison:")
    print("=" * 70)
    print(f"deals table:                {deals_count:3} renewal deals")
    print(f"deals_snapshot ({latest_snapshot_date}): {snapshot_count:3} renewal deals")
    print(f"Difference:                 {abs(deals_count - snapshot_count):3} deals")
    print("=" * 70)

    if deals_count == snapshot_count:
        print("✓ Population agreement: deals and deals_snapshot match")
    else:
        print(f"⚠ Population mismatch: {deals_count - snapshot_count:+d} deals")
        print(f"  Note: deals table has all deals (active + closed)")
        print(f"  Note: deals_snapshot has only open deals (qualified pipeline)")
else:
    print("ERROR: No snapshots found")
