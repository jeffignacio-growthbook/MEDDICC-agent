#!/usr/bin/env python3
"""Test deal IDs that appear in CSV but not in database."""
from dotenv import load_dotenv
load_dotenv()

import os
import requests

# Deal IDs from CSV that aren't in database
test_ids = [
    "45011789061",
    "55649135254",
    "52224419456",
    "57553779546",
    "42089830026"
]

api_key = os.getenv("HUBSPOT_API_KEY")
if not api_key:
    print("ERROR: HUBSPOT_API_KEY not found")
    exit(1)

headers = {"Authorization": f"Bearer {api_key}"}
properties = "dealname,dealstage,pipeline,archived,hs_is_closed,hs_is_closed_won"

print("Testing 5 deal IDs from CSV that aren't in database:")
print("=" * 70)

for deal_id in test_ids:
    url = f"https://api.hubapi.com/crm/v3/objects/deals/{deal_id}"
    params = {"properties": properties}

    response = requests.get(url, headers=headers, params=params)

    if response.status_code == 404:
        print(f"\n[{deal_id}] 404 NOT FOUND — likely archived")
    elif response.status_code == 200:
        data = response.json()
        props = data.get("properties", {})
        name = props.get("dealname", "N/A")
        stage = props.get("dealstage", "N/A")
        pipeline = props.get("pipeline", "N/A")
        archived = props.get("archived", "false")
        is_closed = props.get("hs_is_closed", "N/A")
        is_won = props.get("hs_is_closed_won", "N/A")

        print(f"\n[{deal_id}] 200 OK — FOUND IN HUBSPOT")
        print(f"  Name: {name}")
        print(f"  Stage: {stage}")
        print(f"  Pipeline: {pipeline}")
        print(f"  Archived: {archived}")
        print(f"  Closed: {is_closed}")
        print(f"  Won: {is_won}")
    else:
        print(f"\n[{deal_id}] {response.status_code} — {response.text[:100]}")

print("\n" + "=" * 70)
