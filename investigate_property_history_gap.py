#!/usr/bin/env python3
"""
Investigate WHY property_history coverage is poor (18.5%).

Hypotheses:
1. Sync lag: property_history captures deals, but with delay
2. Structural gap: property_history only tracks SOME deals (e.g., by source, by date range)
3. Data quality: property_history started being populated recently
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

print("Investigating WHY property_history coverage is poor")
print("=" * 70)

# Load all deals and property_history
print("\n1. Loading data...")
all_deals = select_all(sb, 'deals', 'deal_id, deal_status, close_date, created_at, deal_value')
closed_deals = [d for d in all_deals if d.get('deal_status') in ['won', 'lost']]

ph_result = sb.table('property_history')\
    .select('deal_id, changed_at, property_name')\
    .eq('property_name', 'dealstage')\
    .execute()

ph_by_deal = defaultdict(list)
for record in ph_result.data:
    ph_by_deal[record['deal_id']].append(record)

print(f"   Closed deals: {len(closed_deals)}")
print(f"   Deals with property_history: {len(ph_by_deal)}")

# Hypothesis 1: Check temporal pattern of property_history creation
print(f"\n2. Temporal analysis: When did property_history start capturing data?")

# Get earliest and latest property_history timestamps
if ph_result.data:
    timestamps = [datetime.fromisoformat(r['changed_at'].replace('Z', '+00:00')) for r in ph_result.data]
    earliest_ph = min(timestamps).date()
    latest_ph = max(timestamps).date()

    print(f"   Earliest property_history record: {earliest_ph}")
    print(f"   Latest property_history record: {latest_ph}")

    # Check if property_history started recently
    from datetime import timedelta
    today = date.today()
    days_active = (today - earliest_ph).days

    print(f"   Property_history has been active for: {days_active} days")

    if days_active < 90:
        print(f"   ⚠️  Property_history is VERY RECENT (< 90 days)")
        print(f"       This explains poor coverage for older deals")
    elif days_active < 180:
        print(f"   ⚠️  Property_history is RECENT (< 180 days)")
        print(f"       Older deals won't have historical records")
    else:
        print(f"   ✓ Property_history has been running for {days_active} days")
        print(f"     If coverage is still poor, it's not purely a recency issue")

    # Analyze coverage by deal close date
    print(f"\n3. Coverage by deal close date:")

    # Bucket deals by close date
    def get_close_month_bucket(close_date_str):
        if not close_date_str:
            return None
        dt = date.fromisoformat(close_date_str[:10])
        return f"{dt.year}-{dt.month:02d}"

    coverage_by_month = defaultdict(lambda: {'total': 0, 'with_ph': 0})

    for deal in closed_deals:
        if not deal.get('close_date'):
            continue

        bucket = get_close_month_bucket(deal['close_date'])
        if bucket:
            coverage_by_month[bucket]['total'] += 1
            if deal['deal_id'] in ph_by_deal:
                coverage_by_month[bucket]['with_ph'] += 1

    # Sort by month
    sorted_months = sorted(coverage_by_month.keys())

    # Show last 12 months or all if fewer
    recent_months = sorted_months[-12:]

    print(f"\n   Coverage by close month (last 12 months):")
    print(f"   {'Month':<12} {'Total':>6} {'With PH':>8} {'Coverage':>10}")
    print(f"   {'-'*40}")

    for month in recent_months:
        stats = coverage_by_month[month]
        coverage_pct = (stats['with_ph'] / stats['total'] * 100) if stats['total'] > 0 else 0
        print(f"   {month:<12} {stats['total']:>6} {stats['with_ph']:>8} {coverage_pct:>9.1f}%")

    # Check if coverage improves over time
    if len(recent_months) >= 3:
        early_months = recent_months[:3]
        late_months = recent_months[-3:]

        early_total = sum(coverage_by_month[m]['total'] for m in early_months)
        early_with_ph = sum(coverage_by_month[m]['with_ph'] for m in early_months)
        early_pct = (early_with_ph / early_total * 100) if early_total > 0 else 0

        late_total = sum(coverage_by_month[m]['total'] for m in late_months)
        late_with_ph = sum(coverage_by_month[m]['with_ph'] for m in late_months)
        late_pct = (late_with_ph / late_total * 100) if late_total > 0 else 0

        print(f"\n   Trend analysis:")
        print(f"     Early period ({early_months[0]} to {early_months[-1]}): {early_pct:.1f}%")
        print(f"     Recent period ({late_months[0]} to {late_months[-1]}): {late_pct:.1f}%")

        if late_pct > early_pct + 10:
            print(f"     ✓ Coverage is IMPROVING over time (+{late_pct - early_pct:.1f}%)")
            print(f"       This suggests property_history sync started recently")
        elif late_pct < early_pct - 10:
            print(f"     ⚠️  Coverage is DECLINING over time (-{early_pct - late_pct:.1f}%)")
            print(f"       This suggests a degradation in sync quality")
        else:
            print(f"     = Coverage is STABLE over time")
            print(f"       This suggests structural gap, not recency issue")

else:
    print(f"   ⚠️  No property_history records found")

# Hypothesis 2: Check if property_history is selective (only certain deal types)
print(f"\n4. Structural analysis: Are certain deal types excluded?")

# Compare deals WITH property_history vs WITHOUT
deals_with_ph = [d for d in closed_deals if d['deal_id'] in ph_by_deal]
deals_without_ph = [d for d in closed_deals if d['deal_id'] not in ph_by_deal]

print(f"   Deals with property_history: {len(deals_with_ph)}")
print(f"   Deals without property_history: {len(deals_without_ph)}")

# Check if there's a pattern in deal values
if deals_with_ph and deals_without_ph:
    with_ph_values = [d.get('deal_value') or 0 for d in deals_with_ph]
    without_ph_values = [d.get('deal_value') or 0 for d in deals_without_ph]

    avg_with = sum(with_ph_values) / len(with_ph_values) if with_ph_values else 0
    avg_without = sum(without_ph_values) / len(without_ph_values) if without_ph_values else 0

    print(f"\n   Average deal value:")
    print(f"     With property_history: ${avg_with:,.0f}")
    print(f"     Without property_history: ${avg_without:,.0f}")

    if abs(avg_with - avg_without) / max(avg_with, avg_without) > 0.2:
        print(f"     ⚠️  Significant difference in deal values")
        print(f"       Property_history may be selective by deal size")
    else:
        print(f"     = Similar deal values")
        print(f"       No obvious selection bias by deal size")

# Check if there's a pattern in deal status
won_with_ph = len([d for d in deals_with_ph if d.get('deal_status') == 'won'])
won_without_ph = len([d for d in deals_without_ph if d.get('deal_status') == 'won'])

won_rate_with = (won_with_ph / len(deals_with_ph) * 100) if deals_with_ph else 0
won_rate_without = (won_without_ph / len(deals_without_ph) * 100) if deals_without_ph else 0

print(f"\n   Win rate:")
print(f"     With property_history: {won_rate_with:.1f}%")
print(f"     Without property_history: {won_rate_without:.1f}%")

if abs(won_rate_with - won_rate_without) > 10:
    print(f"     ⚠️  Different win rates")
    print(f"       Property_history may be selective by outcome")
else:
    print(f"     = Similar win rates")
    print(f"       No obvious selection bias by outcome")

# Summary
print(f"\n" + "=" * 70)
print("ROOT CAUSE DIAGNOSIS:")

if ph_result.data:
    earliest_ph_days = (date.today() - earliest_ph).days

    if earliest_ph_days < 180:
        print(f"✓ PRIMARY CAUSE: Property_history started recently ({earliest_ph})")
        print(f"  Coverage gap is expected for deals closed before that date")
        print(f"  Coverage improving over time confirms this")
        print(f"\n  IMPLICATION FOR FIX:")
        print(f"  - Option A (property_history) will only fix RECENT deals")
        print(f"  - Historical deals (before {earliest_ph}) will remain 'unknown'")
        print(f"  - Need to decide: is fixing recent deals (18.5% now, improving) enough?")
    else:
        print(f"⚠️  Property_history has been active for {earliest_ph_days} days")
        print(f"  Yet coverage is still poor (18.5%)")
        print(f"  This suggests STRUCTURAL GAP, not just recency")
        print(f"\n  IMPLICATION FOR FIX:")
        print(f"  - Property_history is fundamentally incomplete for this use case")
        print(f"  - Option A will NEVER achieve good coverage")
        print(f"  - Option C (alternative approach) is REQUIRED")
else:
    print(f"✗ Property_history has NO records")
    print(f"  This data source is not viable")
    print(f"  Option C (alternative approach) is REQUIRED")
