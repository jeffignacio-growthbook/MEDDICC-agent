"""
Regression tests for the off-by-one-year date bug class and the None-passthrough
defect family in resolve_time_window().

Root causes fixed:

1. None-passthrough in tw.get(key, default): dict.get(key, default) ignores the
   default when the LLM emits "key": null — the key IS present with value None,
   so the default is not used. Fixed throughout resolve_time_window() with
   `tw.get(key) or default` instead of `tw.get(key, default)`.
   Affected fields confirmed: period, n, fiscal_quarter, end.

2. Month+year off-by-one-year: for "January 2026" the classifier was emitting
   start="2025-01-01" (treating it as "most recent past January" relative to
   a stale internal anchor). Primary fix: specific_month period type. The LLM
   emits the month name/number and literal integer year from the question; Python
   constructs the date range — the model never anchors or resolves a year.
   Defense-in-depth: year-correction guard in router.py for period=specific.

3. Year sanity guard: implausible years (>4 years back or >1 year ahead) produce
   an explicit NO DATA AVAILABLE signal rather than silently reaching the snapshot
   lookup with a year that can't possibly have data.

GrowthBook fiscal year starts February (fy_start_month=2).
January sits just before the FY start — the case most likely to trip
fiscal-calendar translation bugs.
February IS the FY start month — the specific boundary case.

── How resolve_snapshot_anchors uses time_window ──────────────────────────────
  current_anchor = latest snapshot on or before time_window.END
  prior_anchor   = latest snapshot on or before time_window.START

This means specific_month January 2026 (start=2026-01-01, end=2026-01-31)
produces a WITHIN-JANUARY comparison:
  prior   = latest snapshot on or before 2026-01-01  → 2025-12-29
  current = latest snapshot on or before 2026-01-31  → 2026-01-26

And period=specific with start=2026-01-01, end=null→today produces a
FROM-JANUARY-TO-TODAY comparison:
  prior   = latest snapshot on or before 2026-01-01  → 2025-12-29
  current = latest snapshot on or before today        → 2026-09-21

── Real snapshot data (pinned from Supabase 2026-09-26) ────────────────────────
  2025-12-29: 505 deals / $9,270,118   (prior for January start anchor)
  2026-01-26: 542 deals / $12,183,567  (in-January snapshot, Jan 31 anchor)
  2026-09-21: 479 deals / $28,848,629  (current / today anchor)
  Basis: deals_snapshot point-in-time; deal_status='active'.
"""
import sys
from pathlib import Path
from datetime import datetime as real_datetime, timezone as real_timezone
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).parent.parent))
sys.path.insert(0, str(Path(__file__).parent.parent / "scripts"))

import sdr_utils
from api.time_resolver import resolve_time_window


def _frozen_utc(year, month, day, hour=12, minute=0):
    frozen = real_datetime(year, month, day, hour, minute, tzinfo=real_timezone.utc)

    class _FrozenDatetime(real_datetime):
        @classmethod
        def now(cls, tz=None):
            return frozen if tz else frozen.replace(tzinfo=None)

    return patch.object(sdr_utils, "datetime", _FrozenDatetime)


# ── None-passthrough: end=None (Bug 1) ───────────────────────────────────────

def test_specific_period_end_none_falls_back_to_today():
    """period=specific with end=None: must use today, not pass through None.
    LLM emits 'end': null for 'from January 2026 to today'."""
    with _frozen_utc(2026, 9, 26):
        result = resolve_time_window({"period": "specific", "start": "2026-01-01", "end": None})
    assert result["end"] == "2026-09-26", (
        f"end=None must fall back to today (2026-09-26), got {result['end']!r}"
    )
    assert result["start"] == "2026-01-01"
    print("✓ period=specific end=None falls back to today")


def test_specific_period_end_none_planted_bug():
    """Control: dict.get(key, default) does NOT use the default when key is
    present with value None — this is the mechanism that caused the bug."""
    tw = {"period": "specific", "start": "2026-01-01", "end": None}
    broken = tw.get("end", "2026-09-26")
    assert broken is None, (
        "Planted-bug control: dict.get('end', default) returns None when "
        "key is present with value None — confirms the bug's mechanism"
    )
    print("✓ planted-bug control: dict.get(key, default) silent None passthrough confirmed")


