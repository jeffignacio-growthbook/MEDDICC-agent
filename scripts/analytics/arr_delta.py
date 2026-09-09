#!/usr/bin/env python3
"""
ARR delta calculation with explicit edge case handling.

Computes the ARR change for a deal between two snapshots, handling:
1. $0 → value: newly_arr_bearing (separate category, returns None for delta)
2. value → $0: ARR decrease if deal still active, otherwise captured in won/lost
3. value → value: straightforward ARR delta
4. NULL handling: treats NULL as $0 for calculation purposes
5. Stage order threshold: deals below threshold are considered pre-ARR-bearing

Edge cases explicitly resolved:
- $0 → $150K with stage_order 1→2: newly_arr_bearing, NOT +$150K delta
- $100K → $0 while active: -$100K delta (ARR churn on active deal)
- $100K → $0 with won/lost: captured in won_value/lost_value, NOT ARR delta
"""

from typing import Optional, Tuple, Dict, Any
from datetime import date


def arr_delta(
    deal_id: str,
    prev_snapshot: Dict[str, Any],
    curr_snapshot: Dict[str, Any],
    qualified_stage_order: int = 2
) -> Tuple[Optional[float], str]:
    """
    Calculate ARR delta for a deal between two snapshots.

    Args:
        deal_id: Deal ID being analyzed
        prev_snapshot: Previous snapshot row (dict with deal_value, stage_order, deal_status, etc.)
        curr_snapshot: Current snapshot row (dict with deal_value, stage_order, deal_status, etc.)
        qualified_stage_order: Stage order threshold for ARR-bearing deals (default: 2)

    Returns:
        Tuple of (delta_amount, category):
            - delta_amount: float ARR change (can be positive, negative, or None)
            - category: str classification of the change
                * 'newly_arr_bearing': $0→value transition with stage threshold crossing
                * 'arr_increase': value increased
                * 'arr_decrease': value decreased
                * 'arr_churn': value went to $0 on active deal
                * 'no_change': no ARR change
                * 'captured_in_won_lost': change handled by won/lost tracking

    Edge case handling:
        - NULL values treated as $0
        - $0 → value with stage_order crossing → newly_arr_bearing (delta=None)
        - $0 → value without stage crossing → arr_increase (delta=value)
        - value → $0 with won/lost status → captured_in_won_lost (delta=None)
        - value → $0 while active → arr_churn (delta=-value)
    """
    # Extract values with NULL handling
    def get_value(snap):
        v = snap.get('deal_value')
        return float(v) if v is not None else 0.0

    def get_stage_order(snap):
        so = snap.get('stage_order')
        return int(so) if so is not None else 0

    def get_status(snap):
        return snap.get('deal_status', 'active')

    prev_value = get_value(prev_snapshot)
    curr_value = get_value(curr_snapshot)
    prev_stage_order = get_stage_order(prev_snapshot)
    curr_stage_order = get_stage_order(curr_snapshot)
    curr_status = get_status(curr_snapshot)

    # CRITICAL: Check won/lost status FIRST before computing any deltas
    # Deals that closed won/lost should ONLY contribute to won_value/lost_value,
    # NEVER to arr_change, even if their value changed in the same week
    if curr_status in ('won', 'lost'):
        return (None, 'captured_in_won_lost')

    # No change case
    if abs(prev_value - curr_value) < 0.01:
        return (None, 'no_change')

    # Case 1: $0 → value (newly ARR-bearing?)
    if prev_value == 0.0 and curr_value > 0.0:
        # Check if this is a stage threshold crossing (early-stage → ARR-bearing)
        if prev_stage_order < qualified_stage_order and curr_stage_order >= qualified_stage_order:
            # This is newly_arr_bearing - separate category, NOT an ARR delta
            return (None, 'newly_arr_bearing')
        else:
            # Deal was already ARR-bearing (or never had stage data), so this is a genuine increase
            return (curr_value, 'arr_increase')

    # Case 2: value → $0 (ARR churn)
    # Note: won/lost already checked above, so this is guaranteed to be an active deal
    if prev_value > 0.0 and curr_value == 0.0:
        # Deal is still active but value went to $0 - this is ARR churn
        return (-prev_value, 'arr_churn')

    # Case 3: value → value (straightforward delta)
    delta = curr_value - prev_value
    if delta > 0:
        return (delta, 'arr_increase')
    else:
        return (delta, 'arr_decrease')


