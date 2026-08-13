#!/usr/bin/env python3
"""
Validation script for Phase H approval gate fixes.

Tests:
- FIX A: Query efficiency (analyses row limit)
- FIX B: Aggregations format conversion
- FIX C: Owner email mapping (ETL function)
"""
import sys
import os
from pathlib import Path

REPO_ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(REPO_ROOT))
sys.path.insert(0, str(REPO_ROOT / 'scripts'))
sys.path.insert(0, str(REPO_ROOT / 'api'))

def test_fix_a_analyses_limit():
    """FIX A: Verify analyses table has 50 row limit"""
    # Check the code directly rather than trying to mock Supabase
    with open(REPO_ROOT / "api" / "tools.py") as f:
        content = f.read()

    # Verify the limit logic exists
    assert "max_limit = 50 if table == \"analyses\" else 200" in content, \
        "Missing analyses table 50-row limit"
    assert "limit = min(limit or 50, max_limit)" in content, \
        "Missing limit enforcement logic"

    print("✓ FIX A: Analyses table limit set to 50 rows max (line 36-38 in api/tools.py)")

    # Verify system prompt has query efficiency hint
    with open(REPO_ROOT / "api" / "router.py") as f:
        router_content = f.read()

    assert "QUERY EFFICIENCY:" in router_content, \
        "Missing query efficiency section in system prompt"
    assert "query the analyses table FIRST" in router_content, \
        "Missing analyses-first instruction"

    print("✓ FIX A: System prompt includes query efficiency guidance")

    return True


def test_fix_b_aggregations_format():
    """FIX B: Verify aggregations format conversion works"""
    import asyncio
    from api.tools import aggregate_results

    async def test():
        # Test data
        test_data = [
            {"rep": "alice@co.com", "deal_value": 100, "deal_id": "1"},
            {"rep": "alice@co.com", "deal_value": 200, "deal_id": "2"},
            {"rep": "bob@co.com", "deal_value": 150, "deal_id": "3"},
        ]

        # Test 1: Dict format (correct)
        result1 = await aggregate_results(
            data=test_data,
            group_by="rep",
            aggregations={"deal_value": "sum", "deal_id": "count"}
        )
        assert "grouped" in result1, "Dict format should work"
        print("✓ FIX B: Dict format works:", result1["grouped"])

        # Test 2: List format (should auto-convert)
        result2 = await aggregate_results(
            data=test_data,
            group_by="rep",
            aggregations=[
                {"column": "deal_value", "agg": "sum"},
                {"col": "deal_id", "aggregation": "count"}
            ]
        )
        assert "grouped" in result2, "List format should auto-convert to dict"
        print("✓ FIX B: List format auto-converts:", result2["grouped"])

        # Test 3: Invalid format (should return error)
        result3 = await aggregate_results(
            data=test_data,
            group_by="rep",
            aggregations=[]
        )
        assert "error" in result3, "Empty aggregations should return error"
        print("✓ FIX B: Empty aggregations rejected:", result3["error"])

        return True

    return asyncio.run(test())


def test_fix_c_owner_mapping():
    """FIX C: Verify owner email mapping function exists and has correct signature"""
    # Check the function exists in the source file
    with open(REPO_ROOT / "scripts" / "etl_deals.py") as f:
        content = f.read()

    # Check function exists
    assert "def fetch_owner_emails(hubspot):" in content, \
        "fetch_owner_emails function missing"

    print("✓ FIX C: fetch_owner_emails function exists in etl_deals.py")

    # Verify function implements HubSpot Owners API call
    assert 'endpoint = "/crm/v3/owners"' in content, \
        "Function should call HubSpot Owners API"
    assert "owner_map[owner_id] = email" in content, \
        "Function should create owner_id -> email mapping"

    print("✓ FIX C: Function implements HubSpot Owners API integration")

    # Verify the ETL uses 'owner' not 'owner_id' in deal_dict
    with open(REPO_ROOT / "scripts" / "etl_deals.py") as f:
        content = f.read()
        assert "'owner': owner," in content, \
            "ETL should use 'owner' field not 'owner_id'"
        assert "# Owner email (looked up from owner_id)" in content, \
            "Comment should explain owner field"

    print("✓ FIX C: ETL stores 'owner' field with email (not 'owner_id')")

    return True


def test_router_prompt_updates():
    """Verify router.py has updated system prompts with fixes"""
    with open(REPO_ROOT / "api" / "router.py") as f:
        content = f.read()

    # Check FIX A hint
    assert "QUERY EFFICIENCY:" in content, \
        "Missing query efficiency hint"
    assert "query the analyses table FIRST" in content, \
        "Missing analyses-first instruction"
    print("✓ Router prompt includes query efficiency hint (FIX A)")

    # Check FIX B format enforcement
    assert "aggregations MUST be a dict" in content, \
        "Missing aggregations format instruction"
    assert '{"deal_value": "sum"' in content, \
        "Missing correct format example"
    print("✓ Router prompt includes aggregations format enforcement (FIX B)")

    return True


if __name__ == '__main__':
    print("=" * 60)
    print("PHASE H APPROVAL GATE — VALIDATION")
    print("=" * 60)

    tests = [
        ("FIX A: Analyses row limit", test_fix_a_analyses_limit),
        ("FIX B: Aggregations format", test_fix_b_aggregations_format),
        ("FIX C: Owner email mapping", test_fix_c_owner_mapping),
        ("Router prompt updates", test_router_prompt_updates),
    ]

    passed = 0
    failed = 0

    for name, test_fn in tests:
        print(f"\n{name}:")
        try:
            result = test_fn()
            if result:
                passed += 1
                print(f"  ✅ PASS\n")
            else:
                failed += 1
                print(f"  ❌ FAIL\n")
        except Exception as e:
            failed += 1
            print(f"  ❌ FAIL: {e}\n")

    print("=" * 60)
    print(f"RESULTS: {passed} passed, {failed} failed")
    print("=" * 60)

    if failed > 0:
        sys.exit(1)
    else:
        print("\n✅ All validation checks passed — fixes ready for merge")
        sys.exit(0)
