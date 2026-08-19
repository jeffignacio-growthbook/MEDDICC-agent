#!/usr/bin/env python3
"""Test call recording matching logic."""

from pathlib import Path
from dotenv import load_dotenv
load_dotenv(Path.cwd() / '.env')

import sys
sys.path.insert(0, str(Path.cwd()))
from api.db import get_supabase

sb = get_supabase()

# Test meeting: "Demo Call with aolei huang from" on 2026-08-17
test_meeting = {
    'properties': {
        'hs_meeting_title': 'Demo Call with aolei huang from',
        'hs_meeting_start_time': '2026-08-17T14:00:00Z',
        'hubspot_owner_id': '87573414'
    }
}

# Import extraction function
sys.path.insert(0, str(Path.cwd() / 'scripts'))
from etl_meetings import extract_company_from_title, match_call_recording

owner_email = 'jake.stangl@growthbook.io'

print("\nTest Meeting:")
print(f"  Title: {test_meeting['properties']['hs_meeting_title']}")
print(f"  Date: {test_meeting['properties']['hs_meeting_start_time'][:10]}")

# Test company extraction
company = extract_company_from_title(test_meeting['properties']['hs_meeting_title'])
print(f"\nExtracted company: '{company}'")

# Test call recording match
match = match_call_recording(test_meeting, owner_email, sb)

if match:
    print(f"\n✓ Match found:")
    print(f"  Call ID: {match.get('call_id')}")
    print(f"  Title: {match.get('title')}")
    print(f"  Company: {match.get('company_name')}")
    print(f"  Date: {match.get('call_date')}")
else:
    print("\n✗ No match found")

    # Debug: show what calls exist on this date
    print("\nCalls on 2026-08-17:")
    calls = sb.table('calls').select('title,company_name,call_date').eq(
        'call_date', '2026-08-17'
    ).execute()

    if calls.data:
        for call in calls.data[:5]:
            print(f"  - {call.get('title')}")
            print(f"    Company: {call.get('company_name')}")
    else:
        print("  (no calls on this date)")
