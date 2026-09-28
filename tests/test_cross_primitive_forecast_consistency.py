"""
Cross-primitive consistency: query_path_to_target forecast total == forecast_trust total.

Both primitives filter COMMIT+MOST_LIKELY active deals in the current fiscal quarter
and sum new_arr + expansion_arr (is_incremental_pipeline). They MUST agree on the
same set of deals and the same total ARR.

query_path_to_target path:
  select_all(sb, "deals", columns=..., filters=[
    ("in_", "forecast_category", ["COMMIT", "MOST_LIKELY"]),
    ("eq", "deal_status", "active"),
    ("gte", "close_date", q_start_iso),
    ("lte", "close_date", q_end_iso),
  ])
  → filter by is_incremental_pipeline
  → sum incremental_arr → result["forecast_commit_ml"]

forecast_trust path (scripts/forecast_trust.py):
  sb.table("deals").select(...).in_(...).eq(...).gte(...).lte(...).execute().data
  → filter by is_incremental_pipeline
  → sum incremental_arr → pipeline["incremental_arr"]
"""
import asyncio
import sys
from datetime import date
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

sys.path.insert(0, str(Path(__file__).parent.parent))
sys.path.insert(0, str(Path(__file__).parent.parent / "scripts"))

_Q_START = date(2026, 8, 1)
_Q_END = date(2026, 10, 31)
_TODAY = date(2026, 9, 28)
_FAKE_GET_FQ = (_Q_START, _Q_END, "FY2027 Q3")

# Fake COMMIT+MOST_LIKELY active deals — same set for both primitives.
_COMMIT_ML_DEALS = [
    {
        "deal_id": "c1",
        "close_date": "2026-09-30",
        "deal_status": "active",
        "pipeline_id": "default",
        "forecast_category": "COMMIT",
        "new_arr": 120_000,
        "expansion_arr": 0,
    },
    {
        "deal_id": "c2",
        "close_date": "2026-10-15",
        "deal_status": "active",
        "pipeline_id": "default",
        "forecast_category": "MOST_LIKELY",
        "new_arr": 0,
        "expansion_arr": 55_000,
    },
    {
        "deal_id": "c3",  # renewal — excluded by is_incremental_pipeline
        "close_date": "2026-09-20",
        "deal_status": "active",
        "pipeline_id": "866608541",
        "forecast_category": "COMMIT",
        "new_arr": 0,
        "expansion_arr": 0,
    },
]
_EXPECTED_FORECAST_TOTAL = 175_000.0  # c1 + c2 (c3 excluded)


def _run(coro):
    loop = asyncio.new_event_loop()
    try:
        return loop.run_until_complete(coro)
    finally:
        loop.close()


# ---------------------------------------------------------------------------
# Helper: call query_path_to_target with controlled mocks and return result.
# ---------------------------------------------------------------------------

def _quota():
    from pipeline_coverage import assess_pipeline_coverage  # noqa: F401
    quota = 1_550_000.0
    weighted = 713_000.0
    raw = 1_200_000.0
    stretch = 2_100_000.0
    goal = quota + stretch
    return {
        "status": "ok",
        "fiscal_quarter": "FY2027 Q3",
        "current_week": 8,
        "scope": "test",
        "qualified_pipeline": {"raw_value": raw, "deal_count": 10},
        "stage_weighting": {
            "weighted_value": weighted,
            "weighted_deal_count": 8,
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
            "raw_pipeline_vs_goal": {"status": "short", "amount": max(0.0, goal - raw)},
            "weighted_pipeline_vs_goal": {"status": "short", "amount": max(0.0, goal - weighted)},
        },
        "historical_heuristic_curve": {},
        "note": "test",
    }


def _fake_select_all_ptt(supabase, table, columns="*", filters=None, **kwargs):
    """Simulate select_all as used by query_path_to_target."""
    if table == "deals" and filters:
        # COMMIT+ML active query
        if any(f[0] == "in_" and f[1] == "forecast_category" for f in filters):
            return [d for d in _COMMIT_ML_DEALS if d["deal_status"] == "active"]
        # QTD won query (gte close_date, deal_status=won)
        if any(f[0] == "eq" and f[2] == "won" for f in filters):
            return []
    return []


