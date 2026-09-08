#!/usr/bin/env python3
"""
Full validation of notes_last_updated property history approach
Checks 4 critical assumptions before treating as resolved

1. Real coverage at n=737 (not extrapolated from 50-deal sample)
2. Property history retention - does it span full lifecycle or truncate?
3. Bulk event contamination - do admin operations spuriously update this field?
4. dealstage_history coverage - does it match notes_last_updated coverage?
"""
import os
import sys
import requests
import time
import json
from pathlib import Path
from datetime import datetime, timezone
from collections import defaultdict, Counter
from dotenv import load_dotenv

# Load environment
env_path = Path(__file__).parent.parent / ".env"
load_dotenv(env_path)

HUBSPOT_API_KEY = os.getenv('HUBSPOT_API_KEY')
if not HUBSPOT_API_KEY:
    print("❌ HUBSPOT_API_KEY not set")
    sys.exit(1)

# Add scripts to path
sys.path.insert(0, str(Path(__file__).parent.parent / 'api'))
from db import get_supabase
from field_semantics import is_won

# Known bulk event dates from today's investigation
KNOWN_BULK_EVENTS = [
    "2026-04",  # April 2026 bulk cleanup (235 deals, blank lost_reason)
    # Ivan Gomez event date TBD - will check for spikes
]

sb = get_supabase()

print("=" * 80)
print("FULL VALIDATION: notes_last_updated Property History Approach")
print("=" * 80)
print()

# ============================================================================
# SETUP: Fetch all closed deals
# ============================================================================
print("Fetching all closed deals...")
all_deals = sb.table('deals').select(
    'deal_id,company_name,stage,deal_status,create_date,close_date'
).execute().data

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

# ============================================================================
# CHECK 1: Real coverage at n=737
# ============================================================================
print("=" * 80)
print("CHECK 1: REAL COVERAGE (not extrapolated)")
print("=" * 80)
print()

print(f"Fetching property history for all {len(closed_deals)} deals...")
print("This will take ~2.5 minutes with rate limiting (5 calls/sec)")
print()

coverage_stats = {
    'total_deals': len(closed_deals),
    'api_success': 0,
    'api_errors': 0,
    'has_notes_last_updated_current': 0,
    'has_notes_last_updated_history': 0,
    'has_dealstage_history': 0,
    'has_both_histories': 0,
    'notes_last_updated_change_counts': [],
    'dealstage_change_counts': [],
    'deals_with_data': []
}

start_time = time.time()

for i, deal in enumerate(closed_deals):
    deal_id = deal['deal_id']

    if (i + 1) % 50 == 0:
        elapsed = time.time() - start_time
        rate = (i + 1) / elapsed
        remaining = (len(closed_deals) - i - 1) / rate
        print(f"  Progress: {i+1}/{len(closed_deals)} deals ({100*(i+1)/len(closed_deals):.1f}%) - ETA: {remaining:.0f}s")

    # Fetch property history for both notes_last_updated and dealstage
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
        # Rate limit: 5 calls per second
        time.sleep(0.2)

        response = requests.get(url, params=params, headers=headers, timeout=10)

        if response.status_code == 200:
            data = response.json()
            coverage_stats['api_success'] += 1

            # Current values
            props = data.get('properties', {})
            has_nlu_current = bool(props.get('notes_last_updated'))

            # Property histories
            history = data.get('propertiesWithHistory', {})
            nlu_history = history.get('notes_last_updated', [])
            dealstage_history = history.get('dealstage', [])

            has_nlu_history = len(nlu_history) > 0
            has_dealstage_history = len(dealstage_history) > 0

            if has_nlu_current:
                coverage_stats['has_notes_last_updated_current'] += 1

            if has_nlu_history:
                coverage_stats['has_notes_last_updated_history'] += 1
                coverage_stats['notes_last_updated_change_counts'].append(len(nlu_history))

            if has_dealstage_history:
                coverage_stats['has_dealstage_history'] += 1
                coverage_stats['dealstage_change_counts'].append(len(dealstage_history))

            if has_nlu_history and has_dealstage_history:
                coverage_stats['has_both_histories'] += 1

            # Store deal data for retention and contamination checks
            if has_nlu_history or has_dealstage_history:
                coverage_stats['deals_with_data'].append({
                    'deal_id': deal_id,
                    'company_name': deal.get('company_name'),
                    'outcome': deal['outcome'],
                    'create_date': deal.get('create_date'),
                    'close_date': deal.get('close_date'),
                    'notes_last_updated_history': nlu_history,
                    'dealstage_history': dealstage_history
                })
        else:
            coverage_stats['api_errors'] += 1

    except Exception as e:
        coverage_stats['api_errors'] += 1
        continue

