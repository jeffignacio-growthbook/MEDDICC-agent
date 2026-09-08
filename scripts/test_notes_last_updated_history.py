#!/usr/bin/env python3
"""
Test if HubSpot API can fetch notes_last_updated property history
"""
import os
import sys
import requests
from pathlib import Path
from dotenv import load_dotenv

# Load environment
env_path = Path(__file__).parent.parent / ".env"
load_dotenv(env_path)

HUBSPOT_API_KEY = os.getenv('HUBSPOT_API_KEY')
if not HUBSPOT_API_KEY:
    print("❌ HUBSPOT_API_KEY not set")
    sys.exit(1)

# Add scripts to path for database access
sys.path.insert(0, str(Path(__file__).parent.parent / 'api'))
from db import get_supabase

sb = get_supabase()

# Get a sample deal ID
result = sb.table('deals').select('deal_id,company_name,stage').limit(5).execute()
if not result.data:
    print("❌ No deals found")
    sys.exit(1)

print("=" * 80)
print("TESTING HUBSPOT PROPERTY HISTORY API: notes_last_updated")
print("=" * 80)
print()

for deal in result.data[:3]:  # Test first 3 deals
    deal_id = deal['deal_id']
    company_name = deal['company_name'] or 'Unknown'
    stage = deal['stage']

    print(f"Deal: {deal_id} - {company_name} (stage: {stage})")
    print()

    # Test fetching notes_last_updated with history
    url = f"https://api.hubapi.com/crm/v3/objects/deals/{deal_id}"
    params = {
        'properties': 'notes_last_updated,dealstage',
        'propertiesWithHistory': 'notes_last_updated,dealstage'
    }
    headers = {
        'Authorization': f'Bearer {HUBSPOT_API_KEY}',
        'Content-Type': 'application/json'
    }

    try:
        response = requests.get(url, params=params, headers=headers, timeout=10)

        if response.status_code == 200:
            data = response.json()

            # Check current properties
            props = data.get('properties', {})
            current_nlu = props.get('notes_last_updated')
            current_stage = props.get('dealstage')

            print(f"  Current notes_last_updated: {current_nlu}")
            print(f"  Current dealstage: {current_stage}")
            print()

            # Check property history
            history = data.get('propertiesWithHistory', {})

            if 'notes_last_updated' in history:
                nlu_history = history['notes_last_updated']
                print(f"  ✅ notes_last_updated history: {len(nlu_history)} changes")
                print()
                print("     Recent changes (up to 5):")
                for i, change in enumerate(nlu_history[:5]):
                    timestamp = change.get('timestamp')
                    value = change.get('value')
                    source_type = change.get('sourceType', 'unknown')
                    print(f"       {i+1}. {timestamp}: {value} (source: {source_type})")
            else:
                print(f"  ❌ notes_last_updated history NOT in response")
                print(f"     Available history fields: {list(history.keys())}")

            # Check dealstage history for comparison
            if 'dealstage' in history:
                stage_history = history['dealstage']
                print()
                print(f"  ✅ dealstage history: {len(stage_history)} changes (for comparison)")

            print()
            print("-" * 80)
            print()

        elif response.status_code == 401:
            print(f"  ❌ Authentication failed - check HUBSPOT_API_KEY")
            break
        else:
            print(f"  ❌ API request failed: {response.status_code}")
            print(f"     Response: {response.text[:200]}")
            print()

    except requests.exceptions.RequestException as e:
        print(f"  ❌ Request error: {e}")
        print()
        continue

print("=" * 80)
print("TEST COMPLETE")
print("=" * 80)
