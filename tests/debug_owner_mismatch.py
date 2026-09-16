#!/usr/bin/env python3
"""Debug by_owner mismatch in no_filters test case."""
import asyncio
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent / "api"))
sys.path.insert(0, str(Path(__file__).parent.parent / "scripts"))

from handlers import query_pipeline
from db import get_supabase


async def debug():
    """Debug by_owner mismatch."""
    with open("tests/fixtures/query_pipeline_baseline.json") as f:
        baseline = json.load(f)

    sb = get_supabase()

    test_case = baseline["test_cases"][0]  # no_filters
    result = await query_pipeline(test_case["params"], sb)
    expected = test_case["result"]

    print("Comparing by_owner results:")
    print("=" * 80)

    # Show both
    print("\nExpected (baseline):")
    for owner, stats in sorted(expected["by_owner"].items(), key=lambda x: x[1]["value"], reverse=True):
        print(f"  {owner:40s} count={stats['count']:3d} value=${stats['value']:12,.2f}")

    print("\nActual (refactored):")
    for owner, stats in sorted(result["by_owner"].items(), key=lambda x: x[1]["value"], reverse=True):
        print(f"  {owner:40s} count={stats['count']:3d} value=${stats['value']:12,.2f}")

    # Find differences
    print("\nDifferences:")
    for owner in set(list(expected["by_owner"].keys()) + list(result["by_owner"].keys())):
        exp = expected["by_owner"].get(owner)
        res = result["by_owner"].get(owner)
        if exp != res:
            print(f"  {owner}:")
            print(f"    Expected: {exp}")
            print(f"    Actual:   {res}")


if __name__ == "__main__":
    asyncio.run(debug())
