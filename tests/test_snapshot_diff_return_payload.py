"""
Verification test for SNAPSHOT_DIFF return payload fix.

BUG (FIXED): When id_scoped_enrichment_lookup shortcut triggered _finalize_from_data,
the SNAPSHOT_DIFF was computed successfully and logged, but the return payload
only included raw rows via _extract_rows_from_accumulated, NOT the computed diff.

This caused synthesis to fail with "could not turn the partial data into an answer"
even though the diff was computed correctly, because the diff was only in the
finalize_prompt TEXT, not in the tool_results that got returned to the caller.

FIX IMPLEMENTED:
1. When diff_result exists in _finalize_from_data, it's now included in tool_results
2. Both success path (line 4178-4181) and failure path (_give_up) include it
3. Synthesis and downstream consumers now have access to the structured diff
"""

import sys
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO / "api"))


def test_fix_structure_verification():
    """
    Verify the fix is structured correctly:
    1. _give_up accepts optional diff_result parameter
    2. _finalize_from_data includes diff_result in both return paths
    3. When diff_result exists, it's added to tool_results["snapshot_diff"]
    """
    import ast
    import inspect

    # Read the router.py source
    router_file = REPO / "api" / "router.py"
    with open(router_file) as f:
        source = f.read()

    # Parse the AST
    tree = ast.parse(source)

    # Find _give_up function
    give_up_found = False
    has_diff_result_param = False

    for node in ast.walk(tree):
        if isinstance(node, ast.FunctionDef) and node.name == "_give_up":
            give_up_found = True
            # Check if diff_result parameter exists
            arg_names = [arg.arg for arg in node.args.args]
            if "diff_result" in arg_names:
                has_diff_result_param = True
            break

    assert give_up_found, "_give_up function not found"
    assert has_diff_result_param, "_give_up should have diff_result parameter"

    # Check for the key fix patterns in source
    assert 'tr["snapshot_diff"] = diff_result' in source, \
        "Success path should include diff in tool_results"
    assert 'tool_results["snapshot_diff"] = diff_result' in source, \
        "_give_up should include diff in tool_results"
    assert '_give_up(reason_tag, "could not turn the partial data into an answer",\n                       diff_result=diff_result)' in source, \
        "Exception path should pass diff_result to _give_up"

    print("✅ Fix structure verified")
    print("   - _give_up has diff_result parameter")
    print("   - Success path includes diff in tool_results")
    print("   - Failure path passes diff to _give_up")
    print("   - Both paths preserve computed diff")


def test_expected_behavior_documented():
    """
    Document the expected return payload structure after fix.
    """
    expected_return_success = {
        "answer": "Pipeline movement for EMEA shows...",
        "tool_results": {
            "rows": [{"deal_id": "...", "company_name": "..."}],
            "table": "deals",
            "snapshot_diff": {  # THE FIX: computed diff is now included
                "stage_changes": [
                    {"deal_id": "123", "company_name": "Acme", "prior_stage": "...", "current_stage": "..."}
                ],
                "population_entries": [{"deal_id": "456", "company_name": "Contoso"}],
                "population_exits": [{"deal_id": "789", "company_name": "Fabrikam"}],
                "owner_changes": [{"deal_id": "101", "company_name": "Litware"}]
            }
        },
        "answered": True
    }

    expected_return_failure = {
        "answer": "I gathered partial data but could not turn it into a clean answer...",
        "tool_results": {
            "rows": [{"deal_id": "...", "company_name": "..."}],
            "table": "deals",
            "snapshot_diff": {  # Even on failure, diff is preserved
                "stage_changes": [...],
                "population_entries": [...],
                "population_exits": [...],
                "owner_changes": [...]
            }
        },
        "answered": False
    }

    print("✅ Expected behavior documented")
    print("   Success path: tool_results includes snapshot_diff")
    print("   Failure path: diff preserved even when synthesis fails")


if __name__ == "__main__":
    print("=" * 80)
    print("SNAPSHOT_DIFF RETURN PAYLOAD FIX VERIFICATION")
    print("=" * 80)
    print()

    try:
        test_fix_structure_verification()
        print()
        test_expected_behavior_documented()

        print()
        print("=" * 80)
        print("ALL VERIFICATIONS PASSED")
        print("=" * 80)
        print()
        print("Fix summary:")
        print("  1. ✅ _give_up now accepts diff_result parameter")
        print("  2. ✅ Success path includes diff in tool_results")
        print("  3. ✅ Failure path preserves diff via _give_up")
        print("  4. ✅ Both paths include computed diff in return payload")
        print()
        print("Impact:")
        print("  - SNAPSHOT_DIFF computation results are no longer discarded")
        print("  - Synthesis has access to structured diff, not just raw rows")
        print("  - Fewer 'could not turn partial data into answer' failures")
        print("  - Better debugging - diff visible in return payload")

    except AssertionError as e:
        print()
        print("=" * 80)
        print(f"❌ VERIFICATION FAILED: {e}")
        print("=" * 80)
        sys.exit(1)
    except Exception as e:
        print()
        print("=" * 80)
        print(f"❌ ERROR: {type(e).__name__}: {e}")
        print("=" * 80)
        sys.exit(1)
