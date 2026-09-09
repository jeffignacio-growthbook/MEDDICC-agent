#!/usr/bin/env python3
"""
Test hybrid approach on the original 9 deals that revealed the bug.

Tests both:
1. Pure property_history approach (returns 'unknown' for all 9)
2. Hybrid approach with close_date fallback (should correctly identify all 9)
"""

import os
import sys
from datetime import date
from dotenv import load_dotenv

load_dotenv()

from supabase import create_client
SUPABASE_URL = os.getenv('SUPABASE_URL')
SUPABASE_KEY = os.getenv('SUPABASE_SERVICE_KEY')
sb = create_client(SUPABASE_URL, SUPABASE_KEY)

# Import the hybrid function
sys.path.insert(0, 'scripts/analytics')
from deal_status_history import get_deal_status_as_of

print("Testing hybrid approach on original 9 deals")
print("=" * 70)

# The 9 deals we know closed between Aug 24-28
test_deals = [
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

aug24 = date.fromisoformat('2026-08-24')
aug28 = date.fromisoformat('2026-08-28')

print("\nThese deals left the snapshot between Aug 24-28.")
print("Testing HYBRID approach (property_history + close_date fallback):\n")

# Load deal data for close_date and current stage
sys.path.insert(0, 'scripts')
from supabase_client import select_all

deals_data = select_all(sb, 'deals', 'deal_id, close_date, stage, deal_status')
deals_dict = {d['deal_id']: d for d in deals_data}

correct = 0
unknown = 0
wrong = 0

for deal_id, value, expected in test_deals:
    deal = deals_dict.get(deal_id)

    # Get close_date and current stage for fallback
    close_date = None
    current_stage = None
    if deal:
        if deal.get('close_date'):
            close_date = date.fromisoformat(deal['close_date'][:10])
        current_stage = deal.get('stage')

    # Test WITHOUT fallback (pure property_history)
    status_24_pure = get_deal_status_as_of(sb, deal_id, aug24)
    status_28_pure = get_deal_status_as_of(sb, deal_id, aug28)

    # Test WITH fallback (hybrid)
    status_24_hybrid = get_deal_status_as_of(sb, deal_id, aug24,
                                             close_date=close_date,
                                             current_stage=current_stage)
    status_28_hybrid = get_deal_status_as_of(sb, deal_id, aug28,
                                             close_date=close_date,
                                             current_stage=current_stage)

    print(f"Deal {deal_id} (${value:,}, expected {expected}):")
    print(f"  Close date: {close_date}")
    print(f"  Current stage: {current_stage}")

    # Show property_history evidence
    result = sb.table('property_history')\
        .select('changed_at, new_value')\
        .eq('deal_id', deal_id)\
        .eq('property_name', 'dealstage')\
        .order('changed_at')\
        .execute()

    if result.data:
        print(f"  Property_history: {len(result.data)} changes")
        first_stage = result.data[0]
        last_stage = result.data[-1]
        print(f"    First: {first_stage['changed_at'][:10]} → {first_stage['new_value']}")
        print(f"    Last:  {last_stage['changed_at'][:10]} → {last_stage['new_value']}")
    else:
        print(f"  Property_history: No records")

    print(f"  Pure approach (property_history only):")
    print(f"    Aug 24: {status_24_pure}, Aug 28: {status_28_pure}")

    print(f"  Hybrid approach (with close_date fallback):")
    print(f"    Aug 24: {status_24_hybrid}, Aug 28: {status_28_hybrid}")

    # Check if hybrid approach resolves the issue
    if status_28_hybrid == expected:
        print(f"  ✓ HYBRID WORKS: Correctly identified as {expected}")
        correct += 1
    elif status_28_hybrid == 'unknown':
        print(f"  ⚠️  HYBRID RETURNS UNKNOWN (fallback didn't help)")
        unknown += 1
    else:
        print(f"  ✗ HYBRID WRONG (expected {expected}, got {status_28_hybrid})")
        wrong += 1
    print()

print("=" * 70)
print(f"Hybrid approach results: {correct} correct, {unknown} unknown, {wrong} wrong")

if correct == len(test_deals):
    print(f"\n✓ HYBRID APPROACH SOLVES THE PROBLEM")
    print(f"  All 9 deals correctly identified using close_date fallback")
    print(f"  This resolves the original $830K discrepancy")
elif correct > 0:
    print(f"\n⚠️  HYBRID APPROACH PARTIALLY WORKS")
    print(f"  Resolved {correct}/{len(test_deals)} deals")
    print(f"  {unknown} still return 'unknown', {wrong} return wrong status")
else:
    print(f"\n✗ HYBRID APPROACH DOES NOT HELP")
    print(f"  All deals still return 'unknown' or wrong status")

# Analyze WHY hybrid might not work
if unknown > 0 or wrong > 0:
    print(f"\n" + "=" * 70)
    print(f"Investigating why hybrid approach didn't resolve all cases:")

    for deal_id, value, expected in test_deals:
        status_hybrid = get_deal_status_as_of(sb, deal_id, aug28,
                                              close_date=deals_dict.get(deal_id, {}).get('close_date') and
                                              date.fromisoformat(deals_dict[deal_id]['close_date'][:10]) if deals_dict.get(deal_id, {}).get('close_date') else None,
                                              current_stage=deals_dict.get(deal_id, {}).get('stage'))

        if status_hybrid != expected:
            deal = deals_dict.get(deal_id, {})
            close_date_str = deal.get('close_date')
            close_date = date.fromisoformat(close_date_str[:10]) if close_date_str else None
            current_stage = deal.get('stage')

            print(f"\n  Deal {deal_id} (expected {expected}, got {status_hybrid}):")

            if not close_date:
                print(f"    ✗ NO close_date in deals table")
            elif close_date > aug28:
                print(f"    ✗ close_date {close_date} is AFTER Aug 28 (shouldn't use current status)")
            else:
                print(f"    ✓ close_date {close_date} is before/on Aug 28")

            if not current_stage:
                print(f"    ✗ NO current stage in deals table")
            else:
                print(f"    Current stage: {current_stage}")

                # Check if current stage matches expected
                sys.path.insert(0, 'api')
                from field_semantics import is_won, is_lost

                if expected == 'won' and not is_won(current_stage):
                    print(f"    ✗ Expected won but current stage '{current_stage}' is not classified as won")
                elif expected == 'lost' and not is_lost(current_stage):
                    print(f"    ✗ Expected lost but current stage '{current_stage}' is not classified as lost")
                else:
                    print(f"    ✓ Current stage classification matches expected outcome")
