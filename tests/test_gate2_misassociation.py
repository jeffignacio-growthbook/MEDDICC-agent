#!/usr/bin/env python3
"""
Test case to verify Gate 2 doesn't mis-associate .select() with wrong .table().

This tests the specific bug found in verify_activity_baseline.py where:
  Line 61: sb.table("emails").select("id", count="exact")
  Line 75-76: sb.table("deals").select("deal_id,...")

The buggy version associated line 76's columns with line 61's "emails" table,
causing incorrect validation (checking deal columns against email table schema).
"""
from pathlib import Path
import tempfile
import sys

REPO_ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(REPO_ROOT / "tests"))

from test_column_reference_validity import extract_select_calls

def test_no_misassociation():
    """
    Test that .select() calls are correctly associated with their own .table().
    """
    # Create a test file with the exact pattern that caused the bug
    test_code = '''
def check_tables():
    # Pattern 1: Same-line with count parameter (was failing regex)
    emails_count = sb.table("emails").select("id", count="exact").execute()

    # Some lines in between
    print("Checking data...")
    print("=" * 80)

    # Pattern 2: Multi-line split (was being mis-associated with "emails")
    deals = sb.table("deals").select(
        "deal_id,company_name,arr_usd"
    ).eq("status", "active").execute()
'''

    with tempfile.NamedTemporaryFile(mode='w', suffix='.py', delete=False) as f:
        f.write(test_code)
        f.flush()
        test_file = Path(f.name)

    try:
        results = extract_select_calls(test_file)

        # Should find exactly 2 patterns
        assert len(results) == 2, f"Expected 2 patterns, got {len(results)}: {results}"

        # First pattern: emails table with "id" column
        line1, table1, cols1, _ = results[0]
        assert table1 == "emails", f"First pattern should be 'emails', got '{table1}'"
        assert cols1 == "id", f"First pattern should select 'id', got '{cols1}'"

        # Second pattern: deals table with multiple columns
        line2, table2, cols2, _ = results[1]
        assert table2 == "deals", f"Second pattern should be 'deals', got '{table2}'"
        assert "deal_id" in cols2, f"Second pattern should include 'deal_id', got '{cols2}'"
        assert "arr_usd" in cols2, f"Second pattern should include 'arr_usd', got '{cols2}'"

        print("✅ PASS: No mis-association - each .select() matched to correct .table()")
        print(f"   Pattern 1: Line {line1} - {table1}.select({cols1})")
        print(f"   Pattern 2: Line {line2} - {table2}.select({cols2})")
        return True

    finally:
        test_file.unlink()

def test_verify_activity_baseline_case():
    """
    Test the actual file that exposed the bug.
    """
    test_file = REPO_ROOT / "scripts" / "verify_activity_baseline.py"
    if not test_file.exists():
        print(f"⚠️  SKIP: {test_file} not found")
        return True

    results = extract_select_calls(test_file)

    # Find the specific patterns at lines 61 and 75-76
    emails_pattern = None
    deals_pattern = None

    for line_num, table, cols, _ in results:
        if 60 <= line_num <= 62 and table == "emails":
            emails_pattern = (line_num, table, cols)
        if 75 <= line_num <= 77 and table == "deals":
            deals_pattern = (line_num, table, cols)

    # Verify emails pattern was found correctly
    assert emails_pattern is not None, \
        "Should find emails.select() around line 61"
    assert emails_pattern[2] == "id", \
        f"emails pattern should select 'id', got '{emails_pattern[2]}'"

    # Verify deals pattern was found correctly
    assert deals_pattern is not None, \
        "Should find deals.select() around lines 75-76"
    assert "deal_id" in deals_pattern[2], \
        f"deals pattern should include 'deal_id', got '{deals_pattern[2]}'"
    assert deals_pattern[1] == "deals", \
        f"Line 75-76 should be associated with 'deals' table, got '{deals_pattern[1]}'"

    print("✅ PASS: verify_activity_baseline.py correctly parsed")
    print(f"   Line ~61: {emails_pattern[1]}.select({emails_pattern[2]})")
    print(f"   Line ~76: {deals_pattern[1]}.select({deals_pattern[2][:40]}...)")
    return True

if __name__ == "__main__":
    print("="*80)
    print("GATE 2 MIS-ASSOCIATION BUG TEST")
    print("="*80)
    print()

    try:
        test_no_misassociation()
        print()
        test_verify_activity_baseline_case()
        print()
        print("="*80)
        print("✅ ALL TESTS PASSED - Mis-association bug is fixed")
        print("="*80)
        sys.exit(0)
    except AssertionError as e:
        print()
        print("="*80)
        print(f"❌ TEST FAILED: {e}")
        print("="*80)
        sys.exit(1)
    except Exception as e:
        print()
        print("="*80)
        print(f"❌ ERROR: {e}")
        import traceback
        traceback.print_exc()
        print("="*80)
        sys.exit(1)
