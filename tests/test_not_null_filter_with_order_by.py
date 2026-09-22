#!/usr/bin/env python3
"""
Regression test for the 2026-09-22 __not_null__ + order_by bug.

Root cause: filter_table's order_by path (api/tools.py:117-147) lacked
special handling for the __not_null__ marker created at line 91 when
a filter like ["neq", "column", null] is passed.

The code did: q = getattr(q, "__not_null__")(*f[1:])
Which fails with: 'SyncSelectRequestBuilder' object has no attribute '__not_null__'

Correct handling (now at line 122-123):
    if op == "__not_null__":
        q = q.not_.is_(filter_col, "null")

This bug existed since August 13, 2026 (commit 8d8d44ce) and was exposed by
the 24-question battery, specifically question 19: "What's our average MEDDICC
score by stage?" which generates a filter_table call with both:
1. A "not null" filter (filters: [["neq", "overall_score", null]])
2. An order_by clause (order_by: "analyzed_at DESC")

Without the fix, this combination crashes the query before it reaches Supabase.
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

import asyncio
import os
from dotenv import load_dotenv
load_dotenv(Path(__file__).parent.parent / ".env")

from api.tools import filter_table
from api.db import get_supabase


async def test_not_null_with_order_by():
    """Test that filter_table handles ["neq", col, null] with order_by."""
    sb = get_supabase()

    # This filter will be converted to __not_null__ marker at line 91
    filters = [
        ["eq", "deal_status", "active"],
        ["neq", "overall_score", None],  # This becomes ("__not_null__", "overall_score", None)
    ]

    # The order_by triggers the buggy path (line 117-147)
    # Without the fix, this crashes with AttributeError: '__not_null__'
    try:
        result = await filter_table(
            sb,
            table="analyses",
            columns=["deal_id", "overall_score", "analyzed_at"],
            filters=filters,
            limit=10,
            order_by="analyzed_at DESC"
        )

        print(f"✅ PASS: filter_table with neq-null + order_by returned {result['total_found']} rows")
        return True

    except AttributeError as e:
        if "__not_null__" in str(e):
            print(f"❌ FAIL: __not_null__ bug still exists: {e}")
            return False
        raise


async def test_not_null_without_order_by():
    """Verify the non-order_by path (line 150) also handles __not_null__."""
    sb = get_supabase()

    filters = [
        ["eq", "deal_status", "active"],
        ["neq", "overall_score", None],
    ]

    # No order_by - uses select_all path which has correct handling since Aug 13
    try:
        result = await filter_table(
            sb,
            table="analyses",
            columns=["deal_id", "overall_score"],
            filters=filters,
            limit=10
        )

        print(f"✅ PASS: filter_table without order_by returned {result['total_found']} rows")
        return True

    except Exception as e:
        print(f"❌ FAIL: non-order_by path failed: {e}")
        return False


async def main():
    print("=" * 80)
    print("REGRESSION TEST: __not_null__ + order_by bug (2026-09-22)")
    print("=" * 80)
    print()

    test1 = await test_not_null_with_order_by()
    test2 = await test_not_null_without_order_by()

    print()
    if test1 and test2:
        print("✅ ALL TESTS PASSED")
        sys.exit(0)
    else:
        print("❌ SOME TESTS FAILED")
        sys.exit(1)


if __name__ == "__main__":
    asyncio.run(main())
