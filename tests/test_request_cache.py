#!/usr/bin/env python3
"""
Tests for the two-layer request-scoped caching that eliminates redundant
Supabase reads during a single agent_loop invocation.

Layer 1 (forecast_analyses._request_cache):
    Memoizes _get_complete_quarters, query_stage_close_rate,
    _quarter_window_iso, and query_coverage_proxy_target_by_week so they
    run once per request even when called from multiple code paths
    (assess_pipeline_coverage, _downside_inputs, query_path_to_target,
    historical query_pipeline_coverage).

Layer 2 (agent_loop._primitive_cache):
    Prevents the model from re-running an identical call_primitive
    invocation it already made in the same loop (e.g. query_pipeline_coverage({})
    after query_quarter_downside already returned its coverage output).

Trace shape tested: the live Slack question
    "If we lost our two biggest open deals this quarter, what would
     our pipeline coverage look like, and how does that compare to
     how exposed we were last quarter?"
triggers query_quarter_downside (which internally runs
assess_pipeline_coverage → query_stage_close_rate → _get_complete_quarters)
then a direct query_pipeline_coverage(fiscal_quarter='FY2027 Q2') for
the historical half (which also calls query_stage_close_rate →
_get_complete_quarters).  Without caching, _get_complete_quarters
(24k+ row scan) runs 3 times.  With caching, it runs once.
"""
import json
import sys
from pathlib import Path
from unittest.mock import patch, MagicMock, AsyncMock

REPO = Path(__file__).parent.parent
sys.path.insert(0, str(REPO / "tests"))
sys.path.insert(0, str(REPO))
sys.path.insert(0, str(REPO / "scripts"))
sys.path.insert(0, str(REPO / "scripts" / "analytics"))
sys.path.insert(0, str(REPO / "api"))

import logging
import pytest

@pytest.fixture(autouse=True)
def _silence_loggers():
    prev = logging.root.manager.disable
    logging.disable(logging.CRITICAL)
    yield
    logging.disable(prev)


# ── Layer 1: forecast_analyses request cache ──────────────────────────────

class TestRequestCache:
    """_request_cache memoizes expensive Supabase reads within a request."""

    def test_clear_request_cache_empties_cache(self):
        from forecast_analyses import _request_cache, clear_request_cache
        _request_cache["test_key"] = "value"
        clear_request_cache()
        assert _request_cache == {}

    def test_get_complete_quarters_memoized(self):
        """Second call to _get_complete_quarters returns cached result,
        not a second 24k+ row Supabase scan."""
        from forecast_analyses import (
            _get_complete_quarters, _request_cache, clear_request_cache
        )
        clear_request_cache()

        # Build a fake sb that tracks how many times select_all is called
        call_count = {"n": 0}
        fake_rows = [
            {"fiscal_quarter": "FY2027 Q1", "week_of_quarter": w}
            for w in range(1, 14)
        ] + [
            {"fiscal_quarter": "FY2027 Q2", "week_of_quarter": w}
            for w in range(1, 14)
        ]

        def fake_select_all(sb, table, columns=None, filters=None):
            call_count["n"] += 1
            return fake_rows

        with patch("supabase_client.select_all", fake_select_all):
            sb = MagicMock()
            result1 = _get_complete_quarters(sb)
            result2 = _get_complete_quarters(sb)

        assert call_count["n"] == 1, \
            f"select_all called {call_count['n']} times, expected 1 (cache miss)"
        assert result1 == result2
        assert set(result1) == {"FY2027 Q1", "FY2027 Q2"}

        clear_request_cache()

    def test_query_stage_close_rate_memoized(self):
        """Second call to query_stage_close_rate returns cached result."""
        from forecast_analyses import (
            query_stage_close_rate, _request_cache, clear_request_cache
        )
        clear_request_cache()

        call_count = {"n": 0}
        sentinel = {
            "by_stage_order": {},
            "quarters_analyzed": 0,
            "complete_quarters": [],
            "min_evidence_count": 5,
            "scope": "test",
            "note": "test",
        }

        original_fn = query_stage_close_rate.__wrapped__ if hasattr(
            query_stage_close_rate, '__wrapped__') else None

        # Pre-populate the cache to test the memoization path
        _request_cache["stage_close_rate"] = sentinel
        result = query_stage_close_rate(sb=MagicMock())
        assert result is sentinel, "should return cached result"

        clear_request_cache()

    def test_quarter_window_iso_memoized(self):
        """Second call to _quarter_window_iso for same quarter is cached."""
        from forecast_analyses import (
            _quarter_window_iso, _request_cache, clear_request_cache
        )
        clear_request_cache()

        sb = MagicMock()
        fake_resp = MagicMock()
        fake_resp.data = [{"snapshot_date": "2026-05-15"}]
        sb.table.return_value.select.return_value.eq.return_value.limit.return_value.execute.return_value = fake_resp

        with patch("utils.get_fiscal_quarter") as mock_gfq:
            from datetime import date
            mock_gfq.return_value = (date(2026, 5, 1), date(2026, 7, 31), "FY2027 Q2")

            result1 = _quarter_window_iso(sb, "FY2027 Q2")
            result2 = _quarter_window_iso(sb, "FY2027 Q2")

        assert sb.table.call_count == 1, \
            f"Supabase hit {sb.table.call_count} times, expected 1"
        assert result1 == result2 == ("2026-05-01", "2026-07-31")

        clear_request_cache()

    def test_clear_between_requests_prevents_staleness(self):
        """clear_request_cache between invocations ensures fresh data."""
        from forecast_analyses import _request_cache, clear_request_cache
        _request_cache["complete_quarters"] = ["FY2027 Q1"]
        clear_request_cache()
        assert "complete_quarters" not in _request_cache