def test_arr_delta():
    """Test cases for arr_delta function."""
    print("Testing arr_delta function...")
    print("=" * 70)

    test_cases = [
        {
            'name': 'Deal #4: $0→$150K with stage crossing (newly_arr_bearing)',
            'prev': {'deal_value': 0, 'stage_order': 1, 'deal_status': 'active'},
            'curr': {'deal_value': 150000, 'stage_order': 2, 'deal_status': 'active'},
            'expected_delta': None,
            'expected_category': 'newly_arr_bearing'
        },
        {
            'name': '$50K→$51K (straightforward increase)',
            'prev': {'deal_value': 50000, 'stage_order': 3, 'deal_status': 'active'},
            'curr': {'deal_value': 51000, 'stage_order': 3, 'deal_status': 'active'},
            'expected_delta': 1000,
            'expected_category': 'arr_increase'
        },
        {
            'name': '$250K→$300K (straightforward increase)',
            'prev': {'deal_value': 250000, 'stage_order': 3, 'deal_status': 'active'},
            'curr': {'deal_value': 300000, 'stage_order': 3, 'deal_status': 'active'},
            'expected_delta': 50000,
            'expected_category': 'arr_increase'
        },
        {
            'name': '$100K→$50K (straightforward decrease)',
            'prev': {'deal_value': 100000, 'stage_order': 3, 'deal_status': 'active'},
            'curr': {'deal_value': 50000, 'stage_order': 3, 'deal_status': 'active'},
            'expected_delta': -50000,
            'expected_category': 'arr_decrease'
        },
        {
            'name': '$100K→$0 on active deal (ARR churn)',
            'prev': {'deal_value': 100000, 'stage_order': 3, 'deal_status': 'active'},
            'curr': {'deal_value': 0, 'stage_order': 3, 'deal_status': 'active'},
            'expected_delta': -100000,
            'expected_category': 'arr_churn'
        },
        {
            'name': '$100K→$0 on won deal (captured in won_value)',
            'prev': {'deal_value': 100000, 'stage_order': 3, 'deal_status': 'active'},
            'curr': {'deal_value': 0, 'stage_order': 4, 'deal_status': 'won'},
            'expected_delta': None,
            'expected_category': 'captured_in_won_lost'
        },
        {
            'name': '$100K→$0 on lost deal (captured in lost_value)',
            'prev': {'deal_value': 100000, 'stage_order': 3, 'deal_status': 'active'},
            'curr': {'deal_value': 0, 'stage_order': 0, 'deal_status': 'lost'},
            'expected_delta': None,
            'expected_category': 'captured_in_won_lost'
        },
        {
            'name': '$100K→$150K on won deal (captured in won_value, not arr_change)',
            'prev': {'deal_value': 100000, 'stage_order': 3, 'deal_status': 'active'},
            'curr': {'deal_value': 150000, 'stage_order': 4, 'deal_status': 'won'},
            'expected_delta': None,
            'expected_category': 'captured_in_won_lost'
        },
        {
            'name': '$100K→$80K on lost deal (captured in lost_value, not arr_change)',
            'prev': {'deal_value': 100000, 'stage_order': 3, 'deal_status': 'active'},
            'curr': {'deal_value': 80000, 'stage_order': 0, 'deal_status': 'lost'},
            'expected_delta': None,
            'expected_category': 'captured_in_won_lost'
        },
        {
            'name': 'NULL→$50K (treated as $0→$50K)',
            'prev': {'deal_value': None, 'stage_order': 2, 'deal_status': 'active'},
            'curr': {'deal_value': 50000, 'stage_order': 2, 'deal_status': 'active'},
            'expected_delta': 50000,
            'expected_category': 'arr_increase'
        },
        {
            'name': '$50K→NULL (treated as $50K→$0 churn)',
            'prev': {'deal_value': 50000, 'stage_order': 2, 'deal_status': 'active'},
            'curr': {'deal_value': None, 'stage_order': 2, 'deal_status': 'active'},
            'expected_delta': -50000,
            'expected_category': 'arr_churn'
        },
        {
            'name': '$0→$100K without stage crossing (regular increase)',
            'prev': {'deal_value': 0, 'stage_order': 3, 'deal_status': 'active'},
            'curr': {'deal_value': 100000, 'stage_order': 3, 'deal_status': 'active'},
            'expected_delta': 100000,
            'expected_category': 'arr_increase'
        },
    ]

    passed = 0
    failed = 0

    for test in test_cases:
        delta, category = arr_delta('test_deal', test['prev'], test['curr'])

        # Check if result matches expected
        delta_matches = (
            (delta is None and test['expected_delta'] is None) or
            (delta is not None and test['expected_delta'] is not None and abs(delta - test['expected_delta']) < 0.01)
        )
        category_matches = category == test['expected_category']

        if delta_matches and category_matches:
            print(f"\n✓ PASS: {test['name']}")
            print(f"    Result: delta={delta}, category={category}")
            passed += 1
        else:
            print(f"\n✗ FAIL: {test['name']}")
            print(f"    Expected: delta={test['expected_delta']}, category={test['expected_category']}")
            print(f"    Got:      delta={delta}, category={category}")
            failed += 1

    print()
    print("=" * 70)
    print(f"Test Results: {passed} passed, {failed} failed")
    print("=" * 70)

    return failed == 0


if __name__ == '__main__':
    success = test_arr_delta()
    exit(0 if success else 1)
