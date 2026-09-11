#!/usr/bin/env python3
"""
Verify new_arr/expansion_arr are actually populating on the live
deals_snapshot table (migration 064 / PENDING_WORK.md Low Priority #11)
for today's snapshot_date.

Prints row counts (total / non-null new_arr / non-null expansion_arr)
and a sample of real captured values — real confirmation the write path
actually works in production, not just in a mocked test.

Usage: python scripts/check_snapshot_arr_fields.py
"""
import os
import sys
from datetime import date
from pathlib import Path

REPO_ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(REPO_ROOT))
sys.path.insert(0, str(REPO_ROOT / 'scripts'))
sys.path.insert(0, str(REPO_ROOT / 'api'))


def main():
    from db import get_supabase
    from supabase_client import select_all

    sb = get_supabase()
    today = date.today().isoformat()

    rows = select_all(
        sb, 'deals_snapshot',
        columns='deal_id,new_arr,expansion_arr,deal_value,pipeline_id',
        filters=[('eq', 'snapshot_date', today)]
    )

    print(f"snapshot_date={today}")
    print(f"total rows: {len(rows)}")

    if not rows:
        print("⚠️  No rows found for today's snapshot_date.")
        return

    new_arr_populated = [r for r in rows if r.get('new_arr') is not None]
    expansion_arr_populated = [r for r in rows if r.get('expansion_arr') is not None]

    print(f"new_arr non-null: {len(new_arr_populated)} / {len(rows)}")
    print(f"expansion_arr non-null: {len(expansion_arr_populated)} / {len(rows)}")

    either_populated = [r for r in rows
                        if r.get('new_arr') is not None or r.get('expansion_arr') is not None]
    print(f"either non-null: {len(either_populated)} / {len(rows)}")

    print("\nSample rows (first 10 with at least one component populated):")
    for r in either_populated[:10]:
        print(f"  deal_id={r['deal_id']!r} pipeline_id={r.get('pipeline_id')!r} "
              f"new_arr={r.get('new_arr')!r} expansion_arr={r.get('expansion_arr')!r} "
              f"deal_value={r.get('deal_value')!r}")

    if not either_populated:
        print("\n❌ ZERO rows have either component populated — fix did not take effect.")
        print("Sample of what WAS captured (first 5 rows, any values):")
        for r in rows[:5]:
            print(f"  deal_id={r['deal_id']!r} new_arr={r.get('new_arr')!r} "
                  f"expansion_arr={r.get('expansion_arr')!r} deal_value={r.get('deal_value')!r}")


if __name__ == "__main__":
    main()
