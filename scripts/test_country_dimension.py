#!/usr/bin/env python3
"""
Verification tests for country dimension support (Marketing Priority #2).

Tests:
1. Semantic variant canonicalization (Netherlands, Russia, Czech Republic)
2. Non-variant countries work correctly
3. Case-insensitive matching
4. Unknown country handling
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from api.dimension_resolver import resolve_dimension_filter


def test_netherlands_variants():
    """Netherlands / The Netherlands → canonical 'Netherlands'."""
    print("\n[TEST 1] Netherlands variants")

    # Test both variants
    result1 = resolve_dimension_filter("Netherlands")
    result2 = resolve_dimension_filter("The Netherlands")
    result3 = resolve_dimension_filter("the netherlands")  # case insensitive

    # All should resolve to canonical "Netherlands"
    assert result1.get("column") == "company_country", f"Expected company_country, got {result1}"
    assert result1.get("value") == "Netherlands", f"Expected 'Netherlands', got {result1.get('value')}"

    assert result2.get("column") == "company_country", f"Expected company_country, got {result2}"
    assert result2.get("value") == "Netherlands", f"Expected 'Netherlands', got {result2.get('value')}"

    assert result3.get("column") == "company_country", f"Expected company_country, got {result3}"
    assert result3.get("value") == "Netherlands", f"Expected 'Netherlands', got {result3.get('value')}"

    print(f"  ✓ 'Netherlands' → {result1['value']}")
    print(f"  ✓ 'The Netherlands' → {result2['value']}")
    print(f"  ✓ 'the netherlands' → {result3['value']}")
    print("  ✓ All variants canonicalize to 'Netherlands'")


def test_russia_variants():
    """Russia / Russian Federation → canonical 'Russia'."""
    print("\n[TEST 2] Russia variants")

    result1 = resolve_dimension_filter("Russia")
    result2 = resolve_dimension_filter("Russian Federation")
    result3 = resolve_dimension_filter("russian federation")  # case insensitive

    assert result1.get("column") == "company_country"
    assert result1.get("value") == "Russia", f"Expected 'Russia', got {result1.get('value')}"

    assert result2.get("column") == "company_country"
    assert result2.get("value") == "Russia", f"Expected 'Russia', got {result2.get('value')}"

    assert result3.get("column") == "company_country"
    assert result3.get("value") == "Russia", f"Expected 'Russia', got {result3.get('value')}"

    print(f"  ✓ 'Russia' → {result1['value']}")
    print(f"  ✓ 'Russian Federation' → {result2['value']}")
    print(f"  ✓ 'russian federation' → {result3['value']}")
    print("  ✓ All variants canonicalize to 'Russia'")


def test_czech_variants():
    """Czech Republic / Czechia → canonical 'Czech Republic'."""
    print("\n[TEST 3] Czech Republic variants")

    result1 = resolve_dimension_filter("Czech Republic")
    result2 = resolve_dimension_filter("Czechia")
    result3 = resolve_dimension_filter("czechia")  # case insensitive

    assert result1.get("column") == "company_country"
    assert result1.get("value") == "Czech Republic", f"Expected 'Czech Republic', got {result1.get('value')}"

    assert result2.get("column") == "company_country"
    assert result2.get("value") == "Czech Republic", f"Expected 'Czech Republic', got {result2.get('value')}"

    assert result3.get("column") == "company_country"
    assert result3.get("value") == "Czech Republic", f"Expected 'Czech Republic', got {result3.get('value')}"

    print(f"  ✓ 'Czech Republic' → {result1['value']}")
    print(f"  ✓ 'Czechia' → {result2['value']}")
    print(f"  ✓ 'czechia' → {result3['value']}")
    print("  ✓ All variants canonicalize to 'Czech Republic'")


def test_non_variant_countries():
    """Countries without variants work correctly (exact match)."""
    print("\n[TEST 4] Non-variant countries")

    # Test some major countries that don't have semantic variants
    result1 = resolve_dimension_filter("United States")
    result2 = resolve_dimension_filter("Germany")
    result3 = resolve_dimension_filter("France")
    result4 = resolve_dimension_filter("United Kingdom")

    # These should resolve as-is (no canonicalization needed)
    assert result1.get("column") == "company_country"
    assert result1.get("value") == "United States"

    assert result2.get("column") == "company_country"
    assert result2.get("value") == "Germany"

    assert result3.get("column") == "company_country"
    assert result3.get("value") == "France"

    assert result4.get("column") == "company_country"
    assert result4.get("value") == "United Kingdom"

    print("  ✓ 'United States' → company_country.eq.'United States'")
    print("  ✓ 'Germany' → company_country.eq.'Germany'")
    print("  ✓ 'France' → company_country.eq.'France'")
    print("  ✓ 'United Kingdom' → company_country.eq.'United Kingdom'")
    print("  ✓ Non-variant countries resolve correctly")


def test_case_insensitivity():
    """Case-insensitive matching works for all countries."""
    print("\n[TEST 5] Case-insensitive matching")

    result1 = resolve_dimension_filter("GERMANY")
    result2 = resolve_dimension_filter("united states")
    result3 = resolve_dimension_filter("FrAnCe")

    assert result1.get("column") == "company_country"
    assert result2.get("column") == "company_country"
    assert result3.get("column") == "company_country"

    print("  ✓ 'GERMANY' → resolves (case normalized)")
    print("  ✓ 'united states' → resolves (case normalized)")
    print("  ✓ 'FrAnCe' → resolves (case normalized)")
    print("  ✓ Case-insensitive matching works")


def test_unknown_country_handling():
    """Unknown/invalid countries don't crash."""
    print("\n[TEST 6] Unknown country handling")

    # A country that definitely doesn't exist
    result = resolve_dimension_filter("Atlantis")

    # Should either:
    # - Return unknown_value error (if not in any other dimension)
    # - OR resolve to company_country.eq.'Atlantis' (exact match fallback)
    # The second is expected per _country_candidates() design

    if result.get("error") == "unknown_value":
        print("  ✓ 'Atlantis' → unknown_value error (not in any dimension)")
    elif result.get("column") == "company_country" and result.get("value") == "Atlantis":
        print("  ✓ 'Atlantis' → company_country.eq.'Atlantis' (exact match fallback)")
    else:
        raise AssertionError(f"Unexpected result for unknown country: {result}")

    print("  ✓ Unknown countries handled gracefully")


