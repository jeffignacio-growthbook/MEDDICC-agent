#!/usr/bin/env python3
"""
Definitive property_history coverage analysis with careful pagination handling.

The previous analyses showed inconsistent numbers. This script:
1. Uses select_all to handle pagination correctly
2. Reconciles the data quality issues
3. Answers the user's three questions definitively
"""

import os
from datetime import datetime, date, timedelta
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

print("DEFINITIVE property_history coverage analysis")
print("=" * 70)

# Use select_all to handle pagination
print("\n1. Loading data with proper pagination handling...")

all_deals = select_all(sb, 'deals', 'deal_id, deal_status, close_date, created_at, deal_value')
closed_deals = [d for d in all_deals if d.get('deal_status') in ['won', 'lost']]

# Load ALL property_history records for dealstage
ph_records = select_all(sb, 'property_history', 'deal_id, changed_at, old_value, new_value',
                        filters=[('eq', 'property_name', 'dealstage')])

print(f"   Total deals: {len(all_deals)}")
print(f"   Closed deals: {len(closed_deals)}")
print(f"   Property_history dealstage records: {len(ph_records)}")

# Build index
ph_by_deal = defaultdict(list)
for record in ph_records:
    ph_by_deal[record['deal_id']].append(record)

print(f"   Unique deals with property_history: {len(ph_by_deal)}")

# QUESTION 1: Do the SAME 9 deals return 'unknown'?
print(f"\n2. Question 1: Do the original 9 deals return 'unknown'?")

original_9_deals = [
    ('59860100786', 20000, 'won'),
    ('58630730677', 60000, 'won'),
    ('62921497713', 100000, 'lost'),
    ('59171632668', 50000, 'lost'),
    ('62296851044', 150000, 'lost'),
    ('63120688011', 250000, 'lost'),
    ('62741857928', 50000, 'lost'),
    ('59019110029', 75000, 'lost'),
    ('58867845224', 75000, 'lost'),
]

all_unknown = True
for deal_id, value, expected in original_9_deals:
    has_ph = deal_id in ph_by_deal
    if has_ph:
        all_unknown = False
        print(f"   Deal {deal_id}: HAS property_history (unexpected!)")
    else:
        print(f"   Deal {deal_id}: NO property_history (returns 'unknown')")

print(f"\n   ANSWER: {'YES' if all_unknown else 'NO'}, all 9 deals return 'unknown'")
if all_unknown:
    print(f"   → The fix as built does NOT resolve the original problem")
    print(f"   → It makes the failure honest (unknown) instead of wrong (active)")

# QUESTION 2: What % of ALL closed deals have property_history coverage?
print(f"\n3. Question 2: What % of closed deals have property_history?")

# Check for closing transitions
closed_stages = ['closedwon', 'closedlost', 'closed won', 'closed lost', 'won', 'lost']

deals_with_closing_transition = 0
for deal in closed_deals:
    deal_id = deal['deal_id']
    records = ph_by_deal.get(deal_id, [])

    for record in records:
        new_val = (record.get('new_value') or '').lower()
        if any(closed in new_val for closed in closed_stages):
            deals_with_closing_transition += 1
            break

coverage_any = (len([d for d in closed_deals if d['deal_id'] in ph_by_deal]) / len(closed_deals) * 100)
coverage_closing = (deals_with_closing_transition / len(closed_deals) * 100)

print(f"   Closed deals with ANY property_history: {len([d for d in closed_deals if d['deal_id'] in ph_by_deal])}/{len(closed_deals)} ({coverage_any:.1f}%)")
print(f"   Closed deals with CLOSING transition: {deals_with_closing_transition}/{len(closed_deals)} ({coverage_closing:.1f}%)")

print(f"\n   ANSWER: {coverage_closing:.1f}% of closed deals have closing transition in property_history")
print(f"   → {100 - coverage_closing:.1f}% lack historical records and will return 'unknown'")

# QUESTION 3: WHY is coverage poor? Sync lag or structural gap?
print(f"\n4. Question 3: Why is coverage poor?")

# Check temporal pattern
if ph_records:
    timestamps = [datetime.fromisoformat(r['changed_at'].replace('Z', '+00:00')).date()
                  for r in ph_records if r.get('changed_at')]
    earliest_ph = min(timestamps)
    latest_ph = max(timestamps)
    days_active = (date.today() - earliest_ph).days

    print(f"   Property_history date range: {earliest_ph} to {latest_ph} ({days_active} days)")

# Check recent vs old coverage
cutoff_90d = date.today() - timedelta(days=90)
cutoff_180d = date.today() - timedelta(days=180)

recent_90d = [d for d in closed_deals
              if d.get('close_date') and date.fromisoformat(d['close_date'][:10]) >= cutoff_90d]
recent_180d = [d for d in closed_deals
               if d.get('close_date') and date.fromisoformat(d['close_date'][:10]) >= cutoff_180d]
old_deals = [d for d in closed_deals
             if d.get('close_date') and date.fromisoformat(d['close_date'][:10]) < cutoff_180d]

