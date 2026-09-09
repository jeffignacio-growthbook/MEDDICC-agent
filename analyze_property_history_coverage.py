#!/usr/bin/env python3
"""
Analyze property_history coverage for closed deals.

Questions:
1. What % of ALL closed deals have dealstage record in property_history?
2. Is there a sync lag between deal closing and property_history capture?
3. Is this a structural gap or a data quality issue?
"""

import os
from datetime import datetime, date
from dotenv import load_dotenv
from collections import defaultdict

load_dotenv()

from supabase import create_client
SUPABASE_URL = os.getenv('SUPABASE_URL')
SUPABASE_KEY = os.getenv('SUPABASE_SERVICE_KEY')
sb = create_client(SUPABASE_URL, SUPABASE_KEY)

import sys
sys.path.insert(0, 'scripts')
from supabase_client import select_all

print("Property_history coverage analysis for closed deals")
print("=" * 70)

# Get ALL deals with current status won or lost
print("\n1. Loading all closed deals from deals table...")
all_deals = select_all(sb, 'deals', 'deal_id, deal_status, close_date, deal_value, created_at')

won_deals = [d for d in all_deals if d.get('deal_status') == 'won']
lost_deals = [d for d in all_deals if d.get('deal_status') == 'lost']
closed_deals = won_deals + lost_deals

print(f"   Total deals: {len(all_deals)}")
print(f"   Won deals: {len(won_deals)}")
print(f"   Lost deals: {len(lost_deals)}")
print(f"   Total closed: {len(closed_deals)}")

if not closed_deals:
    print("\n⚠️  No closed deals found in deals table")
    sys.exit(0)

# Check property_history coverage
print(f"\n2. Checking property_history coverage...")

# Get ALL dealstage property_history records at once for efficiency
ph_result = sb.table('property_history')\
    .select('deal_id, changed_at, old_value, new_value')\
    .eq('property_name', 'dealstage')\
    .execute()

# Build index by deal_id for fast lookup
ph_by_deal = defaultdict(list)
for record in ph_result.data:
    ph_by_deal[record['deal_id']].append(record)

print(f"   Found {len(ph_result.data)} dealstage records covering {len(ph_by_deal)} unique deals")

# Analyze coverage
deals_with_history = 0
deals_without_history = 0
deals_with_closing_transition = 0

# Track timing for sync lag analysis
timing_data = []

closed_stages = ['closedwon', 'closedlost', 'closed won', 'closed lost', 'won', 'lost']

for deal in closed_deals:
    deal_id = deal['deal_id']
    records = ph_by_deal.get(deal_id, [])

    if records:
        deals_with_history += 1

        # Check if any record shows transition TO a closed stage
        has_closing_transition = False
        latest_closed_transition = None

        for record in records:
            new_val = (record['new_value'] or '').lower()
            old_val = (record['old_value'] or '').lower()

            # Check if this transition moved TO a closed stage
            if any(closed in new_val for closed in closed_stages):
                has_closing_transition = True
                latest_closed_transition = record

        if has_closing_transition:
            deals_with_closing_transition += 1

            # Analyze timing if we have both close_date and changed_at
            if deal.get('close_date') and latest_closed_transition:
                close_date = date.fromisoformat(deal['close_date'][:10])
                changed_at = datetime.fromisoformat(latest_closed_transition['changed_at'].replace('Z', '+00:00')).date()

                lag_days = (changed_at - close_date).days
                timing_data.append({
                    'deal_id': deal_id,
                    'close_date': close_date,
                    'property_history_date': changed_at,
                    'lag_days': lag_days,
                    'deal_value': deal.get('deal_value') or 0
                })
    else:
        deals_without_history += 0

# Calculate percentages
coverage_any_history = (deals_with_history / len(closed_deals) * 100) if closed_deals else 0
coverage_closing_transition = (deals_with_closing_transition / len(closed_deals) * 100) if closed_deals else 0

print(f"\n3. Coverage results:")
print(f"   Closed deals with ANY property_history: {deals_with_history}/{len(closed_deals)} ({coverage_any_history:.1f}%)")
print(f"   Closed deals with CLOSING TRANSITION: {deals_with_closing_transition}/{len(closed_deals)} ({coverage_closing_transition:.1f}%)")
print(f"   Closed deals with NO property_history: {deals_without_history}/{len(closed_deals)} ({100 - coverage_any_history:.1f}%)")

