#!/usr/bin/env python3
"""Check which MEDDICC properties exist in HubSpot."""
import os
import sys
import requests
from pathlib import Path

HUBSPOT_API_KEY = os.getenv('HUBSPOT_API_KEY')
if not HUBSPOT_API_KEY:
    print("ERROR: HUBSPOT_API_KEY not set")
    sys.exit(1)

headers = {
    "Authorization": f"Bearer {HUBSPOT_API_KEY}",
    "Content-Type": "application/json"
}

# Get all deal properties
url = "https://api.hubapi.com/crm/v3/properties/deals"
response = requests.get(url, headers=headers, timeout=30)
response.raise_for_status()
all_props = response.json()

# Filter for MEDDICC properties
meddicc_props = [p for p in all_props['results'] if 'meddicc' in p['name']]

print("MEDDICC Properties Found in HubSpot:")
print("=" * 70)
for prop in sorted(meddicc_props, key=lambda x: x['name']):
    print(f"  {prop['name']:45s} | {prop['type']:10s} | {prop.get('fieldType', 'N/A')}")

print()
print(f"Total MEDDICC properties: {len(meddicc_props)}")
print()

# Check for specific component properties we expect
components = ['metrics', 'economic_buyer', 'decision_criteria', 'decision_process', 'pain', 'champion', 'competition']
print("Checking for component score properties:")
print("=" * 70)
for comp in components:
    score_prop = f"meddicc_{comp}_score"
    status_prop = f"meddicc_{comp}_status"
    rationale_prop = f"meddicc_{comp}_rationale"

    score_exists = any(p['name'] == score_prop for p in meddicc_props)
    status_exists = any(p['name'] == status_prop for p in meddicc_props)
    rationale_exists = any(p['name'] == rationale_prop for p in meddicc_props)

    status_str = "✓" if (score_exists and status_exists and rationale_exists) else "✗"
    print(f"{status_str} {comp:20s}: score={score_exists}, status={status_exists}, rationale={rationale_exists}")
