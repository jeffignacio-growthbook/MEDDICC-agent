#!/usr/bin/env python3
"""
Tests for Criterion C (talk-time diagnostic) in rep_coaching.py.

Covers:
1. Apollo-sourced call → returns diagnostic numbers (no pass/fail)
2. Fireflies-sourced call → explicit source_not_supported (not silently omitted)
"""
import sys
from pathlib import Path
from unittest.mock import MagicMock, patch

sys.path.insert(0, str(Path(__file__).parent))

from rep_coaching import assess_rep_coaching


def _mock_llm_response(response_text):
    """Mock LLMClient.call() to return controlled response."""
    mock_response = MagicMock()
    mock_response.text = response_text
    return mock_response


def _mock_sb_criterion_c(source="apollo", has_identity_data=True):
    """Build MockSB for Criterion C tests with configurable source."""

    class MockSB:
        def __init__(self, source, has_identity_data):
            self.source = source
            self.has_identity_data = has_identity_data
            self.table_name = None
            self.filters = []

        def table(self, name):
            self.table_name = name
            return self

        def select(self, cols):
            return self

        def eq(self, field, value):
            self.filters.append((field, value))
            return self

        def range(self, start, end):
            return self

        def execute(self):
            class Result:
                def __init__(self, table_name, filters, source, has_identity_data):
                    if table_name == "deals":
                        data = [{"stage": "appointmentscheduled"}]  # discovery stage
                    elif table_name == "call_transcripts":
                        # Target call transcript row with source and talk-time data
                        participant_identities = {
                            "rep1": {
                                "name": "Rep", "email": "rep@growthbook.io",
                                "is_internal": True, "is_bot": False
                            },
                            "prospect1": {
                                "name": "Prospect", "email": "prospect@acme.com",
                                "is_internal": False, "is_bot": False
                            }
                        } if has_identity_data else None

                        data = [{
                            "call_id": "target_call",
                            "source": source,
                            "transcript": "Some transcript text",
                            "transcript_quality": "full",
                            "talk_time_seconds": {"rep1": 300.0, "prospect1": 700.0},
                            "question_count": {"rep1": 5, "prospect1": 15},
                            "total_speech_seconds": 1000.0,
                            "participant_identities": participant_identities
                        }]
                    elif table_name == "call_scores" and ("call_id", "target_call") in filters:
                        # Target call scores - Champion weak for test
                        data = [{
                            "call_id": "target_call",
                            "metrics_score": 6,
                            "economic_buyer_score": None,
                            "decision_criteria_score": 5,
                            "decision_process_score": None,
                            "pain_score": 5,
                            "champion_score": 2,  # Weak
                            "competition_score": None,
                            "evidence": {}
                        }]
                    elif table_name == "call_scores":
                        # Pre-calls
                        data = [{
                            "call_id": "pre_call_1",
                            "deal_id": "test_deal",
                            "call_date": "2026-09-10",
                            "text_source": "transcript",
                            "metrics_score": 6,
                            "economic_buyer_score": None,
                            "decision_criteria_score": 5,
                            "decision_process_score": None,
                            "pain_score": 4,
                            "champion_score": 2,
                            "competition_score": None,
                            "evidence": {}
                        }, {
                            "call_id": "target_call",
                            "deal_id": "test_deal",
                            "call_date": "2026-09-15",
                            "text_source": "transcript",
                            "metrics_score": 6,
                            "economic_buyer_score": None,
                            "decision_criteria_score": 5,
                            "decision_process_score": None,
                            "pain_score": 5,
                            "champion_score": 2,
                            "competition_score": None,
                            "evidence": {}
                        }]
                    else:
                        data = []

                    self.data = data
                    self.count = len(data)

                data = []
                count = 0

            result = Result(self.table_name, self.filters, self.source, self.has_identity_data)
            self.filters = []
            return result

    return MockSB(source, has_identity_data)


def test_apollo_source_returns_diagnostic():
    """Scenario 1: Apollo-sourced call → returns diagnostic numbers (no pass/fail)."""
    print("\n[TEST] Criterion C: Apollo-sourced call returns diagnostic")

    sb = _mock_sb_criterion_c(source="apollo", has_identity_data=True)

    # Mock LLM for Criterion B (skip actual LLM call)
    with patch('rep_coaching.LLMClient') as mock_llm_class:
        mock_client = MagicMock()
        mock_client.call.return_value = _mock_llm_response('''```json
{
  "question_asked": false,
  "evidence_quote_or_absence_note": "Mocked response for Criterion C test"
}
```''')
        mock_llm_class.from_config.return_value = mock_client

        result = assess_rep_coaching(sb, "test_deal")

    # Should have criterion_c with diagnostic data
    if "criterion_c" not in result:
        raise AssertionError(f"Expected criterion_c in result, got keys: {result.keys()}")

    criterion_c = result["criterion_c"]

    # Should have status="ok" (not insufficient_data)
    if criterion_c.get("status") != "ok":
        raise AssertionError(f"Expected status='ok' for Apollo diagnostic, got: {criterion_c}")

    # Should have diagnostic fields
    required_fields = ["internal_talk_ratio", "internal_question_share",
                      "matched_seconds", "total_speech_seconds", "unmatched_seconds"]
    for field in required_fields:
        if field not in criterion_c:
            raise AssertionError(f"Expected {field} in criterion_c, got keys: {criterion_c.keys()}")

    # Verify it's diagnostic-only (has the label)
    if "DIAGNOSTIC ONLY" not in criterion_c.get("note", ""):
        raise AssertionError(f"Expected 'DIAGNOSTIC ONLY' label in note, got: {criterion_c['note']}")

    # Verify actual values make sense
    internal_ratio = criterion_c["internal_talk_ratio"]
    if not isinstance(internal_ratio, (int, float)):
        raise AssertionError(f"Expected numeric internal_talk_ratio, got: {internal_ratio}")

    # Internal talks 300s out of 1000s total = 0.3
    if internal_ratio != 0.3:
        raise AssertionError(f"Expected internal_talk_ratio=0.3 (300/1000), got: {internal_ratio}")

    print(f"  ✓ Apollo source returned diagnostic numbers")
    print(f"    internal_talk_ratio: {criterion_c['internal_talk_ratio']}")
    print(f"    internal_question_share: {criterion_c['internal_question_share']}")
    print(f"    matched_seconds: {criterion_c['matched_seconds']}")
    print(f"    Note: '{criterion_c['note'][:80]}...'")


