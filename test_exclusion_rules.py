#!/usr/bin/env python3
"""
Test exclusion rules between movement categories.

Verifies that deals are assigned to EXACTLY ONE category, never double-counted:
1. newly_arr_bearing vs arr_change: $0→value should be ONE category, not both
2. won/lost vs arr_change: deals that close should NOT also contribute to arr_change

These are the exact assumptions that caused today's bugs - verify them explicitly.
"""

import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent / 'scripts' / 'analytics'))

from arr_delta import arr_delta

print("Testing Exclusion Rules for Movement Categories")
print("=" * 70)

# Test 1: newly_arr_bearing vs arr_change exclusion
print("\nTest 1: newly_arr_bearing vs arr_change")
print("-" * 70)
print("A deal going $0→$100K should be EXACTLY ONE of:")
print("  - newly_arr_bearing (if stage_order crossed threshold)")
print("  - arr_increase (if stage_order didn't cross)")
print("Never both, never double-counted.")
print()

test_cases_1 = [
    {
        'name': '$0→$100K with stage crossing',
        'prev': {'deal_value': 0, 'stage_order': 1, 'deal_status': 'active'},
        'curr': {'deal_value': 100000, 'stage_order': 2, 'deal_status': 'active'},
        'expected_category': 'newly_arr_bearing',
        'expected_delta': None,
        'reason': 'Stage crossed threshold - this is newly_arr_bearing'
    },
    {
        'name': '$0→$100K without stage crossing',
        'prev': {'deal_value': 0, 'stage_order': 3, 'deal_status': 'active'},
        'curr': {'deal_value': 100000, 'stage_order': 3, 'deal_status': 'active'},
        'expected_category': 'arr_increase',
        'expected_delta': 100000,
        'reason': 'No stage crossing - this is arr_increase'
    },
]

passed_1 = 0
for test in test_cases_1:
    delta, category = arr_delta('test', test['prev'], test['curr'])

    if category == test['expected_category'] and delta == test['expected_delta']:
        print(f"✓ PASS: {test['name']}")
        print(f"    Category: {category} (correct)")
        print(f"    Delta: {delta} (correct)")
        print(f"    Reason: {test['reason']}")
        passed_1 += 1
    else:
        print(f"✗ FAIL: {test['name']}")
        print(f"    Expected: category={test['expected_category']}, delta={test['expected_delta']}")
        print(f"    Got:      category={category}, delta={delta}")
    print()

if passed_1 == len(test_cases_1):
    print(f"✓ Exclusion Rule 1 VERIFIED: newly_arr_bearing and arr_change are mutually exclusive")
else:
    print(f"✗ Exclusion Rule 1 FAILED: Categories may overlap")

# Test 2: won/lost vs arr_change exclusion
print("\n" + "=" * 70)
print("\nTest 2: won/lost vs arr_change")
print("-" * 70)
print("A deal that closes won/lost should:")
print("  - Be captured in won_value/lost_value")
print("  - NOT also contribute to arr_change")
print("Even if its value changed in the same week.")
print()

test_cases_2 = [
    {
        'name': '$100K→$150K and closes won (value change + won)',
        'prev': {'deal_value': 100000, 'stage_order': 3, 'deal_status': 'active'},
        'curr': {'deal_value': 150000, 'stage_order': 4, 'deal_status': 'won'},
        'should_contribute_to_arr_change': False,
        'reason': 'Deal closed won - should only contribute to won_value, not arr_change'
    },
    {
        'name': '$100K→$80K and closes lost (value change + lost)',
        'prev': {'deal_value': 100000, 'stage_order': 3, 'deal_status': 'active'},
        'curr': {'deal_value': 80000, 'stage_order': 0, 'deal_status': 'lost'},
        'should_contribute_to_arr_change': False,
        'reason': 'Deal closed lost - should only contribute to lost_value, not arr_change'
    },
    {
        'name': '$100K→$0 and closes won (value→$0 + won)',
        'prev': {'deal_value': 100000, 'stage_order': 3, 'deal_status': 'active'},
        'curr': {'deal_value': 0, 'stage_order': 4, 'deal_status': 'won'},
        'should_contribute_to_arr_change': False,
        'reason': 'Deal closed won - should only contribute to won_value, not arr_change'
    },
    {
        'name': '$100K→$150K and stays active (value change, no won/lost)',
        'prev': {'deal_value': 100000, 'stage_order': 3, 'deal_status': 'active'},
        'curr': {'deal_value': 150000, 'stage_order': 3, 'deal_status': 'active'},
        'should_contribute_to_arr_change': True,
        'reason': 'Deal stayed active - should contribute to arr_change'
    },
]

passed_2 = 0
failed_2 = []

for test in test_cases_2:
    delta, category = arr_delta('test', test['prev'], test['curr'])

    # Check if delta would contribute to arr_change
    contributes_to_arr_change = (delta is not None and abs(delta) > 0.01)

    expected = test['should_contribute_to_arr_change']

    if contributes_to_arr_change == expected:
        print(f"✓ PASS: {test['name']}")
        print(f"    Category: {category}")
        print(f"    Delta: {delta}")
        print(f"    Contributes to arr_change: {contributes_to_arr_change} (correct)")
        print(f"    Reason: {test['reason']}")
        passed_2 += 1
    else:
        print(f"✗ FAIL: {test['name']}")
        print(f"    Expected contributes to arr_change: {expected}")
        print(f"    Got contributes to arr_change: {contributes_to_arr_change}")
        print(f"    Category: {category}, Delta: {delta}")
        failed_2.append(test)
    print()

if passed_2 == len(test_cases_2):
    print(f"✓ Exclusion Rule 2 VERIFIED: won/lost and arr_change are mutually exclusive")
else:
    print(f"✗ Exclusion Rule 2 FAILED: {len(failed_2)} cases allow double-counting")
    print(f"\nFailed cases reveal BUG:")
    for test in failed_2:
        print(f"  - {test['name']}")

print("\n" + "=" * 70)
print("SUMMARY")
print("=" * 70)

if passed_1 == len(test_cases_1) and passed_2 == len(test_cases_2):
    print("✓ ALL EXCLUSION RULES VERIFIED")
    print("  Categories are mutually exclusive by construction")
    print("  No double-counting possible")
    print("\nReady for integration")
    exit(0)
else:
    print("✗ EXCLUSION RULES VIOLATED")
    print("  arr_delta function needs fixes before integration")
    print("\nAction items:")
    if passed_1 < len(test_cases_1):
        print("  1. Fix newly_arr_bearing vs arr_change exclusion")
    if passed_2 < len(test_cases_2):
        print("  2. Fix won/lost vs arr_change exclusion")
        print("     → Check won/lost status FIRST before computing deltas")
    exit(1)
