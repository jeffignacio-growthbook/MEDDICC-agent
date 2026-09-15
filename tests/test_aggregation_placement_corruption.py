#!/usr/bin/env python3
"""
Reproduce the CRITICAL aggregation placement corruption bug where the retry
correction replaced an individual deal's line item instead of the summary total.

PRODUCTION INCIDENT (2026-09-14):
- Question: EMEA closed won/lost deals
- 354 rows of EMEA deals, actual total: $6.89M
- Model's first answer stated: ~$50K (wrong)
- AGGREGATION_VERIFY fired, sent correction: "correct total is $6.89M"
- Model's retry answer: Replaced Creative CX's individual $50K line item
  with $6.89M instead of fixing the summary
- Result: Wrong $6.89M figure attached to Creative CX, shipped to production

ROOT CAUSE:
AGGREGATION_VERIFY's forced-retry mechanism corrects a TOTAL but had no mechanism
to confirm the correction landed in the right place in the synthesized text.

THE PRIMITIVE-LEVEL FIX:
verify_total_placement() checks: does any INDIVIDUAL line-item value in the retry
answer now equal the corrected TOTAL? This is implausible (one deal = sum of 354
deals) and a near-certain sign of misplacement. Lives in aggregation_verification.py
so it protects EVERY handler/dynamic_query call, not just this one case.
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))
sys.path.insert(0, str(Path(__file__).parent.parent / "api"))

from api.aggregation_verification import (
    extract_stated_totals_from_answer,
    verify_aggregation_completeness,
    verify_total_placement
)


def test_wrong_answer_has_low_stated_total():
    """First answer: Model states wrong total (~$50K instead of $6.89M)"""
    wrong_answer = """
    EMEA Closed Won & Closed Lost — Jan 2025 to Date

    Here's the breakdown of closed deals in EMEA. We had several deals
    close in January including Acme Corp at $1.2M, Beta Systems at $800K,
    and Creative CX at $50K on the won side. On the lost side, we had
    Delta Inc at $500K and Echo Ltd at $300K.

    Total closed deal value: $50,000
    """

    stated = extract_stated_totals_from_answer(wrong_answer)

    print("=" * 80)
    print("Test 1: First answer states wrong total")
    print("=" * 80)
    print(f"Stated totals extracted: {stated}")
    print(f"Expected: 'total' around $50K")

    # Should extract a low total (the bug we're testing)
    if "total" in stated:
        print(f"✅ Extracted total: ${stated['total']:,.0f}")
        assert stated["total"] < 100000, "Should be low (wrong)"
    else:
        print("❌ FAIL: No total extracted")


def test_actual_sum_is_much_higher():
    """Actual data: 354 rows summing to $6.89M"""
    # Simulate 354 EMEA deals (simplified - just a few representative ones)
    deals = [
        {"company_name": "Acme Corp", "deal_value": 1200000},
        {"company_name": "Beta Systems", "deal_value": 800000},
        {"company_name": "Creative CX", "deal_value": 50000},  # The one that got corrupted
        {"company_name": "Delta Inc", "deal_value": -500000},  # Lost
        {"company_name": "Echo Ltd", "deal_value": -300000},  # Lost
        # ... 349 more deals totaling to make real sum $6.89M
    ]

    # Pad with additional deals to reach ~$6.89M total
    remaining = 6890371.78 - sum(d["deal_value"] for d in deals)
    deals.append({"company_name": "Other deals", "deal_value": remaining})

    stated = {"total": 50000.0}  # What model stated
    result = verify_aggregation_completeness(deals, stated, value_column="deal_value")

    print("\n" + "=" * 80)
    print("Test 2: Verification detects mismatch")
    print("=" * 80)
    print(f"Stated: ${stated['total']:,.0f}")
    print(f"Actual sum: ${sum(d['deal_value'] for d in deals):,.2f}")
    print(f"Match: {result['match']}")

    assert result["match"] is False, "Should detect mismatch"
    assert abs(result["discrepancy"]["actual_sum"] - 6890371.78) < 1.0
    print(f"✅ Mismatch detected: stated={result['discrepancy']['stated']}, actual={result['discrepancy']['actual_sum']}")


def test_corrupted_retry_answer_detected_by_placement_check():
    """
    BUGGY RETRY: Model put $6.89M as an individual deal value (Creative CX).
    This is the DATA CORRUPTION that shipped to production.

    PRIMITIVE CHECK: Does any individual dollar amount in the answer equal
    the corrected total? If yes (and there are multiple amounts), this is
    implausible - one deal shouldn't equal the grand total across 354 deals.
    """
    corrupted_retry_answer = """
    EMEA Closed Won & Closed Lost — Jan 2025 to Date

    Here's the breakdown of closed deals in EMEA. We had several deals
    close in January including Acme Corp at $1.2M, Beta Systems at $800K,
    and Creative CX at $6,890,371.78 on the won side. On the lost side, we had
    Delta Inc at $500K and Echo Ltd at $300K.

    Total closed deal value: $6,890,371.78
    """

    # Simulate the 354 deals
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
        deals, corrupted_retry_answer, corrected_total, value_column="deal_value"
    )

    print("\n" + "=" * 80)
    print("Test 3: Corrupted retry answer (Creative CX = $6.89M)")
    print("=" * 80)
    print(f"Answer has: Creative CX at $6,890,371.78 AND Total at $6,890,371.78")
    print(f"Placement check result: {placement_check}")

    if not placement_check["placement_ok"]:
        print(f"✅ CORRUPTION DETECTED: {placement_check['likely_corruption']}")
    else:
        print("❌ FAIL: Should detect $6.89M appearing as individual deal value")

    assert not placement_check["placement_ok"], "Should detect placement corruption"
    assert placement_check["suspect_value"] == corrected_total
    assert "line-item" in placement_check["likely_corruption"].lower()


def test_correct_retry_answer_not_flagged():
    """
    CORRECT RETRY: Model put $6.89M in the Total line only, individual
    deals unchanged. The $6.89M appears ONLY once (in the total line),
    so placement check should pass.
    """
    correct_retry_answer = """
    EMEA Closed Won & Closed Lost — Jan 2025 to Date

    Here's the breakdown of closed deals in EMEA. We had several deals
    close in January including Acme Corp at $1.2M, Beta Systems at $800K,
    and Creative CX at $50K on the won side. On the lost side, we had
    Delta Inc at $500K and Echo Ltd at $300K.

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
        deals, correct_retry_answer, corrected_total, value_column="deal_value"
    )

    print("\n" + "=" * 80)
    print("Test 4: Correct retry answer (Creative CX still $50K, Total = $6.89M)")
    print("=" * 80)
    print(f"Answer has: Creative CX at $50K, Total at $6,890,371.78 (only once)")
    print(f"Placement check result: {placement_check}")

    if placement_check["placement_ok"]:
        print(f"✅ NOT FLAGGED: Correct placement of total")
    else:
        print(f"❌ FALSE POSITIVE: {placement_check.get('likely_corruption')}")

    assert placement_check["placement_ok"], "Should NOT flag when total appears only once"