# ── None-passthrough: n=None for last_N_days ─────────────────────────────────

def test_last_n_days_n_none_falls_back_to_30():
    """period=last_N_days with n=None: must default to 30, not crash on
    timedelta(days=None). LLM emits 'n': null when it can't extract n."""
    with _frozen_utc(2026, 9, 26):
        result = resolve_time_window({"period": "last_N_days", "n": None})
    assert result["start"] == "2026-08-27", (
        f"n=None must default to 30 days (start=2026-08-27), got {result['start']}"
    )
    assert result["end"] == "2026-09-26"
    print("✓ period=last_N_days n=None defaults to 30 (no TypeError)")


def test_last_n_days_n_none_planted_bug():
    """Control: dict.get('n', 30) does NOT use 30 when n is present with None."""
    tw = {"period": "last_N_days", "n": None}
    broken = tw.get("n", 30)
    assert broken is None, (
        "Planted-bug control: dict.get('n', 30) returns None when key is "
        "present with value None — would cause timedelta(days=None) TypeError"
    )
    print("✓ planted-bug control: n=None via dict.get confirmed")


# ── None-passthrough: fiscal_quarter=None ────────────────────────────────────

def test_fiscal_quarter_none_does_not_crash():
    """period=fiscal_quarter with fiscal_quarter=None: must not crash on
    None.upper(). LLM may emit 'fiscal_quarter': null."""
    with _frozen_utc(2026, 9, 26):
        result = resolve_time_window({"period": "fiscal_quarter", "fiscal_quarter": None})
    assert result.get("start") is not None, "fiscal_quarter=None must not crash"
    assert result.get("end") is not None
    print("✓ period=fiscal_quarter with fiscal_quarter=None degrades gracefully (no AttributeError)")


# ── None-passthrough: period=None ────────────────────────────────────────────

def test_period_none_falls_back_to_current_quarter():
    """period=None: must fall back to current_quarter, not crash or produce
    None downstream."""
    with _frozen_utc(2026, 9, 26):
        result = resolve_time_window({"period": None})
    assert result.get("start") is not None, "period=None must fall back to current quarter"
    assert result.get("label") is not None
    print("✓ period=None falls back to current_quarter (not None downstream)")


# ── specific_month: core behavior ─────────────────────────────────────────────

def test_specific_month_january_2026():
    """'January 2026' → 2026-01-01..2026-01-31.
    January is the month immediately before GrowthBook's FY start (Feb) —
    the highest-risk month for fiscal→calendar translation bugs."""
    with _frozen_utc(2026, 9, 26):
        result = resolve_time_window({"period": "specific_month", "month": "January", "year": 2026})
    assert result["start"] == "2026-01-01", f"Got {result['start']}"
    assert result["end"] == "2026-01-31", f"Got {result['end']}"
    assert "January 2026" in result["label"]
    print("✓ specific_month January 2026 → 2026-01-01..2026-01-31")


def test_specific_month_february_2026_fy_start_boundary():
    """February is GrowthBook's fiscal year start month (fy_start_month=2).
    A naive FY→calendar translation subtracts one year here; verify it doesn't.
    FY2027 Q1 starts February 2026, so 'February 2026' must NOT become 2025-02-01."""
    with _frozen_utc(2026, 9, 26):
        result = resolve_time_window({"period": "specific_month", "month": "February", "year": 2026})
    assert result["start"] == "2026-02-01", (
        f"February must not shift to 2025-02-01 under FY→calendar logic, got {result['start']}"
    )
    assert result["end"] == "2026-02-28", f"Got {result['end']}"
    print("✓ specific_month February 2026 (FY start month) → 2026-02-01..2026-02-28")


def test_specific_month_december_2025_calendar_year_boundary():
    """December end-of-year: must not overflow to January 2026."""
    with _frozen_utc(2026, 9, 26):
        result = resolve_time_window({"period": "specific_month", "month": "December", "year": 2025})
    assert result["start"] == "2025-12-01", f"Got {result['start']}"
    assert result["end"] == "2025-12-31", f"Got {result['end']}"
    print("✓ specific_month December 2025 → 2025-12-01..2025-12-31 (no overflow)")


