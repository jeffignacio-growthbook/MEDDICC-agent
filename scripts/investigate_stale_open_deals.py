#!/usr/bin/env python3
"""
Deep investigation of open deals in closed periods.

Checks for stale/abandoned deals similar to 'Chaos', 'Hey Harper' pattern.
"""

import os
import sys
from pathlib import Path
from datetime import datetime, timezone as tz
from dotenv import load_dotenv

sys.path.insert(0, str(Path(__file__).parent.parent))
load_dotenv()

from scripts.hubspot_deals import HubSpotDealsClient

print("=" * 80)
print("STALE OPEN DEALS INVESTIGATION")
print("=" * 80)
print()

hs = HubSpotDealsClient()

RENEWAL_PIPELINE_ID = "866608541"
CLOSED_WON_STAGE_ID = "1297321623"
CLOSED_LOST_STAGE_ID = "1297321624"

STAGE_NAMES = {
    '1297321618': 'Upcoming Renewal',
    '1297321619': 'Renewal Engaged',
    '1297321620': 'Pricing Presented',
    '1297321622': 'Contract Sent',
    '1297321623': 'Closed Won',
    '1297321624': 'Closed Lost'
}

# Target deals from Q1 and Q2
target_deals = [
    "The Lifetime Value Co. - 2026 Renewal",
    "VSCO - 2026 renewal",
    "Dribbleup - 2026 Renewal",
    "Joyteractive - 2026 Renewal",
    "Docsity - 2026 Renewal",
    "Lease a Bike - 2026 renewal",
    "Lease a Bike Nederland - 2026 Renewal"
]

print("Searching for 7 open deals in closed periods...")
print()

# Fetch all renewal deals
properties = [
    'dealname',
    'closedate',
    'dealstage',
    'renewal_revenue',
    'hs_lastmodifieddate',
    'notes_last_updated',
    'notes_last_contacted',
    'hs_date_entered_1297321618',  # Upcoming Renewal
    'hs_date_entered_1297321619',  # Renewal Engaged
    'hs_date_entered_1297321620',  # Pricing Presented
    'createdate'
]

body = {
    "filterGroups": [
        {
            "filters": [
                {
                    "propertyName": "pipeline",
                    "operator": "EQ",
                    "value": RENEWAL_PIPELINE_ID
                }
            ]
        }
    ],
    "properties": properties,
    "limit": 100
}

all_deals = []
after = None

while True:
    if after:
        body["after"] = after

    response = hs.session.post(
        f"{hs.BASE_URL}/crm/v3/objects/deals/search",
        json=body
    )

    if response.status_code != 200:
        break

    data = response.json()
    results = data.get('results', [])
    all_deals.extend(results)

    paging = data.get('paging', {})
    after = paging.get('next', {}).get('after')

    if not after:
        break

print(f"Found {len(all_deals)} total renewal deals")
print()

# Filter to target deals
now = datetime.now(tz.utc)
found_deals = []

for deal in all_deals:
    props = deal.get('properties', {})
    name = props.get('dealname', '')

    if name in target_deals:
        found_deals.append({
            'name': name,
            'id': deal.get('id'),
            'props': props
        })

print(f"Found {len(found_deals)} of 7 target deals")
print()