# ── Layer 2: agent_loop primitive cache ───────────────────────────────────

class TestPrimitiveCache:
    """_primitive_cache in run_agent_loop prevents duplicate primitive calls."""

    def test_agent_loop_clears_request_cache_on_entry(self):
        """run_agent_loop must call clear_request_cache at the start."""
        import api.agent_loop as al
        src = __import__('inspect').getsource(al.run_agent_loop)
        assert "clear_request_cache" in src, \
            "run_agent_loop must call clear_request_cache()"

    def test_primitive_cache_variable_exists(self):
        """run_agent_loop must initialize _primitive_cache dict."""
        import api.agent_loop as al
        src = __import__('inspect').getsource(al.run_agent_loop)
        assert "_primitive_cache" in src, \
            "run_agent_loop must use _primitive_cache for dedup"

    def test_primitive_cache_checks_before_execute(self):
        """The call_primitive branch must check _primitive_cache before
        calling _execute_call_primitive."""
        import api.agent_loop as al
        src = __import__('inspect').getsource(al.run_agent_loop)
        # The cache check must appear before _execute_call_primitive
        cache_check_pos = src.find("cache_key in _primitive_cache")
        execute_pos = src.find("_execute_call_primitive")
        assert cache_check_pos != -1, "cache lookup missing"
        assert execute_pos != -1, "_execute_call_primitive missing"
        assert cache_check_pos < execute_pos, \
            "cache check must come before _execute_call_primitive call"

    def test_primitive_cache_stores_successful_results(self):
        """Successful primitive results (no 'error' key) must be stored."""
        import api.agent_loop as al
        src = __import__('inspect').getsource(al.run_agent_loop)
        assert '_primitive_cache[cache_key]' in src, \
            "successful results must be stored in _primitive_cache"

    def test_primitive_cache_skips_errors(self):
        """Error results must NOT be cached."""
        import api.agent_loop as al
        src = __import__('inspect').getsource(al.run_agent_loop)
        # The store should be guarded by "error" not in tool_result
        assert '"error" not in tool_result' in src, \
            "cache storage must be guarded by error check"

    def test_cache_key_is_deterministic(self):
        """Cache key must use sort_keys for deterministic JSON."""
        import api.agent_loop as al
        src = __import__('inspect').getsource(al.run_agent_loop)
        assert "sort_keys=True" in src, \
            "cache key must use sort_keys=True for deterministic keying"


# ── Trace-shape test: downside then historical coverage ───────────────────

