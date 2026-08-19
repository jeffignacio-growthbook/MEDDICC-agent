#!/usr/bin/env python3
"""
Behavior-preservation tests for coaching config migration (Phase B).
Guards against regressions when moving hardcoded content to config files.
"""
from pathlib import Path
import sys

REPO_ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(REPO_ROOT / "scripts"))

from coaching_config import load_coaching_config


def test_stage_questions_config_matches_old_hardcoded():
    """
    The stage_focus_questions in coaching_client.yaml must exactly match
    the old hardcoded STAGE_COMPONENT_QUESTIONS from handlers.py.

    This is a permanent regression guard — the frozen dict below is the
    reference implementation extracted from handlers.py lines 2200-2312.
    """

    # Frozen reference: the old hardcoded dict from handlers.py
    OLD_HARDCODED_QUESTIONS = {
        "discovery": {
            "Economic Buyer": [
                "Who has final budget authority for this decision?",
                "What's the approval threshold above which procurement gets involved?",
                "At what dollar amount does this need C-level sign-off?",
            ],
            "Champion": [
                "Who internally is most invested in solving this problem?",
                "Who has skin in the game if experimentation doesn't improve?",
                "Is there someone who's already tried to build internal momentum for this?",
            ],
            "Decision Process": [
                "What does the approval process typically look like for tools in this price range?",
                "Who else needs to be involved before you can move forward?",
                "Have you bought similar tools before — what did that process look like?",
            ],
            "Metrics": [
                "How many experiments are you running per month right now?",
                "What's a typical winning experiment worth in revenue terms?",
                "What does your current setup cost annually, all in?",
            ],
            "Decision Criteria": [
                "What would make this evaluation successful from your perspective?",
                "What are your must-haves versus nice-to-haves?",
                "What would make you choose to stay with your current setup?",
            ],
            "Pain": [
                "What's broken about your current experimentation setup?",
                "What does it cost you to run experiments the way you do today?",
                "Who else in the org feels this pain most acutely?",
            ],
            "Competition": [
                "Are you evaluating other options in parallel?",
                "What else have you looked at so far?",
                "Is there an internal tool the engineering team wants to keep?",
            ],
        },
        "scoping": {
            "Economic Buyer": [
                "Has the economic buyer been briefed on this yet?",
                "What does [EB name] need to see to approve this?",
                "When will you be able to loop in [EB name]?",
            ],
            "Champion": [
                "What does your champion need from us to build the business case internally?",
                "Do they have access to the economic buyer?",
                "What would make them look good by championing this?",
            ],
            "Decision Process": [
                "What happens after technical evaluation — who needs to approve?",
                "What would cause this to stall — security review, legal, procurement?",
                "Is there a specific event or deadline driving the timeline?",
            ],
            "Metrics": [
                "What metrics will you use to measure success in the pilot?",
                "How will you prove ROI to leadership?",
                "What's the baseline you're comparing against?",
            ],
            "Decision Criteria": [
                "What does a successful technical evaluation look like?",
                "Which integration or capability is most critical to validate?",
                "What would cause you to disqualify a vendor at this stage?",
            ],
            "Pain": [
                "What's the cost of waiting another quarter to solve this?",
                "What happens if you don't get this in place before [timeline]?",
                "Is this blocking other initiatives?",
            ],
            "Competition": [
                "How does our approach compare to [competitor] in your eval?",
                "What's [competitor]'s strongest advantage from your perspective?",
                "What would have to be true for you to choose them over us?",
            ],
        },
        "proposal": {
            "Economic Buyer": [
                "When is [EB name] reviewing the proposal?",
                "What questions or concerns does the economic buyer have?",
                "Is there anyone above [EB name] who needs to approve?",
            ],
            "Champion": [
                "What does your champion need to present this to the committee?",
                "Are there internal objections they need help addressing?",
                "What would make them confident presenting this to leadership?",
            ],
            "Decision Process": [
                "What are the remaining steps between here and signature?",
                "Who hasn't weighed in yet that needs to?",
                "What's the timeline for legal review and contracting?",
            ],
            "Metrics": [
                "What ROI metrics will you use to justify this internally?",
                "How are you framing the business case to the exec team?",
                "What does success look like in the first 90 days?",
            ],
            "Decision Criteria": [
                "Are there any open questions or gaps in the proposal?",
                "What would cause leadership to push back on this?",
                "Is pricing structured the way finance needs it?",
            ],
            "Pain": [
                "What's at risk if this doesn't close this quarter?",
                "Is there a consequence to the team if this gets delayed?",
                "What's the political cost of not moving forward?",
            ],
            "Competition": [
                "Are you still evaluating other vendors at this stage?",
                "What's the internal debate between [us] and [competitor]?",
                "What would swing the decision in our favor?",
            ],
        },
    }

    # Load config
    config = load_coaching_config()
    config_questions = config.get("stage_focus_questions", {})

    # Compare
    assert config_questions == OLD_HARDCODED_QUESTIONS, \
        "stage_focus_questions in config does not match old hardcoded dict"

    print("✓ stage_focus_questions config matches old hardcoded dict")
    return True


