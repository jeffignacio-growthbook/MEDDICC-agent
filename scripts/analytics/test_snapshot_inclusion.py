#!/usr/bin/env python3
"""
Guard test: Verify snapshot inclusion rule compliance.

Ensures deals that closed before a snapshot date do not appear in that snapshot.
"""
import os
import sys
from datetime import datetime
from dotenv import load_dotenv

load_dotenv()

sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))
from supabase import create_client
from supabase_client import select_all


def test_snapshot_excludes_deals_closed_before_snapshot_date():
    """
    A deal that closed before date D must not appear in D's snapshot.
    Snapshots capture open pipeline as of a date, not all deals ever.
    """
    sb = create_client(os.environ['SUPABASE_URL'], os.environ['SUPABASE_SERVICE_KEY'])

    # Sample 1000 random snapshot rows
    snapshots = sb.table('deals_snapshot').select(
        'deal_id, snapshot_date, close_date'
    ).limit(1000).execute()

    violations = []

    for snap in snapshots.data:
        snapshot_date = snap.get('snapshot_date')
        close_date = snap.get('close_date')

        if not close_date or not snapshot_date:
            continue

        snapshot_dt = datetime.fromisoformat(snapshot_date).date()
        close_dt = datetime.fromisoformat(close_date).date()

        # Violation: deal closed BEFORE snapshot date
        if close_dt < snapshot_dt:
            violations.append({
                'deal_id': snap['deal_id'],
                'snapshot_date': snapshot_date,
                'close_date': close_date,
                'days_before': (snapshot_dt - close_dt).days
            })

    if violations:
        print(f"\n⚠️  TEST FAILED: {len(violations)} violation(s) found")
        print(f"\nSample violations:")
        for v in violations[:5]:
            print(f"  Deal {v['deal_id']}: closed {v['close_date']}, "
                  f"in snapshot {v['snapshot_date']} ({v['days_before']} days before)")
        raise AssertionError(
            f"Found {len(violations)} deals in snapshots that closed before the snapshot date. "
            "Snapshots must only include deals open on the snapshot date."
        )

    print("\n✓ TEST PASSED: No deals closed before their snapshot date")
    return True


if __name__ == '__main__':
    try:
        test_snapshot_excludes_deals_closed_before_snapshot_date()
        print("\n✓ All snapshot inclusion tests passed")
        sys.exit(0)
    except AssertionError as e:
        print(f"\n✗ Test failed: {e}")
        sys.exit(1)