class TestTraceShapeCaching:
    """Simulates tonight's exact trace: query_quarter_downside (current quarter)
    followed by query_pipeline_coverage(fiscal_quarter='FY2027 Q2') (historical).

    _get_complete_quarters should run ONCE total, not once per
    query_stage_close_rate call."""

    def test_complete_quarters_called_once_across_multiple_close_rate_calls(self):
        """Three calls to query_stage_close_rate (the real trace shape)
        should hit _get_complete_quarters exactly once."""
        from forecast_analyses import (
            query_stage_close_rate, _get_complete_quarters,
            _request_cache, clear_request_cache,
        )
        clear_request_cache()

        gcq_call_count = {"n": 0}
        original_gcq = _get_complete_quarters

        def counting_gcq(sb):
            gcq_call_count["n"] += 1
            # Return a minimal result to avoid deeper Supabase calls
            return ["FY2027 Q1", "FY2027 Q2"]

        # Pre-populate complete_quarters cache to avoid the 24k scan,
        # then track whether query_stage_close_rate re-calls it
        _request_cache["complete_quarters"] = ["FY2027 Q1", "FY2027 Q2"]

        # Also need to mock the per-quarter snapshot reads
        sb = MagicMock()
        fake_resp = MagicMock()
        fake_resp.data = []
        sb.table.return_value.select.return_value.eq.return_value.eq.return_value.order.return_value.execute.return_value = fake_resp

        with patch("forecast_analyses._get_complete_quarters", counting_gcq):
            with patch("forecast_analyses._quarter_window_iso",
                       return_value=("2026-02-01", "2026-04-30")):
                with patch("supabase_client.select_all", return_value=[]):
                    # Call 1: from assess_pipeline_coverage path
                    r1 = query_stage_close_rate(sb)
                    # Call 2: from _downside_inputs path
                    r2 = query_stage_close_rate(sb)
                    # Call 3: from historical query_pipeline_coverage path
                    r3 = query_stage_close_rate(sb)

        assert r1 is r2 is r3, \
            "All three calls should return the exact same cached object"
        # _get_complete_quarters is called exactly once: by the first
        # query_stage_close_rate invocation.  Calls 2 and 3 return the
        # cached stage_close_rate result and never reach _get_complete_quarters.
        assert gcq_call_count["n"] == 1, \
            f"_get_complete_quarters called {gcq_call_count['n']} times; " \
            "expected 1 (first call only, then stage_close_rate is cached)"

        clear_request_cache()

    def test_quarter_window_iso_called_once_per_quarter(self):
        """When multiple query_stage_close_rate paths all need
        _quarter_window_iso('FY2027 Q1'), it should hit Supabase once."""
        from forecast_analyses import (
            _quarter_window_iso, _request_cache, clear_request_cache,
        )
        clear_request_cache()

        sb = MagicMock()
        fake_resp = MagicMock()
        fake_resp.data = [{"snapshot_date": "2026-03-15"}]
        sb.table.return_value.select.return_value.eq.return_value.limit.return_value.execute.return_value = fake_resp

        with patch("utils.get_fiscal_quarter") as mock_gfq:
            from datetime import date
            mock_gfq.return_value = (date(2026, 2, 1), date(2026, 4, 30), "FY2027 Q1")

            # Simulate 3 calls for the same quarter (one per close-rate invocation)
            r1 = _quarter_window_iso(sb, "FY2027 Q1")
            r2 = _quarter_window_iso(sb, "FY2027 Q1")
            r3 = _quarter_window_iso(sb, "FY2027 Q1")

        assert sb.table.call_count == 1, \
            f"Supabase hit {sb.table.call_count} times for same quarter, expected 1"
        assert r1 == r2 == r3

        clear_request_cache()

    def test_different_quarters_cached_independently(self):
        """_quarter_window_iso caches per quarter, not globally."""
        from forecast_analyses import (
            _quarter_window_iso, _request_cache, clear_request_cache,
        )
        clear_request_cache()

        sb = MagicMock()

        def make_resp(snapshot_date):
            r = MagicMock()
            r.data = [{"snapshot_date": snapshot_date}]
            return r

        call_idx = {"i": 0}
        responses = [
            make_resp("2026-03-15"),  # Q1
            make_resp("2026-06-15"),  # Q2
        ]
        quarters_data = [
            (__import__('datetime').date(2026, 2, 1),
             __import__('datetime').date(2026, 4, 30), "FY2027 Q1"),
            (__import__('datetime').date(2026, 5, 1),
             __import__('datetime').date(2026, 7, 31), "FY2027 Q2"),
        ]

        def side_effect_execute():
            idx = call_idx["i"]
            call_idx["i"] += 1
            return responses[idx]

        sb.table.return_value.select.return_value.eq.return_value.limit.return_value.execute = side_effect_execute

        with patch("utils.get_fiscal_quarter") as mock_gfq:
            mock_gfq.side_effect = [quarters_data[0], quarters_data[1]]

            r_q1 = _quarter_window_iso(sb, "FY2027 Q1")
            r_q2 = _quarter_window_iso(sb, "FY2027 Q2")
            # Re-fetch both — should be cached
            r_q1b = _quarter_window_iso(sb, "FY2027 Q1")
            r_q2b = _quarter_window_iso(sb, "FY2027 Q2")

        assert sb.table.call_count == 2, \
            f"Should hit Supabase exactly 2 times (once per quarter), got {sb.table.call_count}"
        assert r_q1 == r_q1b == ("2026-02-01", "2026-04-30")
        assert r_q2 == r_q2b == ("2026-05-01", "2026-07-31")

        clear_request_cache()