def test_blocker_mapping_config_matches_old_hardcoded():
    """
    The objection_category_to_blocker mapping in coaching_client.yaml
    must exactly match the old hardcoded BLOCKER_MAP from handlers.py.

    Frozen reference from handlers.py lines 2329-2336.
    """

    # Frozen reference: the old hardcoded mapping
    OLD_HARDCODED_BLOCKER_MAP = {
        "technical": "technical",
        "product_gap": "technical",
        "switching_cost": "resourcing",
        "internal_politics": "cultural",
        "budget": "commercial",
        "timing": "resourcing",
    }

    # Load config
    config = load_coaching_config()
    config_mapping = config.get("objection_category_to_blocker", {})

    # Compare
    assert config_mapping == OLD_HARDCODED_BLOCKER_MAP, \
        "objection_category_to_blocker in config does not match old hardcoded dict"

    print("✓ objection_category_to_blocker config matches old hardcoded dict")
    return True


def test_blocker_taxonomy_exists_in_seed():
    """
    Verify that blocker_taxonomy exists in the merged config with all
    four blocker types and their prescribed responses.
    """

    config = load_coaching_config()
    blocker_taxonomy = config.get("blocker_taxonomy", {})

    required_types = ["technical", "resourcing", "cultural", "commercial"]
    for blocker_type in required_types:
        assert blocker_type in blocker_taxonomy, \
            f"blocker_taxonomy missing type: {blocker_type}"

        definition = blocker_taxonomy[blocker_type]
        assert "right_response" in definition, \
            f"blocker_taxonomy.{blocker_type} missing right_response"
        assert "signals" in definition, \
            f"blocker_taxonomy.{blocker_type} missing signals"

    print("✓ blocker_taxonomy exists with all 4 types and prescribed responses")
    return True


if __name__ == '__main__':
    print("=" * 70)
    print("COACHING CONFIG MIGRATION VALIDATION")
    print("=" * 70)
    print()

    tests = [
        test_stage_questions_config_matches_old_hardcoded,
        test_blocker_mapping_config_matches_old_hardcoded,
        test_blocker_taxonomy_exists_in_seed,
    ]

    passed = 0
    failed = 0

    for test in tests:
        try:
            test()
            passed += 1
        except AssertionError as e:
            print(f"✗ {test.__name__}: {e}")
            failed += 1
        except Exception as e:
            print(f"✗ {test.__name__}: Unexpected error: {e}")
            failed += 1

    print()
    print("=" * 70)
    print(f"RESULTS: {passed} passed, {failed} failed")
    print("=" * 70)

    exit(0 if failed == 0 else 1)
