#!/usr/bin/env python3
"""
Regression test for aggregate_results() array-column group-by crash (2026-09-22).

Root cause: aggregate_results tried to use list values as dict keys, which
fails with "TypeError: unhashable type: 'list'" because lists aren't hashable.

This bug is deterministic (crashes 100% when triggered) but was gated behind
inconsistent routing - questions could route to either:
- Structured handler (query_sdr_leaderboard) → works
- dynamic_query → aggregate_results with array column → crash

Any question that could route to dynamic_query and call aggregate_results
with an array-type column (participant_emails, participant_domains, or any
future text[] columns) would crash.

Example trigger: "Show me call activity by rep"
→ dynamic_query
→ filter_table(calls) returns rows with participant_emails: ["a@x.com", "b@y.com"]
→ aggregate_results(data, group_by="participant_emails", ...)
→ tries groups[["a@x.com", "b@y.com"]].append(row)
→ TypeError: unhashable type: 'list'

Fix: Convert list values to sorted tuples before using as dict keys.

This is the same category of bug as the ilike-on-text[] crash fixed earlier
in filter_table (lines 127-137), and reuses the same detection pattern:
check isinstance(value, list) and handle it specially.
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

import asyncio
from api.tools import aggregate_results


async def test_array_column_groupby():
    """Test that aggregate_results handles array columns as group_by keys."""

    # Simulate data from calls table with participant_emails as text[]
    data = [
        {"call_id": "1", "participant_emails": ["alice@example.com", "bob@example.com"], "duration": 30},
        {"call_id": "2", "participant_emails": ["alice@example.com", "charlie@example.com"], "duration": 45},
        {"call_id": "3", "participant_emails": ["alice@example.com", "bob@example.com"], "duration": 60},  # Same participants as call 1
        {"call_id": "4", "participant_emails": ["bob@example.com"], "duration": 15},
    ]

    # Without the fix, this crashes with: TypeError: unhashable type: 'list'
    try:
        result = await aggregate_results(
            data=data,
            group_by="participant_emails",
            aggregations={"duration": "sum"}
        )

        rows = result.get("rows", [])

        # Should successfully group by array values (converted to tuples)
        # Call 1 and 3 should be grouped together (same participants)
        print(f"✅ PASS: Grouped {len(rows)} unique participant combinations")
        print(f"   Group count: {result.get('group_count')}")

        # Verify the grouping worked correctly
        # Calls 1 and 3 have the same participants, so should be grouped
        duration_sums = [r.get("duration_sum") for r in rows]
        assert 90 in duration_sums, "Calls 1 and 3 (30+60=90) should be grouped together"

        print("✅ PASS: Correctly grouped calls with identical participant lists")
        return True

    except TypeError as e:
        if "unhashable type: 'list'" in str(e):
            print(f"❌ FAIL: Array column group-by still crashes: {e}")
            return False
        raise


async def test_array_column_different_order():
    """Test that arrays with same elements but different order are grouped together."""

    data = [
        {"id": "1", "emails": ["a@x.com", "b@y.com"], "value": 10},
        {"id": "2", "emails": ["b@y.com", "a@x.com"], "value": 20},  # Same emails, different order
    ]

    result = await aggregate_results(
        data=data,
        group_by="emails",
        aggregations={"value": "sum"}
    )

    rows = result.get("rows", [])

    # Should group together because we sort the list before converting to tuple
    assert len(rows) == 1, f"Expected 1 group, got {len(rows)} (arrays should be sorted before grouping)"
    assert rows[0].get("value_sum") == 30, "Should sum both values (10+20=30)"

    print("✅ PASS: Arrays with same elements but different order are grouped together")
    return True


async def test_mixed_array_and_scalar_columns():
    """Test that aggregate_results handles mix of array and scalar columns."""

    data = [
        {"region": "US", "tags": ["enterprise", "tech"], "revenue": 1000},
        {"region": "US", "tags": ["enterprise", "tech"], "revenue": 2000},  # Same tags
        {"region": "EU", "tags": ["smb"], "revenue": 500},
    ]

    # Group by scalar column (region) - should work as before
    result1 = await aggregate_results(
        data=data,
        group_by="region",
        aggregations={"revenue": "sum"}
    )
    assert len(result1["rows"]) == 2, "Should group by 2 regions"
    print("✅ PASS: Scalar column grouping still works")

    # Group by array column (tags)
    result2 = await aggregate_results(
        data=data,
        group_by="tags",
        aggregations={"revenue": "sum"}
    )
    assert len(result2["rows"]) == 2, "Should group by 2 tag combinations"
    print("✅ PASS: Array column grouping works")

    return True


async def main():
    print("=" * 80)
    print("REGRESSION TEST: aggregate_results array-column group-by (2026-09-22)")
    print("=" * 80)
    print()

    test1 = await test_array_column_groupby()
    test2 = await test_array_column_different_order()
    test3 = await test_mixed_array_and_scalar_columns()

    print()
    if test1 and test2 and test3:
        print("✅ ALL TESTS PASSED")
        sys.exit(0)
    else:
        print("❌ SOME TESTS FAILED")
        sys.exit(1)


if __name__ == "__main__":
    asyncio.run(main())
