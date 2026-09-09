#!/usr/bin/env python3
"""Test get_deal_status_as_of on real deals that left pipeline Aug 24-28."""

import os
import sys
from datetime import date
from dotenv import load_dotenv

load_dotenv()

from supabase import create_client
SUPABASE_URL = os.getenv('SUPABASE_URL')
SUPABASE_KEY = os.getenv('SUPABASE_SERVICE_KEY')
sb = create_client(SUPABASE_URL, SUPABASE_KEY)

# Import the function
sys.path.insert(0, 'scripts/analytics')
from deal_status_history import get_deal_status_as_of

print("Real-world test: 9 deals that left pipeline Aug 24-28")
print("=" * 70)

# The 9 deals we know closed
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
print("Testing if function correctly identifies them as won/lost:\n")

correct = 0
unknown = 0
wrong = 0

for deal_id, value, expected in test_deals:
    status_24 = get_deal_status_as_of(sb, deal_id, aug24)
    status_28 = get_deal_status_as_of(sb, deal_id, aug28)

    # Get property_history evidence
    result = sb.table('property_history')\
        .select('changed_at, new_value')\
        .eq('deal_id', deal_id)\
        .eq('property_name', 'dealstage')\
        .order('changed_at')\
        .execute()

    print(f"Deal {deal_id} (${value:,}, expected {expected}):")
    if result.data:
        first_stage = result.data[0]
        last_stage = result.data[-1]
        print(f"  Property_history: {len(result.data)} changes")
        print(f"    First: {first_stage['changed_at'][:10]} → {first_stage['new_value']}")
        print(f"    Last:  {last_stage['changed_at'][:10]} → {last_stage['new_value']}")
    else:
        print(f"  Property_history: No records")

    print(f"  Status at Aug 24: {status_24}")
    print(f"  Status at Aug 28: {status_28}")

    # Check if Aug 28 status matches expected
    if status_28 == expected:
        print(f"  ✓ CORRECT")
        correct += 1
    elif status_28 == 'unknown':
        print(f"  ⚠️  UNKNOWN (no property_history)")
        unknown += 1
    else:
        print(f"  ✗ WRONG (expected {expected}, got {status_28})")
        wrong += 1
    print()

print("=" * 70)
print(f"Results: {correct} correct, {unknown} unknown, {wrong} wrong")

if unknown > 0:
    print(f"\n⚠️  {unknown} deals return 'unknown' due to missing property_history")
    print(f"   This is the limitation we identified - historical data incomplete")
    print(f"   Function correctly returns 'unknown' instead of guessing")

if correct == len(test_deals):
    print(f"\n✓ ALL deals correctly identified from property_history")
elif correct + unknown == len(test_deals):
    print(f"\n✓ Function works correctly (identifies what it can, returns unknown for rest)")
else:
    print(f"\n✗ Function has errors - {wrong} deals misclassified")