elapsed = time.time() - start_time
print()
print(f"Fetch complete in {elapsed:.1f}s ({len(closed_deals)/elapsed:.1f} deals/sec)")
print()

# Report CHECK 1 results
print("RESULTS:")
print()
print(f"API calls successful: {coverage_stats['api_success']}/{coverage_stats['total_deals']}")
print(f"API errors: {coverage_stats['api_errors']}")
print()

successful = coverage_stats['api_success']
if successful > 0:
    nlu_current_pct = 100 * coverage_stats['has_notes_last_updated_current'] / successful
    nlu_history_pct = 100 * coverage_stats['has_notes_last_updated_history'] / successful
    dealstage_history_pct = 100 * coverage_stats['has_dealstage_history'] / successful
    both_pct = 100 * coverage_stats['has_both_histories'] / successful

    print(f"Has current notes_last_updated: {coverage_stats['has_notes_last_updated_current']}/{successful} ({nlu_current_pct:.1f}%)")
    print(f"Has notes_last_updated history: {coverage_stats['has_notes_last_updated_history']}/{successful} ({nlu_history_pct:.1f}%)")
    print(f"Has dealstage history: {coverage_stats['has_dealstage_history']}/{successful} ({dealstage_history_pct:.1f}%)")
    print(f"Has BOTH histories: {coverage_stats['has_both_histories']}/{successful} ({both_pct:.1f}%)")
    print()

    if coverage_stats['notes_last_updated_change_counts']:
        import statistics
        nlu_counts = coverage_stats['notes_last_updated_change_counts']
        print(f"notes_last_updated changes per deal (n={len(nlu_counts)}):")
        print(f"  Min: {min(nlu_counts)}")
        print(f"  Median: {statistics.median(nlu_counts)}")
        print(f"  Mean: {statistics.mean(nlu_counts):.1f}")
        print(f"  Max: {max(nlu_counts)}")
        print()

    if coverage_stats['dealstage_change_counts']:
        import statistics
        stage_counts = coverage_stats['dealstage_change_counts']
        print(f"dealstage changes per deal (n={len(stage_counts)}):")
        print(f"  Min: {min(stage_counts)}")
        print(f"  Median: {statistics.median(stage_counts)}")
        print(f"  Mean: {statistics.mean(stage_counts):.1f}")
        print(f"  Max: {max(stage_counts)}")
        print()

    # Check if 86% held
    if nlu_history_pct < 80:
        print(f"⚠️  WARNING: Coverage degraded from 86% (50-deal sample) to {nlu_history_pct:.1f}% (full population)")
    elif nlu_history_pct >= 85:
        print(f"✅ Coverage confirmed: {nlu_history_pct:.1f}% matches 86% from sample")
    print()

# ============================================================================
# CHECK 2: Property history retention / truncation
# ============================================================================
print("=" * 80)
print("CHECK 2: PROPERTY HISTORY RETENTION")
print("=" * 80)
print()

print("Checking if property history spans full deal lifecycle or truncates...")
print()

def parse_date(date_str):
    if not date_str:
        return None
    try:
        dt = datetime.fromisoformat(date_str.replace('Z', '+00:00'))
        # Ensure timezone aware
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        return dt
    except:
        return None

retention_analysis = {
    'deals_checked': 0,
    'deals_with_full_history': 0,
    'deals_with_truncation_risk': 0,
    'truncation_examples': []
}

for deal_data in coverage_stats['deals_with_data']:
    if not deal_data['notes_last_updated_history']:
        continue

    retention_analysis['deals_checked'] += 1

    create_date = parse_date(deal_data['create_date'])
    close_date = parse_date(deal_data['close_date'])

    if not create_date or not close_date:
        continue

    # Get earliest notes_last_updated change
    nlu_history = deal_data['notes_last_updated_history']

    # History is sorted most recent first, so last item is earliest
    earliest_change_ts = None
    for change in nlu_history:
        ts_str = change.get('timestamp')
        if ts_str:
            ts = parse_date(ts_str)
            if ts and (earliest_change_ts is None or ts < earliest_change_ts):
                earliest_change_ts = ts

    if earliest_change_ts:
        # Check if earliest change is close to create_date
        days_after_creation = (earliest_change_ts - create_date).days

        # If earliest change is >30 days after creation, likely truncated
        if days_after_creation > 30:
            retention_analysis['deals_with_truncation_risk'] += 1

            if len(retention_analysis['truncation_examples']) < 5:
                retention_analysis['truncation_examples'].append({
                    'deal_id': deal_data['deal_id'],
                    'company': deal_data['company_name'],
                    'create_date': deal_data['create_date'],
                    'earliest_change': earliest_change_ts.isoformat(),
                    'days_gap': days_after_creation,
                    'change_count': len(nlu_history)
                })
        else:
            retention_analysis['deals_with_full_history'] += 1

