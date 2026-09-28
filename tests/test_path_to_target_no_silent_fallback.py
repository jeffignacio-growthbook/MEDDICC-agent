"""
query_path_to_target — guards against silent days_remaining=30 fallback
and correct target-basis (quota-only, not quota+stretch).

Planted-bug controls
--------------------
test_quarter_end_date_failure_returns_error:
  If quarter_end_date raises (e.g. bad fiscal config), the handler MUST
  return an error dict. The bug form would silently swallow the exception
  and use days_remaining=30, producing a plausible-looking but wrong answer.

test_gap_basis_is_quota_only:
  gap_bare must be computed as quota - qtd_closed_won.
  The bug form used weighted_pipeline vs (quota+stretch), which inflates
  the gap by stretch and double-counts existing pipeline.

test_qtd_closed_won_is_disclosed:
  The result must include "qtd_closed_won" and "target_basis" so the
  caller can audit the gap without re-querying.
"""
import asyncio
import sys
from datetime import date
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

sys.path.insert(0, str(Path(__file__).parent.parent))
sys.path.insert(0, str(Path(__file__).parent.parent / "scripts"))

_Q_START = date(2026, 11, 1)
_Q_END = date(2027, 1, 31)
_TODAY = date(2026, 9, 28)
_FAKE_GET_FQ = (_Q_START, _Q_END, "FY2027 Q4")


def _make_cov(quota=1_550_000.0, stretch=2_100_000.0,
              weighted=713_000.0, raw=1_200_000.0):
    goal = (quota + stretch) if (quota is not None and stretch is not None) else None
    gap_amount = max(0.0, (goal or 0.0) - weighted) if goal else 0.0
    return {
        "status": "ok",
        "fiscal_quarter": "FY2027 Q4",
        "current_week": 8,
        "scope": "test",
        "qualified_pipeline": {"raw_value": raw, "deal_count": 5},
        "stage_weighting": {
            "weighted_value": weighted,
            "weighted_deal_count": 4,
            "unweighted_value": 0.0,
            "unweighted_deal_count": 0,
            "by_stage_order": {},
        },
        "real_target": {
            "quota": quota,
            "stretch": stretch,
            "goal": goal,
            "stretch_note": None,
            "note": "test",
        },
        "gap_to_goal": {
            "raw_pipeline_vs_goal": {"status": "short",
                                     "amount": max(0.0, (goal or 0.0) - raw)},
            "weighted_pipeline_vs_goal": {"status": "short", "amount": gap_amount},
        },
        "historical_heuristic_curve": {},
        "note": "test",
    }


def _make_feasibility(days=33):
    return {
        "days_remaining": days,
        "feasible_fraction": 0.4,
        "n_cycles": 10,
        "avg_cycle_days": 45.0,
        "median_cycle_days": 40,
        "near_zero_threshold": 0.05,
        "net_new_viable": True,
    }


def _run(coro):
    return asyncio.get_event_loop().run_until_complete(coro)


def _import_handler():
    from api.handlers import query_path_to_target
    return query_path_to_target


# ---------------------------------------------------------------------------
# Shared patch context — avoids repeating the same 8 patches in every test.
# Each test adds its own overrides on top.
# ---------------------------------------------------------------------------
_BASE_PATCHES = [
    ("pipeline_coverage.assess_pipeline_coverage", None),       # per-test override
    ("api.time_resolver.current_quarter_label", "Q4_FY2027"),
    ("api.time_resolver.quarter_end_date", _Q_END),             # per-test override
    ("api.time_resolver._client_config", {"fiscal": {"fy_start_month": 2}}),
    ("api.time_resolver._today", _TODAY),
    ("utils.get_fiscal_quarter", _FAKE_GET_FQ),
    ("field_semantics.is_incremental_pipeline", True),
    ("api.incremental_arr.incremental_arr", 0.0),
    ("api.handlers.select_all", []),                            # per-test override
    ("path_to_target.time_feasibility", None),                  # per-test override
    ("path_to_target.path_to_target", None),                    # per-test override
]


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------

def test_quarter_end_date_failure_returns_error():
    """When quarter_end_date raises, handler must return an error dict — NOT
    silently fall back to days_remaining=30."""
    handler = _import_handler()
    sb = MagicMock()
    fake_cov = _make_cov()

    def _fake_ptt(gap, scenarios, feasibility, **kwargs):
        return {"gap_bare": gap, "feasibility": feasibility, "headline": "test"}

    with (
        patch("pipeline_coverage.assess_pipeline_coverage", return_value=fake_cov),
        patch("api.time_resolver.current_quarter_label", return_value="Q4_FY2027"),
        patch("api.time_resolver.quarter_end_date",
              side_effect=ValueError("bad fiscal config")),
        patch("api.time_resolver._client_config",
              return_value={"fiscal": {"fy_start_month": 2}}),
        patch("api.time_resolver._today", return_value=_TODAY),
        patch("utils.get_fiscal_quarter", return_value=_FAKE_GET_FQ),
        patch("path_to_target.time_feasibility", return_value=_make_feasibility()),
        patch("path_to_target.path_to_target", side_effect=_fake_ptt),
        patch("api.handlers.select_all", return_value=[]),
    ):
        result = _run(handler({}, sb))

    assert result.get("status") == "error", (
        f"Expected error dict when quarter_end_date raises, got: {result}\n"
        "Planted bug: silent 'days_remaining = 30' fallback is present — remove it."
    )
    assert "error" in result, f"Result missing 'error' key: {result}"
    assert result.get("days_remaining") != 30, (
        "Handler returned days_remaining=30 instead of an error — "
        "the silent fallback has been reintroduced."
    )


