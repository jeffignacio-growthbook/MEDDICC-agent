#!/usr/bin/env python3
"""Check if incremental_arr exists as a HubSpot property."""
from dotenv import load_dotenv
load_dotenv()

import os
import requests

api_key = os.getenv("HUBSPOT_API_KEY")
if not api_key:
    print("ERROR: HUBSPOT_API_KEY not found")
    exit(1)

headers = {"Authorization": f"Bearer {api_key}"}
url = "https://api.hubapi.com/crm/v3/properties/deals"

response = requests.get(url, headers=headers)

if response.status_code != 200:
    print(f"ERROR: {response.status_code} - {response.text}")
    exit(1)

data = response.json()
properties = data.get('results', [])

# Search for incremental
incremental_props = [
    p for p in properties
    if 'incremental' in p['name'].lower() or 'incremental' in p.get('label', '').lower()
]

print(f"Found {len(incremental_props)} properties matching 'incremental':")
print("=" * 70)

for p in incremental_props:
    print(f"\nName: {p['name']}")
    print(f"Label: {p.get('label', 'N/A')}")
    print(f"Type: {p.get('type', 'N/A')}")
    print(f"Field Type: {p.get('fieldType', 'N/A')}")
    if p.get('description'):
        print(f"Description: {p['description'][:100]}")

if not incremental_props:
    print("No properties found matching 'incremental'")
    print("\nSearching for 'arr' properties instead:")
    arr_props = [p for p in properties if 'arr' in p['name'].lower()]
    print(f"\nFound {len(arr_props)} properties with 'arr' in name:")
    for p in arr_props[:10]:
        print(f"  {p['name']:40} | {p.get('label', 'N/A')}")
