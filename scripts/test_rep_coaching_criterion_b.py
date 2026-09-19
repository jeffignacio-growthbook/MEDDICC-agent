#!/usr/bin/env python3
"""
Tests for Criterion B (discovery question mapping) in rep_coaching.py.

Covers:
1. Transcript where rep asks listed question → question_asked=True with quote
2. Transcript where rep doesn't ask → question_asked=False with absence note
3. Champion-specific genuine_champion signal detection
4. Graceful failure when LLM response doesn't parse cleanly
"""
import sys
from pathlib import Path
from unittest.mock import MagicMock, patch

sys.path.insert(0, str(Path(__file__).parent))

from rep_coaching import assess_rep_coaching


def _mock_sb_criterion_b(transcript, call_scores_scenario="champion_weak"):
    """Build MockSB for Criterion B tests with configurable transcript."""

    class MockSB:
        def __init__(self, transcript, call_scores_scenario):
            self.transcript = transcript
            self.call_scores_scenario = call_scores_scenario
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
                def __init__(self, table_name, filters, transcript, scenario):
                    if table_name == "deals":
                        data = [{"stage": "appointmentscheduled"}]  # discovery stage
                    elif table_name == "call_transcripts":
                        data = [{
                            "call_id": "target_call",
                            "transcript": transcript,
                            "transcript_quality": "full"
                        }]
                    elif table_name == "call_scores" and ("call_id", "target_call") in filters:
                        # Target call scores - Champion weak for these tests
                        data = [{
                            "call_id": "target_call",
                            "metrics_score": 6,
                            "economic_buyer_score": None,
                            "decision_criteria_score": 5,
                            "decision_process_score": None,
                            "pain_score": 5,
                            "champion_score": 2 if scenario == "champion_weak" else 7,
                            "competition_score": None,
                            "evidence": {}
                        }]
                    elif table_name == "call_scores":
                        # Pre-calls - Champion weak
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
                            "champion_score": 2,  # Red - weak
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
                            "champion_score": 2 if scenario == "champion_weak" else 7,
                            "competition_score": None,
                            "evidence": {}
                        }]
                    else:
                        data = []

                    self.data = data
                    self.count = len(data)

                data = []
                count = 0

            result = Result(self.table_name, self.filters, self.transcript, self.call_scores_scenario)
            self.filters = []
            return result

    return MockSB(transcript, call_scores_scenario)


def _mock_llm_response(response_text):
    """Mock LLMClient.call() to return controlled response."""
    mock_response = MagicMock()
    mock_response.text = response_text
    return mock_response


def test_question_asked_with_quote():
    """Scenario 1: Rep clearly asks a listed question → question_asked=True with quote."""
    print("\n[TEST] Criterion B: question asked with quote")

    transcript = """
Sales Rep: Thanks for taking the time today. I wanted to understand your current setup better.
Can you tell me who internally is most invested in solving this experimentation problem?

Prospect: That would be Sarah, our Director of Product. She's been pushing for better
experimentation capabilities for the past year.

Sales Rep: Great, and what's the typical winning experiment worth in revenue terms for you?

Prospect: We've seen experiments that moved the needle by $50K-100K in monthly revenue.
"""

    sb = _mock_sb_criterion_b(transcript, "champion_weak")

    # Mock LLM to return positive match
    with patch('rep_coaching.LLMClient') as mock_llm_class:
        mock_client = MagicMock()
        mock_client.call.return_value = _mock_llm_response('''```json
{
  "question_asked": true,
  "evidence_quote_or_absence_note": "Rep asked: 'who internally is most invested in solving this experimentation problem?'"
}
```''')
        mock_llm_class.from_config.return_value = mock_client

        result = assess_rep_coaching(sb, "test_deal")

    # Verify Criterion B present
    if "criterion_b" not in result:
        raise AssertionError(f"Expected criterion_b in result, got keys: {result.keys()}")

    criterion_b = result["criterion_b"]
    mappings = criterion_b.get("question_mapping", [])

    if not mappings:
        raise AssertionError(f"Expected question_mapping entries, got: {criterion_b}")

    # Find Champion mapping (should be weak at discovery stage)
    champion_map = next((m for m in mappings if m["component"] == "champion"), None)
    if not champion_map:
        raise AssertionError(f"Expected champion in mappings, got: {mappings}")

    # Verify question_asked=True with quote
    if not champion_map["question_asked"]:
        raise AssertionError(f"Expected question_asked=True, got: {champion_map}")

    evidence = champion_map["evidence_quote_or_absence_note"]
    if "who internally is most invested" not in evidence.lower():
        raise AssertionError(f"Expected quote in evidence, got: {evidence}")

    print(f"  ✓ question_asked=True for Champion")
    print(f"    Evidence: '{evidence[:80]}...'")