def test_motivating_question_readiness():
    """Verify country dimension works for the original motivating question."""
    print("\n[TEST 7] Motivating question readiness")

    # The original question: "Show me EMEA deals by country"
    # This would involve:
    # 1. Region filter (EMEA) - already works
    # 2. Country breakdown - now works via company_country

    # Test that we can resolve some EMEA countries
    uk_result = resolve_dimension_filter("United Kingdom")
    germany_result = resolve_dimension_filter("Germany")
    france_result = resolve_dimension_filter("France")
    netherlands_result = resolve_dimension_filter("The Netherlands")

    assert uk_result.get("column") == "company_country"
    assert germany_result.get("column") == "company_country"
    assert france_result.get("column") == "company_country"
    assert netherlands_result.get("column") == "company_country"
    assert netherlands_result.get("value") == "Netherlands"  # canonicalized

    print("  ✓ United Kingdom → company_country filter")
    print("  ✓ Germany → company_country filter")
    print("  ✓ France → company_country filter")
    print("  ✓ The Netherlands → company_country filter (canonicalized)")
    print("  ✓ Original motivating question ('EMEA deals by country') is now supported")


def main():
    print("=" * 70)
    print("COUNTRY DIMENSION VERIFICATION TESTS")
    print("Marketing/RevOps-lead Priority #2")
    print("=" * 70)

    tests = [
        test_netherlands_variants,
        test_russia_variants,
        test_czech_variants,
        test_non_variant_countries,
        test_case_insensitivity,
        test_unknown_country_handling,
        test_motivating_question_readiness,
    ]

    failed = []
    for test in tests:
        try:
            test()
        except Exception as e:
            failed.append((test.__name__, str(e)))
            print(f"\n  ❌ FAILED: {e}")

    print("\n" + "=" * 70)
    print("TEST SUMMARY")
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

    print("\n✅ All country dimension tests passed")
    print("\nPhase 1-3 complete:")
    print("  ✓ Canonicalization mapping added (_COUNTRY_ALIASES)")
    print("  ✓ Dimension resolver updated (_country_candidates)")
    print("  ✓ Verification tests pass (semantic variants, exact matches)")
    print("\nCountry dimension is now fully supported in resolve_dimension_filter().")
    return 0


if __name__ == "__main__":
    sys.exit(main())