# Analyze sync lag
if timing_data:
    print(f"\n4. Sync lag analysis ({len(timing_data)} deals with timing data):")

    # Calculate statistics
    lags = [d['lag_days'] for d in timing_data]
    avg_lag = sum(lags) / len(lags)
    min_lag = min(lags)
    max_lag = max(lags)

    # Count same-day vs delayed
    same_day = len([l for l in lags if l == 0])
    delayed = len([l for l in lags if l != 0])

    print(f"   Average lag: {avg_lag:.1f} days")
    print(f"   Min lag: {min_lag} days")
    print(f"   Max lag: {max_lag} days")
    print(f"   Same-day capture: {same_day}/{len(lags)} ({same_day/len(lags)*100:.1f}%)")
    print(f"   Delayed capture: {delayed}/{len(lags)} ({delayed/len(lags)*100:.1f}%)")

    # Show distribution
    print(f"\n   Lag distribution:")
    lag_buckets = defaultdict(int)
    for lag in lags:
        if lag == 0:
            lag_buckets['0 days (same-day)'] += 1
        elif lag < 0:
            lag_buckets['< 0 days (backdated)'] += 1
        elif lag <= 7:
            lag_buckets['1-7 days'] += 1
        elif lag <= 30:
            lag_buckets['8-30 days'] += 1
        else:
            lag_buckets['> 30 days'] += 1

    for bucket in ['< 0 days (backdated)', '0 days (same-day)', '1-7 days', '8-30 days', '> 30 days']:
        count = lag_buckets.get(bucket, 0)
        if count > 0:
            pct = count / len(lags) * 100
            print(f"     {bucket}: {count} ({pct:.1f}%)")
else:
    print(f"\n4. Sync lag analysis: No timing data available")

# Check recent deals specifically (last 90 days)
print(f"\n5. Recent deal analysis (last 90 days):")
cutoff = datetime.now().date()
cutoff_90d = date(cutoff.year, cutoff.month, cutoff.day)
from datetime import timedelta
cutoff_90d = cutoff - timedelta(days=90)

recent_closed = [d for d in closed_deals
                 if d.get('close_date') and date.fromisoformat(d['close_date'][:10]) >= cutoff_90d]

if recent_closed:
    recent_with_history = len([d for d in recent_closed if d['deal_id'] in ph_by_deal])
    recent_coverage = (recent_with_history / len(recent_closed) * 100) if recent_closed else 0

    print(f"   Recent closed deals: {len(recent_closed)}")
    print(f"   With property_history: {recent_with_history} ({recent_coverage:.1f}%)")

    # Check if coverage is better/worse for recent deals
    if coverage_any_history > 0:
        if recent_coverage > coverage_any_history:
            print(f"   ✓ Coverage is BETTER for recent deals (+{recent_coverage - coverage_any_history:.1f}%)")
        elif recent_coverage < coverage_any_history:
            print(f"   ⚠️  Coverage is WORSE for recent deals (-{coverage_any_history - recent_coverage:.1f}%)")
        else:
            print(f"   = Coverage is SAME for recent deals")
else:
    print(f"   No deals closed in last 90 days")

# Summary and diagnosis
print(f"\n" + "=" * 70)
print("DIAGNOSIS:")

if coverage_closing_transition >= 90:
    print("✓ Property_history has GOOD coverage (>90%)")
    print("  The 9 original deals are likely an edge case or timing issue")
    print("  Proceeding with Option A (fix with get_deal_status_as_of) is viable")
elif coverage_closing_transition >= 50:
    print("⚠️  Property_history has MODERATE coverage (50-90%)")
    print("  Significant minority of deals lack historical records")
    print("  Proceeding with Option A will fix SOME but not ALL cases")
    print(f"  Expect ~{100 - coverage_closing_transition:.0f}% of closed deals to still return 'unknown'")
elif coverage_closing_transition >= 10:
    print("✗ Property_history has POOR coverage (10-50%)")
    print("  Majority of deals lack historical records")
    print("  Option A will only fix a small fraction of cases")
    print("  Consider Option C (alternative approach) instead")
else:
    print("✗✗ Property_history has CRITICAL coverage gap (<10%)")
    print("  Almost no closed deals have historical records")
    print("  property_history is NOT a viable data source for this use case")
    print("  Option C (alternative approach) is REQUIRED")

# Specific answer to original 9 deals
print(f"\nAnswer to user's question 1:")
print(f"  'Do the SAME 9 deals from original $830K discovery return unknown?'")
print(f"  → YES, all 9 return 'unknown' (confirmed by test_real_world_status.py)")
print(f"  → The fix as built does NOT resolve the original problem")
print(f"  → It just makes the failure honest (unknown) instead of wrong (silently active)")

print(f"\nAnswer to user's question 2:")
print(f"  'What % of ALL closed deals have property_history coverage?'")
print(f"  → {coverage_closing_transition:.1f}% have closing transition in property_history")
print(f"  → {100 - coverage_closing_transition:.1f}% lack historical records")
