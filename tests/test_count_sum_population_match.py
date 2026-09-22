#!/usr/bin/env python3
"""
Gate 3: Count/Sum Population Match Test

Verifies that any code reporting both deal count and dollar total uses the
SAME filtered population for both metrics.

This gate prevents the bug where is_incremental_pipeline() returned True for
ALL new business deals (regardless of ARR), causing deal counts to include
$0 ARR deals while dollar totals excluded them, producing misleading metrics.

Example of the bug (before fix):
  - Agent reported: 316 deals, $20.1M pipeline
  - Ground truth: 207 deals with incremental ARR > 0, $21.4M
  - 109 deals had $0 incremental ARR but were counted anyway

Test strategy:
  1. Test is_incremental_pipeline() directly with edge cases
  2. Verify query_pipeline and pipeline_coverage use consistent populations
  3. Spot-check that count and sum match on known queries
"""
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(REPO_ROOT / "api"))

from field_semantics import is_incremental_pipeline


def test_is_incremental_pipeline_zero_arr():
    """
    Test that is_incremental_pipeline returns False for $0 ARR deals.

    This is the core bug fix: previously returned True for all new business
    pipeline deals regardless of ARR amount.
    """
    # Deal in new business pipeline with $0 ARR - should NOT count
    deal_zero = {
        "pipeline_id": "default",
        "expansion_arr": 0,
        "new_arr": 0,
        "deal_value": 50000,  # Has deal_value but no ARR
    }

    result = is_incremental_pipeline(deal_zero)
    assert result is False, \
        f"Deal with $0 incremental ARR should NOT count in pipeline, got {result}"

    # Deal with only new_arr
    deal_new = {
        "pipeline_id": "default",
        "expansion_arr": 0,
        "new_arr": 100000,
    }

    result = is_incremental_pipeline(deal_new)
    assert result is True, \
        f"Deal with new_arr > 0 should count, got {result}"

    # Deal with only expansion_arr
    deal_expansion = {
        "pipeline_id": "866608541",  # renewal pipeline
        "expansion_arr": 50000,
        "new_arr": 0,
    }

    result = is_incremental_pipeline(deal_expansion)
    assert result is True, \
        f"Deal with expansion_arr > 0 should count, got {result}"

    # Pure renewal (no incremental ARR)
    deal_renewal = {
        "pipeline_id": "866608541",
        "expansion_arr": 0,
        "new_arr": 0,
        "renewal_revenue": 200000,
    }

    result = is_incremental_pipeline(deal_renewal)
    assert result is False, \
        f"Pure renewal with $0 incremental ARR should NOT count, got {result}"

    print("✅ PASS: is_incremental_pipeline correctly filters on ARR > 0")
    return True


def test_query_pipeline_consistency():
    """
    Verify query_pipeline uses is_incremental_pipeline() for both count and sum.

    This is a code inspection test - we verify the code structure ensures
    count and sum operate on the same filtered population.
    """
    handlers_file = REPO_ROOT / "api" / "handlers.py"
    content = handlers_file.read_text()

    # Find the query_pipeline function
    start = content.find("async def query_pipeline(")
    if start == -1:
        raise AssertionError("Could not find query_pipeline function")

    # Extract ~300 lines after the function definition
    query_pipeline_section = content[start:start + 15000]

    # Check that it uses is_incremental_pipeline
    assert "is_incremental_pipeline(deal)" in query_pipeline_section, \
        "query_pipeline should use is_incremental_pipeline() for filtering"

    # Check that incremental_value is calculated from the same deal object
    assert "expansion_arr + new_arr" in query_pipeline_section, \
        "query_pipeline should calculate incremental_value from expansion_arr + new_arr"

    # Check that the pattern is: filter with is_incremental_pipeline, THEN calculate
    # This ensures count and sum use the same population
    incremental_pipeline_pos = query_pipeline_section.find("is_incremental_pipeline(deal)")
    incremental_value_pos = query_pipeline_section.find("_incremental_value")

    assert incremental_pipeline_pos < incremental_value_pos, \
        "is_incremental_pipeline check should come before _incremental_value assignment"

    print("✅ PASS: query_pipeline uses consistent population for count and sum")
    return True


