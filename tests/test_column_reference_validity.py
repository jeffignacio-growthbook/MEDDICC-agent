#!/usr/bin/env python3
"""
GATE 2: Column reference validity check.

CRITICAL GATE: Prevents the "amount" bug pattern from recurring.

The Bug Pattern (2026-09-21, Bug #1):
- scripts/forecast_trust.py referenced column "amount"
- That column never existed in any table (should be "arr_usd")
- Mocked tests passed (mocked data had whatever columns the test wanted)
- Production crashed: "column 'amount' does not exist"
- Result: forecast_trust primitive completely broken

This test FAILS THE BUILD if:
1. Code references a column name in a .select() call
2. That column doesn't exist in data_dictionary for that table
3. AND it's NOT in the allowlist (dynamic/wildcard selects)

Source of Truth: LIVE data_dictionary table (via SUPABASE_DB_URL).
NOT migration files - those can be stale relative to what's registered.

Coverage: Static analysis of literal column names only. Dynamic column
references (e.g., computed strings, wildcards) are allowlisted.
"""
import re
import sys
from pathlib import Path
from typing import Dict, Set, List, Tuple

# Setup paths
REPO_ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(REPO_ROOT / "api"))

from dotenv import load_dotenv
load_dotenv(REPO_ROOT / ".env")

from db import get_supabase

# Files to scan for column references
SCAN_DIRS = [
    REPO_ROOT / "scripts",
    REPO_ROOT / "api",
]

# Skip one-off analysis/investigation scripts (not production code)
# These reference historical columns or are exploratory scripts not in active use
SKIP_PATTERNS = [
    "analyze_signal",
    "check_signal",
    "compare_signal",
    "derive_signal",
    "investigate_signal",
    "recompute_with_",
    "sample_newly_",
    "test_meddicc_timing",
    "check_enterprise_discovery_fallback",
    "check_meddicc_scores_for_validation",
]

# Allowlist: (file_pattern, reason) for .select() calls that can't be statically validated
ALLOWLIST_COLUMN_CHECKS = {
    # Wildcard selects (valid but unvalidatable)
    ('*', 'select("*")'):
        "Wildcard select - fetches all columns, can't statically validate",

    # Dynamic column construction
    ('dynamic_columns', 'select(dynamic_columns)'):
        "Dynamic column string - runtime-constructed, can't statically validate",

    # Count queries (no specific columns)
    ('count(*)', 'select("count(*)")'):
        "Count aggregation - no specific column references",

    # Add specific known dynamic cases here as they're found
}


def get_registered_columns() -> Dict[str, Set[str]]:
    """
    Query LIVE data_dictionary table for all registered columns by table.

    Returns: {table_name: {col1, col2, ...}}

    This is the source of truth - migration files can be stale.
    """
    sb = get_supabase()

    try:
        result = sb.table("data_dictionary").select(
            "supabase_table, supabase_column"
        ).execute()

        columns_by_table = {}
        for row in result.data:
            table = row["supabase_table"]
            column = row["supabase_column"]

            if table not in columns_by_table:
                columns_by_table[table] = set()
            columns_by_table[table].add(column.lower())

        return columns_by_table

    except Exception as e:
        print(f"❌ Failed to query data_dictionary: {e}")
        print("   Ensure SUPABASE_URL and SUPABASE_SERVICE_KEY are set")
        raise


def extract_select_calls(file_path: Path) -> List[Tuple[int, str, str, str]]:
    """
    Extract all .select() calls from a Python file.

    Handles both same-line and multi-line patterns:
    - Same-line: sb.table("deals").select("deal_id, arr_usd")
    - Multi-line: sb.table("deals")\n    .select("deal_id, arr_usd")

    Returns: [(line_num, table_name, select_arg, full_line), ...]
    """
    if not file_path.suffix == ".py":
        return []

    try:
        content = file_path.read_text()
    except:
        return []

    selects = []
    lines = content.split("\n")

    # Patterns
    table_pattern = r'\.table\(["\'](\w+)["\']\)'
    select_pattern = r'\.select\(["\']([^"\']+)["\']\)'

    # Track which lines we've already processed as multi-line selects
    processed_selects = set()

    for i, line in enumerate(lines, 1):
        # Skip comments
        if line.strip().startswith("#"):
            continue

        # Find table name
        table_match = re.search(table_pattern, line)
        if not table_match:
            continue

        table_name = table_match.group(1)

        # Try to find select on the same line first (most common)
        select_match = re.search(select_pattern, line)
        if select_match:
            select_arg = select_match.group(1)
            selects.append((i, table_name, select_arg, line.strip()))
            continue

        # No select on same line - look ahead for multi-line pattern
        # Most multi-line patterns are within 1-3 lines, but check up to 15 for safety
        for j in range(i, min(i + 15, len(lines))):
            if j in processed_selects:
                continue

            lookahead_line = lines[j]

            # Skip empty lines and comments
            if not lookahead_line.strip() or lookahead_line.strip().startswith("#"):
                continue

            # Look for .select( on this line
            if '.select(' in lookahead_line:
                select_line_num = j + 1

                # Try to find the select argument on this line first
                select_match = re.search(select_pattern, lookahead_line)
                if select_match:
                    select_arg = select_match.group(1)
                    processed_selects.add(j)
                    selects.append((select_line_num, table_name, select_arg, lookahead_line.strip()))
                    break

                # Select argument might be on the next line (e.g., .select(\n    'columns'))
                # Look ahead one more line for the string argument
                if j + 1 < len(lines):
                    next_line = lines[j + 1]
                    # Match a string at the start of the line (after whitespace)
                    arg_match = re.match(r'\s*["\']([^"\']+)["\']', next_line)
                    if arg_match:
                        select_arg = arg_match.group(1)
                        processed_selects.add(j)
                        processed_selects.add(j + 1)
                        # Use the line where the columns are actually defined
                        selects.append((j + 2, table_name, select_arg, next_line.strip()))
                        break

    return selects


