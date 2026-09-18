#!/usr/bin/env python3
"""Investigate the 3 missing deals and 1 extra deal."""
from dotenv import load_dotenv
load_dotenv()

import os
import requests
from supabase import create_client

api_key = os.getenv("HUBSPOT_API_KEY")
supabase_url = os.getenv("SUPABASE_URL")
supabase_key = os.getenv("SUPABASE_SERVICE_KEY")

headers = {"Authorization": f"Bearer {api_key}"}
supabase = create_client(supabase_url, supabase_key)

missing_in_db = ["64133406245", "64138563750", "64279365540"]
extra_in_db = ["29591984407"]

print("=" * 70)
print("MISSING IN DB (3 deals in API but not in database):")
print("=" * 70)

for deal_id in missing_in_db:
    url = f"https://api.hubapi.com/crm/v3/objects/deals/{deal_id}"
    params = {"properties": "dealname,pipeline,dealstage,createdate,closedate,hs_is_closed"}

    response = requests.get(url, headers=headers, params=params)

    if response.status_code == 200:
        data = response.json()
        props = data.get("properties", {})
        print(f"\n[{deal_id}] HubSpot API shows:")
        print(f"  Name: {props.get('dealname', 'N/A')}")
        print(f"  Pipeline: {props.get('pipeline', 'N/A')}")
        print(f"  Stage: {props.get('dealstage', 'N/A')}")
        print(f"  Created: {props.get('createdate', 'N/A')}")
        print(f"  Close Date: {props.get('closedate', 'N/A')}")
        print(f"  Is Closed: {props.get('hs_is_closed', 'N/A')}")
    else:
        print(f"\n[{deal_id}] API error: {response.status_code}")

print("\n" + "=" * 70)
print("EXTRA IN DB (1 deal in database but not in current API renewal query):")
print("=" * 70)

for deal_id in extra_in_db:
    # Check database
    db_response = supabase.table("deals") \
        .select("deal_id,company_name,pipeline_id,stage,updated_at") \
        .eq("deal_id", deal_id) \
        .execute()

    if db_response.data:
        db_deal = db_response.data[0]
        print(f"\n[{deal_id}] Database shows:")
        print(f"  Company: {db_deal.get('company_name', 'N/A')}")
        print(f"  Pipeline: {db_deal.get('pipeline_id', 'N/A')}")
        print(f"  Stage: {db_deal.get('stage', 'N/A')}")
        print(f"  Updated: {db_deal.get('updated_at', 'N/A')}")

    # Check HubSpot current state
    url = f"https://api.hubapi.com/crm/v3/objects/deals/{deal_id}"
    params = {"properties": "dealname,pipeline,dealstage,hs_is_closed"}

    response = requests.get(url, headers=headers, params=params)

    if response.status_code == 200:
        data = response.json()
        props = data.get("properties", {})
        print(f"\n  HubSpot current state:")
        print(f"    Name: {props.get('dealname', 'N/A')}")
        print(f"    Pipeline: {props.get('pipeline', 'N/A')}")
        print(f"    Stage: {props.get('dealstage', 'N/A')}")
        print(f"    Is Closed: {props.get('hs_is_closed', 'N/A')}")
    else:
        print(f"\n  HubSpot API: {response.status_code} - likely deleted")

print("\n" + "=" * 70)
