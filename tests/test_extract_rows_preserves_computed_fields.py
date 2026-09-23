"""
REGRESSION TEST: _extract_rows_from_accumulated must preserve ALL computed fields.

BUG (FIXED 2026-09-23): This function returned only {"rows": ..., "table": ...},
stripping out computed fields (summary, totals, snapshot_dates, ARR, etc.). This
caused FOUR separate incidents tonight where handlers computed values correctly
but they were discarded before reaching tool_results/synthesis.

FIX: Default to preserve EVERYTHING from step_data, only explicitly handle rows.
This ensures ANY future computed field (not just known ones) survives extraction.

This test uses a CANARY field (test_canary_field) that the code doesn't know about,
proving the fix is general rather than just covering specific field names.
"""

import sys
from pathlib import Path
import ast

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO))


def test_synthesis_mode_preserves_all_fields():
    """Synthesis mode: preserve ALL fields from step_data, not just rows/table."""
    # Extract _extract_rows_from_accumulated function
    router_path = REPO / "api" / "router.py"
    with open(router_path) as f:
        tree = ast.parse(f.read())

    for node in ast.walk(tree):
        if isinstance(node, ast.FunctionDef) and node.name == "_extract_rows_from_accumulated":
            func_code = ast.Module(body=[node], type_ignores=[])
            func_code = compile(func_code, '<string>', 'exec')

            # Mock logger
            class MockLogger:
                def info(self, *args, **kwargs): pass
                def warning(self, *args, **kwargs): pass

            namespace = {"logger": MockLogger()}
            exec(func_code, namespace)
            _extract_rows_from_accumulated = namespace["_extract_rows_from_accumulated"]
            break

    # Create step_data with rows, table, AND arbitrary computed fields
    step_data = {
        "rows": [{"deal_id": "123", "company": "Acme"}, {"deal_id": "456", "company": "Widgets"}],
        "table": "deals",
        # Known computed fields
        "summary": {"new_to_pipeline": 24, "added_arr_total": 2776296, "net_arr_change": 1798796},
        "totals": {"prior": 162, "current": 176, "net": 14},
        "snapshot_dates": ["2026-09-07", "2026-09-21"],
        # CANARY: arbitrary field the code doesn't know about
        "test_canary_field": {"canary_value": 42, "canary_label": "test"},
        # Another canary
        "arbitrary_computed_result": "this should survive extraction",
    }

    accumulated_data = {"step_0": step_data}

    result = _extract_rows_from_accumulated(accumulated_data, mode="synthesis")

    # Verify rows and table are present
    assert "rows" in result, "rows should be present"
    assert "table" in result, "table should be present"
    assert len(result["rows"]) == 2, "rows should have correct count"
    assert result["table"] == "deals", "table should match"

    # Verify ALL computed fields are preserved
    assert "summary" in result, "summary should be preserved"
    assert result["summary"]["added_arr_total"] == 2776296, "ARR data should survive"

    assert "totals" in result, "totals should be preserved"
    assert result["totals"]["net"] == 14, "totals data should survive"

    assert "snapshot_dates" in result, "snapshot_dates should be preserved"
    assert result["snapshot_dates"] == ["2026-09-07", "2026-09-21"], "dates should survive"

    # CRITICAL: Verify canary fields survived
    assert "test_canary_field" in result, "Canary field should be preserved"
    assert result["test_canary_field"]["canary_value"] == 42, "Canary data should survive"

    assert "arbitrary_computed_result" in result, "Arbitrary field should be preserved"
    assert result["arbitrary_computed_result"] == "this should survive extraction"

    print("✅ Synthesis mode preserves ALL fields (including canary)")


