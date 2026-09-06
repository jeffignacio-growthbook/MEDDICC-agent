#!/usr/bin/env python3
"""
Analyze the 326 deals closed on April 6, 2026.

Determines whether this was:
1. Single bulk action (one actor, clustered timestamps)
2. Coordinated cleanup (few actors, similar timing)
3. Distributed decisions (many actors, spread across day)
"""
import os
import sys
import json
import requests
from pathlib import Path
from datetime import datetime
from collections import Counter, defaultdict
from dotenv import load_dotenv

load_dotenv()

# Load property history cache to get the 326 deal IDs
cache_path = Path('property_history_cache.json')
cache = json.load(open(cache_path))

# Find all deals closed on April 6, 2026
april_6_deals = []
for deal_id, data in cache['deals'].items():
    history = data.get('history', [])
    for entry in sorted(history, key=lambda x: x['timestamp']):
        ts = entry['timestamp'][:10]
        val = entry['value']

        if ts == '2026-04-06' and val in ['closedwon', 'closedlost', '1297321623', '1297321624', '68509551']:
            april_6_deals.append(deal_id)
            break

print(f"Found {len(april_6_deals)} deals closed on April 6, 2026")
print()

# Now fetch additional data from HubSpot for these deals
HUBSPOT_API_KEY = os.environ['HUBSPOT_API_KEY']
base_url = "https://api.hubapi.com/crm/v3/objects/deals"
headers = {
    'Authorization': f'Bearer {HUBSPOT_API_KEY}',
    'Content-Type': 'application/json'
}

# Properties to fetch
properties = [
    'dealname',
    'dealstage',
    'hubspot_owner_id',
    'hs_lastmodifieddate',
    'closedate',
    'hs_date_entered_closedlost',
    'hs_date_exited_closedlost',
    'notes_last_updated',
    'num_notes',
    'hs_num_associated_activities'
]

print("Fetching deal details from HubSpot...")
print("(This may take a few minutes for 326 deals)")
print()

deal_details = {}
errors = []

for i, deal_id in enumerate(april_6_deals[:326], 1):
    if i % 50 == 0:
        print(f"  Fetched {i}/326 deals...")

    try:
        url = f"{base_url}/{deal_id}"
        params = {'properties': ','.join(properties)}
        response = requests.get(url, params=params, headers=headers)
        response.raise_for_status()

        data = response.json()
        props = data.get('properties', {})

        deal_details[deal_id] = {
            'dealname': props.get('dealname'),
            'hubspot_owner_id': props.get('hubspot_owner_id'),
            'lastmodifieddate': props.get('hs_lastmodifieddate'),
            'closedate': props.get('closedate'),
            'date_entered_closedlost': props.get('hs_date_entered_closedlost'),
            'num_notes': props.get('num_notes', 0),
            'num_activities': props.get('hs_num_associated_activities', 0)
        }

        import time
        time.sleep(0.11)  # Rate limit: ~9 calls/sec

    except Exception as e:
        errors.append({'deal_id': deal_id, 'error': str(e)})

print(f"\nFetched {len(deal_details)} deals successfully")
if errors:
    print(f"Errors: {len(errors)}")

# Now fetch owner emails
print("\nFetching owner information...")
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
    owner_id = deal.get('hubspot_owner_id', 'unassigned')
    email = owner_emails.get(owner_id, 'unassigned')
    owner_counts[email] += 1

print(f"{'Owner Email':<40} {'Deal Count':<15} {'% of Total'}")
print("-"*70)
for email, count in owner_counts.most_common(10):
    pct = (count / len(deal_details)) * 100
    print(f"{email:<40} {count:<15} {pct:>5.1f}%")

if len(owner_counts) > 10:
    print(f"\n... and {len(owner_counts) - 10} more owners")

print()
print(f"Total unique owners: {len(owner_counts)}")
if len(owner_counts) == 1:
    print("⚠️  SINGLE OWNER - Suggests bulk action by one person")
elif len(owner_counts) <= 5:
    print("⚠️  FEW OWNERS - Suggests coordinated cleanup")
else:
    print("✓ DISTRIBUTED - Multiple owners involved")

# Analysis 2: Timestamp clustering
print()
print("="*70)
print("ANALYSIS 2: TIMESTAMP CLUSTERING")
print("="*70)
print()

