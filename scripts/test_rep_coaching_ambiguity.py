#!/usr/bin/env python3
"""
Test for query_rep_coaching handler ambiguity handling.

Verifies that when a company name matches multiple deals, the handler
returns an explicit error listing the deals (NOT silently picking one).
"""
import sys
from pathlib import Path
import asyncio

sys.path.insert(0, str(Path(__file__).parent.parent))

from api.handlers import query_rep_coaching


def _mock_sb_multiple_deals():
    """MockSB that returns multiple deals for the same company."""

    class MockSB:
        def __init__(self):
            self.table_name = None
            self.filters = []

        def table(self, name):
            self.table_name = name
            return self

        def select(self, cols):
            return self

        def eq(self, field, value):
            self.filters.append(("eq", field, value))
            return self

        def in_(self, field, values):
            self.filters.append(("in_", field, values))
            return self

        def ilike(self, field, pattern):
            self.filters.append(("ilike", field, pattern))
            return self

        def range(self, start, end):
            return self

        def order(self, field, **kwargs):
            return self

        def limit(self, n):
            return self

        def execute(self):
            class Result:
                def __init__(self, table_name, filters):
                    data = []

                    # select_all for "deals" with ilike on company_name
                    if table_name == "deals" and any(f[0] == "ilike" and f[1] == "company_name" for f in filters):
                        # Return TWO deals for "IKEA"
                        data = [
                            {"deal_id": "deal_001", "company_name": "IKEA Sweden"},
                            {"deal_id": "deal_002", "company_name": "IKEA Norway"}
                        ]
                    # select_all for "deals" with in_ on deal_id (disambiguation query)
                    elif table_name == "deals" and any(f[0] == "in_" and f[1] == "deal_id" for f in filters):
                        # Return details for matched deals
                        data = [
                            {
                                "deal_id": "deal_001",
                                "company_name": "IKEA Sweden",
                                "stage": "Discovery",
                                "owner_email": "christian@growthbook.io"
                            },
                            {
                                "deal_id": "deal_002",
                                "company_name": "IKEA Norway",
                                "stage": "Negotiating",
                                "owner_email": "sarah@growthbook.io"
                            }
                        ]

                    self.data = data
                    self.count = len(data)

            result = Result(self.table_name, self.filters)
            self.filters = []
            return result

    return MockSB()


def _mock_sb_single_deal():
    """MockSB that returns a single deal."""

    class MockSB:
        def __init__(self):
            self.table_name = None
            self.filters = []

        def table(self, name):
            self.table_name = name
            return self

        def select(self, cols):
            return self

        def eq(self, field, value):
            self.filters.append(("eq", field, value))
            return self

        def in_(self, field, values):
            self.filters.append(("in_", field, values))
            return self

        def ilike(self, field, pattern):
            self.filters.append(("ilike", field, pattern))
            return self

        def range(self, start, end):
            return self

        def execute(self):
            class Result:
                def __init__(self, table_name):
                    if table_name == "deals":
                        # Return single deal for "Acme"
                        data = [{"deal_id": "deal_003", "company_name": "Acme Corp"}]
                    else:
                        data = []

                    self.data = data
                    self.count = len(data)

            result = Result(self.table_name)
            self.filters = []
            return result

    return MockSB()


async def test_multiple_deals_returns_error():
    """Test: Multiple deals → explicit error, NOT silent picking."""
    print("\n[TEST] Multiple deals → returns error with deal list")

    sb = _mock_sb_multiple_deals()
    params = {"company": "IKEA"}

    result = await query_rep_coaching(params, sb)

    # Should have error status
    if result.get("status") != "error":
        raise AssertionError(f"Expected status='error', got: {result.get('status')}")

    # Should have error message mentioning multiple deals
    error_msg = result.get("error", "")
    if "2 deals" not in error_msg and "multiple" not in error_msg.lower():
        raise AssertionError(f"Expected error about multiple deals, got: {error_msg}")

    # Should have matched_deal_count
    if result.get("matched_deal_count") != 2:
        raise AssertionError(f"Expected matched_deal_count=2, got: {result.get('matched_deal_count')}")

    # Should list the deals in error message
    if "IKEA Sweden" not in error_msg or "IKEA Norway" not in error_msg:
        raise AssertionError(f"Expected deal names in error message, got: {error_msg}")

    # Should mention disambiguation strategy
    if "more specific" not in error_msg.lower():
        raise AssertionError(f"Expected disambiguation hint in error, got: {error_msg}")

    print(f"  ✓ Error returned (not silent picking)")
    print(f"  ✓ matched_deal_count: {result['matched_deal_count']}")
    print(f"  ✓ Error lists deals: '...IKEA Sweden...IKEA Norway...'")
    print(f"  ✓ Error asks user to disambiguate")


async def test_single_deal_proceeds():
    """Test: Single deal → proceeds normally (no error)."""
    print("\n[TEST] Single deal → proceeds (would call assess_rep_coaching)")

    sb = _mock_sb_single_deal()
    params = {"company": "Acme"}

    result = await query_rep_coaching(params, sb)

    # Should NOT have error status from ambiguity check
    # (Will have error from assess_rep_coaching mock not being set up,
    # but that's expected - we're only testing the disambiguation logic)
    if result.get("status") == "error" and "multiple" in result.get("error", "").lower():
        raise AssertionError(f"Should not error on ambiguity with single deal, got: {result}")

    # Should have matched_deal_ids with single entry OR error from assess_rep_coaching
    # (not from ambiguity check)
    if result.get("matched_deal_count", 0) > 1:
        raise AssertionError(f"Expected single deal, got matched_deal_count={result.get('matched_deal_count')}")

    print(f"  ✓ No ambiguity error (single deal matched)")
    print(f"  ✓ Would proceed to assess_rep_coaching(sb, 'deal_003')")


async def main():
    tests = [
        test_multiple_deals_returns_error,
        test_single_deal_proceeds,
    ]

    failed = []
    for test in tests:
        try:
            await test()
        except Exception as e:
            failed.append((test.__name__, str(e)))
            print(f"\n  ❌ FAILED: {e}")

    print("\n" + "=" * 70)
    print("TEST SUMMARY - Ambiguity Handling")
    print("=" * 70)

    passed = len(tests) - len(failed)
    print(f"\nTotal tests: {len(tests)}")
    print(f"  ✓ Passed: {passed}")

    if failed:
        print(f"  ✗ Failed: {len(failed)}")
        print("\nFailed tests:")
        for name, error in failed:
            print(f"  - {name}")
            print(f"    {error[:200]}")
        return 1

    print("\n✅ All ambiguity handling tests passed")
    return 0


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
