"""
ADVERSARIAL VERIFICATION: Test semantic gap detector on REAL cases.

This is NOT a unit test - it's verification that the keyword-matching
detector actually works on the real question that motivated it, and
doesn't fire false positives on cases where handlers already return
the requested data.

Keyword-matching is inherently risky (same as router alias fix, false-
positive guards) - needs adversarial proof, not just passing unit tests.
"""

import sys
from pathlib import Path
import ast

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO))

# Extract _detect_semantic_gap function
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


def test_ryans_exact_question():
    """
    TEST 1: Ryan's EXACT original question that motivated this fix.

    Question: "Tell me the amount of pipeline in $ and number of deals
              we've added to the pipeline in the last two weeks"

    Expected: Should detect gap when query_pipeline_movement returns
              only counts (no dollar fields)
    """
    question = "Tell me the amount of pipeline in $ and number of deals we've added to the pipeline in the last two weeks"

    # Simulate what query_pipeline_movement CURRENTLY returns (before specific fix)
    current_result = {
        "view": "movement",
        "added_count": 15,
        "new_to_pipeline_ids": ["123", "456", "789"],
        "entered_from_other_stage_ids": ["abc", "def"],
        "movement_summary": {
            "added": 15,
            "exited": 8,
            "stage_changes": 22
        },
        "by_week": [
            {"week_label": "Aug 28", "added": 7, "exited": 3},
            {"week_label": "Sep 4", "added": 8, "exited": 5}
        ]
    }

    gap = _detect_semantic_gap(question, current_result, "query_pipeline_movement")

    print("=" * 80)
    print("TEST 1: Ryan's Exact Question")
    print("=" * 80)
    print(f"Question: {question}")
    print()
    print("Handler result keys:", list(current_result.keys()))
    print("Handler result has dollar fields:", any("arr" in str(k).lower() or "value" in str(k).lower()
                                                   for k in current_result.keys()))
    print()

    if gap:
        gap_type, gap_detail = gap
        print(f"✅ PASS: Gap detected (type={gap_type})")
        print(f"   Detail: {gap_detail}")
        print()
        print("Expected behavior:")
        print("  1. [SEMANTIC_GAP] log fires")
        print("  2. Fast-path finalization SKIPPED")
        print("  3. Loop continues")
        print("  4. Model queries for dollar data (sum incremental_arr for new_ids)")
        print("  5. Synthesis includes real $ figure")
    else:
        print(f"❌ FAIL: Gap NOT detected")
        print("   This is the REAL question that motivated the fix!")
        print("   Detector MUST catch this case.")
        return False

    return True


def test_handler_with_dollar_fields():
    """
    TEST 2: Negative case - handler ALREADY returns dollar fields.

    Question asks for $ but handler includes arr/value fields.
    Should NOT detect gap (no false positive).
    """
    question = "What's our Q3 pipeline value in ARR?"

    # Simulate query_pipeline returning dollar fields
    result_with_dollars = {
        "total_pipeline": 5500000,
        "total_deals": 120,
        "incremental_arr": 5500000,  # HAS dollar field
        "by_stage": {
            "Discovery": {"deals": 30, "arr": 800000},
            "Negotiation": {"deals": 25, "arr": 1200000}
        }
    }

    gap = _detect_semantic_gap(question, result_with_dollars, "query_pipeline")

    print("=" * 80)
    print("TEST 2: Handler Already Has Dollar Fields")
    print("=" * 80)
    print(f"Question: {question}")
    print()
    print("Handler result keys:", list(result_with_dollars.keys()))
    print("Handler result has dollar fields:", "incremental_arr" in result_with_dollars)
    print()

    if gap is None:
        print(f"✅ PASS: No gap detected (correct - handler has dollar fields)")
        print()
        print("Expected behavior:")
        print("  1. Detector sees 'ARR' in question")
        print("  2. Detector finds 'incremental_arr' in result")
        print("  3. No gap → fast-path finalization proceeds normally")
        print("  4. No unnecessary extra loop iteration")
    else:
        gap_type, gap_detail = gap
        print(f"❌ FAIL: False positive - gap detected when handler has dollars")
        print(f"   Gap type: {gap_type}")
        print(f"   Detail: {gap_detail}")
        print()
        print("This is a FALSE POSITIVE - handler already returns dollar data!")
        return False

    return True