def test_gap_basis_is_quota_only():
    """gap_bare must be quota - qtd_closed_won, NOT quota+stretch - weighted_pipeline.

    Planted bug: gap_bare = weighted_pipeline_vs_goal.amount
    = quota + stretch - weighted = 3_650_000 - 713_000 = 2_937_000.
    Correct: gap_bare = quota - qtd_closed_won = 1_550_000 - 373_400 = 1_176_600."""
    handler = _import_handler()
    sb = MagicMock()

    quota = 1_550_000.0
    qtd_won_arr = 373_400.0
    expected_gap = quota - qtd_won_arr  # 1_176_600.0

    fake_cov = _make_cov(quota=quota, stretch=2_100_000.0, weighted=713_000.0)
    captured = {}

    def _capture_ptt(gap, scenarios, feasibility, **kwargs):
        captured["gap_bare"] = gap
        return {"gap_bare": gap, "feasibility": feasibility, "headline": "test",
                "qtd_closed_won": None, "target_basis": None, "target_used": None,
                "stretch_target": None, "days_remaining": None, "fiscal_quarter": None,
                "qtd_won_deal_count": None}

    fake_won_deal = {
        "deal_id": "d1", "close_date": "2026-09-01",
        "deal_status": "won", "pipeline_id": "default",
        "new_arr": qtd_won_arr, "expansion_arr": 0,
    }

    def _fake_select_all(supabase, table, columns="*", filters=None, **kwargs):
        # QTD won query: filters include gte close_date
        if table == "deals" and filters and any(
            f[0] == "gte" and f[1] == "close_date" for f in (filters or [])
        ):
            return [fake_won_deal]
        return []

    with (
        patch("pipeline_coverage.assess_pipeline_coverage", return_value=fake_cov),
        patch("api.time_resolver.current_quarter_label", return_value="Q4_FY2027"),
        patch("api.time_resolver.quarter_end_date", return_value=_Q_END),
        patch("api.time_resolver._client_config",
              return_value={"fiscal": {"fy_start_month": 2}}),
        patch("api.time_resolver._today", return_value=_TODAY),
        patch("utils.get_fiscal_quarter", return_value=_FAKE_GET_FQ),
        patch("field_semantics.is_incremental_pipeline", return_value=True),
        patch("api.incremental_arr.incremental_arr", return_value=qtd_won_arr),
        patch("api.handlers.select_all", side_effect=_fake_select_all),
        patch("path_to_target.time_feasibility", return_value=_make_feasibility()),
        patch("path_to_target.path_to_target", side_effect=_capture_ptt),
    ):
        result = _run(handler({}, sb))

    if result.get("status") == "error":
        pytest.fail(f"Handler returned error unexpectedly: {result}")

    gap = captured.get("gap_bare")
    assert gap is not None, "path_to_target was never called — handler short-circuited"
    assert abs(gap - expected_gap) < 1.0, (
        f"gap_bare={gap:,.0f} but expected {expected_gap:,.0f} "
        f"(quota={quota:,.0f} minus qtd_won={qtd_won_arr:,.0f}).\n"
        "Planted bug: gap uses quota+stretch (not quota-only) or "
        "QTD closed-won is not subtracted."
    )


def test_qtd_closed_won_is_disclosed():
    """Result must include 'qtd_closed_won', 'target_basis', and 'days_remaining'.

    Without these, the gap cannot be audited externally."""
    handler = _import_handler()
    sb = MagicMock()
    fake_cov = _make_cov()

    def _fake_ptt(gap, scenarios, feasibility, **kwargs):
        return {"gap_bare": gap, "feasibility": feasibility, "headline": "test"}

    with (
        patch("pipeline_coverage.assess_pipeline_coverage", return_value=fake_cov),
        patch("api.time_resolver.current_quarter_label", return_value="Q4_FY2027"),
        patch("api.time_resolver.quarter_end_date", return_value=_Q_END),
        patch("api.time_resolver._client_config",
              return_value={"fiscal": {"fy_start_month": 2}}),
        patch("api.time_resolver._today", return_value=_TODAY),
        patch("utils.get_fiscal_quarter", return_value=_FAKE_GET_FQ),
        patch("field_semantics.is_incremental_pipeline", return_value=True),
        patch("api.incremental_arr.incremental_arr", return_value=0.0),
        patch("api.handlers.select_all", return_value=[]),
        patch("path_to_target.time_feasibility", return_value=_make_feasibility()),
        patch("path_to_target.path_to_target", side_effect=_fake_ptt),
    ):
        result = _run(handler({}, sb))

    if result.get("status") == "error":
        pytest.fail(f"Handler returned error unexpectedly: {result}")

    for key in ("qtd_closed_won", "target_basis", "days_remaining"):
        assert key in result, (
            f"'{key}' missing from result — gap is not auditable. Got keys: {list(result)}"
        )


if __name__ == "__main__":
    test_quarter_end_date_failure_returns_error()
    print("PASS: quarter_end_date failure returns error (not silent days_remaining=30)")

    test_gap_basis_is_quota_only()
    print("PASS: gap_bare is quota - qtd_closed_won (not quota+stretch - weighted)")

    test_qtd_closed_won_is_disclosed()
    print("PASS: qtd_closed_won and target_basis are disclosed in result")
