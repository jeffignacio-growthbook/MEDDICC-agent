#!/usr/bin/env python3
"""
Real-database test for array column filtering (Bug #2 fix verification).

Tests that ilike/like operators work correctly on text[] array columns like
participant_emails, using the REAL Supabase database (not mocks).

This catches the Bug #2 root cause: mocked tests can't catch PostgreSQL
operator type mismatches.
"""
import sys
import os
from pathlib import Path

# Setup paths
repo_root = Path(__file__).parent.parent
sys.path.insert(0, str(repo_root / "api"))
sys.path.insert(0, str(repo_root / "scripts"))

# Load environment variables
from dotenv import load_dotenv
load_dotenv(repo_root / ".env")

def test_array_column_ilike_filter():
    """
    Test that filter_table handles text[] array columns correctly with ilike.

    This is a REAL database test (not mocked) that exercises the exact code
    path that crashed in Bug #2: filtering participant_emails (text[] array)
    with ilike operator.
    """
    # Import here after path setup
    from db import get_supabase
    import asyncio

    async def run_test():
        from tools import filter_table

        sb = get_supabase()

        # Test the exact query pattern that crashed:
        # participant_emails is text[] array in calls table
        # ilike on array requires special handling (cs operator)

        result = await filter_table(
            sb=sb,
            table="calls",
            columns=["call_id", "company_name", "participant_emails"],
            filters=[
                ["ilike", "participant_emails", "%growthbook%"]
            ],
            limit=5
        )

        # Verify query succeeded (didn't crash with PostgreSQL operator error)
        assert "error" not in result, f"Query failed: {result.get('error')}"
        assert "rows" in result, "Result missing rows key"

        # The query should succeed even if it returns 0 rows
        # (Schema validity is what we're testing, not data existence)
        print(f"✅ Array column filter succeeded: {len(result['rows'])} rows returned")

        # If we got rows, verify participant_emails is present
        if result["rows"]:
            assert "participant_emails" in result["rows"][0], \
                "participant_emails column missing from result"
            print(f"✅ participant_emails array column properly returned")

        return True

    try:
        success = asyncio.run(run_test())
        assert success, "Test did not complete successfully"
        print("✅ BUG #2 FIX VERIFIED: Array column filtering works against REAL database")
        return True
    except Exception as e:
        print(f"❌ Test failed: {e}")
        raise


if __name__ == "__main__":
    test_array_column_ilike_filter()
    print("\n✅ All array column filtering tests passed!")
