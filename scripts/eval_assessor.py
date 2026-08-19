#!/usr/bin/env python3
"""
Regression tests for assessor and table_classifier LLMClient migration.
Guards against raw .messages calls that silently disable quality checks.
"""

import sys
from pathlib import Path

# Add paths
sys.path.insert(0, str(Path(__file__).parent.parent / "api"))

import asyncio
from unittest.mock import MagicMock, AsyncMock


def test_assessor_uses_llmclient_complete():
    """
    Assessor calls .complete() on the LLMClient and returns the real
    verdict score, NOT the 0.50 exception fallback. Guards against the
    raw .messages regression.
    """
    print("\n[TEST] Assessor uses LLMClient.complete() and returns real score")

    from api.assessor import assess_correctness

    # Mock LLMClient that returns a valid assessment
    mock_client = MagicMock()
    mock_response = MagicMock()
    mock_response.text = '{"correct": true, "score": 0.9, "issue": null, "tone_score": 0.85}'
    mock_client.complete = MagicMock(return_value=mock_response)

    # Run the assessor
    result = asyncio.run(assess_correctness(
        question="What deals are at risk?",
        handler_used="query_deals_at_risk",
        tool_results={"deals": [{"deal_id": "123"}]},
        answer="5 deals are at risk",
        client=mock_client,
        budget_used=0.05
    ))

    # Verify .complete() was called (not .messages.create)
    assert mock_client.complete.called, \
        "Assessor must call .complete() on LLMClient"

    # Verify it returned the real score from the LLM, not the 0.5 fallback
    assert result["score"] == 0.9, \
        f"Expected real score 0.9 from LLM, got {result['score']} (0.5 means fallback triggered)"

    # Verify no AttributeError was raised (would happen with raw .messages call)
    assert result.get("correct") is True, \
        "Assessment should have returned correct verdict"

    print("✓ Assessor calls .complete() and returns real score 0.9 (not 0.5 fallback)")


def test_assessor_returns_fallback_only_on_real_exception():
    """
    The 0.50 fallback fires only when .complete() actually raises,
    not on every call.
    """
    print("\n[TEST] Assessor fallback only triggers on exception")

    from api.assessor import assess_correctness

    # Test 1: .complete() raises → fallback score 0.5
    mock_client_error = MagicMock()
    mock_client_error.complete = MagicMock(side_effect=Exception("LLM error"))

    result_error = asyncio.run(assess_correctness(
        question="test",
        handler_used="test_handler",
        tool_results={},
        answer="test answer",
        client=mock_client_error,
        budget_used=0.05
    ))

    assert result_error["score"] == 0.5, \
        "Should return fallback score 0.5 when .complete() raises"
    print("  ✓ Exception → fallback score 0.5")

    # Test 2: .complete() succeeds → real score
    mock_client_success = MagicMock()
    mock_response = MagicMock()
    mock_response.text = '{"correct": true, "score": 0.75, "issue": null}'
    mock_client_success.complete = MagicMock(return_value=mock_response)

    result_success = asyncio.run(assess_correctness(
        question="test",
        handler_used="test_handler",
        tool_results={},
        answer="test answer",
        client=mock_client_success,
        budget_used=0.05
    ))

    assert result_success["score"] == 0.75, \
        f"Should return real score 0.75 when .complete() succeeds, got {result_success['score']}"
    print("  ✓ Success → real score 0.75")

    print("✓ Fallback only triggers on real exceptions")


def test_table_classifier_uses_complete():
    """
    table_classifier calls .complete() and parses the table list,
    not client.messages.create().
    """
    print("\n[TEST] table_classifier uses LLMClient.complete()")

    from api.table_classifier import classify_relevant_tables

    # Mock LLMClient that returns a valid table list
    mock_client = MagicMock()
    mock_response = MagicMock()
    mock_response.text = '["deals", "analyses", "calls"]'
    mock_client.complete = MagicMock(return_value=mock_response)

    # Run classifier
    result = classify_relevant_tables(
        question="What deals are at risk?",
        client=mock_client
    )

    # Verify .complete() was called
    assert mock_client.complete.called, \
        "table_classifier must call .complete() on LLMClient"

    # Verify it parsed the table list correctly
    assert isinstance(result, list), \
        "Should return a list of tables"
    assert "deals" in result, \
        "Should have parsed 'deals' from the response"
    assert "analyses" in result, \
        "Should have parsed 'analyses' from the response"

    print("✓ table_classifier uses .complete() and parses table list correctly")


def main():
    """Run all assessor regression tests."""
    print("=" * 70)
    print("ASSESSOR REGRESSION TESTS")
    print("=" * 70)

    tests = [
        test_assessor_uses_llmclient_complete,
        test_assessor_returns_fallback_only_on_real_exception,
        test_table_classifier_uses_complete,
    ]

    passed = 0
    failed = 0

    for test in tests:
        try:
            test()
            passed += 1
        except AssertionError as e:
            failed += 1
            print(f"\n❌ FAILED: {test.__name__}")
            print(f"   {e}")
        except Exception as e:
            failed += 1
            print(f"\n❌ ERROR in {test.__name__}: {e}")
            import traceback
            traceback.print_exc()

    print("\n" + "=" * 70)
    print(f"RESULTS: {passed} passed, {failed} failed")
    print("=" * 70)

    return 0 if failed == 0 else 1


if __name__ == "__main__":
    sys.exit(main())