# ── Planted-bug controls ─────────────────────────────────────────────────

def test_PLANTED_BUG_request_cache_exists():
    """CONTROL: _request_cache dict must exist in forecast_analyses.
    If someone removes it, memoization silently breaks."""
    import forecast_analyses as fa
    assert hasattr(fa, '_request_cache'), \
        "PLANTED BUG: _request_cache dict removed from forecast_analyses"
    assert isinstance(fa._request_cache, dict), \
        "PLANTED BUG: _request_cache is not a dict"
    print("✓ PLANTED BUG control: _request_cache exists")


def test_PLANTED_BUG_clear_request_cache_exists():
    """CONTROL: clear_request_cache must be importable.
    agent_loop.py depends on it."""
    from forecast_analyses import clear_request_cache
    assert callable(clear_request_cache), \
        "PLANTED BUG: clear_request_cache not callable"
    print("✓ PLANTED BUG control: clear_request_cache importable")


def test_PLANTED_BUG_primitive_cache_in_agent_loop():
    """CONTROL: _primitive_cache must be used in run_agent_loop.
    If removed, duplicate primitives waste budget."""
    import api.agent_loop as al
    src = __import__('inspect').getsource(al.run_agent_loop)
    assert "_primitive_cache" in src, \
        "PLANTED BUG: _primitive_cache removed from run_agent_loop"
    assert "cache_key" in src, \
        "PLANTED BUG: cache_key logic removed from run_agent_loop"
    print("✓ PLANTED BUG control: _primitive_cache in run_agent_loop")


def test_PLANTED_BUG_agent_loop_clears_cache_on_entry():
    """CONTROL: run_agent_loop must clear forecast_analyses cache.
    If removed, stale data leaks across requests."""
    import api.agent_loop as al
    src = __import__('inspect').getsource(al.run_agent_loop)
    assert "clear_request_cache" in src, \
        "PLANTED BUG: clear_request_cache call removed from run_agent_loop"
    print("✓ PLANTED BUG control: run_agent_loop clears request cache")


def test_PLANTED_BUG_coverage_proxy_target_cache_key():
    """CONTROL: query_coverage_proxy_target_by_week must check _request_cache.
    If removed, the 52-call deals_snapshot sweep runs twice per request."""
    import inspect
    from forecast_analyses import query_coverage_proxy_target_by_week
    src = inspect.getsource(query_coverage_proxy_target_by_week)
    assert "coverage_proxy_target_by_week" in src, \
        "PLANTED BUG: cache key removed from query_coverage_proxy_target_by_week"
    assert "_request_cache" in src, \
        "PLANTED BUG: _request_cache lookup removed from query_coverage_proxy_target_by_week"
    print("✓ PLANTED BUG control: coverage_proxy_target_by_week cache key present")


