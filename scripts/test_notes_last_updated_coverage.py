#!/usr/bin/env python3
"""
Test coverage of notes_last_updated property history across all deals
"""
import os
import sys
import requests
import time
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
from field_semantics import is_won

sb = get_supabase()

# Get closed deals (won/lost) like we did for Signal 3
print("Fetching closed deals...")
all_deals = sb.table('deals').select('deal_id,company_name,stage,deal_status').execute().data

# Filter to closed deals
closed_deals = []
for deal in all_deals:
    if is_won(deal.get('stage')):
        deal['outcome'] = 'won'
        closed_deals.append(deal)
    elif deal.get('deal_status') == 'lost':
        deal['outcome'] = 'lost'
        closed_deals.append(deal)

print(f"Total closed deals: {len(closed_deals)}")
print(f"  Won: {len([d for d in closed_deals if d['outcome'] == 'won'])}")
print(f"  Lost: {len([d for d in closed_deals if d['outcome'] == 'lost'])}")
print()

# Sample first 50 deals to test coverage (rate limit friendly)
sample_size = min(50, len(closed_deals))
sample_deals = closed_deals[:sample_size]

print(f"Testing property history coverage on sample of {sample_size} deals...")
print()

coverage_stats = {
    'total_tested': 0,
    'has_current_value': 0,
    'has_history': 0,
    'history_count_distribution': [],
    'api_errors': 0
}

for i, deal in enumerate(sample_deals):
    deal_id = deal['deal_id']

    if (i + 1) % 10 == 0:
        print(f"  Progress: {i+1}/{sample_size} deals tested...")

    # Fetch with property history
    url = f"https://api.hubapi.com/crm/v3/objects/deals/{deal_id}"
    params = {
        'properties': 'notes_last_updated',
        'propertiesWithHistory': 'notes_last_updated'
    }
    headers = {
        'Authorization': f'Bearer {HUBSPOT_API_KEY}',
        'Content-Type': 'application/json'
    }

    try:
        # Rate limit: 5 calls per second
        time.sleep(0.2)

        response = requests.get(url, params=params, headers=headers, timeout=10)

        if response.status_code == 200:
            data = response.json()

            coverage_stats['total_tested'] += 1

            # Check current value
            props = data.get('properties', {})
            if props.get('notes_last_updated'):
                coverage_stats['has_current_value'] += 1

            # Check history
            history = data.get('propertiesWithHistory', {})
            nlu_history = history.get('notes_last_updated', [])

            if len(nlu_history) > 0:
                coverage_stats['has_history'] += 1
                coverage_stats['history_count_distribution'].append(len(nlu_history))
        else:
            coverage_stats['api_errors'] += 1

    except Exception as e:
        coverage_stats['api_errors'] += 1
        continue

print()
print("=" * 80)
print("COVERAGE ANALYSIS")
print("=" * 80)
print()

tested = coverage_stats['total_tested']
has_current = coverage_stats['has_current_value']
has_history = coverage_stats['has_history']
errors = coverage_stats['api_errors']

print(f"Deals tested: {tested}")
print(f"API errors: {errors}")
print()

if tested > 0:
    print(f"Has current notes_last_updated value: {has_current}/{tested} ({100*has_current/tested:.1f}%)")
    print(f"Has notes_last_updated history: {has_history}/{tested} ({100*has_history/tested:.1f}%)")
    print()

    if coverage_stats['history_count_distribution']:
        import statistics
        hist_counts = coverage_stats['history_count_distribution']
        print(f"History change counts (for deals with history):")
        print(f"  Min: {min(hist_counts)}")
        print(f"  Median: {statistics.median(hist_counts)}")
        print(f"  Max: {max(hist_counts)}")
        print(f"  Mean: {statistics.mean(hist_counts):.1f}")
    print()

    # Extrapolate to full population
    if has_history > 0:
        coverage_pct = 100 * has_history / tested
        estimated_full = int(len(closed_deals) * coverage_pct / 100)

        print("=" * 80)
        print("COMPARISON TO SIGNAL 3 (CALLS ONLY)")
        print("=" * 80)
        print()
        print(f"Signal 3 call data coverage: 402/{len(closed_deals)} (23.1%)")
        print(f"Estimated notes_last_updated coverage: {estimated_full}/{len(closed_deals)} ({coverage_pct:.1f}%)")
        print()

        if coverage_pct > 23.1:
            improvement = coverage_pct - 23.1
            print(f"✅ IMPROVEMENT: +{improvement:.1f} percentage points over calls-only data")
        else:
            print(f"⚠️ Similar or lower coverage than calls-only data")

print()
print("=" * 80)