print(f"Deals with notes_last_updated history: {retention_analysis['deals_checked']}")
print(f"  Full history (earliest change within 30 days of creation): {retention_analysis['deals_with_full_history']}")
print(f"  Truncation risk (earliest change >30 days after creation): {retention_analysis['deals_with_truncation_risk']}")
print()

if retention_analysis['deals_with_truncation_risk'] > 0:
    trunc_pct = 100 * retention_analysis['deals_with_truncation_risk'] / retention_analysis['deals_checked']
    print(f"⚠️  WARNING: {trunc_pct:.1f}% of deals show truncation risk")
    print()
    print("Examples of potential truncation:")
    for ex in retention_analysis['truncation_examples']:
        print(f"  {ex['deal_id']} ({ex['company']})")
        print(f"    Created: {ex['create_date']}")
        print(f"    Earliest change: {ex['earliest_change']}")
        print(f"    Gap: {ex['days_gap']} days")
        print(f"    Total changes: {ex['change_count']}")
        print()
else:
    print("✅ No significant truncation detected")
print()

# ============================================================================
# CHECK 3: Bulk event contamination
# ============================================================================
print("=" * 80)
print("CHECK 3: BULK EVENT CONTAMINATION")
print("=" * 80)
print()

print("Checking for suspicious spikes in notes_last_updated changes...")
print("Known bulk events from today's investigation:")
print("  - April 2026 bulk cleanup (235 deals)")
print("  - Ivan Gomez departure (date TBD)")
print()

# Collect all change dates
change_dates_counter = Counter()

for deal_data in coverage_stats['deals_with_data']:
    for change in deal_data['notes_last_updated_history']:
        ts_str = change.get('timestamp')
        if ts_str:
            ts = parse_date(ts_str)
            if ts:
                date_str = ts.strftime('%Y-%m-%d')
                change_dates_counter[date_str] += 1

# Find top 20 dates with most changes
top_dates = change_dates_counter.most_common(20)

print("Top 20 dates with most notes_last_updated changes:")
print()
print(f"{'Date':<12} {'Changes':<8} {'Status'}")
print("-" * 50)

for date_str, count in top_dates:
    # Flag suspicious if >50 changes on single date (arbitrary threshold)
    suspicious = ""
    if count > 50:
        suspicious = "⚠️  SUSPICIOUS SPIKE"
    elif "2026-04" in date_str:
        suspicious = "⚠️  KNOWN BULK EVENT (Apr 2026)"

    print(f"{date_str:<12} {count:<8} {suspicious}")

print()

# Check April 2026 specifically
april_2026_changes = sum(count for date, count in top_dates if "2026-04" in date)
if april_2026_changes > 100:
    print(f"⚠️  WARNING: {april_2026_changes} changes in April 2026 (known bulk cleanup month)")
    print("   notes_last_updated may update on ADMINISTRATIVE changes, not just real activity")
else:
    print(f"April 2026 changes: {april_2026_changes} (within normal range)")

print()

# ============================================================================
# CHECK 4: dealstage_history coverage independently verified
# ============================================================================
print("=" * 80)
print("CHECK 4: DEALSTAGE HISTORY COVERAGE (independent verification)")
print("=" * 80)
print()

print("Verifying dealstage_history coverage independently...")
print()