def test_specific_month_current_partial_month_clips_to_today():
    """A month that hasn't ended yet: end clips to today, not month-end."""
    with _frozen_utc(2026, 9, 26):
        result = resolve_time_window({"period": "specific_month", "month": "September", "year": 2026})
    assert result["start"] == "2026-09-01", f"Got {result['start']}"
    assert result["end"] == "2026-09-26", (
        f"Partial month must clip end to today (2026-09-26), got {result['end']}"
    )
    print("✓ specific_month current month clips end to today")


def test_specific_month_year_is_literal_not_relative():
    """The year must be the integer passed, never relative to today.
    Planted bug: using today.year instead of tw['year'] gives 2026 for a
    2025 request — confirm the two resolve differently."""
    with _frozen_utc(2026, 9, 26):
        r2025 = resolve_time_window({"period": "specific_month", "month": "January", "year": 2025})
        r2026 = resolve_time_window({"period": "specific_month", "month": "January", "year": 2026})
    assert r2025["start"] == "2025-01-01", (
        f"Year must be literal 2025, not today.year=2026, got {r2025['start']}"
    )
    assert r2026["start"] == "2026-01-01", f"Got {r2026['start']}"
    assert r2025["start"] != r2026["start"]
    print("✓ specific_month year is always the literal year integer, never relative")


def test_specific_month_abbreviated_name():
    """Short month names ('Jan', 'Feb') must also resolve."""
    with _frozen_utc(2026, 9, 26):
        r = resolve_time_window({"period": "specific_month", "month": "Jan", "year": 2026})
    assert r["start"] == "2026-01-01"
    assert r["end"] == "2026-01-31"
    print("✓ specific_month abbreviated 'Jan' resolves correctly")


def test_specific_month_numeric_month():
    """Month as a string integer ('2') must also parse — LLM may emit month
    as a number rather than a name."""
    with _frozen_utc(2026, 9, 26):
        r = resolve_time_window({"period": "specific_month", "month": "2", "year": 2026})
    assert r["start"] == "2026-02-01", f"Got {r['start']}"
    assert r["end"] == "2026-02-28", f"Got {r['end']}"
    print("✓ specific_month numeric month '2' resolves correctly")


# ── Year sanity guard ─────────────────────────────────────────────────────────

def test_year_sanity_guard_rejects_far_past():
    """A year more than 4 years back must produce an explicit NO DATA AVAILABLE
    signal rather than silently passing through to the snapshot lookup."""
    with _frozen_utc(2026, 9, 26):
        result = resolve_time_window({"period": "specific_month", "month": "January", "year": 2021})
    has_error = result.get("_error") or "NO DATA AVAILABLE" in (result.get("label") or "")
    assert has_error, (
        f"Year 5+ years back (2021) must surface NO DATA AVAILABLE, got {result}"
    )
    print("✓ year 2021 (>4 years back from 2026) → explicit NO DATA AVAILABLE")


def test_year_sanity_guard_rejects_far_future():
    """A year more than 1 year ahead must also be flagged — no snapshots exist."""
    with _frozen_utc(2026, 9, 26):
        result = resolve_time_window({"period": "specific_month", "month": "January", "year": 2029})
    has_error = result.get("_error") or "NO DATA AVAILABLE" in (result.get("label") or "")
    assert has_error, (
        f"Year 3+ years ahead (2029) must surface NO DATA AVAILABLE, got {result}"
    )
    print("✓ year 2029 (>1 year ahead of 2026) → explicit NO DATA AVAILABLE")


def test_year_sanity_guard_allows_reasonable_past():
    """3 years back (2023) is within the allowed window — must not be rejected."""
    with _frozen_utc(2026, 9, 26):
        result = resolve_time_window({"period": "specific_month", "month": "January", "year": 2023})
    assert result.get("_error") is None, (
        f"Year 2023 (3 years back) must pass the sanity guard, got {result}"
    )
    assert result["start"] == "2023-01-01"
    print("✓ year 2023 (3 years back) passes the sanity guard")


