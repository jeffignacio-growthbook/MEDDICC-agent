#!/usr/bin/env python3
"""
Tests for Criterion A (MEDDICC component advancement) in rep_coaching.py.

Covers three scenarios:
1. Weak component advances (band improves red→yellow or yellow→green)
2. Weak component doesn't advance (stays same or regresses)
3. Zero weak components at current stage (returns empty list, not error)
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))

from rep_coaching import assess_rep_coaching


def _mock_sb_with_scenario(scenario: str):
    """Build MockSB for specific test scenario."""

    class MockSB:
        def __init__(self, scenario):
            self.scenario = scenario
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
                def __init__(self, table_name, filters, scenario):
                    # Scenario 1: Component advances (champion red→yellow)
                    if scenario == "component_advances":
                        if table_name == "deals":
                            data = [{"stage": "appointmentscheduled"}]  # discovery stage
                        elif table_name == "call_scores" and ("call_id", "target_call") in filters:
                            # Target call: champion improved to yellow (5)
                            data = [{
                                "call_id": "target_call",
                                "metrics_score": 7,
                                "economic_buyer_score": None,
                                "decision_criteria_score": 6,
                                "decision_process_score": None,
                                "pain_score": 5,
                                "champion_score": 5,  # Yellow band
                                "competition_score": None,
                                "evidence": {
                                    "champion": "Contact offered to introduce us to VP of Ops"
                                }
                            }]
                        elif table_name == "call_scores":
                            # Pre-calls: champion was red (2)
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
                                "champion_score": 2,  # Red band
                                "competition_score": None,
                                "evidence": {"champion": "Contact seems helpful but not advocating"}
                            }, {
                                "call_id": "target_call",
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

                    # Scenario 2: Component doesn't advance (champion stays red)
                    elif scenario == "component_no_advance":
                        if table_name == "deals":
                            data = [{"stage": "appointmentscheduled"}]  # discovery stage
                        elif table_name == "call_scores" and ("call_id", "target_call") in filters:
                            # Target call: champion still red (2)
                            data = [{
                                "call_id": "target_call",
                                "metrics_score": 7,
                                "economic_buyer_score": None,
                                "decision_criteria_score": 6,
                                "decision_process_score": None,
                                "pain_score": 5,
                                "champion_score": 2,  # Still red
                                "competition_score": None,
                                "evidence": {
                                    "champion": "Still just a coordinator, not selling internally"
                                }
                            }]
                        elif table_name == "call_scores":
                            # Pre-calls: champion was red (2)
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
                                "champion_score": 2,  # Red band
                                "competition_score": None,
                                "evidence": {}
                            }, {
                                "call_id": "target_call",
                                "deal_id": "test_deal",
                                "call_date": "2026-09-15",
                                "text_source": "transcript",
                                "metrics_score": 7,
                                "economic_buyer_score": None,
                                "decision_criteria_score": 6,
                                "decision_process_score": None,
                                "pain_score": 5,
                                "champion_score": 2,
                                "competition_score": None,
                                "evidence": {}
                            }]
                        else:
                            data = []

                    # Scenario 3: Zero weak components (all green/acceptable)
                    elif scenario == "zero_weak":
                        if table_name == "deals":
                            data = [{"stage": "appointmentscheduled"}]  # discovery stage
                        elif table_name == "call_scores" and ("call_id", "target_call") in filters:
                            # Target call: all strong scores
                            data = [{
                                "call_id": "target_call",
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
                            # Pre-calls: all strong
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
                                "champion_score": 7,  # Green
                                "competition_score": 6,
                                "evidence": {}
                            }, {
                                "call_id": "target_call",
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

                    # Coverage queries (same for all scenarios)
                    else:
                        data = []

                    self.data = data
                    self.count = len(data)

                data = []
                count = 0

            result = Result(self.table_name, self.filters, self.scenario)
            self.filters = []  # Reset
            return result

    return MockSB(scenario)


def test_component_advances():
    """Scenario 1: Weak component (champion) advances from red to yellow."""
    print("\n[TEST] Criterion A: component advances (red→yellow)")

    sb = _mock_sb_with_scenario("component_advances")
    result = assess_rep_coaching(sb, "test_deal")

    # Should have criterion_a with advancements
    if "criterion_a" not in result:
        raise AssertionError(f"Expected criterion_a in result, got keys: {result.keys()}")

    criterion_a = result["criterion_a"]
    advancements = criterion_a.get("advancements", [])

    if not advancements:
        raise AssertionError(f"Expected at least one advancement, got: {criterion_a}")

    # Find champion advancement
    champion_adv = next((a for a in advancements if a["component"] == "champion"), None)
    if not champion_adv:
        raise AssertionError(f"Expected champion in advancements, got: {advancements}")

    # Verify advancement
    if champion_adv["prior_band"] != "red":
        raise AssertionError(f"Expected prior_band='red', got {champion_adv['prior_band']}")
    if champion_adv["this_call_band"] != "yellow":
        raise AssertionError(f"Expected this_call_band='yellow', got {champion_adv['this_call_band']}")
    if not champion_adv["advanced"]:
        raise AssertionError(f"Expected advanced=True for red→yellow, got: {champion_adv}")

    # Verify evidence present
    if not champion_adv.get("evidence"):
        raise AssertionError(f"Expected evidence for advancement, got: {champion_adv}")

    print(f"  ✓ Champion advanced from {champion_adv['prior_band']} to "
          f"{champion_adv['this_call_band']}, advanced={champion_adv['advanced']}")
    print(f"    Evidence: '{champion_adv['evidence'][:60]}...'")


def test_component_no_advance():
    """Scenario 2: Weak component (champion) doesn't advance (stays red)."""
    print("\n[TEST] Criterion A: component doesn't advance (stays red)")

    sb = _mock_sb_with_scenario("component_no_advance")
    result = assess_rep_coaching(sb, "test_deal")

    # Should have criterion_a with advancements list
    if "criterion_a" not in result:
        raise AssertionError(f"Expected criterion_a in result, got keys: {result.keys()}")

    criterion_a = result["criterion_a"]
    advancements = criterion_a.get("advancements", [])

    if not advancements:
        raise AssertionError(f"Expected at least one entry in advancements, got: {criterion_a}")

    # Find champion entry
    champion_adv = next((a for a in advancements if a["component"] == "champion"), None)
    if not champion_adv:
        raise AssertionError(f"Expected champion in advancements, got: {advancements}")

    # Verify NO advancement
    if champion_adv["prior_band"] != "red":
        raise AssertionError(f"Expected prior_band='red', got {champion_adv['prior_band']}")
    if champion_adv["this_call_band"] != "red":
        raise AssertionError(f"Expected this_call_band='red', got {champion_adv['this_call_band']}")
    if champion_adv["advanced"]:
        raise AssertionError(f"Expected advanced=False for red→red, got: {champion_adv}")

    print(f"  ✓ Champion stayed at {champion_adv['prior_band']}, advanced={champion_adv['advanced']}")
    print(f"    Evidence: '{champion_adv['evidence'][:60] if champion_adv.get('evidence') else 'None'}...'")