def test_entity_extraction_mode_preserves_fields():
    """Entity extraction mode: preserve ALL fields from step_data."""
    router_path = REPO / "api" / "router.py"
    with open(router_path) as f:
        tree = ast.parse(f.read())

    for node in ast.walk(tree):
        if isinstance(node, ast.FunctionDef) and node.name == "_extract_rows_from_accumulated":
            func_code = ast.Module(body=[node], type_ignores=[])
            func_code = compile(func_code, '<string>', 'exec')

            # Mock logger
            class MockLogger:
                def info(self, *args, **kwargs): pass
                def warning(self, *args, **kwargs): pass

            namespace = {"logger": MockLogger()}
            exec(func_code, namespace)
            _extract_rows_from_accumulated = namespace["_extract_rows_from_accumulated"]
            break

    # Create step_data with entity ID column + computed fields
    step_data = {
        "rows": [
            {"deal_id": "123", "company": "Acme"},
            {"deal_id": "456", "company": "Widgets"}
        ],
        "table": "deals",
        "summary": {"count": 2, "arr_total": 500000},
        "test_canary_field": "canary value should survive",
    }

    accumulated_data = {"step_0_raw": step_data}

    # Mock sb with entity_registry data
    class MockResult:
        def __init__(self, data):
            self.data = data

    class MockTable:
        def select(self, *args):
            return self
        def execute(self):
            return MockResult([{"id_column": "deal_id"}])

    class MockSB:
        def table(self, name):
            return MockTable()

    sb = MockSB()

    result = _extract_rows_from_accumulated(accumulated_data, mode="entity_extraction", sb=sb)

    # Verify rows and table
    assert "rows" in result
    assert "table" in result
    assert len(result["rows"]) == 2

    # Verify computed fields survived
    assert "summary" in result, "summary should be preserved in entity mode"
    assert result["summary"]["arr_total"] == 500000

    # CRITICAL: Canary field
    assert "test_canary_field" in result, "Canary should survive entity extraction"
    assert result["test_canary_field"] == "canary value should survive"

    print("✅ Entity extraction mode preserves ALL fields (including canary)")


def test_fallback_mode_preserves_fields():
    """Fallback (no entities): preserve ALL fields from step_data."""
    router_path = REPO / "api" / "router.py"
    with open(router_path) as f:
        tree = ast.parse(f.read())

    for node in ast.walk(tree):
        if isinstance(node, ast.FunctionDef) and node.name == "_extract_rows_from_accumulated":
            func_code = ast.Module(body=[node], type_ignores=[])
            func_code = compile(func_code, '<string>', 'exec')

            # Mock logger
            class MockLogger:
                def info(self, *args, **kwargs): pass
                def warning(self, *args, **kwargs): pass

            namespace = {"logger": MockLogger()}
            exec(func_code, namespace)
            _extract_rows_from_accumulated = namespace["_extract_rows_from_accumulated"]
            break

    # Step with no entity ID columns - triggers fallback
    step_data = {
        "rows": [{"metric": "pipeline", "value": 5000000}],
        "table": "analytics",
        "summary": {"total_value": 5000000},
        "test_canary_field": {"nested": {"canary": "deep value"}},
    }

    accumulated_data = {"step_0_raw": step_data}

    # Mock sb with empty entity registry
    class MockResult:
        def __init__(self, data):
            self.data = data

    class MockTable:
        def select(self, *args):
            return self
        def execute(self):
            return MockResult([])  # No entity columns

    class MockSB:
        def table(self, name):
            return MockTable()

    sb = MockSB()

    result = _extract_rows_from_accumulated(accumulated_data, mode="entity_extraction", sb=sb)

    # Verify rows and table
    assert "rows" in result
    assert len(result["rows"]) == 1

    # Verify computed fields survived fallback path
    assert "summary" in result, "summary should be preserved in fallback"
    assert result["summary"]["total_value"] == 5000000

    # CRITICAL: Canary field on fallback path
    assert "test_canary_field" in result, "Canary should survive fallback path"
    assert result["test_canary_field"]["nested"]["canary"] == "deep value"

    print("✅ Fallback mode preserves ALL fields (including canary)")


if __name__ == "__main__":
    print("=" * 80)
    print("REGRESSION TEST: _extract_rows_from_accumulated field preservation")
    print("=" * 80)
    print()
    print("Testing that ALL fields survive extraction, not just rows/table.")
    print("Uses CANARY fields (test_canary_field) to prove generality.")
    print()

    try:
        test_synthesis_mode_preserves_all_fields()
        print()
        test_entity_extraction_mode_preserves_fields()
        print()
        test_fallback_mode_preserves_fields()

        print()
        print("=" * 80)
        print("✅ ALL TESTS PASSED")
        print("=" * 80)
        print()
        print("Verified: _extract_rows_from_accumulated preserves ALL fields")
        print("  ✅ Synthesis mode: all fields preserved")
        print("  ✅ Entity extraction mode: all fields preserved")
        print("  ✅ Fallback mode: all fields preserved")
        print("  ✅ Canary fields (arbitrary names) survive all paths")
        print()
        print("This proves the fix is GENERAL - any future computed field")
        print("will survive extraction without needing code changes here.")

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
