#!/usr/bin/env python3
"""
Schema-dictionary drift detector.

The Problem:
When someone runs a manual migration adding new columns to queryable tables
(deals.region, deals_snapshot.segment, etc.), but forgets to register them
in data_dictionary, those columns become INVISIBLE to the dynamic query
system — the exact bug pattern that hid region/segment and
new_arr/expansion_arr/renewal_revenue from users for days.

This check is the FOURTH structural gate (after date-math, primitive-contract,
and handler-param-completeness). Unlike those per-PR gates, this runs on a
SCHEDULE (daily/weekly) because schema drift comes from manual DB changes,
not code commits.

Two categories of drift:
  (a) HIGH SEVERITY: Columns exist in real Postgres schema but are missing
      from data_dictionary with is_queryable=True. This makes real data
      invisible to queries — same as the region/segment incident.

  (b) LOWER SEVERITY: Columns registered in data_dictionary but no longer
      exist in the real schema (stale registration). Worth flagging for
      cleanup but doesn't break queries.

Usage:
    python scripts/check_schema_dictionary_drift.py           # exits 1 on category (a) drift
    python scripts/check_schema_dictionary_drift.py --verbose # show clean tables too

Requires:
    SUPABASE_DB_URL: Direct Postgres connection string (same as backfill_data_dictionary.py)
"""

import os
import sys
import argparse
import psycopg2
from pathlib import Path

# Add project root to path
sys.path.insert(0, str(Path(__file__).parent.parent))
sys.path.insert(0, str(Path(__file__).parent))

REPO_ROOT = Path(__file__).parent.parent

# All tables that handlers and dynamic_query can query
# Sourced from backfill_data_dictionary.py QUERYABLE_TABLES + SDR/persona tables
QUERYABLE_TABLES = [
    # Core sales tables
    "deals",
    "deals_snapshot",
    "calls",
    "analyses",

    # Signal tables
    "objections",
    "feature_gaps",
    "win_loss_narratives",
    "competitive_signals",
    "pipeline_signals",
    "deal_risks",

    # Pipeline analytics
    "waterfall_weekly",
    "forecast_weekly",
    "pipeline_generation_weekly",

    # Performance & targets
    "rep_performance",
    "rep_targets",

    # SDR metrics
    "sdr_metrics",
    "sdr_users",

    # User context
    "user_personas",

    # Views (read-only aggregations)
    "arr_by_customer",
]

# Exclusions: columns we know about but intentionally don't register
# Load from config/data_dictionary_exclusions.yaml if needed
EXCLUSIONS_PATH = REPO_ROOT / "config" / "data_dictionary_exclusions.yaml"


def load_exclusions() -> set:
    """Load excluded (table, column) pairs from config file."""
    if not EXCLUSIONS_PATH.exists():
        return set()

    import yaml
    data = yaml.safe_load(EXCLUSIONS_PATH.read_text()) or {}
    return {(e["table"], e["column"]) for e in (data.get("excluded") or [])}


def get_real_schema_columns(conn) -> dict:
    """
    Query information_schema.columns for all columns in QUERYABLE_TABLES.

    Returns:
        {table_name: [(column_name, data_type), ...]}
    """
    cur = conn.cursor()

    tables_clause = ",".join(f"'{t}'" for t in QUERYABLE_TABLES)

    query = f"""
    SELECT table_name, column_name, data_type
    FROM information_schema.columns
    WHERE table_schema = 'public'
      AND table_name IN ({tables_clause})
    ORDER BY table_name, ordinal_position;
    """

    cur.execute(query)
    results = cur.fetchall()
    cur.close()

    # Group by table
    by_table = {}
    for table_name, column_name, data_type in results:
        if table_name not in by_table:
            by_table[table_name] = []
        by_table[table_name].append((column_name, data_type))

    return by_table


def get_registered_columns(conn) -> dict:
    """
    Query data_dictionary for all registered columns where is_queryable=True.

    Returns:
        {table_name: [(column_name, data_type), ...]}
    """
    cur = conn.cursor()

    query = """
    SELECT supabase_table, supabase_column, data_type
    FROM data_dictionary
    WHERE is_queryable = TRUE
    ORDER BY supabase_table, supabase_column;
    """

    cur.execute(query)
    results = cur.fetchall()
    cur.close()

    # Group by table
    by_table = {}
    for table_name, column_name, data_type in results:
        if table_name not in by_table:
            by_table[table_name] = []
        by_table[table_name].append((column_name, data_type))

    return by_table


def check_drift(real_schema, registered, exclusions) -> tuple:
    """
    Compare real schema against data_dictionary registrations.

    Returns:
        (missing_from_dict, stale_in_dict)

        missing_from_dict: [(table, column, pg_type)] - HIGH severity
        stale_in_dict: [(table, column, data_type)] - LOWER severity
    """
    missing_from_dict = []
    stale_in_dict = []

    # Check all real tables
    all_tables = set(real_schema.keys()) | set(registered.keys())

    for table in sorted(all_tables):
        real_cols = {col: dtype for col, dtype in real_schema.get(table, [])}
        reg_cols = {col: dtype for col, dtype in registered.get(table, [])}

        # Category (a): Real columns not in data_dictionary
        for col, dtype in real_cols.items():
            if col not in reg_cols:
                # Check if explicitly excluded
                if (table, col) not in exclusions:
                    missing_from_dict.append((table, col, dtype))

        # Category (b): Registered columns not in real schema
        for col, dtype in reg_cols.items():
            if col not in real_cols:
                stale_in_dict.append((table, col, dtype))

    return missing_from_dict, stale_in_dict