def test_zero_weak_components():
    """Scenario 3: Zero weak components → empty advancements list (not error)."""
    print("\n[TEST] Criterion A: zero weak components → empty list")

    sb = _mock_sb_with_scenario("zero_weak")
    result = assess_rep_coaching(sb, "test_deal")

    # Should have criterion_a
    if "criterion_a" not in result:
        raise AssertionError(f"Expected criterion_a in result, got keys: {result.keys()}")

    criterion_a = result["criterion_a"]

    # Should have empty advancements list
    if "advancements" not in criterion_a:
        raise AssertionError(f"Expected advancements key, got: {criterion_a}")

    advancements = criterion_a["advancements"]
    if advancements:
        raise AssertionError(f"Expected empty advancements list, got {len(advancements)} entries: "
                             f"{advancements}")

    # Should NOT have error status
    if "status" in criterion_a and criterion_a["status"] == "insufficient_data":
        raise AssertionError(f"Zero weak components should return empty list, not error: {criterion_a}")

    # Should have explanatory note
    if "note" not in criterion_a:
        raise AssertionError(f"Expected explanatory note, got: {criterion_a}")

    if "nothing for the rep to advance" not in criterion_a["note"].lower():
        raise AssertionError(f"Expected 'nothing to advance' in note, got: {criterion_a['note']}")

    print(f"  ✓ Zero weak components correctly returned empty list (not error)")
    print(f"    Note: '{criterion_a['note'][:80]}...'")


def main():
    tests = [
        test_component_advances,
        test_component_no_advance,
        test_zero_weak_components,
    ]

    failed = []
    for test in tests:
        try:
            test()
        except Exception as e:
            failed.append((test.__name__, str(e)))
            print(f"\n  ❌ FAILED: {e}")

    print("\n" + "=" * 70)
    print("TEST SUMMARY - Step 4: Criterion A (MEDDICC Component Advancement)")
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

    print("\n✅ All Criterion A tests passed")
    return 0


if __name__ == "__main__":
    sys.exit(main())