# ── Layer 1 extension: coverage proxy target memoization ────────────────

class TestCoverageProxyTargetCache:
    """query_coverage_proxy_target_by_week reads deals_snapshot 52 times
    (4 quarters × 13 weeks) via _qualified_pipeline_at_week.  Both
    assess_pipeline_coverage and query_path_to_target call it within the
    same agent-loop invocation.  The cache must eliminate the second
    52-call sweep."""

    def test_coverage_proxy_target_memoized(self):
        """Second call returns cached result, zero additional Supabase hits.

        Uses StrictSupabase + the REAL select_all (wrapped only to count
        calls) so the real deal_status/is_incremental_pipeline() filter
        predicates run, same as every other caller of
        actual_incremental_closed_won — not a hand-written select_all
        side_effect keyed on the old 'stage' shape."""
        from forecast_analyses import (
            query_coverage_proxy_target_by_week, _request_cache,
            clear_request_cache,
        )
        import supabase_client as _sc
        from strict_supabase import StrictSupabase
        clear_request_cache()

        snapshot_rows = [
            {"deal_id": f"s_{q}_{w}", "deal_value": 10000.0,
             "pipeline_id": "new_biz", "stage_order": 3,
             "close_date": "2026-03-15", "snapshot_date": "2026-03-15",
             "fiscal_quarter": f"FY2027 Q{q}", "week_of_quarter": w}
            for q in range(1, 5) for w in range(1, 14)
        ]
        # Prior-year 'deals': a normal win plus a reopened deal — deal_status
        # flipped back to "open", `stage` still stale at "closedwon". Must be
        # excluded from prior_year_actual; a regression to the old
        # is_won(stage) filter would count it and double the proxy target.
        deals = [
            {"deal_id": "normal_win", "deal_status": "won", "stage": "closedwon",
             "pipeline_id": "default", "new_arr": 100000, "expansion_arr": 0,
             "close_date": "2025-03-15"},
            {"deal_id": "reopened", "deal_status": "open", "stage": "closedwon",
             "pipeline_id": "default", "new_arr": 999999, "expansion_arr": 0,
             "close_date": "2025-03-10"},
        ]
        sb = StrictSupabase({"deals_snapshot": snapshot_rows, "deals": deals})

        select_all_count = {"n": 0}
        real_select_all = _sc.select_all

        def counting_select_all(sb, table, columns=None, filters=None, page_size=1000):
            select_all_count["n"] += 1
            return real_select_all(sb, table, columns=columns, filters=filters,
                                    page_size=page_size)

        def fake_get_fiscal_quarter(d):
            from datetime import date
            month = d.month
            if 2 <= month <= 4:
                fy = d.year + 1
                return (date(d.year, 2, 1), date(d.year, 4, 30),
                        f"FY{fy} Q1")
            if 5 <= month <= 7:
                fy = d.year + 1
                return (date(d.year, 5, 1), date(d.year, 7, 31),
                        f"FY{fy} Q2")
            if 8 <= month <= 10:
                fy = d.year + 1
                return (date(d.year, 8, 1), date(d.year, 10, 31),
                        f"FY{fy} Q3")
            fy = d.year + 1
            return (date(d.year, 11, 1), date(d.year + 1, 1, 31),
                    f"FY{fy} Q4")

        with patch("supabase_client.select_all", counting_select_all), \
             patch("utils.get_fiscal_quarter", fake_get_fiscal_quarter):
            result1 = query_coverage_proxy_target_by_week(sb)
            count_after_first = select_all_count["n"]

            result2 = query_coverage_proxy_target_by_week(sb)
            count_after_second = select_all_count["n"]

        assert count_after_second == count_after_first, \
            f"Second call added {count_after_second - count_after_first} " \
            "Supabase hits; expected 0 (cached)"
        assert result1 is result2, \
            "Second call should return the exact same cached object"
        assert result1.get('heuristic') is True
        assert 'by_week' in result1
        pt = result1['proxy_targets']['FY2027 Q1']
        assert pt['value'] == 200000, (
            f"Expected proxy target value=200000 (2x prior-year $100k, "
            f"reopened deal excluded), got {pt} — the filter may be reading "
            f"`stage` instead of deal_status again")

        clear_request_cache()

    def test_coverage_proxy_target_pre_populated_cache(self):
        """Pre-populating the cache key returns immediately, no Supabase."""
        from forecast_analyses import (
            query_coverage_proxy_target_by_week, _request_cache,
            clear_request_cache,
        )
        clear_request_cache()

        sentinel = {"by_week": {}, "heuristic": True, "label": "HEURISTIC",
                    "test_sentinel": True}
        _request_cache["coverage_proxy_target_by_week"] = sentinel

        result = query_coverage_proxy_target_by_week(sb=MagicMock())
        assert result is sentinel, "Should return pre-populated cache value"

        clear_request_cache()

    def test_clear_request_cache_clears_coverage_proxy(self):
        """clear_request_cache must also clear the proxy target entry."""
        from forecast_analyses import _request_cache, clear_request_cache
        _request_cache["coverage_proxy_target_by_week"] = {"test": True}
        clear_request_cache()
        assert "coverage_proxy_target_by_week" not in _request_cache


