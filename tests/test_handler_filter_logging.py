"""
2026-09-11, fix #3 of the same night's batch: query_pipeline_movement's
zero-row mystery took hours to even start diagnosing because nobody had
the actual outgoing filter clause to compare against known-good data —
the fix there was a single unconditional INFO-level log line right
before the Supabase call. An audit of every OTHER dedicated handler in
api/handlers.py that builds its own direct Supabase filters (the same
category of risk: NOT routed through dynamic_query_loop, own
eq/neq/ilike filter construction, often using values a model extracted
from free text) found none of them had that same defensive logging.

This pins that every audited handler now logs its fully-constructed
filter clause, unconditionally, before the relevant Supabase call —
so the NEXT unexplained zero-row incident on any of these handlers
starts with a byte-exact query to compare against the database,
instead of another multi-hour blind investigation.

Handlers covered (ranked by the audit's risk assessment, highest
first): query_pipeline, query_call_quality, query_sdr_metrics (two
call sites), query_sdr_pipeline_sourced, query_stale_deals,
query_rep_pipeline, query_deal_health, query_team_leaderboard,
query_coverage. query_pipeline_movement itself was fixed and tested
earlier the same night (tests/test_pipeline_movement_fiscal_quarter_
filter_bug.py) and query_rep_attainment already had this kind of
logging before tonight — neither is re-tested here.
"""
import asyncio
import logging
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))
sys.path.insert(0, str(Path(__file__).parent.parent / "scripts"))

import api.handlers as handlers_module


class _ListLogHandler(logging.Handler):
    def __init__(self):
        super().__init__()
        self.records = []

    def emit(self, record):
        self.records.append(self.format(record))


def _run_and_capture(coro_fn, *args, **kwargs):
    """Runs an async handler with a list-capturing log handler attached
    to api.handlers's logger, returning (result_or_exception, log_lines)."""
    handler = _ListLogHandler()
    logger = logging.getLogger("api.handlers")
    logger.addHandler(handler)
    logger.setLevel(logging.INFO)
    result, error = None, None
    try:
        result = asyncio.run(coro_fn(*args, **kwargs))
    except Exception as e:
        error = e
    finally:
        logger.removeHandler(handler)
    return result, error, handler.records


class _FakeSupabase:
    pass


def _empty_select_all(sb, table, columns=None, filters=None):
    return []


def _check_tag_fires(name, coro, params, tag):
    orig = handlers_module.select_all
    handlers_module.select_all = _empty_select_all
    try:
        result, error, records = _run_and_capture(coro, params, _FakeSupabase())
    finally:
        handlers_module.select_all = orig

    matches = [r for r in records if tag in r]
    assert matches, (
        f"{name}: expected a log line containing {tag!r} — got records: "
        f"{records!r} (handler raised: {error!r})" if error else
        f"{name}: expected a log line containing {tag!r} — got records: {records!r}"
    )
    print(f"✓ {name} logs its filter clause via {tag}")


def test_query_pipeline_logs_filter():
    _check_tag_fires(
        "query_pipeline", handlers_module.query_pipeline,
        {"owner_email": "christian@growthbook.io"},
        "[QUERY_PIPELINE_FILTER]",
    )


def test_query_call_quality_team_mode_logs_filter():
    _check_tag_fires(
        "query_call_quality (team/rep mode)", handlers_module.query_call_quality,
        {"owner_email": "christian@growthbook.io", "time_window": {}},
        "[QUERY_CALL_QUALITY_FILTER]",
    )


def test_query_sdr_metrics_logs_filter():
    _check_tag_fires(
        "query_sdr_metrics", handlers_module.query_sdr_metrics,
        {"sdr_email": "jake.stangl@growthbook.io",
         "time_window": {"start": "2026-08-01", "end": "2026-09-08", "label": "this period"}},
        "[QUERY_SDR_METRICS_FILTER]",
    )


def test_query_sdr_pipeline_sourced_logs_filter():
    _check_tag_fires(
        "query_sdr_pipeline_sourced", handlers_module.query_sdr_pipeline_sourced,
        {"sdr_email": "jake.stangl@growthbook.io",
         "time_window": {"start": "2026-08-01", "end": "2026-09-08", "label": "this period"}},
        "[QUERY_SDR_PIPELINE_SOURCED_FILTER]",
    )