# Parse timestamps
timestamps = []
for deal_id, details in deal_details.items():
    ts_str = details.get('date_entered_closedlost')
    if ts_str:
        try:
            # Parse ISO timestamp
            ts = datetime.fromisoformat(ts_str.replace('Z', '+00:00'))
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
    print()

    # Count by hour
    hour_counts = Counter(ts.hour for ts in timestamps)
    print("Distribution by hour (UTC):")
    print("-"*40)
    for hour in sorted(hour_counts.keys()):
        count = hour_counts[hour]
        bar = '█' * (count // 5)
        print(f"{hour:02d}:00 - {hour:02d}:59: {count:>3} deals {bar}")

    print()

    # Check clustering (% within first hour)
    first_hour = earliest + __import__('datetime').timedelta(hours=1)
    within_first_hour = sum(1 for ts in timestamps if ts <= first_hour)
    pct_first_hour = (within_first_hour / len(timestamps)) * 100

    print(f"Within first hour: {within_first_hour}/{len(timestamps)} ({pct_first_hour:.1f}%)")

    if pct_first_hour > 80:
        print("⚠️  HIGHLY CLUSTERED - Suggests single bulk action (workflow/API)")
    elif pct_first_hour > 50:
        print("⚠️  MODERATELY CLUSTERED - Suggests coordinated action")
    else:
        print("✓ SPREAD ACROSS DAY - Distributed individual actions")
else:
    print("⚠️  No hs_date_entered_closedlost timestamps available")
    print("Falling back to hs_lastmodifieddate...")

    # Use lastmodifieddate as fallback
    mod_timestamps = []
    for details in deal_details.values():
        ts_str = details.get('lastmodifieddate')
        if ts_str:
            try:
                ts = datetime.fromisoformat(ts_str.replace('Z', '+00:00'))
                mod_timestamps.append(ts)
            except:
                pass

    if mod_timestamps:
        mod_timestamps.sort()
        earliest = mod_timestamps[0]
        latest = mod_timestamps[-1]

        print(f"First modified: {earliest.strftime('%Y-%m-%d %H:%M:%S UTC')}")
        print(f"Last modified:  {latest.strftime('%Y-%m-%d %H:%M:%S UTC')}")
        print(f"Time span:      {(latest - earliest).total_seconds() / 3600:.1f} hours")

# Analysis 3: Activity history for sample
print()
print("="*70)
print("ANALYSIS 3: ACTIVITY HISTORY (Sample of 20)")
print("="*70)
print()

# Take a random sample of 20 deals
import random
sample_deal_ids = random.sample(list(deal_details.keys()), min(20, len(deal_details)))

print(f"{'Deal ID':<15} {'Name':<30} {'Notes':<8} {'Activities':<12} {'Status'}")
print("-"*90)

active_count = 0
dormant_count = 0

for deal_id in sample_deal_ids[:20]:
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
    print("✓ MOSTLY DORMANT - Cleanup of stale deals makes sense")
elif active_count >= 10:
    print("⚠️  MANY ACTIVE - Some deals with real activity were closed")
else:
    print("⚠️  MIXED - Some dormant, some active")

# Summary
print()
print("="*70)
print("SUMMARY FOR SALES LEADERSHIP CONVERSATION")
print("="*70)
print()

# Determine the pattern
if len(owner_counts) == 1:
    pattern = "SINGLE ACTOR"
    question = f"Did {list(owner_counts.keys())[0]} run a bulk close-lost workflow on April 6?"
elif len(owner_counts) <= 5 and (not timestamps or pct_first_hour > 50):
    pattern = "COORDINATED CLEANUP"
    question = "Was there a directive to clean up stale deals on April 6?"
else:
    pattern = "DISTRIBUTED DECISIONS"
    question = "Why did 326 deals close on the same day across multiple owners?"

print(f"Pattern: {pattern}")
print()
print(f"Recommended question for sales leadership:")
print(f'  "{question}"')
print()

if len(owner_counts) <= 5:
    print("Suggested approach:")
    print(f"  1. Contact primary owners: {', '.join(list(owner_counts.keys())[:3])}")
    print(f"  2. Ask specifically about April 6, 2026 close-lost actions")
    print(f"  3. Check for workflow logs or automation runs")

# Save results
output = {
    'analysis_date': datetime.now().isoformat(),
    'total_deals': len(deal_details),
    'owner_distribution': dict(owner_counts),
    'timestamp_span_minutes': (latest - earliest).total_seconds() / 60 if timestamps else None,
    'clustered_pct': pct_first_hour if timestamps else None,
    'sample_active': active_count,
    'sample_dormant': dormant_count,
    'pattern': pattern,
    'recommended_question': question
}

output_path = Path('april_6_analysis.json')
with open(output_path, 'w') as f:
    json.dump(output, f, indent=2)

print()
print(f"Full results saved to: {output_path}")
