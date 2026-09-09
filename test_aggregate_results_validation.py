#!/usr/bin/env python3
"""
Test all failure modes for aggregate_results validation.
Confirm each fails loudly with clear error, not silently.
"""
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).parent
sys.path.insert(0, str(REPO_ROOT / 'api'))
sys.path.insert(0, str(REPO_ROOT / 'scripts'))

# Mock the tools module's aggregate_results with PROPOSED validation
async def aggregate_results_with_validation(data, group_by, aggregations, accumulated_data=None):
    """Proposed validation logic - catches all failure modes."""
    from collections import defaultdict

    # VALIDATION 1: Empty array
    if isinstance(data, list) and len(data) == 0:
        return {
            "error": "Empty data array. Use data='step_N' to reference a previous result.",
            "rows": [],
            "validation_failed": "empty_array"
        }

    # VALIDATION 2: Invalid step reference (when we have accumulated_data context)
    if isinstance(data, str) and accumulated_data is not None:
        if data not in accumulated_data:
            available = list(accumulated_data.keys())
            return {
                "error": f"'{data}' is not a valid step reference. Available steps: {available}",
                "rows": [],
                "validation_failed": "invalid_step_reference"
            }

    # VALIDATION 3: Direct data arrays (discourage even when non-empty)
    # NOTE: This is optional - could allow non-empty arrays for backwards compat
    # For now, let's just warn but allow it
    if isinstance(data, list) and len(data) > 0:
        # Could return error here to force step references
        # For now, just log warning and continue (backwards compatible)
        pass

    # VALIDATION 4: Check group_by column exists
    if isinstance(data, list) and data and group_by not in data[0]:
        available_cols = list(data[0].keys())[:10]
        return {
            "error": f"Column '{group_by}' not found in data. Available: {available_cols}",
            "rows": [],
            "validation_failed": "invalid_group_by"
        }

    # Existing aggregation logic (simplified for test)
    groups = defaultdict(list)
    for row in data:
        groups[row.get(group_by, "unknown")].append(row)

    result = []
    for key, rows in groups.items():
        entry = {group_by: key}
        for col, agg in aggregations.items():
            vals = [r.get(col) for r in rows if r.get(col) is not None]
            if agg == "sum":
                entry[f"{col}_sum"] = sum(vals)
            elif agg == "count":
                entry[f"{col}_count"] = len(rows)
        result.append(entry)

    return {"rows": result, "group_count": len(result)}


async def run_tests():
    print("=" * 70)
    print("AGGREGATE_RESULTS VALIDATION TESTS")
    print("=" * 70)
    print()

    passed = failed = 0

    def check(name, condition, details=""):
        nonlocal passed, failed
        if condition:
            passed += 1
            print(f"  ✅ {name}")
        else:
            failed += 1
            print(f"  ❌ {name}")
            if details:
                print(f"     {details}")

    # Set up accumulated_data for step reference tests
    accumulated_data = {
        "step_0": {"rows": [{"week": "2026-09-01", "value": 100}]},
        "step_1": {"rows": [{"week": "2026-09-02", "value": 200}]},
    }

    print("Test 1: Empty array (current bug)")
    print("-" * 70)
    result = await aggregate_results_with_validation(
        data=[],
        group_by="week",
        aggregations={"value": "sum"}
    )
    check("Returns error for empty array", "error" in result)
    check("Error mentions 'empty data'", "error" in result and "empty" in result["error"].lower())
    check("Returns validation_failed flag", result.get("validation_failed") == "empty_array")
    print()

    print("Test 2: Invalid step reference")
    print("-" * 70)
    result = await aggregate_results_with_validation(
        data="step_99",  # Doesn't exist
        group_by="week",
        aggregations={"value": "sum"},
        accumulated_data=accumulated_data
    )
    check("Returns error for invalid step", "error" in result)
    check("Error mentions available steps", "error" in result and "step_0" in result["error"])
    check("Returns validation_failed flag", result.get("validation_failed") == "invalid_step_reference")
    print()

    print("Test 3: Missing group_by column")
    print("-" * 70)
    result = await aggregate_results_with_validation(
        data=[{"week": "2026-09-01", "value": 100}],
        group_by="nonexistent",  # Column doesn't exist
        aggregations={"value": "sum"}
    )
    check("Returns error for missing column", "error" in result)
    check("Error mentions 'not found'", "error" in result and "not found" in result["error"].lower())
    check("Error lists available columns", "error" in result and "week" in result["error"])
    print()

    print("Test 4: Valid data (should succeed)")
    print("-" * 70)
    result = await aggregate_results_with_validation(
        data=[
            {"week": "2026-09-01", "value": 100},
            {"week": "2026-09-01", "value": 50},
            {"week": "2026-09-02", "value": 200}
        ],
        group_by="week",
        aggregations={"value": "sum"}
    )
    check("Returns rows for valid input", "rows" in result and len(result["rows"]) > 0)
    check("No error for valid input", "error" not in result)
    check("Correct aggregation (week 1: 150)",
          any(r.get("week") == "2026-09-01" and r.get("value_sum") == 150 for r in result["rows"]))
    check("Correct aggregation (week 2: 200)",
          any(r.get("week") == "2026-09-02" and r.get("value_sum") == 200 for r in result["rows"]))
    print()

    print("=" * 70)
    print(f"RESULTS: {passed} passed, {failed} failed")
    print("=" * 70)

    return 0 if failed == 0 else 1


if __name__ == "__main__":
    import asyncio
    sys.exit(asyncio.run(run_tests()))
