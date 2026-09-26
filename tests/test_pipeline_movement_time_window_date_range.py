"""
2026-09-26: query_pipeline_movement always filtered on fiscal_quarter,
even when the classifier emitted an explicit time_window with start/end.

Live failure: "compare our pipeline from January 2026 to today"
  Classifier emitted: time_window={"period":"custom","start":"2026-01-01",
                                   "end":"2026-01-31"}
  Handler ran:        filters=[('eq','fiscal_quarter','FY2027 Q3'),...]
  Answer returned:    current-quarter (Aug 19 – Sep 21) data, not Jan 2026

Root cause: fiscal_quarter defaults to _pm_current_quarter_label() when
not present in params, and the DB filter used fiscal_quarter equality —
a date-range proxy that silently overrides any explicit time_window dates.
The time_window.start/end were only used to compute requested_days for
snapshot-anchor selection, AFTER the rows were already filtered to the
wrong quarter.

Fix: when time_window has both start and end, use snapshot_date gte/lte
filters instead of fiscal_quarter eq, so the user's explicit date range
is respected regardless of which fiscal quarter(s) it spans.
"""
import asyncio
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))
sys.path.insert(0, str(Path(__file__).parent.parent / "scripts"))

import api.handlers as handlers_module
from api.handlers import query_pipeline_movement

# A single Jan 2026 snapshot row (FY2027 Q1, not the current Q3)
JAN_2026_ROW = {
    "deal_id": "900000001",
    "snapshot_date": "2026-01-15",
    "pipeline_id": "default",
    "stage_id": "79653122",
    "stage_order": 3,
    "close_date": "2026-03-31",
    "owner_email": "rep@growthbook.io",
    "snapshot_source": "prospective",
    "backfill_confidence": "exact",
    "week_of_quarter": 3,
    "fiscal_quarter": "FY2027 Q1",
    "company_name": "Acme Corp",
}

# A Q3 2026 snapshot row (current quarter)
Q3_ROW = {
    "deal_id": "900000002",
    "snapshot_date": "2026-09-08",
    "pipeline_id": "default",
    "stage_id": "79653122",
    "stage_order": 3,
    "close_date": "2026-11-15",
    "owner_email": "rep@growthbook.io",
    "snapshot_source": "prospective",
    "backfill_confidence": "exact",
    "week_of_quarter": 6,
    "fiscal_quarter": "FY2027 Q3",
    "company_name": "Beta Corp",
}

ALL_ROWS = [JAN_2026_ROW, Q3_ROW]


class _FakeSupabase:
    pass


def _make_select_all(rows_by_date_filter=None, captured=None):
    """Returns a select_all stub that filters rows by snapshot_date gte/lte
    if those filters are present, mimicking Supabase server-side filtering."""
    def _select_all(sb, table, columns=None, filters=None):
        if captured is not None:
            captured.append({"table": table, "filters": list(filters or [])})
        if table != "deals_snapshot":
            return []
        rows = list(ALL_ROWS)
        for f in (filters or []):
            op, col, val = f[0], f[1], f[2]
            if col == "snapshot_date":
                if op == "gte":
                    rows = [r for r in rows if r["snapshot_date"] >= val]
                elif op == "lte":
                    rows = [r for r in rows if r["snapshot_date"] <= val]
            elif col == "fiscal_quarter" and op == "eq":
                rows = [r for r in rows if r["fiscal_quarter"] == val]
            elif col == "pipeline_id":
                if op == "eq":
                    rows = [r for r in rows if r["pipeline_id"] == val]
                elif op == "neq":
                    rows = [r for r in rows if r["pipeline_id"] != val]
        return rows
    return _select_all


def test_explicit_time_window_uses_snapshot_date_filter_not_fiscal_quarter():
    """When time_window has start+end, the DB filter must use snapshot_date
    gte/lte — NOT ('eq','fiscal_quarter', <current quarter>)."""
    captured = []
    orig = handlers_module.select_all
    handlers_module.select_all = _make_select_all(captured=captured)
    try:
        result = asyncio.run(query_pipeline_movement(
            {
                "view": "composition",
                "time_window": {
                    "start": "2026-01-01",
                    "end": "2026-01-31",
                    "label": "January 2026",
                },
            },
            _FakeSupabase(),
        ))
    finally:
        handlers_module.select_all = orig

    snap_calls = [c for c in captured if c["table"] == "deals_snapshot"]
    assert snap_calls, "expected a deals_snapshot query"
    filters = snap_calls[0]["filters"]

    ops = [(f[0], f[1]) for f in filters]
    # Must have snapshot_date range filters
    assert ("gte", "snapshot_date") in ops, (
        f"expected (gte, snapshot_date) in filters; got {filters}"
    )
    assert ("lte", "snapshot_date") in ops, (
        f"expected (lte, snapshot_date) in filters; got {filters}"
    )
    # Must NOT filter on fiscal_quarter (that would lock to the wrong quarter)
    assert not any(f[1] == "fiscal_quarter" and f[0] == "eq" for f in filters), (
        f"found unexpected fiscal_quarter eq filter; got {filters}"
    )


