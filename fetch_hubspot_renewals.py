#!/usr/bin/env python3
"""Fetch all renewal pipeline deals directly from HubSpot API."""
from dotenv import load_dotenv
load_dotenv()

import os
import requests
import json

api_key = os.getenv("HUBSPOT_API_KEY")
if not api_key:
    print("ERROR: HUBSPOT_API_KEY not found")
    exit(1)

headers = {"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"}

# Search for all renewal pipeline deals
url = "https://api.hubapi.com/crm/v3/objects/deals/search"

payload = {
    "filterGroups": [{
        "filters": [{
            "propertyName": "pipeline",
            "operator": "EQ",
            "value": "866608541"
        }]
    }],
    "properties": ["dealname", "dealstage", "pipeline", "hs_is_closed", "hs_is_closed_won"],
    "limit": 100
}

all_deals = []
after = None

print("Fetching all renewal pipeline (866608541) deals from HubSpot...")
print("=" * 70)

while True:
    if after:
        payload["after"] = after

    response = requests.post(url, headers=headers, json=payload)

    if response.status_code != 200:
        print(f"ERROR: {response.status_code} - {response.text}")
        break

    data = response.json()
    results = data.get("results", [])
    all_deals.extend(results)

    print(f"Fetched {len(all_deals)} deals so far...")

    paging = data.get("paging", {})
    after = paging.get("next", {}).get("after")

    if not after:
        break

print("\n" + "=" * 70)
print(f"Total renewal pipeline deals from HubSpot API: {len(all_deals)}")

# Write to file
with open("/tmp/api_renewal_deals.txt", "w") as f:
    for deal in all_deals:
        f.write(f"{deal['id']}\n")

with open("/tmp/api_renewal_deals.json", "w") as f:
    json.dump(all_deals, f, indent=2)

print(f"Wrote {len(all_deals)} deal IDs to /tmp/api_renewal_deals.txt")
print(f"Wrote full data to /tmp/api_renewal_deals.json")

# Show breakdown
closed = sum(1 for d in all_deals if d.get("properties", {}).get("hs_is_closed") == "true")
won = sum(1 for d in all_deals if d.get("properties", {}).get("hs_is_closed_won") == "true")
active = len(all_deals) - closed

print(f"\nBreakdown:")
print(f"  Active: {active}")
print(f"  Closed Won: {won}")
print(f"  Closed Lost: {closed - won}")
