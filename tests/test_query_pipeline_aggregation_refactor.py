"""
Test that query_pipeline aggregation refactor produces EXACT same output as baseline.

Baseline captured 2026-09-15 before aggregation refactor (Phase 1a).
Verifies byte-for-byte match for:
- total_deals
- total_pipeline
- by_stage breakdown (all keys and values)
- by_owner breakdown (all keys and values)
- deals list (length and values)
"""
import asyncio
import json
import sys
from pathlib import Path

import pytest

# Add api/ to path
sys.path.insert(0, str(Path(__file__).parent.parent / "api"))
sys.path.insert(0, str(Path(__file__).parent.parent / "scripts"))

from handlers import query_pipeline
from db import get_supabase


BASELINE_PATH = Path(__file__).parent / "fixtures" / "query_pipeline_baseline.json"


@pytest.fixture(scope="module")
def baseline():
    """Load baseline fixture."""
    with open(BASELINE_PATH) as f:
        return json.load(f)


@pytest.fixture(scope="module")
def sb():
    """Supabase client."""
    return get_supabase()


@pytest.mark.asyncio
async def test_query_pipeline_no_filters_exact_match(baseline, sb):
    """Test case 1: No filters - exact match against baseline."""
    test_case = baseline["test_cases"][0]
    assert test_case["name"] == "no_filters"

    result = await query_pipeline(test_case["params"], sb)
    expected = test_case["result"]

    # Critical fields that must match EXACTLY
    assert result["total_deals"] == expected["total_deals"], \
        f"total_deals mismatch: {result['total_deals']} != {expected['total_deals']}"

    assert result["total_pipeline"] == expected["total_pipeline"], \
        f"total_pipeline mismatch: {result['total_pipeline']:.2f} != {expected['total_pipeline']:.2f}"

    # by_stage: all keys and values must match
    assert set(result["by_stage"].keys()) == set(expected["by_stage"].keys()), \
        f"by_stage keys mismatch: {set(result['by_stage'].keys())} != {set(expected['by_stage'].keys())}"

    for stage, stats in expected["by_stage"].items():
        assert result["by_stage"][stage]["count"] == stats["count"], \
            f"by_stage[{stage}] count mismatch"
        assert result["by_stage"][stage]["value"] == stats["value"], \
            f"by_stage[{stage}] value mismatch"

    # by_owner: all keys and values must match
    assert set(result["by_owner"].keys()) == set(expected["by_owner"].keys()), \
        f"by_owner keys mismatch"

    for owner, stats in expected["by_owner"].items():
        assert result["by_owner"][owner]["count"] == stats["count"], \
            f"by_owner[{owner}] count mismatch"
        assert result["by_owner"][owner]["value"] == stats["value"], \
            f"by_owner[{owner}] value mismatch"

    # deals list: length must match
    assert len(result["deals"]) == len(expected["deals"]), \
        f"deals list length mismatch: {len(result['deals'])} != {len(expected['deals'])}"


@pytest.mark.asyncio
async def test_query_pipeline_stage_filter_exact_match(baseline, sb):
    """Test case 2: stage_filter='scoping' - exact match."""
    test_case = baseline["test_cases"][1]
    assert test_case["name"] == "stage_filter_scoping"

    result = await query_pipeline(test_case["params"], sb)
    expected = test_case["result"]

    assert result["total_deals"] == expected["total_deals"]
    assert result["total_pipeline"] == expected["total_pipeline"]


@pytest.mark.asyncio
async def test_query_pipeline_pipeline_filter_exact_match(baseline, sb):
    """Test case 3: pipeline_filter='new_business' - exact match."""
    test_case = baseline["test_cases"][2]
    assert test_case["name"] == "pipeline_filter_new_business"

    result = await query_pipeline(test_case["params"], sb)
    expected = test_case["result"]

    assert result["total_deals"] == expected["total_deals"]
    assert result["total_pipeline"] == expected["total_pipeline"]


@pytest.mark.asyncio
async def test_query_pipeline_owner_filter_exact_match(baseline, sb):
    """Test case 4: owner_email filter - exact match."""
    test_case = baseline["test_cases"][3]
    assert test_case["name"] == "owner_filter"

    if test_case["params"] is None:
        pytest.skip("No owner_filter test case in baseline")

    result = await query_pipeline(test_case["params"], sb)
    expected = test_case["result"]

    assert result["total_deals"] == expected["total_deals"]
    assert result["total_pipeline"] == expected["total_pipeline"]


@pytest.mark.asyncio
async def test_query_pipeline_combined_filters_exact_match(baseline, sb):
    """Test case 5: stage_filter + pipeline_filter - exact match."""
    test_case = baseline["test_cases"][4]
    assert test_case["name"] == "combined_stage_pipeline"

    result = await query_pipeline(test_case["params"], sb)
    expected = test_case["result"]

    assert result["total_deals"] == expected["total_deals"]
    assert result["total_pipeline"] == expected["total_pipeline"]


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