# ── Deep-equality: cache-hit returns identical shape to cache-miss ──────

class TestCacheHitMissDeepEquality:
    """For each cached function, call once (cache miss), call again (cache hit),
    assert the two returns are deeply equal (and same object identity)."""

    def test_get_complete_quarters_deep_equal(self):
        from forecast_analyses import (
            _get_complete_quarters, _request_cache, clear_request_cache
        )
        clear_request_cache()

        fake_rows = [
            {"fiscal_quarter": "FY2027 Q1", "week_of_quarter": w}
            for w in range(1, 14)
        ]

        with patch("supabase_client.select_all", return_value=fake_rows):
            sb = MagicMock()
            miss = _get_complete_quarters(sb)
            hit = _get_complete_quarters(sb)

        assert miss == hit, f"Shape mismatch: miss={miss!r}, hit={hit!r}"
        assert miss is hit, "Cache hit should return the same object"
        clear_request_cache()

    def test_quarter_window_iso_deep_equal(self):
        from forecast_analyses import (
            _quarter_window_iso, _request_cache, clear_request_cache
        )
        clear_request_cache()

        sb = MagicMock()
        fake_resp = MagicMock()
        fake_resp.data = [{"snapshot_date": "2026-05-15"}]
        sb.table.return_value.select.return_value.eq.return_value.limit.return_value.execute.return_value = fake_resp

        with patch("utils.get_fiscal_quarter") as mock_gfq:
            from datetime import date
            mock_gfq.return_value = (date(2026, 5, 1), date(2026, 7, 31), "FY2027 Q2")
            miss = _quarter_window_iso(sb, "FY2027 Q2")
            hit = _quarter_window_iso(sb, "FY2027 Q2")

        assert miss == hit, f"Shape mismatch: miss={miss!r}, hit={hit!r}"
        assert miss is hit, "Cache hit should return the same object"
        clear_request_cache()

    def test_query_stage_close_rate_deep_equal(self):
        from forecast_analyses import (
            query_stage_close_rate, _request_cache, clear_request_cache
        )
        clear_request_cache()

        fake_rows_snapshot = [
            {"deal_id": "d1", "stage_order": 2, "pipeline_id": "new_biz"}
        ]

        def fake_select_all(sb, table, columns=None, filters=None):
            if columns == 'fiscal_quarter,week_of_quarter':
                return [{"fiscal_quarter": "FY2027 Q1", "week_of_quarter": w}
                        for w in range(1, 14)]
            if table == 'deals':
                return [{"deal_id": "d1", "stage": "closedwon",
                         "close_date": "2026-03-15"}]
            return fake_rows_snapshot

        with patch("supabase_client.select_all", fake_select_all), \
             patch("forecast_analyses._quarter_window_iso",
                   return_value=("2026-02-01", "2026-04-30")), \
             patch("field_semantics._RENEWAL_PIPELINE_ID", "renewal_123"), \
             patch("field_semantics.is_won", return_value=True):
            sb = MagicMock()
            miss = query_stage_close_rate(sb)
            hit = query_stage_close_rate(sb)

        assert miss == hit, f"Shape mismatch: miss keys={set(miss)}, hit keys={set(hit)}"
        assert miss is hit, "Cache hit should return the same object"
        clear_request_cache()

    def test_coverage_proxy_target_by_week_deep_equal(self):
        """Uses StrictSupabase so the real deal_status/is_incremental_
        pipeline() filter predicates run (not a hand-written select_all
        side_effect keyed on the old 'stage' shape)."""
        from forecast_analyses import (
            query_coverage_proxy_target_by_week, _request_cache,
            clear_request_cache,
        )
        from strict_supabase import StrictSupabase
        clear_request_cache()

        snapshot_rows = [
            {"deal_id": f"s_{w}", "deal_value": 100000.0,
             "pipeline_id": "new_biz", "stage_order": 3,
             "close_date": "2026-03-15", "snapshot_date": "2026-03-15",
             "fiscal_quarter": "FY2027 Q1", "week_of_quarter": w}
            for w in range(1, 14)
        ]
        # A normal win plus a reopened deal (deal_status flipped back to
        # "open", `stage` still stale at "closedwon") — must be excluded;
        # a regression to the old is_won(stage) filter would count it.
        deals = [
            {"deal_id": "normal_win", "deal_status": "won", "stage": "closedwon",
             "pipeline_id": "default", "new_arr": 100000, "expansion_arr": 0,
             "close_date": "2025-03-15"},
            {"deal_id": "reopened", "deal_status": "open", "stage": "closedwon",
             "pipeline_id": "default", "new_arr": 999999, "expansion_arr": 0,
             "close_date": "2025-03-10"},
        ]
        sb = StrictSupabase({"deals_snapshot": snapshot_rows, "deals": deals})

        def fake_gfq(d):
            from datetime import date
            return (date(d.year, 2, 1), date(d.year, 4, 30), "FY2027 Q1")

        with patch("utils.get_fiscal_quarter", fake_gfq):
            miss = query_coverage_proxy_target_by_week(sb)
            hit = query_coverage_proxy_target_by_week(sb)

        assert miss == hit, f"Shape mismatch: miss keys={set(miss)}, hit keys={set(hit)}"
        assert miss is hit, "Cache hit should return the same object"
        pt = miss['proxy_targets']['FY2027 Q1']
        assert pt['value'] == 200000, (
            f"Expected proxy target value=200000 (2x prior-year $100k, "
            f"reopened deal excluded), got {pt} — the filter may be reading "
            f"`stage` instead of deal_status again")
        clear_request_cache()


