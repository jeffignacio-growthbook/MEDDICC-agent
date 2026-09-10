#!/usr/bin/env python3
"""
Authoritative check: every column on deals, deals_snapshot, and
waterfall_weekly is either registered in data_dictionary or explicitly
excluded in config/data_dictionary_exclusions.yaml.

This is the live counterpart to tests/test_data_dictionary_registration.py.
That test is a fast, offline, forward-looking gate (new migrations only —
see its docstring for why a static check can't safely re-litigate
history). This script is the actual source of truth: it queries the real
Postgres schema and the real data_dictionary table, so it also catches
historical gaps that predate migration 062 — like deals_snapshot.region
and deals_snapshot.segment themselves were, for three days, before this
gate existed.

Reuses get_missing_columns() from backfill_data_dictionary.py (the same
query, already written and working) rather than re-deriving it, filtered
to the three tables the dynamic query loop most depends on getting right.

Usage:
    python scripts/check_data_dictionary_coverage.py            # exits 1 on any real gap
    python scripts/check_data_dictionary_coverage.py --fix      # also backfills via
                                                                  backfill_data_dictionary.py

Requires SUPABASE_DB_URL (a direct Postgres connection string — same env
var backfill_data_dictionary.py uses).
"""
import os
import sys
import argparse
import yaml
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))

TRACKED_TABLES = {"deals", "deals_snapshot", "waterfall_weekly"}

REPO_ROOT = Path(__file__).parent.parent
EXCLUSIONS_PATH = REPO_ROOT / "config" / "data_dictionary_exclusions.yaml"


def load_exclusions() -> set:
    if not EXCLUSIONS_PATH.exists():
        return set()
    data = yaml.safe_load(EXCLUSIONS_PATH.read_text()) or {}
    return {(e["table"], e["column"]) for e in (data.get("excluded") or [])}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--fix", action="store_true",
                        help="Run backfill_data_dictionary.py for any real gap found")
    args = parser.parse_args()

    import psycopg2
    from backfill_data_dictionary import get_missing_columns

    db_url = os.getenv("SUPABASE_DB_URL")
    if not db_url:
        print("SUPABASE_DB_URL not set — cannot run the live coverage check.")
        print("(This is the direct Postgres connection string backfill_data_dictionary.py "
              "already uses, not SUPABASE_URL/SUPABASE_SERVICE_KEY.)")
        sys.exit(2)

    conn = psycopg2.connect(db_url)
    try:
        missing = get_missing_columns(conn)  # [(table, column, pg_type), ...]
    finally:
        conn.close()

    missing_tracked = [(t, c, dt) for (t, c, dt) in missing if t in TRACKED_TABLES]
    excluded = load_exclusions()

    real_gaps = [(t, c, dt) for (t, c, dt) in missing_tracked if (t, c) not in excluded]

    print(f"Checked {TRACKED_TABLES}")
    print(f"  {len(missing_tracked)} column(s) in Postgres but not in data_dictionary")
    print(f"  {len(excluded)} exclusion(s) on file")
    print(f"  {len(real_gaps)} real, unexcused gap(s)")
    print()

    if not real_gaps:
        print("✓ Every column on deals/deals_snapshot/waterfall_weekly is registered "
              "in data_dictionary or explicitly excluded.")
        sys.exit(0)

    print("✗ REGISTRATION GAP — column(s) exist in Postgres but are invisible to the "
          "dynamic query loop:")
    for table, column, pg_type in real_gaps:
        print(f"    {table}.{column}  ({pg_type})")
    print()
    print("This is exactly the deals_snapshot.region/segment defect from 2026-09-11: "
          "a real, populated column the model cannot see or use. Either register it "
          "(a migration inserting into data_dictionary — see migration 062 for the "
          "pattern, or run this script with --fix) or add it to "
          f"{EXCLUSIONS_PATH.relative_to(REPO_ROOT)} with a real reason.")

    if args.fix:
        print("\n--fix requested: running backfill_data_dictionary.py for these columns...")
        os.system(f"{sys.executable} {Path(__file__).parent / 'backfill_data_dictionary.py'}")

    sys.exit(1)


if __name__ == "__main__":
    main()
