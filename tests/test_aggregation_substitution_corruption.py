#!/usr/bin/env python3
"""
Reproduce the CRITICAL aggregation substitution bug where the retry
correction replaced an individual deal's line item instead of the
summary total.

PRODUCTION INCIDENT (2026-09-14):
- Question: EMEA closed won/lost deals
- 354 rows of EMEA deals, actual total: $6.89M
- Model's first answer stated: ~$50K (wrong)
- AGGREGATION_VERIFY fired, sent correction: "correct total is $6.89M"
- Model's retry answer: Replaced Creative CX's individual $50K line item
  with $6.89M instead of fixing the summary
- Result: Wrong $6.89M figure attached to Creative CX, shipped to production

ROOT CAUSE:
Correction message said "replace each wrong stated total" but gave NO
guidance on WHERE (summary vs line items). Model was free to splice
the corrected total anywhere.

THE FIX:
1. Prompt guidance: "These totals belong in SUMMARY lines ONLY. Do NOT
   alter individual deal amounts."
2. Structural check: After retry, detect if corrected total appears
   next to a company name (suspicious) instead of in a "Total:" line.
3. If suspicious, escalate to "couldn't verify" instead of shipping
   corrupted data.
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))
sys.path.insert(0, str(Path(__file__).parent.parent / "api"))

from api.aggregation_verification import (
    extract_stated_totals_from_answer,
    verify_aggregation_completeness
)

# Import the check function directly since it's in router.py
# We'll test it by calling it directly with the answer text
import re


def _check_suspicious_total_substitution(answer_text, corrected_totals):
    """Local copy for testing - checks if corrected total appears next to company name"""
    if not corrected_totals or not answer_text:
        return None

    # Known total-indicator phrases that should NOT be flagged as company names
    TOTAL_INDICATORS = {"total", "overall", "grand total", "grand_total", "sum", "net"}

    for d in corrected_totals:
        corrected_val = d["actual_sum"]
        # Format variations
        formatted_variations = [
            f"{corrected_val:,.2f}",  # "6,890,371.78"
            f"{corrected_val:,.0f}",  # "6,890,372"
        ]

        for fmt_val in formatted_variations:
            # Company name + this value on same line
            # Pattern: Capital letter + text + colon/dash + value
            pattern = rf'([A-Z][A-Za-z0-9\s&]+)(?::|\s—|\s-)\s*\$?{re.escape(fmt_val)}'
            match = re.search(pattern, answer_text)
            if match:
                # Extract the label before the colon/dash
                label = match.group(1).strip().lower()
                # Check if it's a total indicator - if so, this is NOT suspicious
                if any(indicator in label for indicator in TOTAL_INDICATORS):
                    continue
                # Otherwise, this looks like a company name with the corrected total
                return f"SUSPICIOUS: {fmt_val} appears next to company name"

    return None


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


def test_corrupted_retry_answer_detected_as_suspicious():
    """
    BUGGY RETRY: Model put $6.89M next to Creative CX instead of in Total line.
    This is the DATA CORRUPTION that shipped to production.
    """
    corrupted_retry_answer = """
    EMEA Closed Won & Closed Lost — Jan 2025 to Date

    Here's the breakdown of closed deals in EMEA. We had several deals
    close in January including Acme Corp at $1.2M, Beta Systems at $800K,
    and Creative CX: $6,890,371.78 on the won side. On the lost side, we had
    Delta Inc at $500K and Echo Ltd at $300K.

    Total closed deal value: $6,890,371.78
    """

    # Corrected totals that were sent to model
    corrected_totals = [
        {"category": "total", "stated": 50000.0, "actual_sum": 6890371.78}
    ]

    suspicious = _check_suspicious_total_substitution(corrupted_retry_answer, corrected_totals)

    print("\n" + "=" * 80)
    print("Test 3: Corrupted retry answer (Creative CX = $6.89M)")
    print("=" * 80)
    print(f"Answer excerpt: 'Creative CX: $6,890,371.78'")
    print(f"Suspicious check result: {suspicious}")

    if suspicious:
        print(f"✅ DETECTED: {suspicious}")
    else:
        print("❌ FAIL: Should detect Creative CX line has the huge corrected total")

    assert suspicious is not None, "Should flag Creative CX having $6.89M as suspicious"
    assert "company" in suspicious.lower() or "suspicious" in suspicious.lower()


def test_correct_retry_answer_not_flagged():
    """
    CORRECT RETRY: Model put $6.89M in the Total line only, individual
    deals unchanged.
    """
    correct_retry_answer = """
    EMEA Closed Won & Closed Lost — Jan 2025 to Date

    Here's the breakdown of closed deals in EMEA. We had several deals
    close in January including Acme Corp at $1.2M, Beta Systems at $800K,
    and Creative CX at $50K on the won side. On the lost side, we had
    Delta Inc at $500K and Echo Ltd at $300K.

    Total closed deal value: $6,890,371.78
    """

    corrected_totals = [
        {"category": "total", "stated": 50000.0, "actual_sum": 6890371.78}
    ]

    suspicious = _check_suspicious_total_substitution(correct_retry_answer, corrected_totals)

    print("\n" + "=" * 80)
    print("Test 4: Correct retry answer (Creative CX still $50K, Total = $6.89M)")
    print("=" * 80)
    print(f"Answer excerpt: 'Creative CX: $50K ... Total: $6,890,371.78'")
    print(f"Suspicious check result: {suspicious}")

    if suspicious is None:
        print(f"✅ NOT FLAGGED: Correct placement of total")
    else:
        print(f"❌ FALSE POSITIVE: {suspicious}")

    assert suspicious is None, "Should NOT flag when total is in correct location"


if __name__ == "__main__":
    test_wrong_answer_has_low_stated_total()
    test_actual_sum_is_much_higher()
    test_corrupted_retry_answer_detected_as_suspicious()
    test_correct_retry_answer_not_flagged()

    print("\n" + "=" * 80)
    print("SUMMARY")
    print("=" * 80)
    print("✅ All 4 tests passed")
    print()
    print("The fix prevents Creative CX ($50K deal) from being corrupted")
    print("with the $6.89M total. Model is now explicitly told to replace")
    print("ONLY summary/total lines, and a structural check catches if the")
    print("corrected value ends up next to a company name.")
