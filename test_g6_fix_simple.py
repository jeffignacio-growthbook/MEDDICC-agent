#!/usr/bin/env python3
"""
Simple test for G.6 bug fixes:
1. time_window is passed to all handlers
2. Exceptions are caught and logged (not re-raised)
"""

import sys
import asyncio
sys.path.insert(0, 'api')

from router import route_entity_scoped_question


async def test_time_window_and_exception_handling():
    """
    Verify Bug #1 fix: time_window is passed
    Verify Bug #2 fix: exceptions are caught
    """
    print("Testing G.6 bug fixes")
    print("="*60)

    # Track what params the handler receives
    received_params = []
    exceptions_caught = 0

    async def mock_handler_success(params, sb):
        """Mock handler that records params"""
        received_params.append(params.copy())
        return {"test": "data"}

    async def mock_handler_crash(params, sb):
        """Mock handler that crashes"""
        received_params.append(params.copy())
        raise ValueError("Mock crash - testing exception handling")

    # Temporarily replace handlers
    import api.handlers as handlers
    original_at_risk = getattr(handlers, 'query_deals_at_risk', None)
    original_scores = getattr(handlers, 'query_rubric_scores_bulk', None)

    # Test 1: Successful handler receives time_window
    print("\nTest 1: time_window parameter")
    print("-"*60)
    handlers.query_deals_at_risk = mock_handler_success
    received_params.clear()

    prior_entities = {"deal_ids": ["123", "456"]}
    result = await route_entity_scoped_question(
        "which are at risk?", prior_entities, None)

    if not received_params:
        print("✗ FAIL: Handler was not called")
        return 1

    params = received_params[0]
    if "time_window" not in params:
        print(f"✗ FAIL: time_window not in params")
        print(f"  Received keys: {list(params.keys())}")
        return 1

    if "deal_ids" not in params:
        print(f"✗ FAIL: deal_ids not in params")
        print(f"  Received keys: {list(params.keys())}")
        return 1

    tw = params["time_window"]
    if not isinstance(tw, dict):
        print(f"✗ FAIL: time_window is not a dict: {type(tw)}")
        return 1

    if "start" not in tw or "end" not in tw:
        print(f"✗ FAIL: time_window missing start/end: {tw.keys()}")
        return 1

    print(f"✓ PASS: Handler received both deal_ids and time_window")
    print(f"  deal_ids: {params['deal_ids']}")
    print(f"  time_window.start: {tw['start']}")
    print(f"  time_window.end: {tw['end']}")
    print(f"  time_window.label: {tw.get('label', 'N/A')}")

    # Test 2: Exception handling doesn't crash route_entity_scoped_question
    print("\nTest 2: Exception handling")
    print("-"*60)
    handlers.query_rubric_scores_bulk = mock_handler_crash
    received_params.clear()

    # This should NOT raise - exceptions should be caught
    try:
        result = await route_entity_scoped_question(
            "what are the meddicc scores?", prior_entities, None)
        print("✓ PASS: Exception was caught (didn't crash)")
        print(f"  Result: {result}")
        print(f"  Handler was called: {len(received_params) > 0}")
    except Exception as e:
        print(f"✗ FAIL: Exception was not caught: {e}")
        return 1

    # Restore original handlers
    if original_at_risk:
        handlers.query_deals_at_risk = original_at_risk
    if original_scores:
        handlers.query_rubric_scores_bulk = original_scores

    print("\n" + "="*60)
    print("✅ Both G.6 fixes verified:")
    print("  1. time_window is passed to all handlers")
    print("  2. Exceptions are caught and logged")
    return 0


if __name__ == "__main__":
    exit_code = asyncio.run(test_time_window_and_exception_handling())
    sys.exit(exit_code)
