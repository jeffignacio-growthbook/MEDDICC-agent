#!/usr/bin/env python3
"""
Full integration tests for rep_coaching.py — baseline scenarios across realistic conditions.

Covers:
1. Deal with no transcript → gate fires (insufficient_data), coverage_note present
2. Deal with Fireflies transcript → A/B run, C shows source_not_supported explicitly
3. Deal with Apollo transcript → all three criteria produce real output
4. Deal with zero weak components → A/B return empty/not-applicable cleanly
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


def _mock_sb_scenario_1_no_transcript():
    """Scenario 1: Deal with NO transcript-scored calls → gate fires."""

    class MockSB:
        def __init__(self):
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
                def __init__(self, table_name):
                    if table_name == "deals":
                        data = [{"stage": "appointmentscheduled"}]
                    elif table_name == "call_scores":
                        # NO transcript-scored calls (empty list)
                        data = []
                    else:
                        data = []

                    self.data = data
                    self.count = len(data)

            result = Result(self.table_name)
            self.filters = []
            return result

    return MockSB()


def _mock_sb_scenario_2_fireflies():
    """Scenario 2: Deal with Fireflies-sourced transcript."""

    class MockSB:
        def __init__(self):
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
                def __init__(self, table_name, filters):
                    if table_name == "deals":
                        data = [{"stage": "appointmentscheduled"}]
                    elif table_name == "call_transcripts":
                        # Fireflies-sourced call (no participant_identities)
                        data = [{
                            "call_id": "fireflies_call",
                            "source": "fireflies",
                            "transcript": "Some transcript text from Fireflies",
                            "transcript_quality": "full",
                            "participant_identities": None
                        }]
                    elif table_name == "call_scores" and ("call_id", "fireflies_call") in filters:
                        # Target call scores - Champion weak
                        data = [{
                            "call_id": "fireflies_call",
                            "metrics_score": 6,
                            "economic_buyer_score": None,
                            "decision_criteria_score": 5,
                            "decision_process_score": None,
                            "pain_score": 5,
                            "champion_score": 2,  # Weak
                            "competition_score": None,
                            "evidence": {"champion": "Contact seems helpful but not advocating"}
                        }]
                    elif table_name == "call_scores":
                        # Pre-calls + target call
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
                            "call_id": "fireflies_call",
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

            result = Result(self.table_name, self.filters)
            self.filters = []
            return result

    return MockSB()


def _mock_sb_scenario_3_apollo():
    """Scenario 3: Deal with Apollo-sourced transcript (all criteria produce output)."""

    class MockSB:
        def __init__(self):
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
                def __init__(self, table_name, filters):
                    if table_name == "deals":
                        data = [{"stage": "appointmentscheduled"}]
                    elif table_name == "call_transcripts":
                        # Apollo-sourced call with participant_identities
                        data = [{
                            "call_id": "apollo_call",
                            "source": "apollo",
                            "transcript": "Rep: Who internally is most invested in solving this? Prospect: Sarah is.",
                            "transcript_quality": "full",
                            "talk_time_seconds": {"rep1": 300.0, "prospect1": 700.0},
                            "question_count": {"rep1": 5, "prospect1": 15},
                            "total_speech_seconds": 1000.0,
                            "participant_identities": {
                                "rep1": {
                                    "name": "Rep", "email": "rep@growthbook.io",
                                    "is_internal": True, "is_bot": False
                                },
                                "prospect1": {
                                    "name": "Prospect", "email": "prospect@acme.com",
                                    "is_internal": False, "is_bot": False
                                }
                            }
                        }]
                    elif table_name == "call_scores" and ("call_id", "apollo_call") in filters:
                        # Target call scores - Champion advanced to yellow
                        data = [{
                            "call_id": "apollo_call",
                            "metrics_score": 7,
                            "economic_buyer_score": None,
                            "decision_criteria_score": 6,
                            "decision_process_score": None,
                            "pain_score": 5,
                            "champion_score": 5,  # Advanced to yellow
                            "competition_score": None,
                            "evidence": {"champion": "Contact offered to introduce us to VP"}
                        }]
                    elif table_name == "call_scores":
                        # Pre-calls + target call
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
                            "champion_score": 2,  # Was red
                            "competition_score": None,
                            "evidence": {}
                        }, {
                            "call_id": "apollo_call",
                            "deal_id": "test_deal",
                            "call_date": "2026-09-15",
                            "text_source": "transcript",
                            "metrics_score": 7,
                            "economic_buyer_score": None,
                            "decision_criteria_score": 6,
                            "decision_process_score": None,
                            "pain_score": 5,
                            "champion_score": 5,
                            "competition_score": None,
                            "evidence": {}
                        }]
                    else:
                        data = []

                    self.data = data
                    self.count = len(data)

            result = Result(self.table_name, self.filters)
            self.filters = []
            return result

    return MockSB()


def _mock_sb_scenario_4_zero_weak():
    """Scenario 4: Deal with zero weak components (all scores green)."""

    class MockSB:
        def __init__(self):
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
                def __init__(self, table_name, filters):
                    if table_name == "deals":
                        data = [{"stage": "appointmentscheduled"}]
                    elif table_name == "call_transcripts":
                        # Apollo-sourced call
                        data = [{
                            "call_id": "strong_call",
                            "source": "apollo",
                            "transcript": "Strong discovery conversation",
                            "transcript_quality": "full",
                            "talk_time_seconds": {"rep1": 300.0, "prospect1": 700.0},
                            "question_count": {"rep1": 5, "prospect1": 15},
                            "total_speech_seconds": 1000.0,
                            "participant_identities": {
                                "rep1": {
                                    "name": "Rep", "email": "rep@growthbook.io",
                                    "is_internal": True, "is_bot": False
                                },
                                "prospect1": {
                                    "name": "Prospect", "email": "prospect@acme.com",
                                    "is_internal": False, "is_bot": False
                                }
                            }
                        }]
                    elif table_name == "call_scores" and ("call_id", "strong_call") in filters:
                        # Target call scores - ALL GREEN
                        data = [{
                            "call_id": "strong_call",
                            "metrics_score": 8,
                            "economic_buyer_score": 7,
                            "decision_criteria_score": 7,
                            "decision_process_score": 8,
                            "pain_score": 7,
                            "champion_score": 8,  # Green
                            "competition_score": 7,
                            "evidence": {}
                        }]
                    elif table_name == "call_scores":
                        # Pre-calls + target call - all green
                        data = [{
                            "call_id": "pre_call_1",
                            "deal_id": "test_deal",
                            "call_date": "2026-09-10",
                            "text_source": "transcript",
                            "metrics_score": 7,
                            "economic_buyer_score": 6,
                            "decision_criteria_score": 6,
                            "decision_process_score": 7,
                            "pain_score": 6,
                            "champion_score": 7,
                            "competition_score": 6,
                            "evidence": {}
                        }, {
                            "call_id": "strong_call",
                            "deal_id": "test_deal",
                            "call_date": "2026-09-15",
                            "text_source": "transcript",
                            "metrics_score": 8,
                            "economic_buyer_score": 7,
                            "decision_criteria_score": 7,
                            "decision_process_score": 8,
                            "pain_score": 7,
                            "champion_score": 8,
                            "competition_score": 7,
                            "evidence": {}
                        }]
                    else:
                        data = []

                    self.data = data
                    self.count = len(data)

            result = Result(self.table_name, self.filters)
            self.filters = []
            return result

    return MockSB()


def test_scenario_1_no_transcript():
    """Scenario 1: Deal with no transcript → gate fires, coverage_note present."""
    print("\n[TEST 1] No transcript → gate fires")

    sb = _mock_sb_scenario_1_no_transcript()
    result = assess_rep_coaching(sb, "test_deal")

    # Should have insufficient_data status
    if result.get("status") != "insufficient_data":
        raise AssertionError(f"Expected status='insufficient_data', got: {result.get('status')}")

    # Should have coverage_note (UNCONDITIONAL field)
    if "coverage_note" not in result:
        raise AssertionError(f"Expected coverage_note in gated response, got keys: {result.keys()}")

    # Should NOT have criterion_a/b/c (gate short-circuits)
    if "criterion_a" in result or "criterion_b" in result or "criterion_c" in result:
        raise AssertionError(f"Gate should short-circuit before criteria assessment, got: {result.keys()}")

    print(f"  ✓ Gate fired correctly (status=insufficient_data)")
    print(f"  ✓ Coverage note present: '{result['coverage_note'][:60]}...'")


def test_scenario_2_fireflies():
    """Scenario 2: Fireflies transcript → A/B run, C explicit source_not_supported."""
    print("\n[TEST 2] Fireflies transcript → A/B run, C source_not_supported")

    sb = _mock_sb_scenario_2_fireflies()

    # Mock LLM for Criterion B
    with patch('rep_coaching.LLMClient') as mock_llm_class:
        mock_client = MagicMock()
        mock_client.call.return_value = _mock_llm_response('''```json
{
  "question_asked": false,
  "evidence_quote_or_absence_note": "Rep did not address champion identification"
}
```''')
        mock_llm_class.from_config.return_value = mock_client

        result = assess_rep_coaching(sb, "test_deal")

    # Should have status=ok (gate passed)
    if result.get("status") != "ok":
        raise AssertionError(f"Expected status='ok', got: {result.get('status')}")

    # Should have criterion_a
    if "criterion_a" not in result:
        raise AssertionError(f"Expected criterion_a, got keys: {result.keys()}")

    # Should have criterion_b
    if "criterion_b" not in result:
        raise AssertionError(f"Expected criterion_b, got keys: {result.keys()}")

    # Should have criterion_c with EXPLICIT source_not_supported
    if "criterion_c" not in result:
        raise AssertionError(f"Expected criterion_c, got keys: {result.keys()}")

    criterion_c = result["criterion_c"]
    if criterion_c.get("status") != "source_not_supported":
        raise AssertionError(f"Expected criterion_c status='source_not_supported', got: {criterion_c}")

    if "fireflies" not in criterion_c.get("reason", "").lower():
        raise AssertionError(f"Expected 'fireflies' in reason, got: {criterion_c['reason']}")

    # Should NOT have diagnostic fields (not applicable)
    if "internal_talk_ratio" in criterion_c:
        raise AssertionError(f"Fireflies should not return diagnostics, got: {criterion_c}")

    print(f"  ✓ Criteria A and B ran successfully")
    print(f"  ✓ Criterion C returned explicit source_not_supported")
    print(f"    Reason: {criterion_c['reason']}")


def test_scenario_3_apollo():
    """Scenario 3: Apollo transcript → all three criteria produce real output."""
    print("\n[TEST 3] Apollo transcript → all three criteria produce output")

    sb = _mock_sb_scenario_3_apollo()

    # Mock LLM for Criterion B
    with patch('rep_coaching.LLMClient') as mock_llm_class:
        mock_client = MagicMock()
        mock_client.call.return_value = _mock_llm_response('''```json
{
  "question_asked": true,
  "evidence_quote_or_absence_note": "Rep asked: 'Who internally is most invested in solving this?'"
}
```''')
        mock_llm_class.from_config.return_value = mock_client

        result = assess_rep_coaching(sb, "test_deal")

    # Should have status=ok
    if result.get("status") != "ok":
        raise AssertionError(f"Expected status='ok', got: {result.get('status')}")

    # Should have all three criteria
    for criterion in ["criterion_a", "criterion_b", "criterion_c"]:
        if criterion not in result:
            raise AssertionError(f"Expected {criterion}, got keys: {result.keys()}")

    # Criterion A should show advancement
    criterion_a = result["criterion_a"]
    if not criterion_a.get("advancements"):
        raise AssertionError(f"Expected advancements in criterion_a, got: {criterion_a}")

    # Criterion B should have question mapping
    criterion_b = result["criterion_b"]
    if not criterion_b.get("question_mapping"):
        raise AssertionError(f"Expected question_mapping in criterion_b, got: {criterion_b}")

    # Criterion C should have diagnostics (Apollo source)
    criterion_c = result["criterion_c"]
    if criterion_c.get("status") != "ok":
        raise AssertionError(f"Expected criterion_c status='ok', got: {criterion_c}")

    if "internal_talk_ratio" not in criterion_c:
        raise AssertionError(f"Expected diagnostic fields in criterion_c, got: {criterion_c.keys()}")

    print(f"  ✓ Criterion A: {len(criterion_a['advancements'])} component(s) assessed")
    print(f"  ✓ Criterion B: {len(criterion_b['question_mapping'])} question(s) mapped")
    print(f"  ✓ Criterion C: internal_talk_ratio={criterion_c['internal_talk_ratio']}")


def test_scenario_4_zero_weak():
    """Scenario 4: Zero weak components → A/B return empty/not-applicable cleanly."""
    print("\n[TEST 4] Zero weak components → empty advancements")

    sb = _mock_sb_scenario_4_zero_weak()

    # Mock LLM for Criterion B (won't be called since no weak components, but mock anyway)
    with patch('rep_coaching.LLMClient') as mock_llm_class:
        mock_client = MagicMock()
        mock_client.call.return_value = _mock_llm_response('''```json
{
  "question_asked": false,
  "evidence_quote_or_absence_note": "Not applicable"
}
```''')
        mock_llm_class.from_config.return_value = mock_client

        result = assess_rep_coaching(sb, "test_deal")

    # Should have status=ok
    if result.get("status") != "ok":
        raise AssertionError(f"Expected status='ok', got: {result.get('status')}")

    # Criterion A should have empty advancements list
    criterion_a = result["criterion_a"]
    if criterion_a.get("advancements"):
        raise AssertionError(f"Expected empty advancements, got {len(criterion_a['advancements'])} entries")

    if "note" not in criterion_a:
        raise AssertionError(f"Expected explanatory note in criterion_a, got: {criterion_a.keys()}")

    if "nothing for the rep to advance" not in criterion_a["note"].lower():
        raise AssertionError(f"Expected 'nothing to advance' in note, got: {criterion_a['note']}")

    # Criterion B should have empty question_mapping
    criterion_b = result["criterion_b"]
    if criterion_b.get("question_mapping"):
        raise AssertionError(f"Expected empty question_mapping, got {len(criterion_b['question_mapping'])} entries")

    if "note" not in criterion_b:
        raise AssertionError(f"Expected explanatory note in criterion_b, got: {criterion_b.keys()}")

    # Criterion C should still run (Apollo source)
    criterion_c = result["criterion_c"]
    if criterion_c.get("status") != "ok":
        raise AssertionError(f"Expected criterion_c status='ok', got: {criterion_c}")

    print(f"  ✓ Criterion A: empty advancements (nothing to advance)")
    print(f"  ✓ Criterion B: empty question_mapping (no weak components)")
    print(f"  ✓ Criterion C: still ran (diagnostic-only, no pass/fail)")
    print(f"    Note: '{criterion_a['note'][:60]}...'")


def main():
    tests = [
        test_scenario_1_no_transcript,
        test_scenario_2_fireflies,
        test_scenario_3_apollo,
        test_scenario_4_zero_weak,
    ]

    failed = []
    for test in tests:
        try:
            test()
        except Exception as e:
            failed.append((test.__name__, str(e)))
            print(f"\n  ❌ FAILED: {e}")

    print("\n" + "=" * 70)
    print("TEST SUMMARY - Integration: Full Rep Coaching Baseline")
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

    print("\n✅ All integration tests passed")
    return 0


if __name__ == "__main__":
    sys.exit(main())