# Analyze each deal
for deal in sorted(found_deals, key=lambda x: x['name']):
    props = deal['props']

    print("=" * 80)
    print(f"DEAL: {deal['name']}")
    print("=" * 80)
    print()

    # Basic info
    stage = props.get('dealstage', '')
    stage_name = STAGE_NAMES.get(stage, f'Unknown ({stage})')
    renewal_revenue = float(props.get('renewal_revenue') or 0)

    print(f"Current stage: {stage_name}")
    print(f"Renewal revenue: ${renewal_revenue:,.2f}")
    print()

    # Close date
    closedate_str = props.get('closedate')
    if closedate_str:
        try:
            closedate = datetime.fromisoformat(closedate_str.replace('Z', '+00:00'))
            days_past_close = (now - closedate).days
            print(f"Close date: {closedate.strftime('%Y-%m-%d')} ({days_past_close} days ago)")
        except:
            print(f"Close date: {closedate_str} (parse error)")
    else:
        print(f"Close date: Not set")
    print()

    # Create date
    createdate_str = props.get('createdate')
    if createdate_str:
        try:
            createdate = datetime.fromisoformat(createdate_str.replace('Z', '+00:00'))
            days_since_created = (now - createdate).days
            print(f"Created: {createdate.strftime('%Y-%m-%d')} ({days_since_created} days ago)")
        except:
            pass

    # Last modified
    last_modified_str = props.get('hs_lastmodifieddate')
    if last_modified_str:
        try:
            last_modified = datetime.fromisoformat(last_modified_str.replace('Z', '+00:00'))
            days_since_modified = (now - last_modified).days
            print(f"Last modified: {last_modified.strftime('%Y-%m-%d')} ({days_since_modified} days ago)")

            if days_since_modified > 90:
                print(f"  ⚠️ STALE: No activity in {days_since_modified} days")
            elif days_since_modified > 60:
                print(f"  ⚠️ VERY INACTIVE: No activity in {days_since_modified} days")
            elif days_since_modified > 30:
                print(f"  ⚠️ INACTIVE: No activity in {days_since_modified} days")
        except:
            pass
    print()

    # Stage history
    print("Stage entry dates:")
    for stage_id, stage_label in [
        ('1297321618', 'Upcoming Renewal'),
        ('1297321619', 'Renewal Engaged'),
        ('1297321620', 'Pricing Presented')
    ]:
        entry_date_str = props.get(f'hs_date_entered_{stage_id}')
        if entry_date_str:
            try:
                entry_date = datetime.fromisoformat(entry_date_str.replace('Z', '+00:00'))
                days_in_stage = (now - entry_date).days
                print(f"  {stage_label}: {entry_date.strftime('%Y-%m-%d')} ({days_in_stage} days ago)")
            except:
                pass

    print()

    # Assessment
    print("ASSESSMENT:")

    if renewal_revenue == 0:
        print("  ⚠️ $0 renewal revenue - should this be in cohort at all?")

    if closedate_str:
        try:
            closedate = datetime.fromisoformat(closedate_str.replace('Z', '+00:00'))
            days_past_close = (now - closedate).days

            if days_past_close > 150:
                print(f"  ⚠️ {days_past_close} days past close date - HIGHLY STALE")
            elif days_past_close > 90:
                print(f"  ⚠️ {days_past_close} days past close date - STALE")
            elif days_past_close > 60:
                print(f"  ⚠️ {days_past_close} days past close date - OVERDUE")
        except:
            pass

    if last_modified_str:
        try:
            last_modified = datetime.fromisoformat(last_modified_str.replace('Z', '+00:00'))
            days_since_modified = (now - last_modified).days

            if days_since_modified > 60 and closedate and (now - closedate).days > 90:
                print(f"  ⚠️ No activity in {days_since_modified} days AND past close → LIKELY ABANDONED")
        except:
            pass

    print()

print("=" * 80)
print("SUMMARY")
print("=" * 80)
print()

# Categorize deals
zero_revenue_deals = [d for d in found_deals if float(d['props'].get('renewal_revenue') or 0) == 0]
stale_deals = []

for deal in found_deals:
    props = deal['props']
    closedate_str = props.get('closedate')
    last_modified_str = props.get('hs_lastmodifieddate')

    if closedate_str and last_modified_str:
        try:
            closedate = datetime.fromisoformat(closedate_str.replace('Z', '+00:00'))
            last_modified = datetime.fromisoformat(last_modified_str.replace('Z', '+00:00'))

            days_past_close = (now - closedate).days
            days_since_modified = (now - last_modified).days

            # Stale if: >90 days past close AND >60 days no activity
            if days_past_close > 90 and days_since_modified > 60:
                stale_deals.append(deal)
        except:
            pass

print(f"Zero revenue deals: {len(zero_revenue_deals)}")
for d in zero_revenue_deals:
    print(f"  - {d['name']}")
print()

print(f"Likely stale/abandoned deals: {len(stale_deals)}")
for d in stale_deals:
    print(f"  - {d['name']}")
print()

print("RECOMMENDATION:")
print()

if zero_revenue_deals:
    print("1. Zero revenue deals should be EXCLUDED from denominator entirely")
    print("   (Not real renewals if no ARR to renew)")
    print()

if stale_deals:
    print("2. Stale/abandoned deals should be:")
    print("   Option A: Excluded from denominator (not real cohort)")
    print("   Option B: Treated as Closed Lost (failed to renew)")
    print()
    print("   Similar to 'Chaos', 'Hey Harper' stale pipeline finding")
    print()

if len(zero_revenue_deals) + len(stale_deals) > 0:
    print("3. After cleanup, recompute Q1 and Q2 GRR on CLEAN cohorts")
else:
    print("No obvious stale deals - all appear to be genuinely in negotiation")