def test_question_not_asked():
    """Scenario 2: Rep doesn't ask about the topic → question_asked=False with absence note."""
    print("\n[TEST] Criterion B: question not asked")

    transcript = """
Sales Rep: Thanks for your time. Let me show you a quick demo of our platform.

Prospect: Sure, sounds good.

Sales Rep: Here's our dashboard where you can see all your experiments...

Prospect: Interesting. What's the pricing like?

Sales Rep: Let me walk you through our packages...
"""

    sb = _mock_sb_criterion_b(transcript, "champion_weak")

    # Mock LLM to return negative match
    with patch('rep_coaching.LLMClient') as mock_llm_class:
        mock_client = MagicMock()
        mock_client.call.return_value = _mock_llm_response('''```json
{
  "question_asked": false,
  "evidence_quote_or_absence_note": "Rep never addressed Champion identification - focused only on product demo and pricing"
}
```''')
        mock_llm_class.from_config.return_value = mock_client

        result = assess_rep_coaching(sb, "test_deal")

    criterion_b = result["criterion_b"]
    mappings = criterion_b.get("question_mapping", [])

    champion_map = next((m for m in mappings if m["component"] == "champion"), None)
    if not champion_map:
        raise AssertionError(f"Expected champion in mappings, got: {mappings}")

    # Verify question_asked=False with absence note
    if champion_map["question_asked"]:
        raise AssertionError(f"Expected question_asked=False, got: {champion_map}")

    evidence = champion_map["evidence_quote_or_absence_note"]
    if "never addressed" not in evidence.lower():
        raise AssertionError(f"Expected absence note in evidence, got: {evidence}")

    print(f"  ✓ question_asked=False for Champion")
    print(f"    Absence note: '{evidence[:80]}...'")


def test_champion_genuine_signal_detection():
    """Scenario 3: Champion-specific genuine_champion signal check."""
    print("\n[TEST] Criterion B: Champion genuine_champion signal detection")

    transcript = """
Sales Rep: Would you be comfortable introducing me to your VP of Engineering?
I think it would be valuable to understand their perspective on this.

Prospect: Absolutely, I can set that up. I've actually already mentioned this to her
and she's interested in learning more.

Sales Rep: That's great. What materials would be helpful for you to present
this internally to your team?

Prospect: A one-pager with ROI projections would be perfect. I want to build
the business case before our Q2 planning meeting.
"""

    sb = _mock_sb_criterion_b(transcript, "champion_weak")

    # Mock LLM to return positive match with champion signal
    with patch('rep_coaching.LLMClient') as mock_llm_class:
        mock_client = MagicMock()
        mock_client.call.return_value = _mock_llm_response('''```json
{
  "question_asked": true,
  "evidence_quote_or_absence_note": "Rep asked: 'Would you be comfortable introducing me to your VP of Engineering?' - directly attempting to elicit genuine champion behavior (introduction to stakeholders). Also asked: 'What materials would be helpful for you to present this internally?' - eliciting champion behavior (asks for materials to present internally)"
}
```''')
        mock_llm_class.from_config.return_value = mock_client

        result = assess_rep_coaching(sb, "test_deal")

    criterion_b = result["criterion_b"]
    mappings = criterion_b.get("question_mapping", [])

    champion_map = next((m for m in mappings if m["component"] == "champion"), None)
    if not champion_map:
        raise AssertionError(f"Expected champion in mappings, got: {mappings}")

    # Verify genuine_champion signal detected
    if not champion_map["question_asked"]:
        raise AssertionError(f"Expected question_asked=True, got: {champion_map}")

    evidence = champion_map["evidence_quote_or_absence_note"]
    if "genuine champion behavior" not in evidence.lower():
        raise AssertionError(f"Expected genuine champion signal in evidence, got: {evidence}")

    print(f"  ✓ Champion genuine_champion signal detected")
    print(f"    Evidence: '{evidence[:100]}...'")


def test_llm_parse_failure_graceful():
    """Scenario 4: LLM returns malformed JSON → graceful failure with None."""
    print("\n[TEST] Criterion B: LLM parse failure handled gracefully")

    transcript = "Some transcript text"

    sb = _mock_sb_criterion_b(transcript, "champion_weak")

    # Mock LLM to return malformed response
    with patch('rep_coaching.LLMClient') as mock_llm_class:
        mock_client = MagicMock()
        mock_client.call.return_value = _mock_llm_response(
            "This is not valid JSON at all, just some text")
        mock_llm_class.from_config.return_value = mock_client

        result = assess_rep_coaching(sb, "test_deal")

    criterion_b = result["criterion_b"]
    mappings = criterion_b.get("question_mapping", [])

    champion_map = next((m for m in mappings if m["component"] == "champion"), None)
    if not champion_map:
        raise AssertionError(f"Expected champion in mappings, got: {mappings}")

    # Verify graceful failure: question_asked=None with error note
    if champion_map["question_asked"] is not None:
        raise AssertionError(f"Expected question_asked=None for parse failure, got: {champion_map}")

    evidence = champion_map["evidence_quote_or_absence_note"]
    if "parsing failed" not in evidence.lower() and "error" not in evidence.lower():
        raise AssertionError(f"Expected parse error note, got: {evidence}")

    print(f"  ✓ Parse failure handled gracefully (question_asked=None)")
    print(f"    Error note: '{evidence[:80]}...'")


def main():
    tests = [
        test_question_asked_with_quote,
        test_question_not_asked,
        test_champion_genuine_signal_detection,
        test_llm_parse_failure_graceful,
    ]

    failed = []
    for test in tests:
        try:
            test()
        except Exception as e:
            failed.append((test.__name__, str(e)))
            print(f"\n  ❌ FAILED: {e}")

    print("\n" + "=" * 70)
    print("TEST SUMMARY - Step 5: Criterion B (Discovery Question Mapping)")
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

    print("\n✅ All Criterion B tests passed")
    return 0


if __name__ == "__main__":
    sys.exit(main())
