"""
Regression tests for the 2026-09-10 date-range defect: "last 2 weeks" asked
from a known date returned snapshots from weeks further back than requested
(e.g. Aug 17-28 instead of Aug 27-Sep 10), in two separate Slack threads on
the same day.

Root cause (two parts):

1. api/handlers.py query_pipeline_movement / _pm_view_movement selected the
   comparison snapshot by checking `time_window.get("type") ==
   "relative_days"` — a shape nothing in the codebase ever produced. The
   router always resolves time_window to {"start", "end", "label"} via
   resolve_time_window() before any handler runs, so requested_days was
   always None and the 'movement' view silently fell back to "compare
   whichever two snapshots happen to be most recent on file", ignoring
   whatever window the user actually asked for.

2. The intent classifier's JSON schema for time_window had no field to
   express a day/week count for period=last_N_days, so resolve_time_window's
   `tw.get("n", 30)` could never be populated correctly for a phrase like
   "last 2 weeks".

These tests pin resolve_time_window() to a known "today" and assert the
exact resulting range, and exercise _pm_view_movement's snapshot-selection
directly to confirm it now honors a requested day count instead of blindly
using the last two snapshots on file.
"""
import sys
from pathlib import Path
from datetime import datetime as real_datetime, timezone as real_timezone
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).parent.parent))
sys.path.insert(0, str(Path(__file__).parent.parent / "scripts"))

import sdr_utils
from api.time_resolver import resolve_time_window
from api.handlers import _pm_view_movement


def _frozen_utc(year, month, day, hour=12, minute=0):
    """Patch sdr_utils.datetime.now() to a fixed UTC instant.

    resolve_time_window() gets "today" via _today() -> today_in_reporting_tz()
    -> sdr_utils.datetime.now(timezone.utc) — not date.today() anymore (see
    api/time_resolver.py's _today() docstring for why). So freezing time for
    these tests means patching sdr_utils.datetime, not api.time_resolver.date.
    """
    frozen = real_datetime(year, month, day, hour, minute, tzinfo=real_timezone.utc)

    class _FrozenDatetime(real_datetime):
        @classmethod
        def now(cls, tz=None):
            return frozen if tz else frozen.replace(tzinfo=None)

    return patch.object(sdr_utils, "datetime", _FrozenDatetime)


def test_last_2_weeks_from_known_date_is_exact():
    """'last 2 weeks' (n=14) from a known 'today' of 2026-09-10 must resolve
    to exactly 2026-08-27 - 2026-09-10, not some other window."""
    with _frozen_utc(2026, 9, 10):
        result = resolve_time_window({"period": "last_N_days", "n": 14})

    assert result["start"] == "2026-08-27", \
        f"Expected start=2026-08-27, got {result['start']}"
    assert result["end"] == "2026-09-10", \
        f"Expected end=2026-09-10, got {result['end']}"
    print("✓ resolve_time_window('last 2 weeks') from a known date is exact")


def test_last_30_days_from_known_date_is_exact():
    """Sanity check a second n value from the same known date."""
    with _frozen_utc(2026, 9, 10):
        result = resolve_time_window({"period": "last_N_days", "n": 30})

    assert result["start"] == "2026-08-11", \
        f"Expected start=2026-08-11, got {result['start']}"
    assert result["end"] == "2026-09-10", \
        f"Expected end=2026-09-10, got {result['end']}"
    print("✓ resolve_time_window('last 30 days') from a known date is exact")


def test_resolve_time_window_uses_reporting_timezone_not_server_utc():
    """Third instance of 'which today does this use', found auditing the
    first two: resolve_time_window() called date.today() (server UTC)
    directly, while client.yaml's reporting.timezone is America/New_York
    and the rest of the system (query_stale_deals, coaching handlers, SDR
    ETL) uses today_in_reporting_tz() instead. For part of every evening
    (UTC has rolled to the next day, New York hasn't) that meant
    resolve_time_window() disagreed with itself about "today" by a full
    day — the exact bug class this whole audit is about, just one layer
    deeper. This freezes UTC "now" to 2026-09-11 02:00 (10pm EDT on
    2026-09-10) — a server reading date.today() would see 2026-09-11, but
    the reporting-timezone-correct date is still 2026-09-10."""
    with _frozen_utc(2026, 9, 11, hour=2, minute=0):
        result = resolve_time_window({"period": "last_N_days", "n": 14})

    assert result["end"] == "2026-09-10", (
        "resolve_time_window must use the reporting timezone (America/"
        "New_York), not server UTC — at 02:00 UTC it's still 2026-09-10 "
        f"in New York, but got end={result['end']}"
    )
    assert result["start"] == "2026-08-27", \
        f"Expected start=2026-08-27, got {result['start']}"
    print("✓ resolve_time_window follows reporting timezone, not server UTC")


