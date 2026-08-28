#!/usr/bin/env python3
"""
Test multi-step entity extraction merges all entity-bearing rows.

Bug caught: dynamic query "Get customers due to renew in Q3 and Q4" ran two steps
(31 rows + 1 row), but only returned the last step (1 row). Silently discarded 97%.
"""

import sys
from pathlib import Path

# Add api to path
sys.path.insert(0, str(Path(__file__).parent.parent))

from api.router import _extract_rows_from_accumulated


def test_multi_step_extraction_merges_all_entity_rows():
    """Two steps returning 31 and 1 rows must yield 32, deduplicated — not 1.
    Last-step-wins silently discarded 31 of 32 deals on a real question."""

    # Simulate accumulated_data from dynamic loop with two steps
    accumulated_data = {
        "step_0": {
            "rows": [
                {"deal_id": f"deal_{i}", "company_name": f"Company {i}", "arr_usd": 10000 * i}
                for i in range(31)
            ],
            "table": "deals"
        },
        "step_1": {
            "rows": [
                {"deal_id": "deal_31", "company_name": "Discord", "arr_usd": 175000}
            ],
            "table": "deals"
        }
    }

    # Mock entity registry (in real code, loaded from Supabase)
    class MockSupabase:
        def table(self, name):
            return self

        def select(self, cols):
            return self

        def execute(self):
            class Result:
                data = [{"id_column": "deal_id"}]
            return Result()

    result = _extract_rows_from_accumulated(
        accumulated_data=accumulated_data,
        mode="entity_extraction",
        sb=MockSupabase()
    )

    rows = result.get("rows", [])

    print(f"[TEST] Multi-step extraction merge")
    print(f"  Input: step_0={len(accumulated_data['step_0']['rows'])} rows, step_1={len(accumulated_data['step_1']['rows'])} rows")
    print(f"  Output: {len(rows)} rows")

    # Should merge both steps (32 total), not return just step_1 (1 row)
    assert len(rows) == 32, f"Expected 32 rows (31 + 1), got {len(rows)}"

    # Verify deduplication works
    deal_ids = {row["deal_id"] for row in rows}
    assert len(deal_ids) == 32, f"Expected 32 unique deal_ids, got {len(deal_ids)}"

    # Check Discord is included
    assert any(row["company_name"] == "Discord" for row in rows), "Discord not found in merged rows"

    print(f"  ✓ Merged all entity-bearing rows correctly")
    print(f"  ✓ Deduplicated on deal_id")


def test_deduplication_on_overlapping_steps():
    """If two steps return the same deal_id, only include it once."""

    accumulated_data = {
        "step_0": {
            "rows": [
                {"deal_id": "deal_1", "company_name": "Acme", "arr_usd": 50000},
                {"deal_id": "deal_2", "company_name": "Beta", "arr_usd": 30000}
            ],
            "table": "deals"
        },
        "step_1": {
            "rows": [
                {"deal_id": "deal_2", "company_name": "Beta", "arr_usd": 30000},  # Duplicate
                {"deal_id": "deal_3", "company_name": "Gamma", "arr_usd": 40000}
            ],
            "table": "deals"
        }
    }

    class MockSupabase:
        def table(self, name):
            return self

        def select(self, cols):
            return self

        def execute(self):
            class Result:
                data = [{"id_column": "deal_id"}]
            return Result()

    result = _extract_rows_from_accumulated(
        accumulated_data=accumulated_data,
        mode="entity_extraction",
        sb=MockSupabase()
    )

    rows = result.get("rows", [])

    print(f"\n[TEST] Deduplication on overlapping steps")
    print(f"  Input: step_0=2 rows, step_1=2 rows (1 duplicate)")
    print(f"  Output: {len(rows)} rows")

    # Should deduplicate: deal_1, deal_2, deal_3 = 3 unique
    assert len(rows) == 3, f"Expected 3 unique rows, got {len(rows)}"

    deal_ids = {row["deal_id"] for row in rows}
    assert deal_ids == {"deal_1", "deal_2", "deal_3"}, f"Unexpected deal_ids: {deal_ids}"

    print(f"  ✓ Deduplicated overlapping rows correctly")


def test_synthesis_mode_unchanged():
    """Synthesis mode should still return last step (not merged)."""

    accumulated_data = {
        "step_0": {
            "rows": [{"total_arr": 100000, "count": 5}],
            "table": "aggregates"
        },
        "step_1": {
            "rows": [{"total_arr": 200000, "count": 10}],
            "table": "aggregates"
        }
    }

    result = _extract_rows_from_accumulated(
        accumulated_data=accumulated_data,
        mode="synthesis",
        sb=None
    )

    rows = result.get("rows", [])

    print(f"\n[TEST] Synthesis mode (unchanged)")
    print(f"  Input: step_0=1 row, step_1=1 row")
    print(f"  Output: {len(rows)} rows")

    # Synthesis mode returns last step with data (step_1)
    assert len(rows) == 1, f"Expected 1 row from synthesis mode, got {len(rows)}"
    assert rows[0]["count"] == 10, f"Expected step_1 data, got {rows[0]}"

    print(f"  ✓ Synthesis mode returns last step (not merged)")


def main():
    """Run all extraction merge tests."""
    print("=" * 70)
    print("MULTI-STEP EXTRACTION TESTS")
    print("=" * 70)

    try:
        test_multi_step_extraction_merges_all_entity_rows()
        test_deduplication_on_overlapping_steps()
        test_synthesis_mode_unchanged()

        print("\n" + "=" * 70)
        print("RESULTS: 3 passed, 0 failed")
        print("=" * 70)
        return 0
    except AssertionError as e:
        print(f"\n  ❌ {e}")
        print("\n" + "=" * 70)
        print("RESULTS: 0 passed, 1 failed")
        print("=" * 70)
        return 1


if __name__ == "__main__":
    sys.exit(main())
