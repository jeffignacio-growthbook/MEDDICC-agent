#!/usr/bin/env python3
"""
Analyze the 326 deals closed on April 6, 2026 - Version 2.

Uses property history timestamps (more accurate) instead of HubSpot API metadata.
"""
import os
import sys
import json
import requests
from pathlib import Path
from datetime import datetime, timedelta
from collections import Counter
from dotenv import load_dotenv

load_dotenv()

# Load property history cache to get deal IDs AND their exact close timestamps
cache_path = Path('property_history_cache.json')
cache = json.load(open(cache_path))

# Find all deals closed on April 6, 2026 with exact timestamps
april_6_closes = []
for deal_id, data in cache['deals'].items():
    history = data.get('history', [])
    for entry in sorted(history, key=lambda x: x['timestamp']):
        ts = entry['timestamp']
        val = entry['value']

        if ts.startswith('2026-04-06') and val in ['closedwon', 'closedlost', '1297321623', '1297321624', '68509551']:
            april_6_closes.append({
                'deal_id': deal_id,
                'close_timestamp': ts,
                'close_stage': val
            })
            break

print(f"Found {len(april_6_closes)} deals closed on April 6, 2026")
print()

# Analysis 2 FIRST (timestamp clustering) - uses data we already have
print("="*70)
print("ANALYSIS 2: TIMESTAMP CLUSTERING")
print("="*70)
print()

timestamps = []
for record in april_6_closes:
    try:
        ts = datetime.fromisoformat(record['close_timestamp'].replace('Z', '+00:00'))
        timestamps.append(ts)
    except:
        pass