def test_explicit_time_window_returns_jan_rows_not_q3_rows():
    """The query must return Jan 2026 rows when time_window is Jan 2026,
    not Sep 2026 rows from the current quarter."""
    orig = handlers_module.select_all
    handlers_module.select_all = _make_select_all()
    try:
        result = asyncio.run(query_pipeline_movement(
            {
                "view": "composition",
                "time_window": {
                    "start": "2026-01-01",
                    "end": "2026-01-31",
                    "label": "January 2026",
                },
            },
            _FakeSupabase(),
        ))
    finally:
        handlers_module.select_all = orig

    # The handler should have loaded the Jan row and built a composition from it
    # (the view='composition' path; if it returns data, the snapshot must be Jan)
    snap_dates = result.get("snapshot_dates", [])
    if snap_dates:
        for d in snap_dates:
            assert d.startswith("2026-01"), (
                f"expected Jan 2026 snapshot date, got {d!r}; "
                f"full result: {result}"
            )
    # If no rows (empty result), that's also acceptable — what's NOT acceptable
    # is returning Q3 snapshot dates
    assert not any(
        (d or "").startswith("2026-09") for d in snap_dates
    ), f"Q3 snapshot dates found when Jan 2026 was requested: {snap_dates}"


def test_no_time_window_still_uses_fiscal_quarter_filter():
    """Without an explicit time_window (no start+end), the handler must
    still use fiscal_quarter equality filter — existing behavior preserved."""
    captured = []
    orig = handlers_module.select_all
    handlers_module.select_all = _make_select_all(captured=captured)
    try:
        result = asyncio.run(query_pipeline_movement(
            {
                "view": "composition",
                "fiscal_quarter": "FY2027 Q3",
            },
            _FakeSupabase(),
        ))
    finally:
        handlers_module.select_all = orig

    snap_calls = [c for c in captured if c["table"] == "deals_snapshot"]
    assert snap_calls, "expected a deals_snapshot query"
    filters = snap_calls[0]["filters"]

    assert any(f[1] == "fiscal_quarter" and f[0] == "eq" for f in filters), (
        f"expected fiscal_quarter eq filter when no time_window; got {filters}"
    )
    assert not any(f[1] == "snapshot_date" for f in filters), (
        f"unexpected snapshot_date filter when fiscal_quarter was explicit; got {filters}"
    )


def test_time_window_label_used_as_display_quarter():
    """When time_window has a label, the handler must use it as the display
    fiscal_quarter in the response instead of the default current-quarter label."""
    orig = handlers_module.select_all
    handlers_module.select_all = _make_select_all()
    try:
        result = asyncio.run(query_pipeline_movement(
            {
                "view": "composition",
                "time_window": {
                    "start": "2026-01-01",
                    "end": "2026-01-31",
                    "label": "January 2026",
                },
            },
            _FakeSupabase(),
        ))
    finally:
        handlers_module.select_all = orig

    fq = result.get("fiscal_quarter", "")
    assert fq == "January 2026", (
        f"expected display fiscal_quarter='January 2026', got {fq!r}"
    )


if __name__ == "__main__":
    test_explicit_time_window_uses_snapshot_date_filter_not_fiscal_quarter()
    print("PASS: explicit time_window uses snapshot_date filter not fiscal_quarter")
    test_explicit_time_window_returns_jan_rows_not_q3_rows()
    print("PASS: explicit time_window returns Jan 2026 rows not Q3 rows")
    test_no_time_window_still_uses_fiscal_quarter_filter()
    print("PASS: no time_window still uses fiscal_quarter filter (regression)")
    test_time_window_label_used_as_display_quarter()
    print("PASS: time_window label used as display fiscal_quarter")
    print("\nAll tests passed.")
