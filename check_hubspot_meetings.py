#!/usr/bin/env python3
"""Check HubSpot meeting properties to validate ETL approach."""

import os
import sys
import json
import requests
from pathlib import Path
from dotenv import load_dotenv

# Load environment variables
env_path = Path(__file__).parent / '.env'
load_dotenv(env_path)

HUBSPOT_API_KEY = os.getenv('HUBSPOT_API_KEY')

if not HUBSPOT_API_KEY:
    print("❌ HUBSPOT_API_KEY not found in .env")
    sys.exit(1)

print("\n" + "="*80)
print("HUBSPOT MEETINGS FIELD VALIDATION")
print("="*80)

# 1. Get sample meetings with key properties
print("\n1. Fetching sample meetings...")
url = "https://api.hubapi.com/crm/v3/objects/meetings"
params = {
    "limit": 10,
    "properties": "hs_meeting_title,hs_meeting_start_time,hs_meeting_outcome,hubspot_owner_id,hs_meeting_end_time,hs_created_by_user_id",
    "archived": "false"
}
headers = {"Authorization": f"Bearer {HUBSPOT_API_KEY}"}

try:
    response = requests.get(url, headers=headers, params=params, timeout=30)
    response.raise_for_status()
    data = response.json()
except Exception as e:
    print(f"❌ API Error: {e}")
    sys.exit(1)

meetings = data.get('results', [])
print(f"   Found {len(meetings)} meetings")

if not meetings:
    print("\n⚠️  No meetings found - may need to adjust filters or check HubSpot data")
    sys.exit(0)

# 2. Analyze meeting owner patterns
print("\n2. Meeting owner analysis:")
print(f"   {'Date':<12} {'Outcome':<20} {'Owner ID':<15} {'Created By':<15}")
print("   " + "-"*70)

owner_ids = set()
outcomes = set()
created_by_ids = set()

for meeting in meetings:
    props = meeting.get('properties', {})
    start_time = props.get('hs_meeting_start_time', '')[:10] if props.get('hs_meeting_start_time') else '(no date)'
    outcome = props.get('hs_meeting_outcome') or '(no outcome)'
    owner_id = props.get('hubspot_owner_id') or '(no owner)'
    created_by = props.get('hs_created_by_user_id') or '(no creator)'

    print(f"   {start_time:<12} {outcome[:18]:<20} {str(owner_id):<15} {str(created_by):<15}")

    if props.get('hubspot_owner_id'):
        owner_ids.add(props.get('hubspot_owner_id'))
    if props.get('hs_meeting_outcome'):
        outcomes.add(props.get('hs_meeting_outcome'))
    if props.get('hs_created_by_user_id'):
        created_by_ids.add(props.get('hs_created_by_user_id'))

# 3. Summary of field usage
print("\n3. Field usage summary:")
print(f"   Unique owner IDs: {len(owner_ids)}")
print(f"   Unique outcomes: {len(outcomes)}")
print(f"   Unique creators: {len(created_by_ids)}")

if outcomes:
    print(f"\n   Outcome values found:")
    for outcome in sorted(outcomes):
        count = sum(1 for m in meetings if m.get('properties', {}).get('hs_meeting_outcome') == outcome)
        print(f"     - {outcome}: {count} meetings")
else:
    print(f"\n   ⚠️  No hs_meeting_outcome values populated")
    print(f"   → Show rate cannot be calculated without outcome data")

# 4. Check if Jake's user ID appears
print("\n4. Looking for Jake Stangl's HubSpot user ID...")
# We need to get HubSpot users to find Jake's ID
users_url = "https://api.hubapi.com/settings/v3/users"
try:
    users_response = requests.get(users_url, headers=headers, timeout=30)
    users_response.raise_for_status()
    users_data = users_response.json()

    jake_user = None
    for user in users_data.get('results', []):
        email = user.get('email', '').lower()
        if 'jake' in email and 'stangl' in email:
            jake_user = user
            break

    if jake_user:
        jake_id = jake_user.get('id')
        jake_email = jake_user.get('email')
        print(f"   ✓ Found: {jake_user.get('firstName')} {jake_user.get('lastName')}")
        print(f"     Email: {jake_email}")
        print(f"     HubSpot User ID: {jake_id}")

        # Check if Jake appears in owner_ids or created_by_ids
        if str(jake_id) in [str(oid) for oid in owner_ids]:
            print(f"   ✓ Jake appears as hubspot_owner_id in sample meetings")
        else:
            print(f"   ⚠️  Jake does NOT appear as owner in these {len(meetings)} sample meetings")

        if str(jake_id) in [str(cid) for cid in created_by_ids]:
            print(f"   ✓ Jake appears as hs_created_by_user_id in sample meetings")
        else:
            print(f"   ⚠️  Jake does NOT appear as creator in these {len(meetings)} sample meetings")
    else:
        print(f"   ✗ Jake Stangl not found in HubSpot users")

except Exception as e:
    print(f"   Error fetching users: {e}")

print("\n" + "="*80)
print("CONCLUSIONS:")
print("="*80)

if outcomes:
    print("✓ hs_meeting_outcome is populated → show rate calculable")
else:
    print("✗ hs_meeting_outcome NOT populated → show rate NOT calculable")
    print("  → Need to use alternative field or accept data gap")

if owner_ids:
    print("✓ hubspot_owner_id is populated → can filter by owner")
    print(f"  → Use hubspot_owner_id = {jake_id if jake_user else 'Jake_ID'} to get Jake's meetings")
else:
    print("✗ hubspot_owner_id NOT populated → cannot filter by owner")
    print("  → Need to use hs_created_by_user_id or associations")

print("\n" + "="*80 + "\n")
