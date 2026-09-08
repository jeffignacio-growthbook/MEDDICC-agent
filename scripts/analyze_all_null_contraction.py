#!/usr/bin/env python3
"""Analyze null contraction pattern across ALL renewal deals (not just closed won)."""

import os
import sys
from pathlib import Path
from datetime import datetime
from collections import defaultdict
from dotenv import load_dotenv

sys.path.insert(0, str(Path(__file__).parent.parent))
load_dotenv()

from scripts.hubspot_deals import HubSpotDealsClient

print("=" * 80)
print("NULL CONTRACTION PATTERN - ALL RENEWAL DEALS")
print("=" * 80)
print()

hs = HubSpotDealsClient()

# Fetch ALL renewal deals
properties = [
    'dealname',
    'closedate',
    'createdate',
    'dealstage',
    'contraction_revenue',
    'gb_arr',
    'prior_arr',
    'hubspot_owner_id'
]

RENEWAL_PIPELINE_ID = "866608541"

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

renewal_deals = []
after = None

while True:
    if after:
        body["after"] = after

    response = hs.session.post(
        f"{hs.BASE_URL}/crm/v3/objects/deals/search",
        json=body
    )

    if response.status_code != 200:
        print(f"Error: {response.status_code}")
        break

    data = response.json()
    results = data.get('results', [])
    renewal_deals.extend(results)

    paging = data.get('paging', {})
    after = paging.get('next', {}).get('after')

    if not after:
        break

print(f"✓ Fetched {len(renewal_deals)} total renewal deals")
print()

# Analyze null contraction deals
null_deals = []

for deal in renewal_deals:
    props = deal.get('properties', {})
    contraction = props.get('contraction_revenue')

    if contraction is None or contraction == '':
        closedate_str = props.get('closedate')
        createdate_str = props.get('createdate')

        closedate = None
        createdate = None

        if closedate_str:
            try:
                closedate = datetime.fromisoformat(closedate_str.replace('Z', '+00:00'))
            except:
                pass

        if createdate_str:
            try:
                createdate = datetime.fromisoformat(createdate_str.replace('Z', '+00:00'))
            except:
                pass

        null_deals.append({
            'name': props.get('dealname', 'Unknown'),
            'stage': props.get('dealstage', 'Unknown'),
            'closedate': closedate,
            'createdate': createdate,
            'gb_arr': props.get('gb_arr'),
            'prior_arr': props.get('prior_arr'),
            'owner_id': props.get('hubspot_owner_id')
        })

print(f"Null/empty contraction deals: {len(null_deals)} ({len(null_deals)/len(renewal_deals)*100:.1f}%)")
print()

# ============================================================================
# DISTRIBUTION ANALYSIS
# ============================================================================
print("=" * 80)
print("NULL CONTRACTION DISTRIBUTION")
print("=" * 80)
print()

# By owner
by_owner = defaultdict(int)
for deal in null_deals:
    owner = deal['owner_id'] or 'No owner'
    by_owner[owner] += 1

print(f"By owner (showing all):")
for owner, count in sorted(by_owner.items(), key=lambda x: -x[1]):
    pct = count / len(null_deals) * 100
    print(f"  {owner}: {count} deals ({pct:.1f}%)")
print()

# By stage
by_stage = defaultdict(int)
stage_names = {
    '1297321618': 'Upcoming Renewal',
    '1297321619': 'Renewal Engaged',
    '1297321620': 'Pricing Presented',
    '1297321622': 'Contract Sent',
    '1297321623': 'Closed Won',
    '1297321624': 'Closed Lost'
}

for deal in null_deals:
    stage_id = deal['stage']
    stage_name = stage_names.get(stage_id, stage_id)
    by_stage[stage_name] += 1

print("By stage:")
for stage in ['Upcoming Renewal', 'Renewal Engaged', 'Pricing Presented',
              'Contract Sent', 'Closed Won', 'Closed Lost']:
    count = by_stage.get(stage, 0)
    if count > 0:
        pct = count / len(null_deals) * 100
        print(f"  {stage}: {count} deals ({pct:.1f}%)")
print()

# By year (using closedate for closed, createdate for open)
by_year = defaultdict(int)
for deal in null_deals:
    date = deal['closedate'] if deal['closedate'] else deal['createdate']
    if date:
        year = date.year
        by_year[year] += 1

print("By year:")
for year in sorted(by_year.keys()):
    count = by_year[year]
    pct = count / len(null_deals) * 100
    print(f"  {year}: {count} deals ({pct:.1f}%)")
print()

# Check for patterns
max_owner_pct = max(by_owner.values()) / len(null_deals) * 100 if by_owner else 0
max_year_pct = max(by_year.values()) / len(null_deals) * 100 if by_year else 0

# Check if mostly open vs closed
closed_won = by_stage.get('Closed Won', 0)
closed_lost = by_stage.get('Closed Lost', 0)
open_deals = len(null_deals) - closed_won - closed_lost
open_pct = open_deals / len(null_deals) * 100 if null_deals else 0

print("=" * 80)
print("PATTERN ANALYSIS")
print("=" * 80)
print()

print(f"Deal lifecycle distribution:")
print(f"  Open deals: {open_deals} ({open_pct:.1f}%)")
print(f"  Closed Won: {closed_won} ({closed_won/len(null_deals)*100:.1f}%)")
print(f"  Closed Lost: {closed_lost} ({closed_lost/len(null_deals)*100:.1f}%)")
print()

if open_pct > 80:
    print("✓ MOSTLY OPEN DEALS")
    print("  Null contraction on open deals is expected (deal not yet closed).")
    print("  This is NOT a data quality issue.")
    print()
    print("  For GRR calculation:")
    print("    - Only use closed won deals")
    print("    - Null on open deals is irrelevant")
    print()
elif max_owner_pct > 50:
    print("⚠️  CONCENTRATED BY OWNER")
    print(f"  {max_owner_pct:.1f}% from single owner suggests one rep doesn't fill field.")
    print()
    print("  For clarifying-questions:")
    print('    Surface: "Some renewals missing contraction data, concentrated')
    print('             in deals owned by [owner name]"')
    print()
elif max_year_pct > 70:
    print("⚠️  CONCENTRATED BY TIME")
    print(f"  {max_year_pct:.1f}% from single year suggests field was introduced mid-history.")
    print()
    print("  For clarifying-questions:")
    print('    Surface: "Contraction tracking started in [year], earlier deals')
    print('             may have incomplete data"')
    print()
else:
    print("✓ RANDOMLY DISTRIBUTED")
    print("  No strong concentration pattern detected.")
    print()
    print("  For GRR calculation:")
    print("    - Option A (treat null as zero) is reasonable default")
    print("    - State this as a checked conclusion")
    print()

# Sample deals
print("Sample null/empty deals:")
for deal in null_deals[:10]:
    stage_id = deal['stage']
    stage_name = stage_names.get(stage_id, stage_id)
    date = deal['closedate'] if deal['closedate'] else deal['createdate']
    date_str = date.strftime('%Y-%m-%d') if date else 'No date'

    print(f"  - {deal['name']}")
    print(f"    Stage: {stage_name}, Date: {date_str}")
    print(f"    GB ARR: {deal['gb_arr']}, Prior ARR: {deal['prior_arr']}")