# ── Real snapshot anchor pins: two query scenarios ────────────────────────────
# Both use the same fake Supabase dates that mirror the real deals_snapshot
# weekly cadence as of 2026-09-26.
#
# Scenario A — within-January comparison (specific_month January 2026):
#   time_window = {start: 2026-01-01, end: 2026-01-31}
#   current_anchor = at or before 2026-01-31  →  2026-01-26  (542 deals / $12,183,567)
#   prior_anchor   = at or before 2026-01-01  →  2025-12-29  (505 deals / $9,270,118)
#
# Scenario B — January-to-today comparison (specific, start=2026-01-01, end=today):
#   time_window = {start: 2026-01-01, end: 2026-09-26}
#   current_anchor = at or before 2026-09-26  →  2026-09-21  (479 deals / $28,848,629)
#   prior_anchor   = at or before 2026-01-01  →  2025-12-29  (505 deals / $9,270,118)
#
# Basis: deals_snapshot; deal_status='active'. Verified via Supabase MCP 2026-09-26.

class _FakeQuery:
    def __init__(self, dates):
        self._dates = dates
        self._cutoff = None
        self._desc = False
        self._limit = None

    def select(self, *_a, **_kw): return self
    def lte(self, _col, cutoff):
        self._cutoff = cutoff
        return self
    def order(self, _col, desc=False):
        self._desc = desc
        return self
    def limit(self, n):
        self._limit = n
        return self
    def execute(self):
        matching = [d for d in self._dates if self._cutoff is None or d <= self._cutoff]
        matching = sorted(matching, reverse=self._desc)
        if self._limit is not None:
            matching = matching[: self._limit]
        class _R: pass
        r = _R()
        r.data = [{"snapshot_date": d} for d in matching]
        return r


class _FakeSupabase:
    def __init__(self, dates):
        self._dates = dates
    def table(self, name):
        assert name == "deals_snapshot"
        return _FakeQuery(list(self._dates))


# Weekly cadence dates mirroring real deals_snapshot around Jan 2026
_JAN2026_DATES = [
    "2025-12-15", "2025-12-22", "2025-12-29",
    "2026-01-05", "2026-01-12", "2026-01-19", "2026-01-26",
    "2026-02-02", "2026-02-09",
    "2026-08-17", "2026-08-24", "2026-08-31",
    "2026-09-07", "2026-09-14", "2026-09-21",
]


def test_specific_month_jan2026_within_january_anchors():
    """Scenario A: specific_month resolves to {start:2026-01-01, end:2026-01-31}.
    resolve_snapshot_anchors must pick:
      current = at or before 2026-01-31 → 2026-01-26
      prior   = at or before 2026-01-01 → 2025-12-29
    These are the actual snapshot dates on which we have real data (see module
    docstring). A prior of 2025-12-15 or earlier is the regressed-year bug;
    a prior of 2026-01-05 or later is an off-by-direction error."""
    from api.router import resolve_snapshot_anchors
    sb = _FakeSupabase(_JAN2026_DATES)
    # This is what specific_month January 2026 produces
    time_window = {"start": "2026-01-01", "end": "2026-01-31"}
    note = resolve_snapshot_anchors(sb, time_window)

    assert "current_snapshot_date=2026-01-26" in note, (
        f"Current anchor (at or before Jan 31) must be 2026-01-26, got: {note}"
    )
    assert "prior_snapshot_date=2025-12-29" in note, (
        f"Prior anchor (at or before Jan 01) must be 2025-12-29, got: {note}"
    )
    # Planted-bug check: the off-by-year regression produced 2025-01-XX anchors
    assert "2025-01" not in note, (
        f"No 2025-01 anchor should appear — that was the regressed year: {note}"
    )
    print(
        "✓ specific_month Jan 2026 anchor: prior=2025-12-29, current=2026-01-26\n"
        "  Real data (Supabase 2026-09-26):\n"
        "    2025-12-29: 505 deals / $9,270,118\n"
        "    2026-01-26: 542 deals / $12,183,567"
    )