def main():
    parser = argparse.ArgumentParser(
        description=__doc__,
        formatter_class=argparse.RawDescriptionHelpFormatter
    )
    parser.add_argument(
        "--verbose", "-v",
        action="store_true",
        help="Show details even when no drift found"
    )
    args = parser.parse_args()

    # Check for database connection
    db_url = os.getenv("SUPABASE_DB_URL")
    if not db_url:
        print("ERROR: SUPABASE_DB_URL not set")
        print()
        print("This check requires a direct Postgres connection string.")
        print("Set SUPABASE_DB_URL to your database connection string.")
        print("(Same env var used by backfill_data_dictionary.py)")
        sys.exit(2)

    # Connect and query
    print(f"Checking schema drift for {len(QUERYABLE_TABLES)} queryable tables...")
    print()

    conn = psycopg2.connect(db_url)
    try:
        real_schema = get_real_schema_columns(conn)
        registered = get_registered_columns(conn)
        exclusions = load_exclusions()

        missing_from_dict, stale_in_dict = check_drift(real_schema, registered, exclusions)
    finally:
        conn.close()

    # Report findings
    total_real_cols = sum(len(cols) for cols in real_schema.values())
    total_reg_cols = sum(len(cols) for cols in registered.values())

    if args.verbose:
        print(f"Real schema: {len(real_schema)} tables, {total_real_cols} columns")
        print(f"Registered: {len(registered)} tables, {total_reg_cols} columns")
        print(f"Exclusions: {len(exclusions)} (table, column) pairs")
        print()

    # Category (a) - HIGH SEVERITY
    if missing_from_dict:
        print("=" * 80)
        print("❌ CATEGORY (a): HIGH SEVERITY - INVISIBLE DATA")
        print("=" * 80)
        print()
        print("The following columns exist in the real Postgres schema but are")
        print("MISSING from data_dictionary (or have is_queryable=False).")
        print()
        print("This is the EXACT BUG PATTERN from the region/segment incident:")
        print("  - Real data exists in the database")
        print("  - data_dictionary doesn't know about it")
        print("  - Dynamic query can't see or use these columns")
        print("  - Users get incomplete/wrong answers")
        print()

        by_table = {}
        for table, col, dtype in missing_from_dict:
            if table not in by_table:
                by_table[table] = []
            by_table[table].append((col, dtype))

        for table in sorted(by_table.keys()):
            print(f"  {table}:")
            for col, dtype in sorted(by_table[table]):
                print(f"    - {col} ({dtype})")

        print()
        print("FIX: Run one of:")
        print("  1. python scripts/backfill_data_dictionary.py")
        print("  2. Create migration inserting into data_dictionary (see migration 062)")
        print(f"  3. Add to {EXCLUSIONS_PATH.relative_to(REPO_ROOT)} with justification")
        print()

    # Category (b) - LOWER SEVERITY
    if stale_in_dict:
        print("=" * 80)
        print("⚠️  CATEGORY (b): LOWER SEVERITY - STALE REGISTRATIONS")
        print("=" * 80)
        print()
        print("The following columns are registered in data_dictionary but")
        print("no longer exist in the real Postgres schema.")
        print()
        print("This won't break queries (the column isn't there to query), but")
        print("it clutters the schema context and could confuse users/models.")
        print()

        by_table = {}
        for table, col, dtype in stale_in_dict:
            if table not in by_table:
                by_table[table] = []
            by_table[table].append((col, dtype))

        for table in sorted(by_table.keys()):
            print(f"  {table}:")
            for col, dtype in sorted(by_table[table]):
                print(f"    - {col} ({dtype})")

        print()
        print("FIX: Delete these rows from data_dictionary or set is_queryable=False")
        print()

    # Summary
    print("=" * 80)
    print("SUMMARY")
    print("=" * 80)
    print(f"Category (a) - Invisible data: {len(missing_from_dict)} column(s)")
    print(f"Category (b) - Stale registrations: {len(stale_in_dict)} column(s)")
    print()

    if not missing_from_dict and not stale_in_dict:
        print("✅ NO DRIFT DETECTED")
        print()
        print(f"All {total_real_cols} columns across {len(real_schema)} queryable tables")
        print("are correctly registered in data_dictionary or explicitly excluded.")
        sys.exit(0)

    # Fail on category (a) - invisible data is a critical error
    if missing_from_dict:
        print("❌ DRIFT CHECK FAILED")
        print()
        print("Schema drift detected in category (a) - columns exist but are invisible.")
        print("This is a CRITICAL error that must be fixed before the next query run.")
        sys.exit(1)

    # Warn on category (b) but don't fail
    if stale_in_dict:
        print("⚠️  DRIFT CHECK WARNING")
        print()
        print("Stale registrations found. Not critical, but should be cleaned up.")
        sys.exit(0)


if __name__ == "__main__":
    main()