if timestamps:
    timestamps.sort()
    earliest = timestamps[0]
    latest = timestamps[-1]

    print(f"First close: {earliest.strftime('%Y-%m-%d %H:%M:%S UTC')}")
    print(f"Last close:  {latest.strftime('%Y-%m-%d %H:%M:%S UTC')}")
    print(f"Time span:   {(latest - earliest).total_seconds() / 60:.1f} minutes")
    print(f"             ({(latest - earliest).total_seconds() / 3600:.1f} hours)")
    print()

    # Count by hour
    hour_counts = Counter(ts.hour for ts in timestamps)
    print("Distribution by hour (UTC):")
    print("-"*50)
    for hour in sorted(hour_counts.keys()):
        count = hour_counts[hour]
        bar = '█' * max(1, count // 5)
        print(f"{hour:02d}:00-{hour:02d}:59: {count:>3} deals {bar}")

    print()

    # Check clustering
    # Within first 5 minutes
    first_5min = earliest + timedelta(minutes=5)
    within_5min = sum(1 for ts in timestamps if ts <= first_5min)
    pct_5min = (within_5min / len(timestamps)) * 100

    # Within first hour
    first_hour = earliest + timedelta(hours=1)
    within_first_hour = sum(1 for ts in timestamps if ts <= first_hour)
    pct_first_hour = (within_first_hour / len(timestamps)) * 100

    # Within first 4 hours
    first_4hours = earliest + timedelta(hours=4)
    within_4hours = sum(1 for ts in timestamps if ts <= first_4hours)
    pct_4hours = (within_4hours / len(timestamps)) * 100

    print(f"Within first 5 minutes: {within_5min:>3}/{len(timestamps)} ({pct_5min:>5.1f}%)")
    print(f"Within first hour:      {within_first_hour:>3}/{len(timestamps)} ({pct_first_hour:>5.1f}%)")
    print(f"Within first 4 hours:   {within_4hours:>3}/{len(timestamps)} ({pct_4hours:>5.1f}%)")
    print()

    if pct_5min > 90:
        clustering = "INSTANT BULK ACTION"
        print(f"⚠️  {clustering} - {pct_5min:.0f}% within 5 minutes")
        print("    Suggests: Workflow execution or API script")
    elif pct_first_hour > 80:
        clustering = "HIGHLY CLUSTERED"
        print(f"⚠️  {clustering} - {pct_first_hour:.0f}% within first hour")
        print("    Suggests: Single bulk action (workflow/admin cleanup)")
    elif pct_4hours > 70:
        clustering = "MODERATELY CLUSTERED"
        print(f"⚠️  {clustering} - {pct_4hours:.0f}% within 4 hours")
        print("    Suggests: Coordinated cleanup by a few people")
    else:
        clustering = "SPREAD ACROSS DAY"
        print(f"✓ {clustering}")
        print("    Suggests: Distributed individual decisions")
else:
    clustering = "UNKNOWN"
    print("⚠️  No timestamps available in property history")

# Now fetch owner and activity data from HubSpot
print()
print("="*70)
print("Fetching additional data from HubSpot...")
print("="*70)
print()

HUBSPOT_API_KEY = os.environ['HUBSPOT_API_KEY']
base_url = "https://api.hubapi.com/crm/v3/objects/deals"
headers = {
    'Authorization': f'Bearer {HUBSPOT_API_KEY}',
    'Content-Type': 'application/json'
}

properties = [
    'dealname',
    'hubspot_owner_id',
    'num_notes',
    'hs_num_associated_activities',
    'hs_num_associated_active_deal_registrations'
]

deal_details = {}
errors = []

deal_ids = [r['deal_id'] for r in april_6_closes]

print(f"Fetching {len(deal_ids)} deals from HubSpot...")
for i, deal_id in enumerate(deal_ids, 1):
    if i % 50 == 0:
        print(f"  {i}/{len(deal_ids)} deals...")

    try:
        url = f"{base_url}/{deal_id}"
        params = {'properties': ','.join(properties)}
        response = requests.get(url, params=params, headers=headers)
        response.raise_for_status()

        data = response.json()
        props = data.get('properties', {})

        # Convert to int, handling None and string values
        try:
            num_notes = int(props.get('num_notes') or 0)
        except (ValueError, TypeError):
            num_notes = 0

        try:
            num_activities = int(props.get('hs_num_associated_activities') or 0)
        except (ValueError, TypeError):
            num_activities = 0

        deal_details[deal_id] = {
            'dealname': props.get('dealname'),
            'hubspot_owner_id': props.get('hubspot_owner_id'),
            'num_notes': num_notes,
            'num_activities': num_activities
        }

        import time
        time.sleep(0.11)

    except Exception as e:
        errors.append({'deal_id': deal_id, 'error': str(e)})

print(f"Fetched {len(deal_details)} deals successfully")
if errors:
    print(f"Errors: {len(errors)}")
print()

# Fetch owner emails
print("Fetching owner emails...")
owner_ids = set(d['hubspot_owner_id'] for d in deal_details.values() if d.get('hubspot_owner_id'))
owner_emails = {}

for owner_id in owner_ids:
    try:
        url = f"https://api.hubapi.com/crm/v3/owners/{owner_id}"
        response = requests.get(url, headers=headers)
        response.raise_for_status()
        data = response.json()
        owner_emails[owner_id] = data.get('email', f'owner_{owner_id}')
        import time
        time.sleep(0.11)
    except Exception as e:
        owner_emails[owner_id] = f'owner_{owner_id}'

print(f"Fetched {len(owner_emails)} owner emails")
print()

# Analysis 1: Owner distribution
print("="*70)
print("ANALYSIS 1: OWNER DISTRIBUTION")
print("="*70)
print()

owner_counts = Counter()
for deal in deal_details.values():
    owner_id = deal.get('hubspot_owner_id')
    if owner_id:
        email = owner_emails.get(owner_id, f'owner_{owner_id}')
        owner_counts[email] += 1
    else:
        owner_counts['unassigned'] += 1

print(f"{'Owner Email':<40} {'Deal Count':<15} {'% of Total'}")
print("-"*70)
for email, count in owner_counts.most_common(10):
    pct = (count / len(deal_details)) * 100
    print(f"{email:<40} {count:<15} {pct:>5.1f}%")

if len(owner_counts) > 10:
    print(f"\n... and {len(owner_counts) - 10} more owners")

print()
print(f"Total unique owners: {len(owner_counts)}")

# Classify owner distribution
unassigned_pct = (owner_counts.get('unassigned', 0) / len(deal_details)) * 100
top_owner_pct = (owner_counts.most_common(1)[0][1] / len(deal_details)) * 100 if owner_counts else 0

if unassigned_pct > 80:
    owner_pattern = "MOSTLY UNASSIGNED"
    print(f"⚠️  {owner_pattern} - {unassigned_pct:.0f}% unassigned")
    print("    Suggests: System/admin action on unassigned deals")
elif top_owner_pct > 70:
    owner_pattern = "SINGLE OWNER DOMINANT"
    print(f"⚠️  {owner_pattern} - {top_owner_pct:.0f}% from top owner")
    print("    Suggests: One person's cleanup action")
elif len(owner_counts) <= 5:
    owner_pattern = "FEW OWNERS"
    print(f"⚠️  {owner_pattern} - {len(owner_counts)} owners")
    print("    Suggests: Coordinated cleanup by small team")
else:
    owner_pattern = "DISTRIBUTED"
    print(f"✓ {owner_pattern} - {len(owner_counts)} owners")
    print("    Suggests: Multiple people involved")

# Analysis 3: Activity history
print()
print("="*70)
print("ANALYSIS 3: ACTIVITY HISTORY (Sample of 20)")
print("="*70)
print()

import random
sample_deal_ids = random.sample(list(deal_details.keys()), min(20, len(deal_details)))

print(f"{'Deal ID':<15} {'Name':<30} {'Notes':<8} {'Activities':<12} {'Status'}")
print("-"*90)

active_count = 0
dormant_count = 0

for deal_id in sample_deal_ids:
    details = deal_details[deal_id]
    name = (details.get('dealname') or 'Untitled')[:28]
    num_notes = details.get('num_notes', 0)
    num_activities = details.get('num_activities', 0)

    # Heuristic: dormant if <2 notes and <3 activities
    if num_notes < 2 and num_activities < 3:
        status = "Dormant"
        dormant_count += 1
    else:
        status = "Active"
        active_count += 1

    print(f"{deal_id:<15} {name:<30} {num_notes:<8} {num_activities:<12} {status}")

print()
print(f"Active deals in sample:  {active_count}/20 ({active_count/20*100:.0f}%)")
print(f"Dormant deals in sample: {dormant_count}/20 ({dormant_count/20*100:.0f}%)")
print()

if dormant_count >= 15:
    activity_pattern = "MOSTLY DORMANT"
    print(f"✓ {activity_pattern} - Cleanup of stale deals makes sense")
elif active_count >= 10:
    activity_pattern = "MANY ACTIVE"
    print(f"⚠️  {activity_pattern} - Some deals with real activity were closed")
else:
    activity_pattern = "MIXED"
    print(f"⚠️  {activity_pattern} - Some dormant, some active")

# Summary
print()
print("="*70)
print("SUMMARY FOR SALES LEADERSHIP CONVERSATION")
print("="*70)
print()

# Determine overall pattern and question
if clustering in ["INSTANT BULK ACTION", "HIGHLY CLUSTERED"]:
    if unassigned_pct > 50:
        pattern = "AUTOMATED SYSTEM ACTION"
        question = "Was there a workflow or system process that bulk-closed unassigned deals on April 6?"
    elif top_owner_pct > 50:
        top_owner_email = owner_counts.most_common(1)[0][0]
        pattern = "SINGLE ACTOR BULK ACTION"
        question = f"Did {top_owner_email} run a bulk close-lost action on April 6, 2026?"
    else:
        pattern = "RAPID COORDINATED ACTION"
        question = "Was there a directive to rapidly close deals on April 6?"
elif clustering == "MODERATELY CLUSTERED" and len(owner_counts) <= 5:
    pattern = "COORDINATED CLEANUP"
    question = "Was there a planned pipeline cleanup on April 6, 2026?"
else:
    pattern = "DISTRIBUTED DECISIONS"
    question = "Why did 326 deals close on the same day across multiple owners?"

print(f"Pattern: {pattern}")
print(f"  - Timestamp: {clustering}")
print(f"  - Owners: {owner_pattern}")
print(f"  - Activity: {activity_pattern}")
print()
print(f"Recommended question for sales leadership:")
print(f'  "{question}"')
print()

# Specific guidance based on pattern
if pattern in ["AUTOMATED SYSTEM ACTION", "SINGLE ACTOR BULK ACTION"]:
    print("Investigation approach:")
    print("  1. Check HubSpot workflow logs for April 6, 2026")
    print("  2. Look for bulk deal updates in audit logs")
    if top_owner_pct > 50:
        top_owner = owner_counts.most_common(1)[0][0]
        print(f"  3. Interview {top_owner} about April 6 actions")
    print("  4. Review automation rules active on that date")
elif pattern == "COORDINATED CLEANUP":
    print("Investigation approach:")
    top_owners = [email for email, _ in owner_counts.most_common(5)]
    print(f"  1. Interview primary owners: {', '.join(top_owners[:3])}")
    print("  2. Ask about Q1 end-of-quarter cleanup directives")
    print("  3. Check for email/Slack communication about pipeline hygiene")
else:
    print("Investigation approach:")
    print("  1. Broad survey: Ask sales leadership about April 6 events")
    print("  2. Check for external factors (market event, product issue)")
    print("  3. Review 339 individual deal histories for common patterns")

# Save results
output = {
    'analysis_date': datetime.now().isoformat(),
    'total_deals': len(deal_details),
    'timestamp_clustering': {
        'pattern': clustering,
        'span_minutes': (latest - earliest).total_seconds() / 60 if timestamps else None,
        'within_5min': within_5min if timestamps else None,
        'within_1hour': within_first_hour if timestamps else None,
        'pct_5min': pct_5min if timestamps else None,
        'pct_1hour': pct_first_hour if timestamps else None,
        'earliest': earliest.isoformat() if timestamps else None,
        'latest': latest.isoformat() if timestamps else None,
    },
    'owner_distribution': {
        'pattern': owner_pattern,
        'unique_owners': len(owner_counts),
        'unassigned_pct': unassigned_pct,
        'top_owner_pct': top_owner_pct,
        'counts': dict(owner_counts)
    },
    'activity_sample': {
        'pattern': activity_pattern,
        'active': active_count,
        'dormant': dormant_count
    },
    'overall_pattern': pattern,
    'recommended_question': question
}

output_path = Path('april_6_analysis.json')
with open(output_path, 'w') as f:
    json.dump(output, f, indent=2)

print()
print(f"Full results saved to: {output_path}")
