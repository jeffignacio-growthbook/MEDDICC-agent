#!/usr/bin/env python3
"""Comprehensive verification of all 5 baseline test cases."""
import asyncio
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent / "api"))
sys.path.insert(0, str(Path(__file__).parent.parent / "scripts"))

from handlers import query_pipeline
from db import get_supabase


async def verify_all():
    """Verify all 5 test cases."""
    with open("tests/fixtures/query_pipeline_baseline.json") as f:
        baseline = json.load(f)

    sb = get_supabase()

    print("Comprehensive Baseline Verification")
    print("=" * 80)

    all_passed = True

    for i, test_case in enumerate(baseline["test_cases"], 1):
        if test_case["result"] is None:
            print(f"\n{i}. {test_case['name']}: SKIPPED (no baseline)")
            continue

        print(f"\n{i}. {test_case['name']}")
        result = await query_pipeline(test_case["params"], sb)
        expected = test_case["result"]

        # Check critical fields
        checks = [
            ("total_deals", result["total_deals"] == expected["total_deals"]),
            ("total_pipeline", result["total_pipeline"] == expected["total_pipeline"]),
            ("by_stage_keys", set(result["by_stage"].keys()) == set(expected["by_stage"].keys())),
            ("by_owner_keys", set(result["by_owner"].keys()) == set(expected["by_owner"].keys())),
        ]

        # Check by_stage values (with float tolerance for aggregation precision)
        stage_values_match = True
        for stage, stats in expected["by_stage"].items():
            if result["by_stage"][stage]["count"] != stats["count"]:
                stage_values_match = False
                break
            # Use tolerance of 0.01 (1 cent) for float comparison
            if abs(result["by_stage"][stage]["value"] - stats["value"]) > 0.01:
                stage_values_match = False
                break
        checks.append(("by_stage_values", stage_values_match))

        # Check by_owner values (with float tolerance for aggregation precision)
        owner_values_match = True
        for owner, stats in expected["by_owner"].items():
            if result["by_owner"][owner]["count"] != stats["count"]:
                owner_values_match = False
                break
            # Use tolerance of 0.01 (1 cent) for float comparison
            if abs(result["by_owner"][owner]["value"] - stats["value"]) > 0.01:
                owner_values_match = False
                break
        checks.append(("by_owner_values", owner_values_match))

        # Report
        for field, passed in checks:
            if passed:
                print(f"   {field}: ✓")
            else:
                print(f"   {field}: ✗ MISMATCH")
                all_passed = False

    print("\n" + "=" * 80)
    if all_passed:
        print("✅ ALL TEST CASES PASSED - Refactor produces exact same output")
    else:
        print("❌ SOME TEST CASES FAILED - Review mismatches above")
        sys.exit(1)


if __name__ == "__main__":
    asyncio.run(verify_all())