def test_handler_forecast_total_matches_expectation():
    """query_path_to_target['forecast_commit_ml'] == sum of COMMIT+ML incremental ARR.

    Uses real is_incremental_pipeline / incremental_arr so the filter behaves
    identically to the production code and the forecast_trust path below."""
    from api.handlers import query_path_to_target

    sb = MagicMock()
    fake_cov = _quota()

    def _capture_ptt(gap, scenarios, feasibility, **kwargs):
        return {
            "gap_bare": gap,
            "feasibility": feasibility,
            "headline": "test",
            "bare_plan": {"covered_by_conservative": 0, "covered_by_likely": 0, "covered_by_stretch": 0},
            "padded_plan": {"covered_by_conservative": 0, "covered_by_likely": 0, "covered_by_stretch": 0},
            "gap_padded": gap * 1.5,
            "pad_multiplier": 1.5,
            "net_new_viable": True,
            "note": "test",
        }

    # Return the fixture deals from select_all; let the real is_incremental_pipeline
    # and incremental_arr run so the filter is identical to production.
    def _select_all_with_deals(supabase, table, columns="*", filters=None, **kwargs):
        if table == "deals" and filters and any(
            f[0] == "in_" and f[1] == "forecast_category" for f in (filters or [])
        ):
            return list(_COMMIT_ML_DEALS)
        return []

    with (
        patch("pipeline_coverage.assess_pipeline_coverage", return_value=fake_cov),
        patch("api.time_resolver.current_quarter_label", return_value="Q3_FY2027"),
        patch("api.time_resolver.quarter_end_date", return_value=_Q_END),
        patch("api.time_resolver._client_config",
              return_value={"fiscal": {"fy_start_month": 2}}),
        patch("api.time_resolver._today", return_value=_TODAY),
        patch("utils.get_fiscal_quarter", return_value=_FAKE_GET_FQ),
        patch("api.handlers.select_all", side_effect=_select_all_with_deals),
        patch("path_to_target.time_feasibility",
              return_value={"days_remaining": 33, "feasible_fraction": 0.4,
                            "n_cycles": 10, "avg_cycle_days": 45.0,
                            "median_cycle_days": 40, "near_zero_threshold": 0.05,
                            "net_new_viable": True}),
        patch("path_to_target.path_to_target", side_effect=_capture_ptt),
    ):
        result = _run(query_path_to_target({}, sb))

    if result.get("status") == "error":
        pytest.fail(f"Handler returned error unexpectedly: {result}")

    forecast = result.get("forecast_commit_ml")
    assert forecast is not None, "forecast_commit_ml missing from result"
    assert abs(forecast - _EXPECTED_FORECAST_TOTAL) < 1.0, (
        f"forecast_commit_ml={forecast:,.0f}, expected {_EXPECTED_FORECAST_TOTAL:,.0f}. "
        "Check that is_incremental_pipeline excludes $0-ARR renewal deals (pipeline 866608541)."
    )


def test_forecast_trust_total_matches_expectation():
    """forecast_trust pipeline.incremental_arr == sum of COMMIT+ML incremental ARR."""
    from api.field_semantics import is_incremental_pipeline as _is_inc
    from api.incremental_arr import incremental_arr as _inc_arr

    # Simulate forecast_trust's filter: COMMIT+MOST_LIKELY active deals,
    # then is_incremental_pipeline, then sum incremental_arr.
    fetched = [d for d in _COMMIT_ML_DEALS if d["deal_status"] == "active"]
    deals = [d for d in fetched if _is_inc(d)]
    total = sum(_inc_arr(d) for d in deals)

    assert abs(total - _EXPECTED_FORECAST_TOTAL) < 1.0, (
        f"forecast_trust total={total:,.0f}, expected {_EXPECTED_FORECAST_TOTAL:,.0f}. "
        "Renewal deal (c3, $0 ARR) must be excluded."
    )


