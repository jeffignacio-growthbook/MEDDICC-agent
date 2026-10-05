#!/usr/bin/env python3
"""
Rollback for the AM-role quota PR (feat/am-role-quota-fy2027-q3-q4).

Undoes, in the live rep_targets table, everything scripts/seed_targets.py
would write for FY2027_Q3/FY2027_Q4 once that PR's config/targets.yaml is
seeded:

  1. Restores the 7 FY2027_Q3 rows exactly as they were BEFORE the AM-role
     change, from data/backups/fy2027_q3_pre_amrole_backup.json (6 rep
     rows + 1 "AE Team" team row, all role=ae, team total $1,550,000).
     An upsert on (period, level, entity_name, metric) — same conflict
     key seed_targets.py uses — so it overwrites whatever those same
     keys hold (e.g. updated Jake/Marcel target_values) with the old
     values, without touching unrelated rows.

  2. Deletes every FY2027_Q4 row. FY2027_Q4 had ZERO rep_targets rows
     before this PR (confirmed), so a rollback of Q4 is simply "delete
     whatever got inserted" — there is nothing to restore it TO.

  3. Deletes the three FY2027_Q3 rows the load newly INSERTS (no prior
     row to upsert over): entity_email in (cary@growthbook.io,
     marsh@growthbook.io, kris@growthbook.io — two am-role, one
     ae-role, all three new to Q3). Matched by explicit email, not by
     role, so a future unrelated rep row is never caught by this
     rollback.

After this script, FY2027_Q3 must hold exactly 7 rows again (the 6
rep rows + "AE Team" at $1,550,000) and FY2027_Q4 must hold zero —
byte-for-byte the pre-PR state. Verify with:

    SELECT period, count(*) FROM rep_targets
    WHERE period IN ('FY2027_Q3', 'FY2027_Q4') GROUP BY period;
    -- healthy: FY2027_Q3 -> 7, FY2027_Q4 absent (0 rows)

SAFETY: this script is NOT run automatically by anything. It is a
rollback net for a human to invoke deliberately, and only upserts/
deletes when --confirm is passed. A bare invocation is a dry run that
prints what it WOULD do and changes nothing.

Usage:
    python scripts/restore_fy2027_q3_pre_amrole.py            # dry run
    python scripts/restore_fy2027_q3_pre_amrole.py --confirm  # actually writes
"""
import argparse
import json
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(REPO_ROOT / 'scripts'))

BACKUP_PATH = REPO_ROOT / 'data' / 'backups' / 'fy2027_q3_pre_amrole_backup.json'
Q4_PERIOD = 'FY2027_Q4'
Q3_PERIOD = 'FY2027_Q3'
Q3_NEW_INSERT_EMAILS = ['cary@growthbook.io', 'marsh@growthbook.io', 'kris@growthbook.io']


def load_backup_rows() -> list:
    if not BACKUP_PATH.exists():
        raise FileNotFoundError(
            f"Backup file not found: {BACKUP_PATH}. Nothing to restore from.")
    rows = json.loads(BACKUP_PATH.read_text())
    if len(rows) != 7:
        raise ValueError(
            f"Expected 7 rows in {BACKUP_PATH}, found {len(rows)}. "
            "Refusing to restore from a backup that doesn't match the "
            "documented FY2027_Q3 pre-AM-role snapshot.")
    return rows


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--confirm', action='store_true',
                         help='Actually write to the live rep_targets table. '
                              'Omit for a dry run (prints the plan only).')
    args = parser.parse_args()

    rows = load_backup_rows()

    print("=" * 70)
    print("ROLLBACK PLAN: restore_fy2027_q3_pre_amrole.py")
    print("=" * 70)
    print()
    print(f"1) Restore {len(rows)} FY2027_Q3 rows from {BACKUP_PATH.name}:")
    for row in rows:
        label = row["entity_name"] if row["level"] == "rep" else f"{row['entity_name']} (team)"
        print(f"   - {label}: ${row['target_value']:,} [{row['role']}]")
    print()
    print(f"2) Delete ALL rep_targets rows where period = '{Q4_PERIOD}' "
          "(Q4 had zero rows before this PR — a rollback is a full delete).")
    print()
    print(f"3) Delete the {len(Q3_NEW_INSERT_EMAILS)} new FY2027_Q3 rows the load "
          f"inserted (no prior row to upsert over): "
          f"{', '.join(Q3_NEW_INSERT_EMAILS)}")
    print()
    print(f"After this: {Q3_PERIOD} must hold exactly 7 rows "
          f"(6 rep + \"AE Team\" at $1,550,000); {Q4_PERIOD} must hold 0.")
    print()

    if not args.confirm:
        print("DRY RUN — nothing written. Re-run with --confirm to apply.")
        return

    from dotenv import load_dotenv
    load_dotenv(REPO_ROOT / '.env')
    from supabase_client import SupabaseWriter
    writer = SupabaseWriter()
    client = writer.client

    print("Restoring FY2027_Q3 rows...")
    restored = 0
    for row in rows:
        try:
            client.table('rep_targets').upsert(
                row, on_conflict='period,level,entity_name,metric'
            ).execute()
            restored += 1
        except Exception as e:
            print(f"  ✗ Failed to restore {row['entity_name']}: {e}")
    print(f"  Restored {restored}/{len(rows)} FY2027_Q3 rows.")
    print()

    print(f"Deleting all {Q4_PERIOD} rows...")
    try:
        resp = client.table('rep_targets').delete().eq(
            'period', Q4_PERIOD).execute()
        deleted_n = len(resp.data) if getattr(resp, 'data', None) else 0
        print(f"  Deleted {deleted_n} {Q4_PERIOD} row(s).")
    except Exception as e:
        print(f"  ✗ Failed to delete {Q4_PERIOD} rows: {e}")

    print()
    print(f"Deleting the {len(Q3_NEW_INSERT_EMAILS)} new {Q3_PERIOD} rows "
          f"({', '.join(Q3_NEW_INSERT_EMAILS)})...")
    try:
        resp = client.table('rep_targets').delete().eq(
            'period', Q3_PERIOD).in_(
            'entity_email', Q3_NEW_INSERT_EMAILS).execute()
        deleted_n = len(resp.data) if getattr(resp, 'data', None) else 0
        print(f"  Deleted {deleted_n} new {Q3_PERIOD} row(s).")
    except Exception as e:
        print(f"  ✗ Failed to delete new {Q3_PERIOD} rows: {e}")

    print()
    print("Done. Verify with:")
    print(f"  SELECT * FROM rep_targets WHERE period IN "
          f"('{Q3_PERIOD}', '{Q4_PERIOD}') ORDER BY period, level, entity_name;")
    print()
    print("  -- Exact-count check (healthy: Q3 -> 7, Q4 -> 0):")
    print(f"  SELECT period, count(*) FROM rep_targets "
          f"WHERE period IN ('{Q3_PERIOD}', '{Q4_PERIOD}') GROUP BY period;")


if __name__ == '__main__':
    main()