def parse_select_columns(select_arg: str) -> List[str]:
    """
    Parse column names from a select string.

    Examples:
        "deal_id, arr_usd, stage" -> ["deal_id", "arr_usd", "stage"]
        "id, status" -> ["id", "status"]
        "*" -> [] (can't validate wildcard)
        "count(*)" -> [] (aggregation, not column reference)

    Returns empty list for patterns we can't/shouldn't validate.
    """
    # Wildcards and aggregations
    if "*" in select_arg:
        return []

    # Parse comma-separated column names
    columns = []
    for col in select_arg.split(","):
        col = col.strip()

        # Skip empty
        if not col:
            continue

        # Skip SQL functions (count, sum, etc.)
        if "(" in col or ")" in col:
            continue

        # Skip AS clauses (column AS alias)
        if " as " in col.lower():
            col = col.lower().split(" as ")[0].strip()

        # Basic sanity: should look like an identifier
        if re.match(r'^[a-zA-Z_][a-zA-Z0-9_]*$', col):
            columns.append(col.lower())

    return columns


def validate_column_references() -> Tuple[List[Tuple], int, int]:
    """
    Scan all Python files for .select() calls and validate column references.

    Returns: (invalid_refs, total_validated, total_allowlisted)
        invalid_refs: [(file, line, table, column, select_arg), ...]
        total_validated: count of .select() calls with literal columns checked
        total_allowlisted: count of .select() calls that couldn't be validated
    """
    # Get registered columns from live data_dictionary
    registered_columns = get_registered_columns()

    invalid_refs = []
    total_selects = 0
    validated_selects = 0
    allowlisted_selects = 0

    # Scan all files
    for scan_dir in SCAN_DIRS:
        if not scan_dir.exists():
            continue

        for file_path in scan_dir.rglob("*.py"):
            # Skip one-off analysis scripts
            if any(pattern in file_path.name for pattern in SKIP_PATTERNS):
                continue

            selects = extract_select_calls(file_path)
            total_selects += len(selects)

            for line_num, table_name, select_arg, full_line in selects:
                # Parse columns from select string
                columns = parse_select_columns(select_arg)

                # If no columns parsed, this is allowlisted (wildcard/dynamic/etc.)
                if not columns:
                    allowlisted_selects += 1
                    continue

                # Check if table is registered
                if table_name not in registered_columns:
                    # Table not in data_dictionary - might be valid but unregistered
                    # Don't fail on this (would be too noisy), just skip
                    allowlisted_selects += 1
                    continue

                # Validate each column
                validated_selects += 1
                for column in columns:
                    if column not in registered_columns[table_name]:
                        rel_path = file_path.relative_to(REPO_ROOT)
                        invalid_refs.append((
                            str(rel_path),
                            line_num,
                            table_name,
                            column,
                            select_arg
                        ))

    return invalid_refs, validated_selects, allowlisted_selects


def test_column_reference_validity():
    """
    CRITICAL CI GATE: Fail if code references non-existent columns.

    This prevents the "amount" bug pattern: code referencing a column
    that doesn't exist in the actual schema, caught only in production.
    """
    print("\n" + "=" * 80)
    print("GATE 2: Column Reference Validity Check")
    print("=" * 80)

    invalid_refs, validated, allowlisted = validate_column_references()

    total = validated + allowlisted

    # Report coverage stats
    print(f"\n📊 Coverage: {validated}/{total} .select() calls validated, "
          f"{allowlisted} allowlisted")
    print(f"   (Allowlisted: wildcards, dynamic columns, count queries)")

    if allowlisted > 0:
        pct = (allowlisted / total * 100) if total > 0 else 0
        print(f"   ⚠️  {pct:.1f}% of selects use dynamic patterns - "
              f"not statically validatable")

    # Report invalid references
    if invalid_refs:
        print("\n" + "=" * 80)
        print("❌ INVALID COLUMN REFERENCES DETECTED")
        print("=" * 80)

        # Group by file
        by_file = {}
        for file, line, table, column, select_arg in invalid_refs:
            if file not in by_file:
                by_file[file] = []
            by_file[file].append((line, table, column, select_arg))

        for file in sorted(by_file.keys()):
            print(f"\n{file}:")
            for line, table, column, select_arg in by_file[file]:
                print(f"  Line {line}: {table}.{column} doesn't exist")
                print(f"    select(\"{select_arg}\")")

        print("\n" + "=" * 80)
        print("This is the SAME BUG PATTERN as the 'amount' incident (Bug #1):")
        print("  - Code referenced column 'amount' in forecast_trust.py")
        print("  - That column never existed (should be 'arr_usd')")
        print("  - Mocked tests passed, production crashed")
        print("")
        print("FIX: Use the correct column name registered in data_dictionary")
        print("     Check: SELECT supabase_column FROM data_dictionary")
        print("            WHERE supabase_table = '<table>'")
        print("=" * 80)

        raise AssertionError(f"Found {len(invalid_refs)} invalid column references")

    print("\n✅ All column references valid")
    print(f"   Validated {validated} .select() calls against live data_dictionary")
    print("=" * 80)


if __name__ == "__main__":
    test_column_reference_validity()