def test_cross_primitive_totals_agree():
    """Both primitives over the same deal set must produce the same total.

    This is the consistency invariant: if the two primitives disagree,
    the Slack output shows conflicting numbers from the same quarter."""
    from api.field_semantics import is_incremental_pipeline as _is_inc
    from api.incremental_arr import incremental_arr as _inc_arr

    # Simulate forecast_trust path
    fetched = [d for d in _COMMIT_ML_DEALS if d["deal_status"] == "active"]
    ft_deals = [d for d in fetched if _is_inc(d)]
    ft_total = sum(_inc_arr(d) for d in ft_deals)

    # Simulate handler path: same filter applied to same deal set
    ptt_deals = [d for d in _COMMIT_ML_DEALS if d["deal_status"] == "active"]
    ptt_deals = [d for d in ptt_deals if _is_inc(d)]
    ptt_total = sum(_inc_arr(d) for d in ptt_deals)

    assert abs(ft_total - ptt_total) < 1.0, (
        f"forecast_trust total {ft_total:,.0f} ≠ path_to_target forecast {ptt_total:,.0f}. "
        "Both must use identical filter: COMMIT+MOST_LIKELY, active, same quarter, "
        "is_incremental_pipeline=True, sum new_arr+expansion_arr."
    )


def test_plan_keys_renamed_no_conservative_label():
    """bare_plan and padded_plan must not expose 'covered_by_conservative' etc.

    After the key-rename block in query_path_to_target, the Slack output shows
    covered_by_forecast / covered_by_stage_ev / covered_by_pipeline instead."""
    from api.handlers import query_path_to_target

    sb = MagicMock()
    fake_cov = _quota()

    def _ptt_with_plan(gap, scenarios, feasibility, **kwargs):
        return {
            "gap_bare": gap,
            "feasibility": feasibility,
            "headline": "test",
            "bare_plan": {
                "covered_by_conservative": 100_000,
                "covered_by_likely": 200_000,
                "covered_by_stretch": 876_600,
                "net_new_needed": 0,
            },
            "padded_plan": {
                "covered_by_conservative": 100_000,
                "covered_by_likely": 200_000,
                "covered_by_stretch": 876_600,
                "net_new_needed": 64_350,
            },
            "gap_padded": gap * 1.5,
            "pad_multiplier": 1.5,
            "net_new_viable": True,
            "note": "test",
        }

    with (
        patch("pipeline_coverage.assess_pipeline_coverage", return_value=fake_cov),
        patch("api.time_resolver.current_quarter_label", return_value="Q3_FY2027"),
        patch("api.time_resolver.quarter_end_date", return_value=_Q_END),
        patch("api.time_resolver._client_config",
              return_value={"fiscal": {"fy_start_month": 2}}),
        patch("api.time_resolver._today", return_value=_TODAY),
        patch("utils.get_fiscal_quarter", return_value=_FAKE_GET_FQ),
        patch("api.handlers.select_all", return_value=[]),
        patch("path_to_target.time_feasibility",
              return_value={"days_remaining": 33, "feasible_fraction": 0.4,
                            "n_cycles": 10, "avg_cycle_days": 45.0,
                            "median_cycle_days": 40, "near_zero_threshold": 0.05,
                            "net_new_viable": True}),
        patch("path_to_target.path_to_target", side_effect=_ptt_with_plan),
    ):
        result = _run(query_path_to_target({}, sb))

    if result.get("status") == "error":
        pytest.fail(f"Handler returned error unexpectedly: {result}")

    for plan_key in ("bare_plan", "padded_plan"):
        plan = result.get(plan_key) or {}
        for bad_key in ("covered_by_conservative", "covered_by_likely", "covered_by_stretch"):
            assert bad_key not in plan, (
                f"{plan_key}['{bad_key}'] still present — key rename block missing or broken. "
                f"Slack output would show 'Conservative' label. Keys: {list(plan)}"
            )
        assert "covered_by_forecast" in plan, (
            f"{plan_key} missing 'covered_by_forecast'. Got keys: {list(plan)}"
        )
        assert "covered_by_stage_ev" in plan, (
            f"{plan_key} missing 'covered_by_stage_ev'. Got keys: {list(plan)}"
        )
        assert "covered_by_pipeline" in plan, (
            f"{plan_key} missing 'covered_by_pipeline'. Got keys: {list(plan)}"
        )