# ── Cache-hit logging ──────────────────────────────────────────────────────

class TestCacheHitLogging:
    """Each cached function must emit a [CACHE_HIT] log line on cache hit."""

    def test_get_complete_quarters_logs_cache_hit(self):
        from forecast_analyses import (
            _get_complete_quarters, _request_cache, clear_request_cache
        )
        clear_request_cache()
        _request_cache["complete_quarters"] = ["FY2027 Q1"]

        with patch("forecast_analyses._logger") as mock_logger:
            _get_complete_quarters(MagicMock())
        mock_logger.info.assert_called_once()
        assert "[CACHE_HIT]" in mock_logger.info.call_args[0][0]
        clear_request_cache()

    def test_quarter_window_iso_logs_cache_hit(self):
        from forecast_analyses import (
            _quarter_window_iso, _request_cache, clear_request_cache
        )
        clear_request_cache()
        _request_cache["qw_iso:FY2027 Q1"] = ("2026-02-01", "2026-04-30")

        with patch("forecast_analyses._logger") as mock_logger:
            _quarter_window_iso(MagicMock(), "FY2027 Q1")
        mock_logger.info.assert_called_once()
        assert "[CACHE_HIT]" in mock_logger.info.call_args[0][0]
        clear_request_cache()

    def test_query_stage_close_rate_logs_cache_hit(self):
        from forecast_analyses import (
            query_stage_close_rate, _request_cache, clear_request_cache
        )
        clear_request_cache()
        _request_cache["stage_close_rate"] = {"test": True}

        with patch("forecast_analyses._logger") as mock_logger:
            query_stage_close_rate(MagicMock())
        mock_logger.info.assert_called_once()
        assert "[CACHE_HIT]" in mock_logger.info.call_args[0][0]
        clear_request_cache()

    def test_coverage_proxy_target_logs_cache_hit(self):
        from forecast_analyses import (
            query_coverage_proxy_target_by_week, _request_cache,
            clear_request_cache
        )
        clear_request_cache()
        _request_cache["coverage_proxy_target_by_week"] = {"test": True}

        with patch("forecast_analyses._logger") as mock_logger:
            query_coverage_proxy_target_by_week(MagicMock())
        mock_logger.info.assert_called_once()
        assert "[CACHE_HIT]" in mock_logger.info.call_args[0][0]
        clear_request_cache()