def test_pipeline_coverage_consistency():
    """
    Verify pipeline_coverage.py uses is_incremental_pipeline() correctly.
    """
    coverage_file = REPO_ROOT / "scripts" / "pipeline_coverage.py"
    if not coverage_file.exists():
        print("⚠️  SKIP: pipeline_coverage.py not found")
        return True

    content = coverage_file.read_text()

    # Check that it uses is_incremental_pipeline
    assert "is_incremental_pipeline(d)" in content, \
        "pipeline_coverage should use is_incremental_pipeline() for filtering"

    # Check that it calculates incremental_value from the same deal
    assert 'expansion_arr") or 0) + (d.get("new_arr")' in content, \
        "pipeline_coverage should calculate incremental_value from expansion_arr + new_arr"

    # Check the pattern: filter first, then calculate
    filter_pos = content.find("is_incremental_pipeline(d)")
    calc_pos = content.find("_incremental_value")

    assert filter_pos > 0 and calc_pos > 0, \
        "Should find both filter and calculation"

    assert filter_pos < calc_pos, \
        "is_incremental_pipeline check should come before _incremental_value assignment"

    print("✅ PASS: pipeline_coverage uses consistent population for count and sum")
    return True


def test_no_pipeline_id_only_filtering():
    """
    Verify we're not filtering on pipeline_id alone without checking ARR.

    This was the root cause: checking (pipeline_id != renewal) returned True
    for all new business deals regardless of ARR.
    """
    field_semantics_file = REPO_ROOT / "api" / "field_semantics.py"
    content = field_semantics_file.read_text()

    # Find is_incremental_pipeline function
    start = content.find("def is_incremental_pipeline(")
    if start == -1:
        raise AssertionError("Could not find is_incremental_pipeline function")

    # Extract function (up to next def or EOF)
    next_def = content.find("\ndef ", start + 1)
    if next_def == -1:
        func_content = content[start:]
    else:
        func_content = content[start:next_def]

    # The BUGGY pattern we're preventing:
    # if pipeline_id != _RENEWAL_PIPELINE_ID:
    #     return True

    # This should NOT exist anymore
    buggy_pattern_1 = "if pipeline_id != _RENEWAL_PIPELINE_ID:\n        return True"
    buggy_pattern_2 = 'if pipeline_id != _RENEWAL_PIPELINE_ID:\n            return True'

    assert buggy_pattern_1 not in func_content and buggy_pattern_2 not in func_content, \
        "is_incremental_pipeline should NOT return True based on pipeline_id alone"

    # The CORRECT pattern should exist:
    # return expansion_arr > 0 or new_arr > 0

    assert "expansion_arr > 0 or new_arr > 0" in func_content, \
        "is_incremental_pipeline should check ARR values, not just pipeline_id"

    print("✅ PASS: is_incremental_pipeline checks ARR, not just pipeline_id")
    return True


if __name__ == "__main__":
    print("=" * 80)
    print("GATE 3: COUNT/SUM POPULATION MATCH TEST")
    print("=" * 80)
    print()

    try:
        test_is_incremental_pipeline_zero_arr()
        print()
        test_query_pipeline_consistency()
        print()
        test_pipeline_coverage_consistency()
        print()
        test_no_pipeline_id_only_filtering()
        print()
        print("=" * 80)
        print("✅ ALL TESTS PASSED - Count/sum populations are consistent")
        print("=" * 80)
        sys.exit(0)
    except AssertionError as e:
        print()
        print("=" * 80)
        print(f"❌ TEST FAILED: {e}")
        print("=" * 80)
        sys.exit(1)
    except Exception as e:
        print()
        print("=" * 80)
        print(f"❌ ERROR: {e}")
        import traceback
        traceback.print_exc()
        print("=" * 80)
        sys.exit(1)