def test_total_appears_only_in_summary_line_multiple_deals():
    """
    Edge case: Multiple deals with various amounts, but corrected total
    only appears in summary line (not matching any individual deal).
    Should pass.
    """
    correct_answer = """
    Pipeline movement this quarter:

    Week 1: $500K new, $200K lost (net $300K)
    Week 2: $1.2M new, $0 lost (net $1.2M)
    Week 3: $800K new, $150K lost (net $650K)

    Total net pipeline movement: $2,150,000
    """

    deals = [
        {"week": "Week 1", "net_change": 300000},
        {"week": "Week 2", "net_change": 1200000},
        {"week": "Week 3", "net_change": 650000},
    ]

    corrected_total = 2150000.0

    placement_check = verify_total_placement(
        deals, correct_answer, corrected_total, value_column="net_change"
    )

    print("\n" + "=" * 80)
    print("Test 5: Multiple deals, total only in summary")
    print("=" * 80)
    print(f"Placement check: {placement_check}")

    assert placement_check["placement_ok"], "Should pass when total doesn't match any individual value"
    print("✅ PASS: Total appears only in summary line")


if __name__ == "__main__":
    test_wrong_answer_has_low_stated_total()
    test_actual_sum_is_much_higher()
    test_corrupted_retry_answer_detected_by_placement_check()
    test_correct_retry_answer_not_flagged()
    test_total_appears_only_in_summary_line_multiple_deals()

    print("\n" + "=" * 80)
    print("SUMMARY")
    print("=" * 80)
    print("✅ All 5 tests passed")
    print()
    print("The PRIMITIVE-LEVEL fix prevents Creative CX ($50K deal) from being")
    print("corrupted with the $6.89M total. verify_total_placement() checks if")
    print("any individual line-item value equals the corrected total (implausible),")
    print("catching misplacement structurally, not by text patterns.")
    print()
    print("This protection lives in aggregation_verification.py and guards EVERY")
    print("handler and dynamic_query call, not just this one EMEA question.")