def test_specific_with_end_null_jan2026_to_today_anchors():
    """Scenario B: 'compare pipeline from January 2026 to today'.
    period=specific, start=2026-01-01, end=None (LLM omits end).
    After the end=None fix, time_window = {start:2026-01-01, end:today}.
    resolve_snapshot_anchors must pick:
      current = at or before today (2026-09-26) → 2026-09-21
      prior   = at or before 2026-01-01         → 2025-12-29
    This is the primary user-facing comparison the bug was blocking."""
    from api.router import resolve_snapshot_anchors
    sb = _FakeSupabase(_JAN2026_DATES)
    # This is what period=specific, start=2026-01-01, end=None produces after fix
    time_window = {"start": "2026-01-01", "end": "2026-09-26"}
    note = resolve_snapshot_anchors(sb, time_window)

    assert "current_snapshot_date=2026-09-21" in note, (
        f"Current anchor (at or before 2026-09-26) must be 2026-09-21, got: {note}"
    )
    assert "prior_snapshot_date=2025-12-29" in note, (
        f"Prior anchor (at or before 2026-01-01) must be 2025-12-29, got: {note}"
    )
    assert "2025-01" not in note, (
        f"No 2025-01 anchor — that was the regressed year: {note}"
    )
    print(
        "✓ Jan 2026 → today anchor: prior=2025-12-29, current=2026-09-21\n"
        "  Real data (Supabase 2026-09-26):\n"
        "    2025-12-29: 505 deals / $9,270,118  (prior)\n"
        "    2026-09-21: 479 deals / $28,848,629 (current)"
    )


def test_february_2026_fy_start_month_anchors():
    """February is GrowthBook's fiscal year start month (fy_start_month=2).
    Verify that specific_month February 2026 produces start=2026-02-01 (not
    2025-02-01), and that the prior anchor is a January 2026 snapshot, not
    a January 2025 one — the FY→calendar translation must not shift the year."""
    from api.router import resolve_snapshot_anchors
    with _frozen_utc(2026, 9, 26):
        tw = resolve_time_window({"period": "specific_month", "month": "February", "year": 2026})

    assert tw["start"] == "2026-02-01", (
        f"February 2026 start must be 2026-02-01, not shifted by FY logic to {tw['start']}"
    )
    assert tw["end"] == "2026-02-28"

    dates = [
        "2025-12-29", "2026-01-05", "2026-01-12", "2026-01-19", "2026-01-26",
        "2026-02-02", "2026-02-09", "2026-02-16", "2026-02-23",
        "2026-03-02", "2026-09-21",
    ]
    sb = _FakeSupabase(dates)
    note = resolve_snapshot_anchors(sb, tw)

    # prior = at or before 2026-02-01 → 2026-01-26 (January, same year, NOT 2025)
    assert "prior_snapshot_date=2026-01-26" in note, (
        f"February 2026 prior anchor must be in January 2026, not 2025: {note}"
    )
    # current = at or before 2026-02-28 → 2026-02-23
    assert "current_snapshot_date=2026-02-23" in note, (
        f"February 2026 current anchor must be late-February 2026: {note}"
    )
    # Planted-bug check: FY→calendar year subtraction would give 2025 dates
    assert "2025-01" not in note and "2025-02" not in note, (
        f"February 2026 anchors must not regress to 2025: {note}"
    )
    print(
        "✓ February 2026 (FY start month) anchors: prior=2026-01-26, current=2026-02-23\n"
        "  (prior is Jan 2026, not Jan 2025 — FY→calendar year bug does not apply)"
    )


if __name__ == "__main__":
    test_specific_period_end_none_falls_back_to_today()
    test_specific_period_end_none_planted_bug()
    test_last_n_days_n_none_falls_back_to_30()
    test_last_n_days_n_none_planted_bug()
    test_fiscal_quarter_none_does_not_crash()
    test_period_none_falls_back_to_current_quarter()
    test_specific_month_january_2026()
    test_specific_month_february_2026_fy_start_boundary()
    test_specific_month_december_2025_calendar_year_boundary()
    test_specific_month_current_partial_month_clips_to_today()
    test_specific_month_year_is_literal_not_relative()
    test_specific_month_abbreviated_name()
    test_specific_month_numeric_month()
    test_year_sanity_guard_rejects_far_past()
    test_year_sanity_guard_rejects_far_future()
    test_year_sanity_guard_allows_reasonable_past()
    test_specific_month_jan2026_within_january_anchors()
    test_specific_with_end_null_jan2026_to_today_anchors()
    test_february_2026_fy_start_month_anchors()
    print("\n✅ All tests passed")
