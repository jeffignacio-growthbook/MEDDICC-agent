#!/usr/bin/env python3
"""
Diagnostic check for Dribbleup and Joyteractive Q1 open deals.

Determine if abandoned/stale (like 'Chaos'/'Hey Harper') or genuinely active.
If stale, should be reclassified as losses per exclude_stale_pipeline pattern.
"""

import os
import sys
from pathlib import Path
from datetime import datetime, timezone as tz, timedelta
from dotenv import load_dotenv

sys.path.insert(0, str(Path(__file__).parent.parent))
load_dotenv()

from scripts.hubspot_deals import HubSpotDealsClient

print("=" * 80)
print("DRIBBLEUP / JOYTERACTIVE STALE DEAL DIAGNOSTIC")
print("=" * 80)
print()

hs = HubSpotDealsClient()

# Target deals
target_deals = {
    "Dribbleup - 2026 Renewal": {
        "close_date": "2026-03-06",
        "renewal_revenue": 12563,
        "days_past_close": 185
    },
    "Joyteractive - 2026 Renewal": {
        "close_date": "2026-02-01",
        "renewal_revenue": 10000,
        "days_past_close": 218
    }
}

print("Checking 2 Q1 deals still open 185-218 days past close...")
print()

# Fetch deals with engagement history
for deal_name in target_deals.keys():
    print("=" * 80)
    print(f"DEAL: {deal_name}")
    print("=" * 80)
    print()

    # Search for deal
    body = {
        "filterGroups": [
            {
                "filters": [
                    {
                        "propertyName": "dealname",
                        "operator": "EQ",
                        "value": deal_name
                    }
                ]
            }
        ],
        "properties": [
            'dealname',
            'closedate',
            'dealstage',
            'renewal_revenue',
            'createdate',
            'hs_lastmodifieddate',
            'notes_last_updated',
            'notes_last_contacted',
            'hs_num_associated_active_deal_registrations',
            'num_notes',
            'num_associated_contacts',
            'hs_date_entered_1297321618',  # Upcoming Renewal
            'hs_date_exited_1297321618'
        ],
        "limit": 1
    }

    response = hs.session.post(
        f"{hs.BASE_URL}/crm/v3/objects/deals/search",
        json=body
    )

    if response.status_code != 200:
        print(f"Error fetching deal: {response.status_code}")
        continue

    data = response.json()
    results = data.get('results', [])

    if not results:
        print(f"Deal not found")
        continue

    deal = results[0]
    deal_id = deal.get('id')
    props = deal.get('properties', {})

    # Basic info
    print(f"Close date: {props.get('closedate', 'N/A')}")
    print(f"Renewal revenue: ${float(props.get('renewal_revenue') or 0):,.2f}")
    print()

    # Timeline
    now = datetime.now(tz.utc)

    closedate_str = props.get('closedate')
    if closedate_str:
        closedate = datetime.fromisoformat(closedate_str.replace('Z', '+00:00'))
        days_past = (now - closedate).days
        print(f"Days past close: {days_past}")

    createdate_str = props.get('createdate')
    if createdate_str:
        createdate = datetime.fromisoformat(createdate_str.replace('Z', '+00:00'))
        days_old = (now - createdate).days
        print(f"Deal age: {days_old} days")

    print()

    # Activity signals
    print("Activity signals:")

    last_modified_str = props.get('hs_lastmodifieddate')
    if last_modified_str:
        last_modified = datetime.fromisoformat(last_modified_str.replace('Z', '+00:00'))
        days_since = (now - last_modified).days
        print(f"  Last modified: {last_modified.strftime('%Y-%m-%d')} ({days_since} days ago)")

        if days_since < 7:
            print(f"    ✓ RECENT activity")
        elif days_since < 30:
            print(f"    ⚠️ Activity within last month")
        elif days_since < 60:
            print(f"    ⚠️ No activity for {days_since} days")
        else:
            print(f"    ⚠️ STALE - no activity for {days_since} days")

    num_notes = props.get('num_notes')
    if num_notes:
        print(f"  Notes: {num_notes} total")

    num_contacts = props.get('num_associated_contacts')
    if num_contacts:
        print(f"  Associated contacts: {num_contacts}")

    print()

    # Stage history
    print("Stage history:")
    entry_str = props.get('hs_date_entered_1297321618')
    if entry_str:
        entry_date = datetime.fromisoformat(entry_str.replace('Z', '+00:00'))
        days_in_stage = (now - entry_date).days
        print(f"  Entered 'Upcoming Renewal': {entry_date.strftime('%Y-%m-%d')}")
        print(f"  Time in stage: {days_in_stage} days")

        if days_in_stage > 180:
            print(f"    ⚠️ HIGHLY STALE - {days_in_stage} days in same stage")
        elif days_in_stage > 90:
            print(f"    ⚠️ STALE - {days_in_stage} days in same stage")

    print()

    # Get engagement timeline (last 5 activities)
    print("Recent engagement timeline:")

    # Check for associated activities via engagements
    engagements_response = hs.session.get(
        f"{hs.BASE_URL}/crm/v3/objects/deals/{deal_id}/associations/notes"
    )

    if engagements_response.status_code == 200:
        engagements = engagements_response.json().get('results', [])
        print(f"  Found {len(engagements)} notes/activities")

        if len(engagements) == 0:
            print(f"    ⚠️ NO NOTES/ACTIVITIES recorded")
    else:
        print(f"  Could not fetch activities")

    print()

    # DIAGNOSTIC CRITERIA (per exclude_stale_pipeline pattern)
    print("DIAGNOSTIC ASSESSMENT:")
    print()

    is_stale = False
    reasons = []

    # Criterion 1: >180 days past close date
    if closedate_str:
        closedate = datetime.fromisoformat(closedate_str.replace('Z', '+00:00'))
        days_past = (now - closedate).days

        if days_past > 180:
            is_stale = True
            reasons.append(f">{days_past} days past close date (>180 day threshold)")

    # Criterion 2: No activity in >60 days
    if last_modified_str:
        last_modified = datetime.fromisoformat(last_modified_str.replace('Z', '+00:00'))
        days_since = (now - last_modified).days

        if days_since > 60:
            reasons.append(f"No activity in {days_since} days (>60 day threshold)")

    # Criterion 3: >90 days in same stage
    if entry_str:
        entry_date = datetime.fromisoformat(entry_str.replace('Z', '+00:00'))
        days_in_stage = (now - entry_date).days

        if days_in_stage > 90:
            reasons.append(f"{days_in_stage} days in 'Upcoming Renewal' stage (>90 day threshold)")

    print(f"Stale indicators found: {len(reasons)}")
    for reason in reasons:
        print(f"  - {reason}")
    print()

    # Final determination
    if is_stale or len(reasons) >= 2:
        print("DETERMINATION: ⚠️ STALE/ABANDONED")
        print()
        print("Recommendation:")
        print("  - Reclassify as Closed Lost (failed to renew)")
        print("  - Exclude from Q1 resolved cohort denominator")
        print("  - Same pattern as 'Chaos', 'Hey Harper' stale pipeline finding")
        print()
    else:
        print("DETERMINATION: ✓ POTENTIALLY ACTIVE")
        print()
        print("Recommendation:")
        print("  - Keep as open (not abandoned)")
        print("  - Exclude from variance analysis (not yet resolved)")
        print("  - Recent activity suggests genuine negotiation")
        print()

print("=" * 80)
print("SUMMARY")
print("=" * 80)
print()

print("Stale deal criteria (per exclude_stale_pipeline pattern):")
print("  1. >180 days past close date AND")
print("  2. No activity in >60 days OR >90 days in same stage")
print()

print("If BOTH deals are stale:")
print("  → Reclassify as losses")
print("  → Recompute Q1 GRR: (14 won, 4 lost) instead of (14 won, 2 lost)")
print("  → This is data quality correction, not judgment call")
print()

print("If either deal has recent activity:")
print("  → Keep as open/unresolved")
print("  → Continue excluding from variance analysis")
print("  → Not stale, just slow-moving renewal")