if successful > 0:
    dealstage_coverage = coverage_stats['has_dealstage_history']
    nlu_coverage = coverage_stats['has_notes_last_updated_history']
    both_coverage = coverage_stats['has_both_histories']

    dealstage_pct = 100 * dealstage_coverage / successful
    nlu_pct = 100 * nlu_coverage / successful
    both_pct = 100 * both_coverage / successful

    print(f"dealstage history coverage: {dealstage_coverage}/{successful} ({dealstage_pct:.1f}%)")
    print(f"notes_last_updated history coverage: {nlu_coverage}/{successful} ({nlu_pct:.1f}%)")
    print(f"Both histories present: {both_coverage}/{successful} ({both_pct:.1f}%)")
    print()

    # Check if they track 1:1
    coverage_diff = abs(dealstage_pct - nlu_pct)

    if coverage_diff > 5:
        print(f"⚠️  WARNING: Coverage mismatch between dealstage ({dealstage_pct:.1f}%) and notes_last_updated ({nlu_pct:.1f}%)")
        print(f"   Difference: {coverage_diff:.1f} percentage points")
        print()

        # Find deals with only one history
        only_dealstage = dealstage_coverage - both_coverage
        only_nlu = nlu_coverage - both_coverage

        print(f"Deals with only dealstage history: {only_dealstage}")
        print(f"Deals with only notes_last_updated history: {only_nlu}")
    else:
        print(f"✅ Coverage matches: {coverage_diff:.1f}pp difference (acceptable)")

    print()

    # Check if both are needed for methodology
    if both_pct < 80:
        print(f"⚠️  WARNING: Only {both_pct:.1f}% of deals have BOTH histories")
        print("   Signal 3 methodology requires matching activities to stages")
        print("   Coverage will be limited to deals with both histories")
    else:
        print(f"✅ {both_pct:.1f}% of deals have both histories (sufficient for methodology)")

print()

# ============================================================================
# FINAL SUMMARY
# ============================================================================
print("=" * 80)
print("VALIDATION SUMMARY")
print("=" * 80)
print()

validation_passed = True
warnings = []

# Check 1: Coverage
if successful > 0:
    nlu_pct = 100 * coverage_stats['has_notes_last_updated_history'] / successful
    if nlu_pct < 80:
        validation_passed = False
        warnings.append(f"CHECK 1 FAIL: Coverage degraded to {nlu_pct:.1f}% (below 80% threshold)")
    elif nlu_pct < 85:
        warnings.append(f"CHECK 1 WARNING: Coverage {nlu_pct:.1f}% lower than 86% sample")
    else:
        print(f"✅ CHECK 1 PASS: Coverage {nlu_pct:.1f}% confirmed")

# Check 2: Retention
if retention_analysis['deals_with_truncation_risk'] > 0:
    trunc_pct = 100 * retention_analysis['deals_with_truncation_risk'] / retention_analysis['deals_checked']
    if trunc_pct > 20:
        validation_passed = False
        warnings.append(f"CHECK 2 FAIL: {trunc_pct:.1f}% of deals show truncation risk")
    else:
        warnings.append(f"CHECK 2 WARNING: {trunc_pct:.1f}% of deals show truncation risk")
else:
    print(f"✅ CHECK 2 PASS: No significant truncation detected")

# Check 3: Contamination
if april_2026_changes > 100:
    warnings.append(f"CHECK 3 WARNING: {april_2026_changes} changes in April 2026 bulk cleanup month")
    print(f"⚠️  CHECK 3 WARNING: Bulk event contamination possible")
else:
    print(f"✅ CHECK 3 PASS: No major contamination spikes detected")

# Check 4: Stage matching
if successful > 0:
    both_pct = 100 * coverage_stats['has_both_histories'] / successful
    if both_pct < 80:
        validation_passed = False
        warnings.append(f"CHECK 4 FAIL: Only {both_pct:.1f}% have both histories (need 80%+)")
    else:
        print(f"✅ CHECK 4 PASS: {both_pct:.1f}% have both histories")

print()

if warnings:
    print("WARNINGS:")
    for warning in warnings:
        print(f"  {warning}")
    print()

if validation_passed:
    print("=" * 80)
    print("✅ VALIDATION PASSED - Proceed with threshold derivation")
    print("=" * 80)
else:
    print("=" * 80)
    print("❌ VALIDATION FAILED - DO NOT proceed without addressing issues")
    print("=" * 80)

# Save results to file for later analysis
output_file = Path(__file__).parent.parent / "notes_last_updated_validation_results.json"
with open(output_file, 'w') as f:
    json.dump({
        'coverage_stats': {
            k: v for k, v in coverage_stats.items()
            if k != 'deals_with_data'  # Exclude large data blob
        },
        'retention_analysis': retention_analysis,
        'bulk_event_analysis': {
            'top_20_dates': top_dates[:20],
            'april_2026_changes': april_2026_changes
        },
        'validation_passed': validation_passed,
        'warnings': warnings
    }, f, indent=2)

print()
print(f"Detailed results saved to: {output_file}")