def _rows(deal_ids):
    return [{"deal_id": d, "stage_id": "1"} for d in deal_ids]


def _stage_cfg():
    return {"1": {"name": "Discovery", "order": 1}}


def test_movement_view_ignores_window_without_the_fix_reproduces_defect():
    """Documents the exact broken mechanism: with requested_days=None (what
    the dead 'type'=='relative_days' check always produced before the fix),
    the view falls back to the last two snapshots on file — Aug 17 and
    Aug 28 here — regardless of what window was actually asked for."""
    all_dates = ["2026-07-01", "2026-07-29", "2026-08-14",
                 "2026-08-17", "2026-08-28"]
    by_date = {d: _rows([1, 2, 3]) for d in all_dates}
    data_gaps = []

    result = _pm_view_movement(by_date, all_dates, _stage_cfg(), data_gaps,
                                requested_days=None, base={})

    assert result["snapshot_dates"] == ["2026-08-17", "2026-08-28"], (
        "This is the defect: with no requested_days, the view just grabs "
        f"the last two snapshots on file, got {result['snapshot_dates']}"
    )
    print("✓ requested_days=None reproduces the reported Aug17-28 window")


def test_movement_view_honors_requested_days_after_fix():
    """With the fix, query_pipeline_movement now derives requested_days from
    the already-resolved time_window (end - start), so a 'last 2 weeks'
    request (14 days) picks the snapshot closest to 14 days before the
    latest one on file — not just whatever the second-to-last snapshot
    happens to be."""
    all_dates = ["2026-07-01", "2026-07-29", "2026-08-14",
                 "2026-08-17", "2026-08-28"]
    by_date = {d: _rows([1, 2, 3]) for d in all_dates}
    data_gaps = []

    result = _pm_view_movement(by_date, all_dates, _stage_cfg(), data_gaps,
                                requested_days=14, base={})

    assert result["snapshot_dates"] == ["2026-08-14", "2026-08-28"], (
        f"Expected the 14-day-prior snapshot (2026-08-14), "
        f"got {result['snapshot_dates']}"
    )
    assert not any("Requested 14 days" in g for g in data_gaps), (
        "An exact 14-day match should not raise a window-mismatch warning: "
        f"{data_gaps}"
    )
    print("✓ requested_days=14 picks the snapshot actually 14 days back")


def test_movement_view_warns_when_no_snapshot_matches_requested_window():
    """When no snapshot exists near the requested window, the view should
    still degrade gracefully — but must say so, not silently substitute an
    unrelated span."""
    all_dates = ["2026-06-01", "2026-08-28"]  # huge gap, no 14-day match
    by_date = {d: _rows([1, 2]) for d in all_dates}
    data_gaps = []

    result = _pm_view_movement(by_date, all_dates, _stage_cfg(), data_gaps,
                                requested_days=14, base={})

    assert result["snapshot_dates"] == ["2026-06-01", "2026-08-28"]
    assert any("Requested 14" in g or "14 days" in g for g in data_gaps), (
        f"Expected a mismatch warning when no snapshot is near the "
        f"requested window, got data_gaps={data_gaps}"
    )
    print("✓ large gap between requested window and available snapshots is flagged")


if __name__ == "__main__":
    test_last_2_weeks_from_known_date_is_exact()
    test_last_30_days_from_known_date_is_exact()
    test_resolve_time_window_uses_reporting_timezone_not_server_utc()
    test_movement_view_ignores_window_without_the_fix_reproduces_defect()
    test_movement_view_honors_requested_days_after_fix()
    test_movement_view_warns_when_no_snapshot_matches_requested_window()
    print("\n✅ All tests passed")
