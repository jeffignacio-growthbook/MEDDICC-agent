#!/usr/bin/env python3
"""
Analyze hybrid approach coverage across ALL closed deals.

Compare:
1. Pure property_history: 43.7% coverage
2. Hybrid (property_history + close_date fallback): ?% coverage

This tells us if the hybrid approach is viable for general use.
"""

import os
from datetime import datetime, date
from dotenv import load_dotenv

load_dotenv()

from supabase import create_client
SUPABASE_URL = os.getenv('SUPABASE_URL')
SUPABASE_KEY = os.getenv('SUPABASE_SERVICE_KEY')
sb = create_client(SUPABASE_URL, SUPABASE_KEY)

import sys
sys.path.insert(0, 'scripts')
from supabase_client import select_all

sys.path.insert(0, 'api')
from field_semantics import is_won, is_lost

print("Hybrid approach coverage analysis")
print("=" * 70)

# Load all closed deals
print("\n1. Loading closed deals...")
all_deals = select_all(sb, 'deals', 'deal_id, deal_status, close_date, stage')
closed_deals = [d for d in all_deals if d.get('deal_status') in ['won', 'lost']]

print(f"   Total closed deals: {len(closed_deals)}")

# Load property_history
ph_records = select_all(sb, 'property_history', 'deal_id, changed_at, new_value',
                        filters=[('eq', 'property_name', 'dealstage')])

ph_by_deal = {}
for record in ph_records:
    deal_id = record['deal_id']
    if deal_id not in ph_by_deal:
        ph_by_deal[deal_id] = []
    ph_by_deal[deal_id].append(record)

print(f"   Deals with property_history: {len(ph_by_deal)}")

# Analyze coverage
print("\n2. Analyzing coverage...")

pure_resolvable = 0  # Deals with property_history showing closing transition
hybrid_resolvable = 0  # Deals resolvable via property_history OR close_date
unresolvable = 0  # Deals with neither property_history nor valid close_date

closed_stages = ['closedwon', 'closedlost', 'closed won', 'closed lost', 'won', 'lost']

for deal in closed_deals:
    deal_id = deal['deal_id']
    close_date_str = deal.get('close_date')
    current_stage = deal.get('stage')

    # Check property_history
    has_ph_closing = False
    records = ph_by_deal.get(deal_id, [])
    for record in records:
        new_val = (record.get('new_value') or '').lower()
        if any(closed in new_val for closed in closed_stages):
            has_ph_closing = True
            break

    # Check close_date + current_stage fallback
    has_close_date_fallback = False
    if close_date_str and current_stage:
        # Verify current_stage is won/lost (as expected for closed deals)
        if is_won(current_stage) or is_lost(current_stage):
            has_close_date_fallback = True

    # Categorize
    if has_ph_closing:
        pure_resolvable += 1
        hybrid_resolvable += 1
    elif has_close_date_fallback:
        # Resolvable ONLY via hybrid approach
        hybrid_resolvable += 1
    else:
        unresolvable += 1

pure_coverage = (pure_resolvable / len(closed_deals) * 100)
hybrid_coverage = (hybrid_resolvable / len(closed_deals) * 100)

print(f"\n3. Coverage comparison:")
print(f"   Pure property_history: {pure_resolvable}/{len(closed_deals)} ({pure_coverage:.1f}%)")
print(f"   Hybrid approach: {hybrid_resolvable}/{len(closed_deals)} ({hybrid_coverage:.1f}%)")
print(f"   Still unresolvable: {unresolvable}/{len(closed_deals)} ({unresolvable/len(closed_deals)*100:.1f}%)")

print(f"\n   Improvement from hybrid: +{hybrid_coverage - pure_coverage:.1f}%")

# Check what's unresolvable
if unresolvable > 0:
    print(f"\n4. Why are {unresolvable} deals still unresolvable?")

    missing_close_date = 0
    missing_stage = 0
    stage_not_closed = 0

    for deal in closed_deals:
        deal_id = deal['deal_id']
        close_date_str = deal.get('close_date')
        current_stage = deal.get('stage')

        # Check if this deal is unresolvable
        records = ph_by_deal.get(deal_id, [])
        has_ph_closing = False
        for record in records:
            new_val = (record.get('new_value') or '').lower()
            if any(closed in new_val for closed in closed_stages):
                has_ph_closing = True
                break

        has_close_date_fallback = False
        if close_date_str and current_stage:
            if is_won(current_stage) or is_lost(current_stage):
                has_close_date_fallback = True

        if not has_ph_closing and not has_close_date_fallback:
            # This deal is unresolvable - why?
            if not close_date_str:
                missing_close_date += 1
            elif not current_stage:
                missing_stage += 1
            elif not (is_won(current_stage) or is_lost(current_stage)):
                stage_not_closed += 1

    print(f"   Missing close_date: {missing_close_date}")
    print(f"   Missing current stage: {missing_stage}")
    print(f"   Stage not classified as won/lost: {stage_not_closed}")

    if missing_close_date > 0:
        print(f"\n   ⚠️  {missing_close_date} closed deals have no close_date")
        print(f"      This is a data quality issue in deals table")
    if stage_not_closed > 0:
        print(f"\n   ⚠️  {stage_not_closed} closed deals have stage not classified as won/lost")
        print(f"      This suggests deal_status and stage are out of sync")

print(f"\n" + "=" * 70)
print("CONCLUSION:")

if hybrid_coverage >= 95:
    print(f"✓ Hybrid approach achieves EXCELLENT coverage ({hybrid_coverage:.1f}%)")
    print(f"  This resolves the won/lost detection bug for nearly all cases")
    print(f"  Remaining {100-hybrid_coverage:.1f}% are data quality issues, not logic bugs")
elif hybrid_coverage >= 80:
    print(f"✓ Hybrid approach achieves GOOD coverage ({hybrid_coverage:.1f}%)")
    print(f"  Significantly better than pure property_history ({pure_coverage:.1f}%)")
    print(f"  Remaining {100-hybrid_coverage:.1f}% likely have data quality issues")
elif hybrid_coverage >= 60:
    print(f"⚠️  Hybrid approach achieves MODERATE coverage ({hybrid_coverage:.1f}%)")
    print(f"  Better than property_history alone, but {100-hybrid_coverage:.1f}% still unresolvable")
    print(f"  Need to investigate data quality issues")
else:
    print(f"✗ Hybrid approach still has LOW coverage ({hybrid_coverage:.1f}%)")
    print(f"  Only +{hybrid_coverage - pure_coverage:.1f}% improvement over property_history")
    print(f"  May need alternative approach")

print(f"\nRECOMMENDATION:")
if hybrid_coverage >= 90:
    print(f"→ Proceed with hybrid approach")
    print(f"  {hybrid_coverage:.1f}% coverage is sufficient for production use")
    print(f"  Remaining gaps are acceptable data quality limitations")
elif hybrid_coverage >= 80:
    print(f"→ Proceed with hybrid approach, monitor data quality")
    print(f"  {hybrid_coverage:.1f}% coverage is workable")
    print(f"  Investigate/fix the {100-hybrid_coverage:.1f}% unresolvable cases")
else:
    print(f"→ Investigate unresolvable cases before proceeding")
    print(f"  {100-hybrid_coverage:.1f}% unresolvable is too high")
    print(f"  Need to understand root cause and potentially fix data quality issues")
