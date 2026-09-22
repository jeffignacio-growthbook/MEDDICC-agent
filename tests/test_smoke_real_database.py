#!/usr/bin/env python3
"""
Real-database smoke tests for all primitives built this session.

PURPOSE: Catch schema bugs that mocked tests miss (Bug #1 root cause).

These tests verify that each primitive's SQL queries are VALID against the
real database schema - they don't crash with "column does not exist" or
type mismatch errors. They do NOT verify result correctness (that's what
the mocked tests do) - only that the query RUNS.

This is cheap insurance:
- Mocks test logic correctness
- These tests catch schema validity
- Together they provide full coverage

Run via: pytest tests/test_smoke_real_database.py
CI runs this alongside mocked tests.
"""
import sys
from pathlib import Path
from datetime import date, timedelta
import asyncio

# Setup paths
repo_root = Path(__file__).parent.parent
sys.path.insert(0, str(repo_root / "api"))
sys.path.insert(0, str(repo_root / "scripts"))

# Load environment
from dotenv import load_dotenv
load_dotenv(repo_root / ".env")

from db import get_supabase


def test_forecast_trust_real_query():
    """Smoke test: assess_forecast_trust() queries don't crash on real schema."""
    from forecast_trust import assess_forecast_trust

    sb = get_supabase()

    # Use a past date to avoid week-gate issues
    as_of = date(2026, 9, 15)  # Week 8 of Q3

    try:
        result = assess_forecast_trust(sb, as_of=as_of)

        # Verify basic structure (not correctness, just didn't crash)
        assert isinstance(result, dict), "Result should be dict"
        assert "status" in result, "Result missing status key"

        print(f"✅ forecast_trust real query succeeded (status: {result['status']})")
        return True
    except Exception as e:
        print(f"❌ forecast_trust query failed: {e}")
        raise


def test_pipeline_coverage_real_query():
    """Smoke test: assess_pipeline_coverage() queries don't crash on real schema."""
    from pipeline_coverage import assess_pipeline_coverage

    sb = get_supabase()

    # Use a past date
    as_of = date(2026, 9, 15)

    try:
        result = assess_pipeline_coverage(sb, as_of=as_of)

        assert isinstance(result, dict), "Result should be dict"
        assert "status" in result, "Result missing status key"

        print(f"✅ pipeline_coverage real query succeeded (status: {result['status']})")
        return True
    except Exception as e:
        print(f"❌ pipeline_coverage query failed: {e}")
        raise


def test_deal_risk_assessor_real_query():
    """Smoke test: get_at_risk_deals() queries don't crash on real schema."""
    from deal_risk_assessor import get_at_risk_deals

    sb = get_supabase()

    try:
        result = get_at_risk_deals(sb, fiscal_quarter="FY2027 Q2")

        assert isinstance(result, dict), "Result should be dict"
        assert "assessed_deals" in result, "Result missing assessed_deals key"
        assert "summary" in result, "Result missing summary key"

        print(f"✅ deal_risk_assessor real query succeeded ({result['summary'].get('total_assessed', 0)} deals)")
        return True
    except Exception as e:
        print(f"❌ deal_risk_assessor query failed: {e}")
        raise


def test_rep_coaching_real_query():
    """Smoke test: assess_rep_coaching() queries don't crash on real schema."""
    from rep_coaching import assess_rep_coaching

    sb = get_supabase()

    # Get a real deal_id from database to test with
    deals = sb.table("deals").select("deal_id").eq("deal_status", "active").limit(1).execute()

    if not deals.data:
        print("⚠️  No active deals found, skipping rep_coaching smoke test")
        return True

    deal_id = deals.data[0]["deal_id"]

    try:
        result = assess_rep_coaching(sb, deal_id=deal_id)

        assert isinstance(result, dict), "Result should be dict"
        assert "status" in result, "Result missing status key"

        print(f"✅ rep_coaching real query succeeded (status: {result['status']})")
        return True
    except Exception as e:
        print(f"❌ rep_coaching query failed: {e}")
        raise


def test_loss_concentration_real_query():
    """Smoke test: assess_loss_concentration() queries don't crash on real schema."""
    from loss_concentration import assess_loss_concentration

    sb = get_supabase()

    try:
        # loss_concentration uses time_window dict, not fiscal_quarter string
        result = assess_loss_concentration(sb, time_window={"period": "last_quarter"})

        assert isinstance(result, dict), "Result should be dict"
        # loss_concentration has flexible return structure, just verify it's a dict

        print(f"✅ loss_concentration real query succeeded")
        return True
    except Exception as e:
        print(f"❌ loss_concentration query failed: {e}")
        raise


def test_array_column_filtering_real_query():
    """Smoke test: Array column (participant_emails) filtering doesn't crash."""
    async def run_test():
        from tools import filter_table

        sb = get_supabase()

        result = await filter_table(
            sb=sb,
            table="calls",
            columns=["call_id", "participant_emails"],
            filters=[["ilike", "participant_emails", "%test%"]],
            limit=1
        )

        assert "error" not in result, f"Query failed: {result.get('error')}"
        assert "rows" in result, "Result missing rows key"

        print(f"✅ array column filtering real query succeeded")
        return True

    try:
        success = asyncio.run(run_test())
        return success
    except Exception as e:
        print(f"❌ array column filtering query failed: {e}")
        raise


if __name__ == "__main__":
    print("\n" + "=" * 70)
    print("REAL-DATABASE SMOKE TESTS")
    print("=" * 70)
    print("\nThese tests verify SQL queries don't crash on real schema.")
    print("They complement mocked tests (logic) with schema validation.\n")

    tests = [
        ("Forecast Trust", test_forecast_trust_real_query),
        ("Pipeline Coverage", test_pipeline_coverage_real_query),
        ("Deal Risk Assessor", test_deal_risk_assessor_real_query),
        ("Rep Coaching", test_rep_coaching_real_query),
        ("Loss Concentration", test_loss_concentration_real_query),
        ("Array Column Filtering", test_array_column_filtering_real_query),
    ]

    passed = 0
    failed = 0

    for name, test_fn in tests:
        print(f"\n[TEST] {name}")
        try:
            test_fn()
            passed += 1
        except Exception as e:
            print(f"  ❌ FAILED: {e}")
            failed += 1

    print("\n" + "=" * 70)
    print(f"RESULTS: {passed} passed, {failed} failed")
    print("=" * 70)

    if failed > 0:
        sys.exit(1)

    print("\n✅ All real-database smoke tests passed!")
    print("Schema validation complete - SQL queries are valid.\n")
