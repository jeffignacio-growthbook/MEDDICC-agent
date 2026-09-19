#!/usr/bin/env python3
"""
Planted-discrepancy test for rep_coaching.py INTEGRATED flow.

Plants known signals across all three criteria and verifies the COMBINED output
reports everything correctly — no criteria dropped, no data corrupted.

Planted scenario:
- Deal at discovery stage with Apollo transcript
- Criterion A: Champion score improves (red→yellow) — SHOULD report advancement
- Criterion B: Rep asks champion question — SHOULD report question_asked=True
- Criterion C: Apollo source with talk_time_seconds — SHOULD return diagnostic numbers
- Coverage note: MUST be present unconditionally

Verifies INTEGRATED output structure contains all expected pieces without corruption.
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


def _mock_sb_planted_scenario():
    """
    Planted scenario with known signals:
    - Discovery stage
    - Apollo transcript
    - Champion advances red (2) → yellow (5)
    - Transcript contains champion question
    - Apollo talk_time_seconds present
    """

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
                        # Discovery stage
                        data = [{"stage": "appointmentscheduled"}]
                    elif table_name == "call_transcripts":
                        # Apollo transcript with champion question
                        data = [{
                            "call_id": "planted_call",
                            "source": "apollo",
                            "transcript": (
                                "Sales Rep: Thanks for your time today. "
                                "Who internally is most invested in solving this problem? "
                                "I want to understand who really cares about fixing this.\n\n"
                                "Prospect: That would be Sarah, our VP of Product. She's been "
                                "pushing for better experimentation for a year now.\n\n"
                                "Sales Rep: Great. Would you be comfortable introducing me to Sarah? "
                                "I think it would be valuable to get her perspective.\n\n"
                                "Prospect: Absolutely, I can set that up. Let me send an intro email."
                            ),
                            "transcript_quality": "full",
                            "talk_time_seconds": {"rep1": 400.0, "prospect1": 600.0},
                            "question_count": {"rep1": 8, "prospect1": 12},
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
                    elif table_name == "call_scores" and ("call_id", "planted_call") in filters:
                        # Target call: Champion advanced to yellow (5)
                        data = [{
                            "call_id": "planted_call",
                            "metrics_score": 7,
                            "economic_buyer_score": None,
                            "decision_criteria_score": 6,
                            "decision_process_score": None,
                            "pain_score": 5,
                            "champion_score": 5,  # Yellow (advanced from red)
                            "competition_score": None,
                            "evidence": {
                                "champion": "Contact offered to introduce us to VP of Product — genuine champion behavior"
                            }
                        }]
                    elif table_name == "call_scores":
                        # Pre-call: Champion was red (2)
                        # Target call: Champion now yellow (5)
                        data = [{
                            "call_id": "pre_call_1",
                            "deal_id": "planted_deal",
                            "call_date": "2026-09-10",
                            "text_source": "transcript",
                            "metrics_score": 6,
                            "economic_buyer_score": None,
                            "decision_criteria_score": 5,
                            "decision_process_score": None,
                            "pain_score": 4,
                            "champion_score": 2,  # Red (weak)
                            "competition_score": None,
                            "evidence": {"champion": "Contact is just a coordinator"}
                        }, {
                            "call_id": "planted_call",
                            "deal_id": "planted_deal",
                            "call_date": "2026-09-15",
                            "text_source": "transcript",
                            "metrics_score": 7,
                            "economic_buyer_score": None,
                            "decision_criteria_score": 6,
                            "decision_process_score": None,
                            "pain_score": 5,
                            "champion_score": 5,  # Yellow (advanced)
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


def test_planted_discrepancy_full_integration():
    """
    Planted-discrepancy test: Verify ALL THREE CRITERIA report correctly in INTEGRATED output.

    Expected:
    - Criterion A: Champion advancement (red→yellow, advanced=True)
    - Criterion B: Champion question asked (question_asked=True with quote)
    - Criterion C: Apollo diagnostics (internal_talk_ratio=0.4 for 400/1000)
    - Coverage note: Present unconditionally
    - No criteria dropped or corrupted
    """
    print("\n[PLANTED-DISCREPANCY TEST] Integrated flow verification")

    sb = _mock_sb_planted_scenario()

    # Mock LLM to return POSITIVE match for champion question
    with patch('rep_coaching.LLMClient') as mock_llm_class:
        mock_client = MagicMock()
        # LLM should detect the champion question in the planted transcript
        mock_client.call.return_value = _mock_llm_response('''```json
{
  "question_asked": true,
  "evidence_quote_or_absence_note": "Rep asked: 'Who internally is most invested in solving this problem?' — directly addresses Champion identification. Also asked for introduction: 'Would you be comfortable introducing me to Sarah?' — attempting to elicit genuine champion behavior (stakeholder introduction)."
}
```''')
        mock_llm_class.from_config.return_value = mock_client

        result = assess_rep_coaching(sb, "planted_deal")

    print("\n[Verifying integrated output structure]")

    # ── 1. Top-level status and coverage ──
    if result.get("status") != "ok":
        raise AssertionError(f"Expected status='ok', got: {result.get('status')}")
    print("  ✓ Status: ok")

    if "coverage_note" not in result:
        raise AssertionError(f"Expected coverage_note (unconditional field), got keys: {result.keys()}")
    print(f"  ✓ Coverage note present: '{result['coverage_note'][:50]}...'")

    # ── 2. Verify all three criteria present ──
    for criterion in ["criterion_a", "criterion_b", "criterion_c"]:
        if criterion not in result:
            raise AssertionError(f"Expected {criterion} in result, got keys: {result.keys()}")
    print("  ✓ All three criteria present in output")

    # ── 3. Criterion A: Champion advancement ──
    print("\n[Verifying Criterion A: MEDDICC Component Advancement]")
    criterion_a = result["criterion_a"]

    advancements = criterion_a.get("advancements", [])
    if not advancements:
        raise AssertionError(f"Expected advancements list, got: {criterion_a}")

    champion_adv = next((a for a in advancements if a["component"] == "champion"), None)
    if not champion_adv:
        raise AssertionError(f"Expected champion in advancements, got: {advancements}")

    # Verify advancement details
    if champion_adv["prior_band"] != "red":
        raise AssertionError(f"Expected prior_band='red', got: {champion_adv['prior_band']}")

    if champion_adv["this_call_band"] != "yellow":
        raise AssertionError(f"Expected this_call_band='yellow', got: {champion_adv['this_call_band']}")

    if not champion_adv["advanced"]:
        raise AssertionError(f"Expected advanced=True for red→yellow, got: {champion_adv}")

    if not champion_adv.get("evidence"):
        raise AssertionError(f"Expected evidence for advancement, got: {champion_adv}")

    print(f"  ✓ Champion advanced: {champion_adv['prior_band']} → {champion_adv['this_call_band']}")
    print(f"  ✓ advanced={champion_adv['advanced']}")
    print(f"  ✓ Evidence: '{champion_adv['evidence'][:60]}...'")

    # ── 4. Criterion B: Discovery question mapping ──
    print("\n[Verifying Criterion B: Discovery Question Mapping]")
    criterion_b = result["criterion_b"]

    mappings = criterion_b.get("question_mapping", [])
    if not mappings:
        raise AssertionError(f"Expected question_mapping list, got: {criterion_b}")

    champion_map = next((m for m in mappings if m["component"] == "champion"), None)
    if not champion_map:
        raise AssertionError(f"Expected champion in mappings, got: {mappings}")

    # Verify question was asked
    if not champion_map["question_asked"]:
        raise AssertionError(f"Expected question_asked=True, got: {champion_map}")

    evidence = champion_map["evidence_quote_or_absence_note"]
    if "who internally is most invested" not in evidence.lower():
        raise AssertionError(f"Expected quote in evidence, got: {evidence}")

    # Verify genuine_champion signal detection (stakeholder introduction)
    if "introducing me to sarah" not in evidence.lower() and "introduction" not in evidence.lower():
        raise AssertionError(f"Expected genuine_champion signal (introduction) in evidence, got: {evidence}")

    print(f"  ✓ Champion question asked: question_asked=True")
    print(f"  ✓ Evidence includes quote: '...Who internally is most invested...'")
    print(f"  ✓ Genuine champion signal detected: stakeholder introduction")

    # ── 5. Criterion C: Talk-time diagnostic ──
    print("\n[Verifying Criterion C: Talk-Time Diagnostic (Apollo)]")
    criterion_c = result["criterion_c"]

    if criterion_c.get("status") != "ok":
        raise AssertionError(f"Expected criterion_c status='ok', got: {criterion_c}")

    # Verify diagnostic fields present
    required_fields = ["internal_talk_ratio", "internal_question_share",
                      "matched_seconds", "total_speech_seconds", "unmatched_seconds"]
    for field in required_fields:
        if field not in criterion_c:
            raise AssertionError(f"Expected {field} in criterion_c, got keys: {criterion_c.keys()}")

    # Verify calculated value (400 internal / 1000 total = 0.4)
    internal_ratio = criterion_c["internal_talk_ratio"]
    if internal_ratio != 0.4:
        raise AssertionError(f"Expected internal_talk_ratio=0.4 (400/1000), got: {internal_ratio}")

    # Verify it's labeled as diagnostic-only
    if "DIAGNOSTIC ONLY" not in criterion_c.get("note", ""):
        raise AssertionError(f"Expected 'DIAGNOSTIC ONLY' label, got: {criterion_c.get('note')}")

    print(f"  ✓ Apollo diagnostic returned: internal_talk_ratio={internal_ratio}")
    print(f"  ✓ All required diagnostic fields present")
    print(f"  ✓ Labeled as DIAGNOSTIC ONLY (no pass/fail)")

    # ── 6. Verify NO CORRUPTION or OMISSION ──
    print("\n[Verifying data integrity]")

    # Check that all expected keys are present at top level
    expected_top_keys = {
        "status", "coverage_note", "target_call_id", "target_call_date",
        "transcript_call_count", "stage_bucket", "weak_components",
        "criterion_a", "criterion_b", "criterion_c"
    }
    actual_top_keys = set(result.keys())
    missing_keys = expected_top_keys - actual_top_keys
    if missing_keys:
        raise AssertionError(f"Missing top-level keys in integrated output: {missing_keys}")

    # Check no criteria are empty dicts (corruption check)
    for criterion in ["criterion_a", "criterion_b", "criterion_c"]:
        if not result[criterion]:
            raise AssertionError(f"{criterion} is empty dict (corrupted): {result[criterion]}")

    print("  ✓ All expected top-level keys present")
    print("  ✓ No criteria corrupted (all have content)")
    print("  ✓ No data omitted from integrated output")

    print("\n[SUCCESS] Planted-discrepancy test passed!")
    print("  → Criterion A reported Champion advancement correctly")
    print("  → Criterion B detected Champion question and genuine signals")
    print("  → Criterion C returned Apollo diagnostics correctly")
    print("  → Coverage note present unconditionally")
    print("  → No corruption or omission in integrated output")

    return 0


def main():
    try:
        return test_planted_discrepancy_full_integration()
    except Exception as e:
        print(f"\n❌ PLANTED-DISCREPANCY TEST FAILED: {e}")
        import traceback
        print(traceback.format_exc())
        return 1


if __name__ == "__main__":
    sys.exit(main())
