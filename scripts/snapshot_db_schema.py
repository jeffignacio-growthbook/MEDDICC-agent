#!/usr/bin/env python3
"""
Snapshot of the real Supabase schema for GATE 2
(tests/test_column_reference_validity.py), which checks every .select()
column against it offline on each push.

  python scripts/snapshot_db_schema.py          # rewrite the snapshot
  python scripts/snapshot_db_schema.py --check  # exit 1 if the live schema drifted

Source: information_schema.columns for schema public (tables and views).
Needs SUPABASE_DB_URL (a Postgres connection string). The weekly
schema-drift-check workflow runs --check, so a column dropped or added in the
database without regenerating the snapshot is caught within a week; GATE 2
itself fails at once on a select naming a table the snapshot doesn't have.
"""
import json
import os
import sys
from datetime import date
from pathlib import Path

SNAPSHOT = Path(__file__).parent.parent / "tests" / "fixtures" / "db_schema_columns.json"

QUERY = """
SELECT c.table_name, c.column_name
  FROM information_schema.columns c
  JOIN information_schema.tables t
    ON t.table_schema = c.table_schema AND t.table_name = c.table_name
 WHERE c.table_schema = 'public'
 ORDER BY c.table_name, c.column_name
"""


def live_schema(url):
    import psycopg2
    with psycopg2.connect(url) as conn, conn.cursor() as cur:
        cur.execute(QUERY)
        out = {}
        for table, column in cur.fetchall():
            out.setdefault(table, []).append(column)
        return out


def diff(old, new):
    lines = []
    for t in sorted(set(old) | set(new)):
        if t not in new:
            lines.append(f"table dropped: {t}")
        elif t not in old:
            lines.append(f"table added: {t}")
        else:
            for c in sorted(set(old[t]) - set(new[t])):
                lines.append(f"column dropped: {t}.{c}")
            for c in sorted(set(new[t]) - set(old[t])):
                lines.append(f"column added: {t}.{c}")
    return lines


def main():
    url = os.getenv("SUPABASE_DB_URL")
    if not url:
        print("❌ SUPABASE_DB_URL is not set")
        return 1
    new = live_schema(url)
    if "--check" in sys.argv:
        old = json.loads(SNAPSHOT.read_text())["tables"]
        changes = diff(old, new)
        if changes:
            print("❌ The live schema differs from tests/fixtures/db_schema_columns.json:")
            for line in changes:
                print(f"   {line}")
            print("Regenerate: python scripts/snapshot_db_schema.py, then rerun GATE 2.")
            return 1
        print(f"✓ Snapshot matches the live schema ({len(new)} tables)")
        return 0
    SNAPSHOT.write_text(json.dumps({
        "_source": "information_schema.columns, schema public (tables and views)",
        "_captured_at": date.today().isoformat(),
        "_regenerate": "python scripts/snapshot_db_schema.py (needs SUPABASE_DB_URL)",
        "tables": new}, indent=1) + "\n")
    print(f"✓ Wrote {SNAPSHOT} ({len(new)} tables, {sum(map(len, new.values()))} columns)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
