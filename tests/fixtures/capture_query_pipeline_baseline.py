#!/usr/bin/env python3
"""
Capture query_pipeline regression baseline BEFORE aggregation refactor.

Runs query_pipeline against REAL current database state for 5 test cases:
1. No filters (baseline)
2. stage_filter="scoping"
3. pipeline_filter="new_business"
4. owner_email set (first owner from by_owner results)
5. Combined: stage_filter + pipeline_filter

Saves output as JSON fixtures for byte-for-byte comparison after refactor.
"""
import asyncio
import json
import sys
from pathlib import Path

# Add api/ and scripts/ to path
sys.path.insert(0, str(Path(__file__).parent.parent.parent / "api"))
sys.path.insert(0, str(Path(__file__).parent.parent.parent / "scripts"))

from handlers import query_pipeline
from db import get_supabase


async def capture_baseline():
    """Capture query_pipeline output for 5 test cases."""
    sb = get_supabase()

    print("Capturing query_pipeline baseline against live database...")
    print("=" * 80)

    # Test case 1: No filters (baseline)
    print("\n1. No filters (baseline)")
    result1 = await query_pipeline({}, sb)
    print(f"   total_deals: {result1['total_deals']}")
    print(f"   total_pipeline: ${result1['total_pipeline']:,.2f}")
    print(f"   by_stage keys: {len(result1['by_stage'])}")
    print(f"   by_owner keys: {len(result1['by_owner'])}")

    # Test case 2: Stage filter
    print("\n2. stage_filter='scoping'")
    result2 = await query_pipeline({"stage_filter": "scoping"}, sb)
    print(f"   total_deals: {result2['total_deals']}")
    print(f"   total_pipeline: ${result2['total_pipeline']:,.2f}")

    # Test case 3: Pipeline filter
    print("\n3. pipeline_filter='new_business'")
    result3 = await query_pipeline({"pipeline_filter": "new_business"}, sb)
    print(f"   total_deals: {result3['total_deals']}")
    print(f"   total_pipeline: ${result3['total_pipeline']:,.2f}")

    # Test case 4: Owner filter (use first owner from baseline)
    first_owner = list(result1['by_owner'].keys())[0] if result1['by_owner'] else None
    if first_owner:
        print(f"\n4. owner_email='{first_owner}'")
        result4 = await query_pipeline({"owner_email": first_owner}, sb)
        print(f"   total_deals: {result4['total_deals']}")
        print(f"   total_pipeline: ${result4['total_pipeline']:,.2f}")
    else:
        print("\n4. owner_email - SKIPPED (no owners in baseline)")
        result4 = None

    # Test case 5: Combined filters
    print("\n5. stage_filter='scoping' + pipeline_filter='new_business'")
    result5 = await query_pipeline({
        "stage_filter": "scoping",
        "pipeline_filter": "new_business"
    }, sb)
    print(f"   total_deals: {result5['total_deals']}")
    print(f"   total_pipeline: ${result5['total_pipeline']:,.2f}")

    # Save all results as JSON fixtures
    fixtures = {
        "captured_at": "2026-09-15 (pre-aggregation-refactor)",
        "test_cases": [
            {
                "name": "no_filters",
                "params": {},
                "result": result1
            },
            {
                "name": "stage_filter_scoping",
                "params": {"stage_filter": "scoping"},
                "result": result2
            },
            {
                "name": "pipeline_filter_new_business",
                "params": {"pipeline_filter": "new_business"},
                "result": result3
            },
            {
                "name": "owner_filter",
                "params": {"owner_email": first_owner} if first_owner else None,
                "result": result4
            },
            {
                "name": "combined_stage_pipeline",
                "params": {
                    "stage_filter": "scoping",
                    "pipeline_filter": "new_business"
                },
                "result": result5
            }
        ],
        "critical_fields_to_verify": [
            "total_deals",
            "total_pipeline",
            "by_stage (all keys and values)",
            "by_owner (all keys and values)",
            "deals (top 20 list length and values)"
        ]
    }

    output_path = Path(__file__).parent / "query_pipeline_baseline.json"
    with open(output_path, "w") as f:
        json.dump(fixtures, f, indent=2, default=str)

    print("\n" + "=" * 80)
    print(f"✅ Baseline captured to: {output_path}")
    print(f"   Total test cases: {len([tc for tc in fixtures['test_cases'] if tc['result']])}")
    print("\nCritical assertion points for post-refactor comparison:")
    print("  - total_deals (count)")
    print("  - total_pipeline (sum)")
    print("  - by_stage: keys and {count, value} for each")
    print("  - by_owner: keys and {count, value} for each")
    print("  - deals: length and incremental_arr values")


if __name__ == "__main__":
    asyncio.run(capture_baseline())
