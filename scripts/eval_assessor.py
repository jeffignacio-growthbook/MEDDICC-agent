#!/usr/bin/env python3
"""
Regression tests for assessor and table_classifier LLMClient migration.
Guards against raw .messages calls that silently disable quality checks.
"""

import sys
from pathlib import Path

# Add paths
sys.path.insert(0, str(Path(__file__).parent.parent / "api"))
sys.path.insert(0, str(Path(__file__).parent))

import asyncio
# StrictFakeLLMClient enforces complete()'s real signature. A plain MagicMock
# accepts model=/temperature= and any other kwarg, so it would have passed
# even while production was broken — which is exactly what happened for two
# days. See scripts/llm_fake.py.
from llm_fake import StrictFakeLLMClient


def test_assessor_uses_llmclient_complete():
    """
    Assessor calls .complete() on the LLMClient and returns the real
    verdict score, NOT the 0.50 exception fallback. Guards against the
    raw .messages regression.
    """
    print("\n[TEST] Assessor uses LLMClient.complete() and returns real score")

    from assessor import assess_correctness

    # Strict fake enforces complete()'s real signature — if the assessor ever
    # re-adds model=/temperature=, this raises TypeError → 0.50 fallback →
    # the score assertion below fails (a MagicMock would have hidden it).
    mock_client = StrictFakeLLMClient(
        '{"correct": true, "score": 0.9, "issue": null, "tone_score": 0.85}'
    )

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
    assert mock_client.called, \
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

    from assessor import assess_correctness

    # Test 1: .complete() raises → fallback score 0.5
    mock_client_error = StrictFakeLLMClient(raises=Exception("LLM error"))

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
    mock_client_success = StrictFakeLLMClient(
        '{"correct": true, "score": 0.75, "issue": null}'
    )

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

    from table_classifier import classify_relevant_tables

    # Strict fake: catches a re-added model=/temperature= on table_classifier,
    # which previously fell back silently to "all tables".
    mock_client = StrictFakeLLMClient('["deals", "analyses", "calls"]')

    # Run classifier
    result = classify_relevant_tables(
        question="What deals are at risk?",
        client=mock_client
    )

    # Verify .complete() was called
    assert mock_client.called, \
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
