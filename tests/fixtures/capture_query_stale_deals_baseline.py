#!/usr/bin/env python3
"""
Capture query_stale_deals regression baseline BEFORE any refactoring.

Runs query_stale_deals against current database for multiple test cases covering
the handler's filter space. Saves output as JSON fixtures for verification.
"""
import asyncio
import json
import sys
from pathlib import Path
from dotenv import load_dotenv

# Load environment
repo_root = Path(__file__).parent.parent.parent
load_dotenv(repo_root / ".env")

sys.path.insert(0, str(repo_root / "api"))

from handlers import query_stale_deals
from db import get_supabase


async def capture_baseline():
    """Capture query_stale_deals output across filter space."""
    sb = get_supabase()

    print("Capturing query_stale_deals baseline against live database...")
    print("=" * 80)

    # Test case 1: No filters (default threshold 21 days)
    print("\n1. No filters (baseline, stale_days=21 default)")
    result1 = await query_stale_deals({}, sb)
    print(f"   stale_count: {result1.get('stale_count')}")
    print(f"   past_close_date_count: {result1.get('past_close_date_count')}")
    print(f"   deals returned: {len(result1.get('stale_deals', []))}")

    # Test case 2: Explicit stale_days threshold
    print("\n2. stale_days=30")
    result2 = await query_stale_deals({"stale_days": 30}, sb)
    print(f"   stale_count: {result2.get('stale_count')}")
    print(f"   deals returned: {len(result2.get('stale_deals', []))}")

    # Test case 3: Owner filter
    # Find an owner from result1 to use
    first_owner = None
    if result1.get('stale_deals'):
        for deal in result1['stale_deals']:
            if deal.get('owner_email'):
                first_owner = deal['owner_email']
                break

    if first_owner:
        print(f"\n3. owner_email='{first_owner}'")
        result3 = await query_stale_deals({"owner_email": first_owner}, sb)
        print(f"   stale_count: {result3.get('stale_count')}")
        print(f"   deals returned: {len(result3.get('stale_deals', []))}")
    else:
        print("\n3. owner_email - SKIPPED (no owners in baseline)")
        result3 = None

    # Test case 4: Stage filter
    # Find a stage from result1 to use
    first_stage = None
    if result1.get('stale_deals'):
        for deal in result1['stale_deals']:
            if deal.get('stage'):
                first_stage = deal['stage']
                break

    if first_stage:
        print(f"\n4. stage='{first_stage}'")
        result4 = await query_stale_deals({"stage": first_stage}, sb)
        print(f"   stale_count: {result4.get('stale_count')}")
        print(f"   deals returned: {len(result4.get('stale_deals', []))}")
    else:
        print("\n4. stage - SKIPPED (no stages in baseline)")
        result4 = None

    # Test case 5: Higher threshold (60 days)
    print("\n5. stale_days=60")
    result5 = await query_stale_deals({"stale_days": 60}, sb)
    print(f"   stale_count: {result5.get('stale_count')}")
    print(f"   deals returned: {len(result5.get('stale_deals', []))}")

    # Test case 6: Combined (owner + stale_days)
    if first_owner:
        print(f"\n6. Combined: owner_email + stale_days=30")
        result6 = await query_stale_deals({
            "owner_email": first_owner,
            "stale_days": 30
        }, sb)
        print(f"   stale_count: {result6.get('stale_count')}")
        print(f"   deals returned: {len(result6.get('stale_deals', []))}")
    else:
        print("\n6. Combined - SKIPPED (no owner available)")
        result6 = None

    # Save all results
    fixtures = {
        "captured_at": "2026-09-17 (post-N+1-fix, post-H4b, pre-further-refactor)",
        "test_cases": [
            {
                "name": "no_filters_default_21_days",
                "params": {},
                "result": result1
            },
            {
                "name": "stale_days_30",
                "params": {"stale_days": 30},
                "result": result2
            },
            {
                "name": "owner_filter",
                "params": {"owner_email": first_owner} if first_owner else None,
                "result": result3
            },
            {
                "name": "stage_filter",
                "params": {"stage": first_stage} if first_stage else None,
                "result": result4
            },
            {
                "name": "stale_days_60",
                "params": {"stale_days": 60},
                "result": result5
            },
            {
                "name": "combined_owner_stale_days",
                "params": {
                    "owner_email": first_owner,
                    "stale_days": 30
                } if first_owner else None,
                "result": result6
            }
        ],
        "critical_fields_to_verify": [
            "stale_count",
            "past_close_date_count",
            "total_stale_pipeline",
            "stale_threshold_days",
            "stale_deals (length and sample deal_ids)"
        ]
    }

    output_path = Path(__file__).parent / "query_stale_deals_baseline.json"
    with open(output_path, "w") as f:
        json.dump(fixtures, f, indent=2, default=str)

    print("\n" + "=" * 80)
    print(f"✅ Baseline captured to: {output_path}")
    print(f"   Total test cases: {len([tc for tc in fixtures['test_cases'] if tc['result']])}")
    print("\nCritical fields for regression verification:")
    print("  - stale_count, past_close_date_count")
    print("  - total_stale_pipeline")
    print("  - stale_deals length")


if __name__ == "__main__":
    asyncio.run(capture_baseline())
