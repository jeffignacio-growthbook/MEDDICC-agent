#!/usr/bin/env python3
"""Quick verification that current code matches baseline."""
import asyncio
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent / "api"))
sys.path.insert(0, str(Path(__file__).parent.parent / "scripts"))

from handlers import query_pipeline
from db import get_supabase


async def verify():
    """Run quick verification."""
    with open("tests/fixtures/query_pipeline_baseline.json") as f:
        baseline = json.load(f)

    sb = get_supabase()

    print("Verifying current code matches baseline...")
    print("=" * 80)

    # Test case 1: No filters
    print("\n1. No filters test")
    test_case = baseline["test_cases"][0]
    result = await query_pipeline(test_case["params"], sb)
    expected = test_case["result"]

    print(f"   total_deals: {result['total_deals']} == {expected['total_deals']} ✓"
          if result['total_deals'] == expected['total_deals'] else
          f"   total_deals: {result['total_deals']} != {expected['total_deals']} ✗")

    print(f"   total_pipeline: ${result['total_pipeline']:,.2f} == ${expected['total_pipeline']:,.2f} ✓"
          if result['total_pipeline'] == expected['total_pipeline'] else
          f"   total_pipeline: ${result['total_pipeline']:,.2f} != ${expected['total_pipeline']:,.2f} ✗")

    # Check by_stage keys match
    if set(result['by_stage'].keys()) == set(expected['by_stage'].keys()):
        print(f"   by_stage keys: {len(result['by_stage'])} stages ✓")
        # Verify values
        mismatches = []
        for stage, stats in expected['by_stage'].items():
            if result['by_stage'][stage]['count'] != stats['count']:
                mismatches.append(f"{stage} count")
            if result['by_stage'][stage]['value'] != stats['value']:
                mismatches.append(f"{stage} value")
        if mismatches:
            print(f"   by_stage values: MISMATCH in {mismatches} ✗")
        else:
            print(f"   by_stage values: all match ✓")
    else:
        print(f"   by_stage keys: MISMATCH ✗")

    # Check by_owner
    if set(result['by_owner'].keys()) == set(expected['by_owner'].keys()):
        print(f"   by_owner keys: {len(result['by_owner'])} owners ✓")
    else:
        print(f"   by_owner keys: MISMATCH ✗")

    print("\n" + "=" * 80)
    print("✅ Pre-refactor baseline verification complete")


if __name__ == "__main__":
    asyncio.run(verify())
