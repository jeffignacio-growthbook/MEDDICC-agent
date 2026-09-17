#!/usr/bin/env python3
"""
Capture query_pipeline_movement regression baseline BEFORE convergence refactor.

Runs query_pipeline_movement against REAL current database state for 6 test cases:
1. No filters (baseline movement view)
2. Pipeline-scoped (pipeline_filter="new_business" - H4 makes this real)
3. Owner-scoped (owner_email set)
4. Time-window variant (movement with explicit time_window)
5. View variant (composition view with weeks)
6. Combined: pipeline_filter + owner_email

Saves output as JSON fixtures for byte-for-byte comparison after refactor.
"""
import asyncio
import json
import sys
from pathlib import Path
from datetime import date, timedelta
from dotenv import load_dotenv

# Load environment variables
repo_root = Path(__file__).parent.parent.parent
load_dotenv(repo_root / ".env")

# Add api/ and scripts/ to path
sys.path.insert(0, str(repo_root / "api"))
sys.path.insert(0, str(repo_root / "scripts"))

from handlers import query_pipeline_movement
from db import get_supabase
from time_resolver import resolve_time_window


async def capture_baseline():
    """Capture query_pipeline_movement output for 6 test cases."""
    sb = get_supabase()

    print("Capturing query_pipeline_movement baseline against live database...")
    print("=" * 80)

    # Test case 1: No filters (baseline movement view)
    print("\n1. No filters (baseline movement view)")
    result1 = await query_pipeline_movement({}, sb)
    print(f"   view: {result1.get('view')}")
    print(f"   fiscal_quarter: {result1.get('fiscal_quarter')}")
    if result1.get('error'):
        print(f"   ERROR: {result1['error']}")
    else:
        print(f"   totals: {result1.get('totals', {})}")
        print(f"   by_stage entries: {len(result1.get('by_stage', []))}")
        print(f"   rows: {len(result1.get('rows', []))}")

    # Test case 2: Pipeline-scoped (pipeline_filter="new_business")
    print("\n2. pipeline_filter='new_business' (H4 fix verification)")
    result2 = await query_pipeline_movement({"pipeline_filter": "new_business"}, sb)
    print(f"   view: {result2.get('view')}")
    if result2.get('error'):
        print(f"   ERROR: {result2['error']}")
    else:
        print(f"   totals: {result2.get('totals', {})}")
        print(f"   by_stage entries: {len(result2.get('by_stage', []))}")

    # Test case 3: Owner-scoped (pick first owner with data from baseline)
    # Need to get an owner from the rows
    first_owner = None
    if result1.get('rows'):
        for row in result1['rows']:
            if row.get('owner_email'):
                first_owner = row['owner_email']
                break

    if first_owner:
        print(f"\n3. owner_email='{first_owner}' (H4 fix verification)")
        result3 = await query_pipeline_movement({"owner_email": first_owner}, sb)
        print(f"   view: {result3.get('view')}")
        if result3.get('error'):
            print(f"   ERROR: {result3['error']}")
        else:
            print(f"   totals: {result3.get('totals', {})}")
            print(f"   data_gaps: {result3.get('data_gaps', [])}")
    else:
        print("\n3. owner_email - SKIPPED (no owners in baseline)")
        result3 = None

    # Test case 4: Time-window variant (last 2 weeks)
    print("\n4. Time-window variant (last 2 weeks movement)")
    time_window = resolve_time_window({"period": "last_2_weeks"})
    result4 = await query_pipeline_movement({"time_window": time_window}, sb)
    print(f"   view: {result4.get('view')}")
    print(f"   time_window: {time_window.get('label')}")
    if result4.get('error'):
        print(f"   ERROR: {result4['error']}")
    else:
        print(f"   totals: {result4.get('totals', {})}")
        print(f"   data_gaps: {result4.get('data_gaps', [])}")

    # Test case 5: View variant (composition with 4 weeks)
    print("\n5. View variant (composition, 4 weeks)")
    result5 = await query_pipeline_movement({"view": "composition", "weeks": 4}, sb)
    print(f"   view: {result5.get('view')}")
    if result5.get('error'):
        print(f"   ERROR: {result5['error']}")
    else:
        # Composition view has different structure
        print(f"   snapshots: {len(result5.get('snapshots', []))}")
        print(f"   rows: {len(result5.get('rows', []))}")

    # Test case 6: Combined filters (pipeline + owner)
    if first_owner:
        print("\n6. Combined: pipeline_filter='new_business' + owner_email")
        result6 = await query_pipeline_movement({
            "pipeline_filter": "new_business",
            "owner_email": first_owner
        }, sb)
        print(f"   view: {result6.get('view')}")
        if result6.get('error'):
            print(f"   ERROR: {result6['error']}")
        else:
            print(f"   totals: {result6.get('totals', {})}")
            print(f"   rows: {len(result6.get('rows', []))}")
    else:
        print("\n6. Combined filters - SKIPPED (no owner available)")
        result6 = None

    # Test case 7: Renewal filter (H1 fix verification - should return actual renewal deals)
    print("\n7. pipeline_filter='renewal' (H1 fix - returns real renewal deals)")
    result7 = await query_pipeline_movement({"pipeline_filter": "renewal"}, sb)
    print(f"   view: {result7.get('view')}")
    if result7.get('error'):
        print(f"   ERROR: {result7['error']}")
    else:
        print(f"   totals: {result7.get('totals', {})}")
        print(f"   by_stage entries: {len(result7.get('by_stage', []))}")
        print(f"   rows: {len(result7.get('rows', []))}")
        if result7.get('rows'):
            print(f"   ✅ SUCCESS: Renewal deals loaded (not empty!)")
        else:
            print(f"   ❌ FAILED: Empty result (H1 fix may not be working)")

    # Save all results as JSON fixtures
    fixtures = {
        "captured_at": "2026-09-17 (pre-convergence-refactor, post-H1-H4-fixes)",
        "test_cases": [
            {
                "name": "no_filters",
                "params": {},
                "result": result1
            },
            {
                "name": "pipeline_filter_new_business",
                "params": {"pipeline_filter": "new_business"},
                "result": result2
            },
            {
                "name": "owner_filter",
                "params": {"owner_email": first_owner} if first_owner else None,
                "result": result3
            },
            {
                "name": "time_window_last_2_weeks",
                "params": {"time_window": time_window},
                "result": result4
            },
            {
                "name": "composition_view_4_weeks",
                "params": {"view": "composition", "weeks": 4},
                "result": result5
            },
            {
                "name": "combined_pipeline_owner",
                "params": {
                    "pipeline_filter": "new_business",
                    "owner_email": first_owner
                } if first_owner else None,
                "result": result6
            },
            {
                "name": "pipeline_filter_renewal",
                "params": {"pipeline_filter": "renewal"},
                "result": result7,
                "note": "H1 fix verification: should return actual renewal deals, not empty"
            }
        ],
        "critical_fields_to_verify": [
            "view",
            "fiscal_quarter",
            "totals (prior, current, net for movement view)",
            "by_stage (all entries with counts)",
            "rows (length and sample deal_ids)",
            "data_gaps (warnings/notes)",
            "snapshots (for composition view)"
        ]
    }

    output_path = Path(__file__).parent / "query_pipeline_movement_baseline.json"
    with open(output_path, "w") as f:
        json.dump(fixtures, f, indent=2, default=str)

    print("\n" + "=" * 80)
    print(f"✅ Baseline captured to: {output_path}")
    print(f"   Total test cases: {len([tc for tc in fixtures['test_cases'] if tc['result']])}")
    print("\nCritical assertion points for post-refactor comparison:")
    print("  - totals: prior, current, net counts")
    print("  - by_stage: all entries with entered/exited/net counts")
    print("  - rows: length and deal_id values")
    print("  - data_gaps: warning messages")
    print("  - view-specific fields (snapshots for composition)")
    print("\nH1 Fix Verification:")
    if result7 and result7.get('rows'):
        print(f"  ✅ Renewal filter working: {len(result7['rows'])} renewal deals captured")
    else:
        print(f"  ❌ WARNING: Renewal filter returned empty/None")


if __name__ == "__main__":
    asyncio.run(capture_baseline())
