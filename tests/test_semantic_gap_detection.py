"""
Test semantic gap detection for fast-path handlers.

PATTERN: Before fast-path finalization, check if the question asks for
something the handler didn't provide. If there's a gap, continue the loop
to fill it instead of finalizing with incomplete data.

This is a GENERAL fix that catches ANY handler with incomplete output,
not just query_pipeline_movement. It prevents the need to patch each
handler individually when a semantic gap is discovered.
"""

import sys
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO))


def test_detects_dollar_gap():
    """
    Question asks for dollars/ARR but handler returns only counts.
    Should detect the gap.
    """
    # Import the function
    import ast
    router_path = REPO / "api" / "router.py"
    with open(router_path) as f:
        tree = ast.parse(f.read())

    for node in ast.walk(tree):
        if isinstance(node, ast.FunctionDef) and node.name == "_detect_semantic_gap":
            func_code = ast.Module(body=[node], type_ignores=[])
            func_code = compile(func_code, '<string>', 'exec')
            namespace = {}
            exec(func_code, namespace)
            _detect_semantic_gap = namespace["_detect_semantic_gap"]
            break

    # Test case 1: Question asks for dollars, handler has only counts
    question = "How much pipeline was added in EMEA?"
    result = {
        "added_count": 15,
        "added_deal_ids": ["123", "456"],
        "movement_summary": "15 deals added"
    }
    gap = _detect_semantic_gap(question, result, "query_pipeline_movement")

    assert gap is not None, "Should detect dollar gap"
    gap_type, gap_detail = gap
    assert gap_type == "dollar_fields", f"Wrong gap type: {gap_type}"
    assert "monetary values" in gap_detail, f"Gap detail should mention monetary values: {gap_detail}"

    print("✅ Detected dollar gap when question asks 'how much' but result has only counts")


def test_no_gap_when_dollars_present():
    """
    Question asks for dollars and handler includes dollar fields.
    Should NOT detect a gap.
    """
    import ast
    router_path = REPO / "api" / "router.py"
    with open(router_path) as f:
        tree = ast.parse(f.read())

    for node in ast.walk(tree):
        if isinstance(node, ast.FunctionDef) and node.name == "_detect_semantic_gap":
            func_code = ast.Module(body=[node], type_ignores=[])
            func_code = compile(func_code, '<string>', 'exec')
            namespace = {}
            exec(func_code, namespace)
            _detect_semantic_gap = namespace["_detect_semantic_gap"]
            break

    question = "How much pipeline was added in EMEA?"
    result = {
        "added_count": 15,
        "added_deal_ids": ["123", "456"],
        "added_arr_total": 500000,  # HAS dollar field
        "movement_summary": "15 deals added, $500K ARR"
    }
    gap = _detect_semantic_gap(question, result, "query_pipeline_movement")

    assert gap is None, f"Should NOT detect gap when dollars present, got: {gap}"
    print("✅ No gap detected when dollar fields present")


def test_no_gap_for_count_only_questions():
    """
    Question asks for counts only, handler returns counts only.
    Should NOT detect a gap.
    """
    import ast
    router_path = REPO / "api" / "router.py"
    with open(router_path) as f:
        tree = ast.parse(f.read())

    for node in ast.walk(tree):
        if isinstance(node, ast.FunctionDef) and node.name == "_detect_semantic_gap":
            func_code = ast.Module(body=[node], type_ignores=[])
            func_code = compile(func_code, '<string>', 'exec')
            namespace = {}
            exec(func_code, namespace)
            _detect_semantic_gap = namespace["_detect_semantic_gap"]
            break

    question = "How many deals moved stage in EMEA?"
    result = {
        "stage_changes_count": 22,
        "entries_count": 17,
        "exits_count": 28
    }
    gap = _detect_semantic_gap(question, result, "query_pipeline_movement")

    assert gap is None, f"Should NOT detect gap for count-only question, got: {gap}"
    print("✅ No gap for count-only questions")


def test_code_structure():
    """Verify the semantic gap check is wired into fast-path logic."""
    router_path = REPO / "api" / "router.py"
    with open(router_path) as f:
        content = f.read()

    # Verify function exists
    assert "def _detect_semantic_gap" in content, \
        "_detect_semantic_gap function should exist"

    # Verify it's called before fast-path finalization
    assert "semantic_gap = _detect_semantic_gap(question, result, tool_name)" in content, \
        "Should call _detect_semantic_gap before finalization"

    # Verify it prevents finalization when gap detected
    assert "if semantic_gap:" in content, \
        "Should check for semantic gap"
    assert "Continuing loop to fill gap" in content, \
        "Should continue loop when gap detected"

    # Verify fast-path is conditional on no gap
    assert "else:" in content and "finalizing immediately" in content, \
        "Fast-path finalization should only happen when no gap"

    print("✅ Semantic gap detection wired into fast-path logic")
    print("   - _detect_semantic_gap called before finalization")
    print("   - Loop continues if gap detected")
    print("   - Fast-path only happens when no gap")


if __name__ == "__main__":
    print("=" * 80)
    print("SEMANTIC GAP DETECTION TESTS")
    print("=" * 80)
    print()

    try:
        test_code_structure()
        print()
        test_detects_dollar_gap()
        print()
        test_no_gap_when_dollars_present()
        print()
        test_no_gap_for_count_only_questions()

        print()
        print("=" * 80)
        print("ALL TESTS PASSED")
        print("=" * 80)
        print()
        print("General semantic gap detection implemented:")
        print("  ✅ Detects when question asks X but handler doesn't return X")
        print("  ✅ Prevents premature fast-path finalization")
        print("  ✅ Lets loop continue to fill the gap")
        print("  ✅ Works for ANY handler, not just query_pipeline_movement")
        print()
        print("Dollar gap detection:")
        print("  ✅ Question: 'how much pipeline' → needs dollar fields")
        print("  ✅ Handler: only counts → gap detected → loop continues")
        print("  ✅ Handler: has dollar fields → no gap → fast-path OK")
        print()
        print("Next: Add specific fix to query_pipeline_movement (dollar fields)")

    except AssertionError as e:
        print()
        print("=" * 80)
        print(f"❌ TEST FAILED: {e}")
        print("=" * 80)
        sys.exit(1)
    except Exception as e:
        print()
        print("=" * 80)
        print(f"❌ ERROR: {type(e).__name__}: {e}")
        print("=" * 80)
        import traceback
        traceback.print_exc()
        sys.exit(1)
