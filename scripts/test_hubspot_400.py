#!/usr/bin/env python3
"""Test HubSpot component scores API call to get actual 400 response body."""
import os
import sys
import requests
from pathlib import Path

REPO_ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(REPO_ROOT / 'scripts'))

HUBSPOT_API_KEY = os.getenv('HUBSPOT_API_KEY')
if not HUBSPOT_API_KEY:
    print("ERROR: HUBSPOT_API_KEY not set")
    sys.exit(1)

# Test with one of the failing deal IDs from the log
deal_id = "60868340629"  # mountain deal that failed

# Prepare component scores payload (mimicking what write_component_scores does)
# Test with identified_pain (the corrected key)
test_properties = {
    "meddicc_identified_pain_score": "8",
    "meddicc_identified_pain_status": "identified",
    "meddicc_identified_pain_rationale": "Test: Slow experimentation blocking product velocity"
}

url = f"https://api.hubapi.com/crm/v3/objects/deals/{deal_id}"
headers = {
    "Authorization": f"Bearer {HUBSPOT_API_KEY}",
    "Content-Type": "application/json"
}
payload = {"properties": test_properties}

print(f"Testing HubSpot API call to deal {deal_id}")
print(f"URL: {url}")
print(f"Payload: {payload}")
print()

response = requests.patch(url, headers=headers, json=payload, timeout=30)

print(f"Status Code: {response.status_code}")
print(f"Response Headers: {dict(response.headers)}")
print()
print("Response Body:")
print(response.text)
print()

if response.status_code != 200:
    print("ERROR: Request failed")
    print(f"Reason: {response.reason}")