# ── Planted-bug controls for cache-hit logging ─────────────────────────────

def test_PLANTED_BUG_cache_hit_logging_exists():
    """CONTROL: all four cached functions must contain [CACHE_HIT] in source."""
    import inspect
    from forecast_analyses import (
        _get_complete_quarters, _quarter_window_iso,
        query_stage_close_rate, query_coverage_proxy_target_by_week
    )
    for fn in [_get_complete_quarters, _quarter_window_iso,
               query_stage_close_rate, query_coverage_proxy_target_by_week]:
        src = inspect.getsource(fn)
        assert "[CACHE_HIT]" in src, \
            f"PLANTED BUG: [CACHE_HIT] log missing from {fn.__name__}"
    print("✓ PLANTED BUG control: [CACHE_HIT] logging in all four functions")


if __name__ == "__main__":
    # Quick smoke run
    t = TestRequestCache()
    t.test_clear_request_cache_empties_cache()
    t.test_get_complete_quarters_memoized()
    t.test_query_stage_close_rate_memoized()
    t.test_quarter_window_iso_memoized()
    t.test_clear_between_requests_prevents_staleness()

    t2 = TestPrimitiveCache()
    t2.test_agent_loop_clears_request_cache_on_entry()
    t2.test_primitive_cache_variable_exists()
    t2.test_primitive_cache_checks_before_execute()
    t2.test_primitive_cache_stores_successful_results()
    t2.test_primitive_cache_skips_errors()
    t2.test_cache_key_is_deterministic()

    t3 = TestTraceShapeCaching()
    t3.test_complete_quarters_called_once_across_multiple_close_rate_calls()
    t3.test_quarter_window_iso_called_once_per_quarter()
    t3.test_different_quarters_cached_independently()

    test_PLANTED_BUG_request_cache_exists()
    test_PLANTED_BUG_clear_request_cache_exists()
    test_PLANTED_BUG_primitive_cache_in_agent_loop()
    test_PLANTED_BUG_agent_loop_clears_cache_on_entry()
    test_PLANTED_BUG_coverage_proxy_target_cache_key()

    t4 = TestCoverageProxyTargetCache()
    t4.test_coverage_proxy_target_memoized()
    t4.test_coverage_proxy_target_pre_populated_cache()
    t4.test_clear_request_cache_clears_coverage_proxy()

    t5 = TestCacheHitMissDeepEquality()
    t5.test_get_complete_quarters_deep_equal()
    t5.test_quarter_window_iso_deep_equal()
    t5.test_query_stage_close_rate_deep_equal()
    t5.test_coverage_proxy_target_by_week_deep_equal()

    t6 = TestCacheHitLogging()
    t6.test_get_complete_quarters_logs_cache_hit()
    t6.test_quarter_window_iso_logs_cache_hit()
    t6.test_query_stage_close_rate_logs_cache_hit()
    t6.test_coverage_proxy_target_logs_cache_hit()

    test_PLANTED_BUG_cache_hit_logging_exists()
    print("\n✅ All request cache tests passed")
