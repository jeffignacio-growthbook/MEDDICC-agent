#!/usr/bin/env python3
"""
Regression test: query_pipeline_movement refactor must match frozen baseline.

Compares current handler output against tests/fixtures/query_pipeline_movement_baseline.json
for all 7 test cases. Uses 0.01 float tolerance (same as query_pipeline precedent).
"""
import asyncio
import json
import sys
from pathlib import Path
from dotenv import load_dotenv

# Load environment
repo_root = Path(__file__).parent.parent
load_dotenv(repo_root / ".env")

sys.path.insert(0, str(repo_root / "api"))

from handlers import query_pipeline_movement
from db import get_supabase


def compare_values(baseline_val, current_val, path="", float_tolerance=0.01):
    """Compare two values with float tolerance. Returns (matches, differences)."""
    differences = []

    if type(baseline_val) != type(current_val):
        differences.append(f"{path}: type mismatch (baseline={type(baseline_val).__name__}, current={type(current_val).__name__})")
        return False, differences

    if isinstance(baseline_val, dict):
        all_keys = set(baseline_val.keys()) | set(current_val.keys())
        for key in all_keys:
            if key not in baseline_val:
                differences.append(f"{path}.{key}: missing in baseline")
            elif key not in current_val:
                differences.append(f"{path}.{key}: missing in current")
            else:
                matches, subdiffs = compare_values(
                    baseline_val[key], current_val[key], f"{path}.{key}", float_tolerance
                )
                if not matches:
                    differences.extend(subdiffs)

    elif isinstance(baseline_val, list):
        if len(baseline_val) != len(current_val):
            differences.append(
                f"{path}: list length mismatch (baseline={len(baseline_val)}, current={len(current_val)})"
            )
            return False, differences
        for i, (b_item, c_item) in enumerate(zip(baseline_val, current_val)):
            matches, subdiffs = compare_values(b_item, c_item, f"{path}[{i}]", float_tolerance)
            if not matches:
                differences.extend(subdiffs)

    elif isinstance(baseline_val, (int, float)) and isinstance(current_val, (int, float)):
        if abs(float(baseline_val) - float(current_val)) > float_tolerance:
            differences.append(
                f"{path}: numeric mismatch (baseline={baseline_val}, current={current_val}, diff={abs(float(baseline_val) - float(current_val))})"
            )

    elif baseline_val != current_val:
        differences.append(f"{path}: value mismatch (baseline={baseline_val!r}, current={current_val!r})")

    return len(differences) == 0, differences


async def test_regression():
    """Run all 7 test cases and compare against frozen baseline."""
    # Load frozen baseline
    baseline_path = repo_root / "tests/fixtures/query_pipeline_movement_baseline.json"
    with open(baseline_path, 'r') as f:
        baseline = json.load(f)

    print(f"Loaded baseline: {baseline['captured_at']}")
    print(f"Testing {len(baseline['test_cases'])} cases...\n")

    sb = get_supabase()
    all_passed = True

    for i, tc in enumerate(baseline['test_cases'], 1):
        name = tc['name']
        params = tc['params']
        baseline_result = tc['result']

        # Skip if params is None (test was skipped during capture)
        if params is None:
            print(f"{i}. {name}: SKIPPED (no params in baseline)")
            continue

        print(f"{i}. {name}")
        print(f"   Params: {params}")

        # Run current handler
        try:
            current_result = await query_pipeline_movement(params, sb)
        except Exception as e:
            print(f"   ❌ FAILED: Exception during query: {e}")
            all_passed = False
            continue

        # Compare critical fields
        critical_fields = ['view', 'fiscal_quarter', 'totals', 'by_stage', 'rows', 'data_gaps']

        matches = True
        for field in critical_fields:
            baseline_val = baseline_result.get(field)
            current_val = current_result.get(field)

            field_matches, diffs = compare_values(baseline_val, current_val, field)

            if not field_matches:
                matches = False
                print(f"   ❌ MISMATCH in {field}:")
                for diff in diffs[:5]:  # Show first 5 differences
                    print(f"      {diff}")
                if len(diffs) > 5:
                    print(f"      ... and {len(diffs) - 5} more differences")

        if matches:
            row_count = len(current_result.get('rows', []))
            totals = current_result.get('totals', {})
            print(f"   ✅ MATCH ({row_count} rows, totals={totals})")
        else:
            all_passed = False

        print()

    if all_passed:
        print("=" * 80)
        print("✅ ALL REGRESSION TESTS PASSED")
        print("   Current behavior matches frozen baseline exactly")
        return 0
    else:
        print("=" * 80)
        print("❌ REGRESSION TEST FAILURES DETECTED")
        print("   Current behavior differs from frozen baseline")
        print("   Review differences above - may indicate new findings or bugs")
        return 1


if __name__ == "__main__":
    exit_code = asyncio.run(test_regression())
    sys.exit(exit_code)