def test_fireflies_source_explicit_not_supported():
    """Scenario 2: Fireflies-sourced call → explicit source_not_supported."""
    print("\n[TEST] Criterion C: Fireflies-sourced call returns explicit source_not_supported")

    sb = _mock_sb_criterion_c(source="fireflies", has_identity_data=False)

    # Mock LLM for Criterion B
    with patch('rep_coaching.LLMClient') as mock_llm_class:
        mock_client = MagicMock()
        mock_client.call.return_value = _mock_llm_response('''```json
{
  "question_asked": false,
  "evidence_quote_or_absence_note": "Mocked response"
}
```''')
        mock_llm_class.from_config.return_value = mock_client

        result = assess_rep_coaching(sb, "test_deal")

    # Should have criterion_c
    if "criterion_c" not in result:
        raise AssertionError(f"Expected criterion_c in result, got keys: {result.keys()}")

    criterion_c = result["criterion_c"]

    # Should have status="source_not_supported" (explicit, not omitted)
    if criterion_c.get("status") != "source_not_supported":
        raise AssertionError(
            f"Expected status='source_not_supported' for Fireflies, got: {criterion_c}")

    # Should have reason field
    if "reason" not in criterion_c:
        raise AssertionError(f"Expected reason field, got: {criterion_c}")

    reason = criterion_c["reason"]
    if "fireflies" not in reason.lower():
        raise AssertionError(f"Expected 'fireflies' in reason, got: {reason}")

    # Should have explanatory note
    if "note" not in criterion_c:
        raise AssertionError(f"Expected note field, got: {criterion_c}")

    note = criterion_c["note"]
    if "apollo" not in note.lower() or "permanent" not in note.lower():
        raise AssertionError(
            f"Expected note explaining Apollo-only limitation, got: {note}")

    # Should NOT have diagnostic fields (they're not applicable)
    if "internal_talk_ratio" in criterion_c:
        raise AssertionError(
            f"Fireflies source should not return diagnostic numbers, got: {criterion_c}")

    print(f"  ✓ Fireflies source returned explicit source_not_supported")
    print(f"    status: {criterion_c['status']}")
    print(f"    reason: {criterion_c['reason']}")
    print(f"    Note: '{note[:100]}...'")


def test_gong_source_explicit_not_supported():
    """Scenario 3: Gong-sourced call → explicit source_not_supported."""
    print("\n[TEST] Criterion C: Gong-sourced call returns explicit source_not_supported")

    sb = _mock_sb_criterion_c(source="gong", has_identity_data=False)

    # Mock LLM for Criterion B
    with patch('rep_coaching.LLMClient') as mock_llm_class:
        mock_client = MagicMock()
        mock_client.call.return_value = _mock_llm_response('''```json
{
  "question_asked": false,
  "evidence_quote_or_absence_note": "Mocked response"
}
```''')
        mock_llm_class.from_config.return_value = mock_client

        result = assess_rep_coaching(sb, "test_deal")

    criterion_c = result["criterion_c"]

    # Should have explicit source_not_supported for Gong too
    if criterion_c.get("status") != "source_not_supported":
        raise AssertionError(
            f"Expected status='source_not_supported' for Gong, got: {criterion_c}")

    if "gong" not in criterion_c.get("reason", "").lower():
        raise AssertionError(f"Expected 'gong' in reason, got: {criterion_c['reason']}")

    print(f"  ✓ Gong source returned explicit source_not_supported")
    print(f"    status: {criterion_c['status']}")
    print(f"    reason: {criterion_c['reason']}")


def main():
    tests = [
        test_apollo_source_returns_diagnostic,
        test_fireflies_source_explicit_not_supported,
        test_gong_source_explicit_not_supported,
    ]

    failed = []
    for test in tests:
        try:
            test()
        except Exception as e:
            failed.append((test.__name__, str(e)))
            print(f"\n  ❌ FAILED: {e}")

    print("\n" + "=" * 70)
    print("TEST SUMMARY - Step 6: Criterion C (Talk-Time Diagnostic)")
    print("=" * 70)

    passed = len(tests) - len(failed)
    print(f"\nTotal tests: {len(tests)}")
    print(f"  ✓ Passed: {passed}")

    if failed:
        print(f"  ✗ Failed: {len(failed)}")
        print("\nFailed tests:")
        for name, error in failed:
            print(f"  - {name}")
            print(f"    {error[:200]}")
        return 1

    print("\n✅ All Criterion C tests passed")
    return 0


if __name__ == "__main__":
    sys.exit(main())
