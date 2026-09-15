#!/usr/bin/env python3
"""
Test the GAP CASE in verify_total_placement():

Current logic: "appears once = OK"
Gap scenario: Model replaces Creative CX with $6.89M and NEVER restates
a separate summary total. Count = 1, but this is STILL corruption.

Example:
- Acme Corp: $1.2M
- Beta Systems: $800K
- Creative CX: $6,890,371.78  ← CORRUPTED (this is the ONLY occurrence)
- Delta Inc: $500K
- Echo Ltd: $300K
(No separate "Total:" line)

Current check: count=1 → OK
Reality: CORRUPTED (single deal shouldn't equal 354-deal aggregate)
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))
sys.path.insert(0, str(Path(__file__).parent.parent / "api"))

from api.aggregation_verification import verify_total_placement


def test_gap_case_single_occurrence_but_wrong_location():
    """
    GAP CASE: Corrected total appears EXACTLY ONCE, but in wrong location
    (attached to a specific deal, no separate summary line exists).

    This is the exact same corruption as the Creative CX incident, just
    without the tell-tale duplicate. Current logic would pass this.
    """
    gap_case_answer = """
    EMEA Closed Won & Closed Lost — Jan 2025 to Date

    Here's the breakdown of closed deals in EMEA:
    - Acme Corp: $1.2M
    - Beta Systems: $800K
    - Creative CX: $6,890,371.78
    - Delta Inc: $500K (lost)
    - Echo Ltd: $300K (lost)

    These are the closed deals for the period.
    """

    # 354 deals, actual total $6.89M
    deals = [
        {"company_name": "Acme Corp", "deal_value": 1200000},
        {"company_name": "Beta Systems", "deal_value": 800000},
        {"company_name": "Creative CX", "deal_value": 50000},  # Real value
        {"company_name": "Delta Inc", "deal_value": -500000},
        {"company_name": "Echo Ltd", "deal_value": -300000},
    ]
    remaining = 6890371.78 - sum(d["deal_value"] for d in deals)
    deals.append({"company_name": "Other deals", "deal_value": remaining})

    corrected_total = 6890371.78

    placement_check = verify_total_placement(
        deals, gap_case_answer, corrected_total, value_column="deal_value"
    )

    print("=" * 80)
    print("GAP CASE TEST: Single occurrence, wrong location")
    print("=" * 80)
    print(f"Answer has Creative CX: $6,890,371.78 (ONLY occurrence)")
    print(f"No separate 'Total:' line exists")
    print(f"Placement check result: {placement_check}")
    print()

    if not placement_check["placement_ok"]:
        print(f"✅ GAP CAUGHT: {placement_check.get('likely_corruption')}")
        return True
    else:
        print("❌ GAP MISSED: Current logic says OK (count=1)")
        print("   Reality: CORRUPTED (Creative CX shouldn't equal 354-deal total)")
        print()
        print("NEEDED: Second signal beyond count - check if single occurrence")
        print("        appears next to specific deal/company name (implausible)")
        return False


def test_correct_single_occurrence_in_summary():
    """
    CORRECT CASE: Corrected total appears EXACTLY ONCE in summary line.
    Should NOT be flagged (this is the intended behavior).
    """
    correct_answer = """
    EMEA Closed Won & Closed Lost — Jan 2025 to Date

    We had several deals close including Acme Corp ($1.2M), Beta Systems
    ($800K), Creative CX ($50K), Delta Inc ($500K lost), and Echo Ltd
    ($300K lost).

    Total closed deal value: $6,890,371.78
    """

    deals = [
        {"company_name": "Acme Corp", "deal_value": 1200000},
        {"company_name": "Beta Systems", "deal_value": 800000},
        {"company_name": "Creative CX", "deal_value": 50000},
        {"company_name": "Delta Inc", "deal_value": -500000},
        {"company_name": "Echo Ltd", "deal_value": -300000},
    ]
    remaining = 6890371.78 - sum(d["deal_value"] for d in deals)
    deals.append({"company_name": "Other deals", "deal_value": remaining})

    corrected_total = 6890371.78

    placement_check = verify_total_placement(
        deals, correct_answer, corrected_total, value_column="deal_value"
    )

    print("\n" + "=" * 80)
    print("CORRECT CASE: Single occurrence in summary line")
    print("=" * 80)
    print(f"Placement check result: {placement_check}")

    if placement_check["placement_ok"]:
        print("✅ CORRECT: Not flagged (count=1, in summary line)")
        return True
    else:
        print(f"❌ FALSE POSITIVE: {placement_check.get('likely_corruption')}")
        return False


if __name__ == "__main__":
    print("Testing the GAP CASE in verify_total_placement()\n")

    gap_caught = test_gap_case_single_occurrence_but_wrong_location()
    correct_ok = test_correct_single_occurrence_in_summary()

    print("\n" + "=" * 80)
    print("SUMMARY")
    print("=" * 80)

    if gap_caught and correct_ok:
        print("✅ Both cases handled correctly")
    elif not gap_caught:
        print("❌ GAP EXISTS: Single occurrence in wrong location NOT caught")
        print()
        print("FIX NEEDED:")
        print("  When count=1, add second signal:")
        print("  - Does the ONE occurrence appear next to specific deal/company name?")
        print("  - If yes → Suspicious (one deal shouldn't equal 354-deal aggregate)")
        print("  - If no → OK (probably in summary line)")
    else:
        print("⚠️  Gap caught but false positive on correct case")
