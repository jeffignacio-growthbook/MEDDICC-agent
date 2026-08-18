#!/usr/bin/env python3
"""Check Jake Stangl's recent meetings in HubSpot."""

import os
import sys
import json
import requests
from pathlib import Path
from dotenv import load_dotenv
from datetime import datetime, timedelta

# Load environment variables
env_path = Path(__file__).parent / '.env'
load_dotenv(env_path)

HUBSPOT_API_KEY = os.getenv('HUBSPOT_API_KEY')
JAKE_HUBSPOT_ID = '87573414'

print("\n" + "="*80)
print("JAKE STANGL'S RECENT MEETINGS")
print("="*80)

# Get meetings created in the last 6 months
print(f"\n1. Fetching meetings owned by Jake (ID: {JAKE_HUBSPOT_ID})...")

url = "https://api.hubapi.com/crm/v3/objects/meetings/search"
headers = {
    "Authorization": f"Bearer {HUBSPOT_API_KEY}",
    "Content-Type": "application/json"
}

# Search for meetings owned by Jake
payload = {
    "filterGroups": [
        {
            "filters": [
                {
                    "propertyName": "hubspot_owner_id",
                    "operator": "EQ",
                    "value": JAKE_HUBSPOT_ID
                }
            ]
        }
    ],
    "properties": [
        "hs_meeting_title",
        "hs_meeting_start_time",
        "hs_meeting_end_time",
        "hs_meeting_outcome",
        "hs_meeting_body",
        "hubspot_owner_id",
        "hs_created_by_user_id",
        "hs_createdate",
        "hs_lastmodifieddate"
    ],
    "sorts": [
        {
            "propertyName": "hs_meeting_start_time",
            "direction": "DESCENDING"
        }
    ],
    "limit": 20
}

try:
    response = requests.post(url, headers=headers, json=payload, timeout=30)
    response.raise_for_status()
    data = response.json()
except Exception as e:
    print(f"❌ API Error: {e}")
    sys.exit(1)

meetings = data.get('results', [])
total = data.get('total', 0)

print(f"   Total meetings owned by Jake: {total}")
print(f"   Showing {len(meetings)} most recent")

if not meetings:
    print("\n⚠️  Jake has no meetings in HubSpot")
    print("   Possible reasons:")
    print("   - Jake books meetings but they're owned by AEs after handoff")
    print("   - Meetings are tracked differently (calendar integration not enabled)")
    print("   - Need to filter by hs_created_by_user_id instead of hubspot_owner_id")

    # Try searching by creator instead
    print(f"\n2. Trying hs_created_by_user_id instead...")
    payload["filterGroups"][0]["filters"][0]["propertyName"] = "hs_created_by_user_id"

    response2 = requests.post(url, headers=headers, json=payload, timeout=30)
    response2.raise_for_status()
    data2 = response2.json()

    meetings2 = data2.get('results', [])
    total2 = data2.get('total', 0)

    print(f"   Meetings created by Jake: {total2}")

    if not meetings2:
        print("\n❌ No meetings found by owner OR creator")
        print("   → Meetings ETL will need different approach")
        print("   → Check with Ryan how SDR meetings are logged in HubSpot")
    else:
        print(f"\n✓ Found {len(meetings2)} meetings created by Jake")
        print("\n   Recent meetings:")
        for m in meetings2[:5]:
            props = m.get('properties', {})
            title = props.get('hs_meeting_title', '(no title)')[:40]
            start = props.get('hs_meeting_start_time', '')[:10]
            outcome = props.get('hs_meeting_outcome') or '(no outcome)'
            owner = props.get('hubspot_owner_id', '(no owner)')

            print(f"     {start} | {title:<40} | Owner: {owner} | {outcome}")

        print("\n   → Use hs_created_by_user_id for ETL filtering")
else:
    print("\n✓ Found meetings owned by Jake")
    print("\n   Recent meetings:")
    print(f"   {'Date':<12} {'Title':<40} {'Outcome':<20}")
    print("   " + "-"*75)

    for meeting in meetings[:10]:
        props = meeting.get('properties', {})
        title = props.get('hs_meeting_title', '(no title)')[:38]
        start_time = props.get('hs_meeting_start_time', '')[:10] if props.get('hs_meeting_start_time') else '(no date)'
        outcome = props.get('hs_meeting_outcome') or '(no outcome)'

        print(f"   {start_time:<12} {title:<40} {outcome:<20}")

    # Check outcome population
    outcomes_populated = sum(1 for m in meetings if m.get('properties', {}).get('hs_meeting_outcome'))
    print(f"\n   Outcome field populated: {outcomes_populated}/{len(meetings)} meetings")

    if outcomes_populated == 0:
        print("   ⚠️  hs_meeting_outcome is never populated for Jake's meetings")
        print("   → Show rate cannot be calculated from HubSpot data")
        print("   → Options:")
        print("      1. Accept data gap (meetings_booked only, no meetings_held)")
        print("      2. Use hs_meeting_end_time presence as proxy for 'held'")
        print("      3. Manually track show rate outside HubSpot")

print("\n" + "="*80 + "\n")