def test_count_only_question_with_count_result():
    """
    TEST 3: Control case - question asks for counts, handler returns counts.

    Should NOT detect gap (handler output matches question intent).
    """
    question = "How many deals moved stage in the last week?"

    result = {
        "stage_changes_count": 22,
        "stage_changes": [
            {"deal_id": "123", "prior_stage": "Discovery", "current_stage": "Negotiation"},
            {"deal_id": "456", "prior_stage": "Negotiation", "current_stage": "Closed Won"}
        ]
    }

    gap = _detect_semantic_gap(question, result, "query_pipeline_movement")

    print("=" * 80)
    print("TEST 3: Count Question + Count Result")
    print("=" * 80)
    print(f"Question: {question}")
    print()
    print("Question asks for dollars:", any(term in question.lower() for term in ["$", "arr", "value"]))
    print()

    if gap is None:
        print(f"✅ PASS: No gap detected (correct - question doesn't ask for dollars)")
        print()
        print("Expected behavior:")
        print("  1. Question asks 'how many' (count, not dollars)")
        print("  2. Detector doesn't require dollar fields")
        print("  3. No gap → fast-path proceeds")
    else:
        gap_type, gap_detail = gap
        print(f"❌ FAIL: False positive on count-only question")
        print(f"   Gap type: {gap_type}")
        print(f"   Detail: {gap_detail}")
        return False

    return True


def test_nested_dollar_field():
    """
    TEST 4: Dollar field in nested structure (by_stage, by_week).

    Should detect it and NOT flag as gap.
    """
    question = "How much pipeline by stage?"

    result = {
        "by_stage": {
            "Discovery": {"deal_count": 30, "total_arr": 800000},  # Nested dollar field
            "Negotiation": {"deal_count": 25, "total_arr": 1200000}
        }
    }

    gap = _detect_semantic_gap(question, result, "query_pipeline")

    print("=" * 80)
    print("TEST 4: Nested Dollar Fields")
    print("=" * 80)
    print(f"Question: {question}")
    print()
    print("Dollar field location: nested in by_stage dict (total_arr)")
    print()

    if gap is None:
        print(f"✅ PASS: No gap detected (nested dollar fields found)")
        print()
        print("Recursive search found total_arr in nested dict")
    else:
        gap_type, gap_detail = gap
        print(f"❌ FAIL: Missed nested dollar fields")
        print(f"   Gap type: {gap_type}")
        print(f"   Detail: {gap_detail}")
        print()
        print("Detector should recursively search nested dicts!")
        return False

    return True


if __name__ == "__main__":
    print("=" * 80)
    print("ADVERSARIAL VERIFICATION: Real Cases, Not Unit Tests")
    print("=" * 80)
    print()
    print("Testing keyword-matching detector on:")
    print("  1. Ryan's EXACT original question (must catch)")
    print("  2. Handler with dollar fields (must NOT false-positive)")
    print("  3. Count-only question (must NOT false-positive)")
    print("  4. Nested dollar fields (must NOT false-positive)")
    print()

    results = []

    try:
        results.append(("Ryan's question", test_ryans_exact_question()))
        print()
        results.append(("Handler has dollars", test_handler_with_dollar_fields()))
        print()
        results.append(("Count-only question", test_count_only_question_with_count_result()))
        print()
        results.append(("Nested dollar fields", test_nested_dollar_field()))

        print()
        print("=" * 80)
        print("VERIFICATION RESULTS")
        print("=" * 80)
        print()

        all_passed = all(result[1] for result in results)

        for name, passed in results:
            status = "✅ PASS" if passed else "❌ FAIL"
            print(f"{status}: {name}")

        print()

        if all_passed:
            print("=" * 80)
            print("✅ ALL ADVERSARIAL TESTS PASSED")
            print("=" * 80)
            print()
            print("Detector proven on REAL cases:")
            print("  ✅ Catches Ryan's exact question (the motivating case)")
            print("  ✅ No false positives when handler has dollar fields")
            print("  ✅ No false positives on count-only questions")
            print("  ✅ Finds dollar fields in nested structures")
            print()
            print("VERIFIED: General detector works on real cases.")
            print()
            print("Next: Add specific fields to query_pipeline_movement")
            print("  - added_arr_total")
            print("  - exited_arr_total")
            print("  - stage_change_arr_delta")
            print()
            print("Defense in depth: general detector + specific fields")
        else:
            print("=" * 80)
            print("❌ VERIFICATION FAILED")
            print("=" * 80)
            print()
            print("Detector has issues - DO NOT trust it for production yet.")
            print("Fix the failing cases before adding specific fields.")
            sys.exit(1)

    except Exception as e:
        print()
        print("=" * 80)
        print(f"❌ ERROR: {type(e).__name__}: {e}")
        print("=" * 80)
        import traceback
        traceback.print_exc()
        sys.exit(1)
