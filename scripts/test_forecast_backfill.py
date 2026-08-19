#!/usr/bin/env python3
"""
Tests for forecast_category backfill point-in-time matching.

Critical: Backfill must NEVER use future values (lookahead bias).
Each snapshot gets the most recent history entry with timestamp <= snapshot_date.
"""

import sys
from datetime import datetime, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))


def test_backfill_never_uses_future_category_value():
    """
    A history entry dated after the snapshot_date must never be selected.

    Construct a deal with category change on day N+2 and assert the day-N
    snapshot gets the day N-5 value, not the day N+2 value.

    This prevents lookahead bias that would make commit calibration look
    artificially good.
    """
    print("\n[TEST] Backfill never uses future category value")

    # Mock history for a deal:
    # - Day N-5: PIPELINE
    # - Day N+2: COMMIT
    history = [
        {
            'timestamp': '2026-01-05T10:00:00.000Z',  # Day N-5
            'value': 'PIPELINE'
        },
        {
            'timestamp': '2026-01-12T14:00:00.000Z',  # Day N+2
            'value': 'COMMIT'
        }
    ]

    snapshot_date = '2026-01-10'  # Day N

    # Import the matching function (will create it)
    from backfill_forecast_category import get_category_at_snapshot_date

    result = get_category_at_snapshot_date(history, snapshot_date)

    # Should get PIPELINE (day N-5), NOT COMMIT (day N+2)
    if result != 'PIPELINE':
        raise AssertionError(
            f"Expected 'PIPELINE' (most recent past value), got '{result}'\n"
            f"This is lookahead bias - snapshot on {snapshot_date} cannot see "
            f"the future value 'COMMIT' from 2026-01-12"
        )

    print("  ✓ Snapshot on 2026-01-10 correctly gets 'PIPELINE' from 2026-01-05")
    print("  ✓ Future value 'COMMIT' from 2026-01-12 correctly ignored")
    print("  ✓ No lookahead bias")


def test_backfill_returns_null_when_no_past_history():
    """
    If a deal's earliest category history postdates the snapshot,
    return NULL (not a default, not forward-fill).
    """
    print("\n[TEST] Backfill returns NULL when no past history")

    # History starts AFTER the snapshot date
    history = [
        {
            'timestamp': '2026-02-15T10:00:00.000Z',
            'value': 'BEST_CASE'
        }
    ]

    snapshot_date = '2026-02-10'  # Before any history

    from backfill_forecast_category import get_category_at_snapshot_date

    result = get_category_at_snapshot_date(history, snapshot_date)

    if result is not None:
        raise AssertionError(
            f"Expected None (no history before snapshot), got '{result}'\n"
            f"Do not forward-fill, do not default to PIPELINE"
        )

    print("  ✓ Snapshot on 2026-02-10 correctly gets NULL")
    print("  ✓ No forward-fill from future value")
    print("  ✓ No default to PIPELINE")


def test_backfill_selects_most_recent_past_value():
    """
    When multiple history entries predate the snapshot,
    select the most recent one.
    """
    print("\n[TEST] Backfill selects most recent past value")

    # Multiple past values
    history = [
        {
            'timestamp': '2026-01-05T10:00:00.000Z',
            'value': 'PIPELINE'
        },
        {
            'timestamp': '2026-01-08T14:00:00.000Z',
            'value': 'BEST_CASE'
        },
        {
            'timestamp': '2026-01-15T16:00:00.000Z',  # Future
            'value': 'COMMIT'
        }
    ]

    snapshot_date = '2026-01-10'

    from backfill_forecast_category import get_category_at_snapshot_date

    result = get_category_at_snapshot_date(history, snapshot_date)

    if result != 'BEST_CASE':
        raise AssertionError(
            f"Expected 'BEST_CASE' (most recent past), got '{result}'\n"
            f"Should select 2026-01-08 value, not 2026-01-05 or 2026-01-15"
        )

    print("  ✓ Correctly selected 'BEST_CASE' from 2026-01-08")
    print("  ✓ Ignored older value from 2026-01-05")
    print("  ✓ Ignored future value from 2026-01-15")


def test_backfill_handles_exact_timestamp_match():
    """
    When history timestamp exactly equals snapshot_date,
    that value should be used (it's not "future").
    """
    print("\n[TEST] Backfill handles exact timestamp match")

    history = [
        {
            'timestamp': '2026-01-10T00:00:00.000Z',  # Exact match
            'value': 'COMMIT'
        }
    ]

    snapshot_date = '2026-01-10'

    from backfill_forecast_category import get_category_at_snapshot_date

    result = get_category_at_snapshot_date(history, snapshot_date)

    if result != 'COMMIT':
        raise AssertionError(
            f"Expected 'COMMIT' (exact date match), got '{result}'"
        )

    print("  ✓ Exact timestamp match correctly returns value")


def main():
    """Run all point-in-time matching tests."""
    print("=" * 70)
    print("FORECAST CATEGORY BACKFILL TESTS")
    print("=" * 70)

    tests = [
        test_backfill_never_uses_future_category_value,
        test_backfill_returns_null_when_no_past_history,
        test_backfill_selects_most_recent_past_value,
        test_backfill_handles_exact_timestamp_match,
    ]

    failed = []

    for test in tests:
        try:
            test()
        except Exception as e:
            failed.append((test.__name__, str(e)))
            print(f"\n  ❌ FAILED: {e}")

    print("\n" + "=" * 70)
    print("TEST SUMMARY")
    print("=" * 70)

    passed = len(tests) - len(failed)
    print(f"\nTotal tests: {len(tests)}")
    print(f"  ✓ Passed: {passed}")

    if failed:
        print(f"  ✗ Failed: {len(failed)}")
        print("\nFailed tests:")
        for name, error in failed:
            print(f"  - {name}")
            print(f"    {error[:200]}")
        return 1

    print("\n✅ All point-in-time matching tests passed")
    print("   Backfill logic is safe from lookahead bias")
    return 0


if __name__ == '__main__':
    sys.exit(main())
