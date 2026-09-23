"""
Test suite for canonical incremental_arr() NULL handling.

CRITICAL requirement: NULL in new_arr or expansion_arr must NOT cause
the row's contribution to be lost. Each NULL must coalesce to 0.
"""

import sys
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO / "api"))

from incremental_arr import incremental_arr, incremental_arr_with_exclusions


def test_both_values_present():
    """Normal case: both new_arr and expansion_arr have values"""
    deal = {"new_arr": 50000, "expansion_arr": 30000}
    result = incremental_arr(deal)
    assert result == 80000, f"Expected 80000, got {result}"
    print("✅ Both values present: 50000 + 30000 = 80000")


def test_new_arr_null_expansion_present():
    """CRITICAL: new_arr=NULL must coalesce to 0, not lose expansion_arr"""
    deal = {"new_arr": None, "expansion_arr": 30000}
    result = incremental_arr(deal)
    assert result == 30000, f"Expected 30000 (expansion_arr only), got {result}"
    print("✅ new_arr=NULL, expansion_arr=30000 → 30000 (NULL coalesced to 0)")


def test_expansion_arr_null_new_arr_present():
    """CRITICAL: expansion_arr=NULL must coalesce to 0, not lose new_arr"""
    deal = {"new_arr": 50000, "expansion_arr": None}
    result = incremental_arr(deal)
    assert result == 50000, f"Expected 50000 (new_arr only), got {result}"
    print("✅ new_arr=50000, expansion_arr=NULL → 50000 (NULL coalesced to 0)")


def test_both_null():
    """Both NULL should result in 0, not NULL or error"""
    deal = {"new_arr": None, "expansion_arr": None}
    result = incremental_arr(deal)
    assert result == 0, f"Expected 0 (both NULL), got {result}"
    print("✅ Both NULL → 0")


def test_both_zero():
    """Explicit 0 values (different from NULL)"""
    deal = {"new_arr": 0, "expansion_arr": 0}
    result = incremental_arr(deal)
    assert result == 0, f"Expected 0 (both zero), got {result}"
    print("✅ Both 0 → 0")


def test_missing_keys():
    """Missing keys should behave same as NULL"""
    deal = {}
    result = incremental_arr(deal)
    assert result == 0, f"Expected 0 (missing keys), got {result}"
    print("✅ Missing keys → 0 (same as NULL)")


def test_mixed_null_and_zero():
    """NULL vs 0 should behave identically"""
    deal1 = {"new_arr": None, "expansion_arr": 0}
    deal2 = {"new_arr": 0, "expansion_arr": None}
    result1 = incremental_arr(deal1)
    result2 = incremental_arr(deal2)
    assert result1 == 0, f"Expected 0, got {result1}"
    assert result2 == 0, f"Expected 0, got {result2}"
    print("✅ NULL and 0 mixed → both yield 0")


def test_renewal_pipeline_exclusion():
    """Test incremental_arr_with_exclusions renewal filter"""
    deal = {"new_arr": 50000, "expansion_arr": 30000, "pipeline_id": "123"}

    # Without exclusion
    result1 = incremental_arr_with_exclusions(deal, renewal_pipeline_id=None)
    assert result1 == 80000, f"Expected 80000, got {result1}"

    # With non-matching exclusion
    result2 = incremental_arr_with_exclusions(deal, renewal_pipeline_id="999")
    assert result2 == 80000, f"Expected 80000, got {result2}"

    # With matching exclusion
    result3 = incremental_arr_with_exclusions(deal, renewal_pipeline_id="123")
    assert result3 == 0, f"Expected 0 (renewal excluded), got {result3}"

    print("✅ Renewal pipeline exclusion works correctly")


def test_string_numeric_values():
    """Handle string numeric values (common in CSV/JSON)"""
    deal = {"new_arr": "50000", "expansion_arr": "30000"}
    result = incremental_arr(deal)
    assert result == 80000, f"Expected 80000, got {result}"
    print("✅ String numeric values converted correctly")


if __name__ == "__main__":
    print("=" * 80)
    print("INCREMENTAL ARR NULL HANDLING TESTS")
    print("=" * 80)
    print()

    try:
        test_both_values_present()
        test_new_arr_null_expansion_present()
        test_expansion_arr_null_new_arr_present()
        test_both_null()
        test_both_zero()
        test_missing_keys()
        test_mixed_null_and_zero()
        test_renewal_pipeline_exclusion()
        test_string_numeric_values()

        print()
        print("=" * 80)
        print("ALL TESTS PASSED")
        print("=" * 80)
        print()
        print("NULL handling verified:")
        print("  ✅ new_arr=NULL → coalesced to 0, expansion_arr preserved")
        print("  ✅ expansion_arr=NULL → coalesced to 0, new_arr preserved")
        print("  ✅ Both NULL → 0 (not NULL, not error)")
        print("  ✅ Missing keys → same as NULL")
        print()
        print("This is the MANDATORY pattern - without 'or 0' coalescing,")
        print("NULL values would propagate and cause rows to be lost.")

    except AssertionError as e:
        print()
        print("=" * 80)
        print(f"❌ TEST FAILED: {e}")
        print("=" * 80)
        sys.exit(1)
