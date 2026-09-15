#!/usr/bin/env python3
"""
Reproduce the AGGREGATION_VERIFY extraction bug where _extract_total()
grabs the wrong number from draft answer text.

BUG: _AMOUNT_RE has optional $ sign (\$?), so it matches ANY bare number,
not just dollar amounts. When a sentence mentions "total" and contains
both a year (2025) and a dollar figure ($6.8M), it grabs the year.

LIVE INCIDENTS (2026-09-14):
- "stated total" extracted as 8.0, 2025.0, 2025.0 across three questions
- None of these are plausible dollar totals
- Hypothesis confirmed: grabbing year from date text, not the real $ figure
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent / "api"))

from aggregation_verification import extract_stated_totals_from_answer, _extract_total


def test_bug_extracts_year_instead_of_dollar_total():
    """
    LIVE CASE 1: Draft answer mentions "Jan 2025 to Date" in title,
    then states "Total closed deal value: $6,890,371.78" in body.

    CURRENT BUG: Extracts 2025.0 (the year)
    EXPECTED: Should extract 6890371.78 (the dollar figure)
    """
    draft_text = """
    EMEA Closed Won & Closed Lost — Jan 2025 to Date

    Here's the breakdown of closed deals in EMEA from January 2025 to present:

    Total closed deal value: $6,890,371.78
    - Won: $4.2M across 12 deals
    - Lost: $2.7M across 8 deals
    """

    result = _extract_total(draft_text)

    print(f"Test 1: Year in title, $ total in body")
    print(f"  Draft text (excerpt): 'Jan 2025 to Date... Total closed deal value: $6,890,371.78'")
    print(f"  Extracted: {result}")
    print(f"  Expected: 6890371.78")

    if result == 2025.0:
        print(f"  ❌ BUG CONFIRMED: Extracted year (2025) instead of dollar total")
        return False
    elif abs(result - 6890371.78) < 1.0:
        print(f"  ✅ CORRECT: Extracted the real dollar total")
        return True
    else:
        print(f"  ⚠️  UNEXPECTED: Got {result}, neither the year nor the expected total")
        return False


def test_bug_extracts_deal_count_instead_of_total():
    """
    LIVE CASE 2: Draft answer mentions "8 deals" early, then
    states "Total pipeline: $1.2M" later.

    CURRENT BUG: Might extract 8.0 (deal count)
    EXPECTED: Should extract 1200000.0 (the dollar figure)
    """
    draft_text = """
    Current pipeline includes 8 deals across multiple stages.

    Total pipeline value: $1.2M
    """

    result = _extract_total(draft_text)

    print(f"\nTest 2: Deal count mentioned, then $ total")
    print(f"  Draft text (excerpt): '8 deals... Total pipeline value: $1.2M'")
    print(f"  Extracted: {result}")
    print(f"  Expected: 1200000.0")

    if result == 8.0:
        print(f"  ❌ BUG CONFIRMED: Extracted deal count (8) instead of dollar total")
        return False
    elif abs(result - 1200000.0) < 1.0:
        print(f"  ✅ CORRECT: Extracted the real dollar total")
        return True
    else:
        print(f"  ⚠️  UNEXPECTED: Got {result}, neither count nor expected total")
        return False


def test_bug_bare_number_in_total_sentence():
    """
    LIVE CASE 3: The sentence containing "total" has a bare number
    (no $ sign) before the actual dollar figure.

    Example: "Total for 2025 Q1: $500K"

    CURRENT BUG: Extracts 2025.0 (bare number in same sentence)
    EXPECTED: Should extract 500000.0 (the dollar figure)
    """
    draft_text = """
    Total for 2025 Q1 is $500K across all regions.
    """

    result = _extract_total(draft_text)

    print(f"\nTest 3: Bare number in same sentence as 'total'")
    print(f"  Draft text: 'Total for 2025 Q1 is $500K'")
    print(f"  Extracted: {result}")
    print(f"  Expected: 500000.0")

    if result == 2025.0:
        print(f"  ❌ BUG CONFIRMED: Extracted bare number (2025) instead of dollar total")
        return False
    elif abs(result - 500000.0) < 1.0:
        print(f"  ✅ CORRECT: Extracted the real dollar total")
        return True
    else:
        print(f"  ⚠️  UNEXPECTED: Got {result}, neither 2025 nor expected total")
        return False


def test_full_extraction_with_multiple_categories():
    """
    Test the full extract_stated_totals_from_answer() function with
    a realistic multi-category answer that has a year in the title.
    """
    draft_text = """
    EMEA Pipeline Movement — Jan 2025 to Date

    Total net change: $1.5M

    By week:
    - Jan 6: $200K won
    - Jan 13: $300K won, $100K lost
    - Jan 20: $400K won
    - Jan 27: $500K won, $200K lost
    """

    result = extract_stated_totals_from_answer(draft_text)

    print(f"\nTest 4: Full extraction with categories")
    print(f"  Draft text includes: 'Jan 2025 to Date' and 'Total net change: $1.5M'")
    print(f"  Extracted totals: {result}")

    success = True

    if "total" not in result:
        print(f"  ❌ FAIL: No 'total' key extracted")
        success = False
    elif result.get("total") == 2025.0:
        print(f"  ❌ BUG CONFIRMED: 'total' = 2025.0 (year), not $1.5M")
        success = False
    elif abs(result.get("total", 0) - 1500000.0) < 1.0:
        print(f"  ✅ CORRECT: 'total' = {result['total']} (~$1.5M)")
    else:
        print(f"  ⚠️  UNEXPECTED: 'total' = {result.get('total')}")
        success = False

    # Also check category extraction
    if "Jan 6" in result:
        print(f"  ✅ Category 'Jan 6' extracted: {result['Jan 6']}")

    return success


if __name__ == "__main__":
    print("=" * 80)
    print("AGGREGATION EXTRACTION BUG REPRODUCTION")
    print("=" * 80)
    print()
    print("BUG: _AMOUNT_RE regex has optional $ sign (\\$?), matching ANY bare number.")
    print("Result: Extracts years, counts, or other stray digits instead of $ totals.")
    print()
    print("=" * 80)

    results = []
    results.append(test_bug_extracts_year_instead_of_dollar_total())
    results.append(test_bug_extracts_deal_count_instead_of_total())
    results.append(test_bug_bare_number_in_total_sentence())
    results.append(test_full_extraction_with_multiple_categories())

    print()
    print("=" * 80)
    print("SUMMARY")
    print("=" * 80)

    passed = sum(results)
    total = len(results)

    if passed == total:
        print(f"✅ All {total} tests passed - bug is FIXED")
    else:
        print(f"❌ {total - passed}/{total} tests failed - bug is ACTIVE")
        print()
        print("ROOT CAUSE:")
        print("  _AMOUNT_RE = re.compile(r'([+-]?)\\$?([\\d][\\d,]*...')")
        print("                                      ^^^ Optional $ sign!")
        print()
        print("FIX: Change \\$? to \\$ (required) OR add context check")
        print("     (e.g., only match numbers immediately after 'total' + colon)")