recent_90d_with_ph = len([d for d in recent_90d if d['deal_id'] in ph_by_deal])
recent_180d_with_ph = len([d for d in recent_180d if d['deal_id'] in ph_by_deal])
old_with_ph = len([d for d in old_deals if d['deal_id'] in ph_by_deal])

coverage_90d = (recent_90d_with_ph / len(recent_90d) * 100) if recent_90d else 0
coverage_180d = (recent_180d_with_ph / len(recent_180d) * 100) if recent_180d else 0
coverage_old = (old_with_ph / len(old_deals) * 100) if old_deals else 0

print(f"\n   Coverage by deal age:")
print(f"     Last 90 days:  {recent_90d_with_ph}/{len(recent_90d)} ({coverage_90d:.1f}%)")
print(f"     Last 180 days: {recent_180d_with_ph}/{len(recent_180d)} ({coverage_180d:.1f}%)")
print(f"     Older deals:   {old_with_ph}/{len(old_deals)} ({coverage_old:.1f}%)")

# Check the original 9 deals' close dates
print(f"\n   Original 9 deals' close dates:")
for deal_id, value, expected in original_9_deals[:3]:  # Just show first 3
    matching = [d for d in closed_deals if d['deal_id'] == deal_id]
    if matching:
        close_date = matching[0].get('close_date', 'unknown')
        print(f"     Deal {deal_id}: closed {close_date}")

# DIAGNOSIS
print(f"\n" + "=" * 70)
print("ROOT CAUSE DIAGNOSIS:")

if coverage_90d < 10 and coverage_old < 10:
    print(f"✗ CRITICAL: Property_history has {coverage_90d:.1f}% coverage even for RECENT deals")
    print(f"  This is a STRUCTURAL GAP, not a recency issue")
    print(f"  Property_history is NOT a viable data source for this use case")
    print(f"\n  ANSWER to 'WHY?': Property_history likely:")
    print(f"    - Only tracks SOME deal types (by source, integration, etc)")
    print(f"    - Only tracks deals touched in certain ways")
    print(f"    - Has a fundamental limitation preventing full coverage")
elif coverage_90d > coverage_old + 20:
    print(f"✓ Property_history coverage improving over time:")
    print(f"  Recent (90d): {coverage_90d:.1f}%")
    print(f"  Old: {coverage_old:.1f}%")
    print(f"\n  ANSWER to 'WHY?': Property_history sync started/improved recently")
    print(f"    - Historical deals pre-date the sync")
    print(f"    - Recent deals have better coverage")
    print(f"    - But even {coverage_90d:.1f}% is not sufficient for reliable tracking")
else:
    print(f"⚠️  Property_history coverage is STABLE but LOW:")
    print(f"  Recent (90d): {coverage_90d:.1f}%")
    print(f"  Old: {coverage_old:.1f}%")
    print(f"\n  ANSWER to 'WHY?': Structural limitation, not timing")
    print(f"    - Coverage is consistently low across all time periods")
    print(f"    - Property_history only captures a minority of deals")

print(f"\n" + "=" * 70)
print("RECOMMENDATION:")

if coverage_90d >= 80:
    print(f"→ Option A (property_history fix) is VIABLE")
    print(f"  Recent coverage is {coverage_90d:.1f}%, sufficient for current operations")
    print(f"  Historical gaps are acceptable limitation")
elif coverage_90d >= 50:
    print(f"→ Option A is MARGINAL")
    print(f"  Will fix {coverage_90d:.1f}% of recent cases")
    print(f"  But {100-coverage_90d:.1f}% will still return 'unknown'")
    print(f"  Need user decision: is {coverage_90d:.1f}% good enough?")
else:
    print(f"→ Option C (alternative approach) is REQUIRED")
    print(f"  Property_history only covers {coverage_90d:.1f}% of recent deals")
    print(f"  Even for current operations, this is insufficient")
    print(f"  The original 9 deals ALL returned 'unknown' because they're in the {100-coverage_90d:.1f}% without coverage")

# Check if the 9 deals are genuinely recent
print(f"\n" + "=" * 70)
print("SPECIFIC CHECK: Are the original 9 deals recent enough to expect coverage?")

aug_24 = date.fromisoformat('2026-08-24')
for deal_id, value, expected in original_9_deals:
    matching = [d for d in closed_deals if d['deal_id'] == deal_id]
    if matching:
        close_date_str = matching[0].get('close_date')
        if close_date_str:
            close_date = date.fromisoformat(close_date_str[:10])
            days_ago = (date.today() - close_date).days
            is_recent = days_ago <= 90

            has_ph = deal_id in ph_by_deal

            marker = "✓ RECENT" if is_recent else "OLD"
            coverage_marker = "HAS PH" if has_ph else "NO PH"

            print(f"  Deal {deal_id}: closed {close_date} ({days_ago}d ago) [{marker}] [{coverage_marker}]")

print(f"\n  If these deals are RECENT but still have NO property_history:")
print(f"  → Confirms property_history coverage is insufficient even for current ops")