def test_query_stale_deals_logs_filter():
    _check_tag_fires(
        "query_stale_deals", handlers_module.query_stale_deals,
        {"owner_email": "christian@growthbook.io"},
        "[QUERY_STALE_DEALS_FILTER]",
    )


def test_query_rep_pipeline_logs_filter():
    _check_tag_fires(
        "query_rep_pipeline", handlers_module.query_rep_pipeline,
        {"owner_email": "christian@growthbook.io"},
        "[QUERY_REP_PIPELINE_FILTER]",
    )


def test_query_deal_health_logs_filter():
    """query_deal_health's owner_email filter is applied on its SECOND
    select_all call (against 'deals', joining deal_ids found from the
    first 'analyses' query) — an empty first-query stub short-circuits
    before ever reaching it, so this needs a fixture that returns at
    least one analysis row to exercise the code path being tested."""
    def fake_select_all(sb, table, columns=None, filters=None):
        if table == "analyses":
            return [{"deal_id": "123", "overall_score": 3}]
        return []

    orig = handlers_module.select_all
    handlers_module.select_all = fake_select_all
    try:
        _, error, records = _run_and_capture(
            handlers_module.query_deal_health,
            {"owner_email": "christian@growthbook.io"}, _FakeSupabase())
    finally:
        handlers_module.select_all = orig

    matches = [r for r in records if "[QUERY_DEAL_HEALTH_FILTER]" in r]
    assert matches, (
        f"query_deal_health: expected the filter log line — got records: "
        f"{records!r} (handler raised: {error!r})"
    )
    print("✓ query_deal_health logs its filter clause via [QUERY_DEAL_HEALTH_FILTER]")


def test_query_team_leaderboard_logs_filter():
    _check_tag_fires(
        "query_team_leaderboard", handlers_module.query_team_leaderboard,
        {"time_window": {"start": "2026-08-01", "end": "2026-09-08", "label": "this period"}},
        "[QUERY_TEAM_LEADERBOARD_FILTER]",
    )


def test_query_coverage_logs_filter():
    _check_tag_fires(
        "query_coverage", handlers_module.query_coverage,
        {"time_window": {"start": "2026-08-01", "end": "2026-09-08", "label": "this period"}},
        "[QUERY_COVERAGE_FILTER]",
    )


def test_filters_are_exact_and_byte_visible_not_summarized():
    """Spot-check: the logged filter for a case-sensitive email must
    show the value verbatim (via !r), not a summarized/truncated form —
    this is the entire point of the fix."""
    orig = handlers_module.select_all
    handlers_module.select_all = _empty_select_all
    try:
        _, _, records = _run_and_capture(
            handlers_module.query_pipeline, {"owner_email": "Christian@GrowthBook.io"},
            _FakeSupabase())
    finally:
        handlers_module.select_all = orig

    line = next(r for r in records if "[QUERY_PIPELINE_FILTER]" in r)
    assert "'Christian@GrowthBook.io'" in line, (
        f"expected the exact-case email to appear verbatim in the log — got: {line!r}"
    )
    print("✓ logged filters preserve exact case/values, nothing summarized away")


if __name__ == "__main__":
    tests = [
        test_query_pipeline_logs_filter,
        test_query_call_quality_team_mode_logs_filter,
        test_query_sdr_metrics_logs_filter,
        test_query_sdr_pipeline_sourced_logs_filter,
        test_query_stale_deals_logs_filter,
        test_query_rep_pipeline_logs_filter,
        test_query_deal_health_logs_filter,
        test_query_team_leaderboard_logs_filter,
        test_query_coverage_logs_filter,
        test_filters_are_exact_and_byte_visible_not_summarized,
    ]
    failed = 0
    for t in tests:
        try:
            t()
        except AssertionError as e:
            failed += 1
            print(f"✗ {t.__name__}: {e}")
    if failed:
        print(f"\n{failed}/{len(tests)} tests FAILED")
        sys.exit(1)
    print(f"\n✅ All {len(tests)} tests passed")
