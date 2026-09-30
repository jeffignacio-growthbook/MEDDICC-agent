#!/usr/bin/env python3
"""
query_pipeline_coverage accepts fiscal_quarter to assess historical quarters.

When fiscal_quarter names a past quarter, the primitive reads pipeline state
from deals_snapshot (the last available week for that quarter) rather than
live active deals.  ARR fields (new_arr, expansion_arr) come from the deals
table — they are not on the snapshot.

Item 2 of the "schema injection follow-up" plan: closing the exact gap the
C4 override identified in the live trace ("query_pipeline_coverage only
returns current quarter data and cannot be parameterized to return historical
quarters").
"""
import json
import sys
from datetime import date
from pathlib import Path
from unittest.mock import patch

REPO = Path(__file__).parent.parent
sys.path.insert(0, str(REPO / "tests"))
sys.path.insert(0, str(REPO))
sys.path.insert(0, str(REPO / "scripts"))
sys.path.insert(0, str(REPO / "scripts" / "analytics"))
sys.path.insert(0, str(REPO / "api"))

import logging  # noqa: E402
import pytest  # noqa: E402

@pytest.fixture(autouse=True)
def _silence_loggers():
    """Suppress noisy log output during these tests without affecting other
    test files that may run in the same session."""
    prev = logging.root.manager.disable
    logging.disable(logging.CRITICAL)
    yield
    logging.disable(prev)

from strict_supabase import StrictSupabase  # noqa: E402

# Minimal stage rates fixture
RATES = {
    "by_stage_order": {
        "3": {"stage_name": "Discovery", "win_rate": 0.15, "n_observed": 20},
        "4": {"stage_name": "Negotiating", "win_rate": 0.29, "n_observed": 25},
        "5": {"stage_name": "Awaiting Signature", "win_rate": 0.65, "n_observed": 15},
    },
    "min_evidence_count": 5,
}

TARGET_Q3 = {"period": "FY2027_Q3", "level": "team", "metric": "incremental_arr", "target_value": 1550000}

# Sales pipeline ID (must match config/client.yaml's default)
SALES_PIPELINE = "default"

# Discovery stage ID (matches config/client.yaml qualifying stages)
DISCOVERY_STAGE = "24682892"
NEGOTIATING_STAGE = "43449439"


def _snapshot_row(deal_id, stage_order, pipeline_id=SALES_PIPELINE,
                  close_date="2026-07-15", deal_status="active",
                  fiscal_quarter="FY2027 Q2", week_of_quarter=13,
                  snapshot_date="2026-07-31"):
    return {
        "deal_id": deal_id,
        "pipeline_id": pipeline_id,
        "stage_order": stage_order,
        "close_date": close_date,
        "deal_status": deal_status,
        "fiscal_quarter": fiscal_quarter,
        "week_of_quarter": week_of_quarter,
        "snapshot_date": snapshot_date,
        "stage_id": None, "deal_value": 100000, "owner_email": "rep@co.com",
        "snapshot_source": "prospective",
    }


def _deal_row(deal_id, new_arr=50000, expansion_arr=30000, **kw):
    return {
        "deal_id": deal_id,
        "new_arr": new_arr,
        "expansion_arr": expansion_arr,
        "pipeline_id": kw.get("pipeline_id", SALES_PIPELINE),
        "stage": kw.get("stage", DISCOVERY_STAGE),
        "close_date": kw.get("close_date", "2026-07-15"),
        "deal_status": kw.get("deal_status", "active"),
    }


def _run_historical(snapshots, deals, fiscal_quarter="FY2027 Q2",
                    targets=None, rates=None):
    from pipeline_coverage import assess_pipeline_coverage
    sb = StrictSupabase({
        "deals_snapshot": snapshots,
        "deals": deals,
        "rep_targets": targets or [],
    })
    with patch("utils.get_fiscal_quarter") as gfq, \
         patch("snapshot_deals.get_week_of_quarter") as gw, \
         patch("time_resolver.current_quarter_label") as cql, \
         patch("time_resolver.resolve_time_window") as rtw, \
         patch("forecast_analyses.query_stage_close_rate") as sr, \
         patch("forecast_analyses.query_coverage_proxy_target_by_week") as curve:
        gfq.return_value = (date(2026, 8, 1), date(2026, 10, 31), "FY2027 Q3")
        gw.return_value = 8
        cql.return_value = "Q3_FY2027"
        rtw.return_value = {"start": "2026-05-01", "end": "2026-07-31", "label": "Q2 FY2027"}
        sr.return_value = rates or RATES
        curve.return_value = {"by_week": {}}
        return assess_pipeline_coverage(sb, fiscal_quarter=fiscal_quarter)


def _run_current(deals, targets=None, rates=None):
    from pipeline_coverage import assess_pipeline_coverage
    sb = StrictSupabase({
        "deals": deals,
        "rep_targets": targets or [TARGET_Q3],
    })
    with patch("utils.get_fiscal_quarter") as gfq, \
         patch("snapshot_deals.get_week_of_quarter") as gw, \
         patch("time_resolver.current_quarter_label") as cql, \
         patch("forecast_analyses.query_stage_close_rate") as sr, \
         patch("forecast_analyses.query_coverage_proxy_target_by_week") as curve:
        gfq.return_value = (date(2026, 8, 1), date(2026, 10, 31), "FY2027 Q3")
        gw.return_value = 8
        cql.return_value = "Q3_FY2027"
        sr.return_value = rates or RATES
        curve.return_value = {"by_week": {}}
        return assess_pipeline_coverage(sb, as_of=date(2026, 9, 25))


# ─── Tests ───────────────────────────────────────────────────────────────

def test_historical_quarter_reads_snapshot():
    """Historical quarter reads from deals_snapshot, not live deals."""
    snaps = [
        _snapshot_row("d1", stage_order=3),
        _snapshot_row("d2", stage_order=4),
    ]
    deals = [_deal_row("d1", new_arr=100000, expansion_arr=0),
             _deal_row("d2", new_arr=200000, expansion_arr=0)]
    r = _run_historical(snaps, deals)
    assert r["is_historical"] is True
    assert r["fiscal_quarter"] == "FY2027 Q2"
    assert r["qualified_pipeline"]["deal_count"] == 2
    assert r["qualified_pipeline"]["raw_value"] == 300000
    assert "deals_snapshot" in r["scope"]
    print("✓ historical quarter reads from deals_snapshot")


def test_historical_quarter_joins_arr_from_deals():
    """ARR values come from the deals table, not from snapshot."""
    snaps = [_snapshot_row("d1", stage_order=3)]
    deals = [_deal_row("d1", new_arr=75000, expansion_arr=25000)]
    r = _run_historical(snaps, deals)
    assert r["qualified_pipeline"]["raw_value"] == 100000
    print("✓ historical quarter joins ARR from deals table")


def test_historical_quarter_uses_latest_snapshot_week():
    """When multiple weeks exist, uses the latest one."""
    snaps = [
        _snapshot_row("d1", stage_order=3, week_of_quarter=10),
        _snapshot_row("d2", stage_order=4, week_of_quarter=10),
        _snapshot_row("d1", stage_order=4, week_of_quarter=13),
        _snapshot_row("d2", stage_order=5, week_of_quarter=13),
    ]
    deals = [_deal_row("d1", new_arr=100000, expansion_arr=0),
             _deal_row("d2", new_arr=100000, expansion_arr=0)]
    r = _run_historical(snaps, deals)
    assert r["qualified_pipeline"]["deal_count"] == 2
    # Both at week-13 stages (4 and 5), weighted at 0.29 and 0.65
    expected_weighted = 100000 * 0.29 + 100000 * 0.65
    assert abs(r["stage_weighting"]["weighted_value"] - expected_weighted) < 1
    print("✓ historical quarter uses latest snapshot week")


def test_historical_quarter_no_target_discloses():
    """When no target exists for the requested quarter, gap_to_goal is null
    and the note discloses the absence."""
    snaps = [_snapshot_row("d1", stage_order=3)]
    deals = [_deal_row("d1")]
    r = _run_historical(snaps, deals, targets=[])
    assert r["real_target"]["goal"] is None
    assert r["gap_to_goal"]["raw_pipeline_vs_goal"] is None
    assert "No stated target" in r["real_target"]["note"]
    print("✓ historical quarter with no target discloses absence")


def test_historical_quarter_with_target():
    """When targets exist for the past quarter, gap-to-goal is computed."""
    snaps = [_snapshot_row("d1", stage_order=3)]
    deals = [_deal_row("d1", new_arr=500000, expansion_arr=0)]
    targets = [{"period": "FY2027_Q2", "level": "team",
                "metric": "incremental_arr", "target_value": 1000000}]
    r = _run_historical(snaps, deals, targets=targets)
    # No stretch target in targets.yaml for Q2, so goal = None (quota alone is not goal)
    # With only quota, goal requires both quota AND stretch
    assert r["real_target"]["quota"] == 1000000
    print("✓ historical quarter with target returns quota")


def test_current_quarter_regression():
    """Current quarter still works via live deals, not snapshot."""
    deals = [_deal_row("d1", new_arr=200000, expansion_arr=0,
                       close_date="2026-09-15")]
    r = _run_current(deals)
    assert r["is_historical"] is False
    assert r["fiscal_quarter"] == "FY2027 Q3"
    assert r["qualified_pipeline"]["deal_count"] == 1
    assert r["qualified_pipeline"]["raw_value"] == 200000
    assert "deals_snapshot" not in r["scope"]
    print("✓ current quarter regression: still uses live deals")


def test_normalize_quarter_label():
    """Various quarter label formats are normalized to 'FY2027 Q3'."""
    from pipeline_coverage import _normalize_quarter_label
    with patch("utils.get_fiscal_quarter") as gfq:
        gfq.return_value = (date(2026, 8, 1), date(2026, 10, 31), "FY2027 Q3")
        assert _normalize_quarter_label("FY2027 Q3") == "FY2027 Q3"
        assert _normalize_quarter_label("Q3_FY2027") == "FY2027 Q3"
        assert _normalize_quarter_label("FY2027Q2") == "FY2027 Q2"
        assert _normalize_quarter_label("q2_fy2027") == "FY2027 Q2"
        assert _normalize_quarter_label("Q3") == "FY2027 Q3"
    print("✓ normalize_quarter_label handles all formats")


def test_historical_renewal_not_weighted():
    """Renewal-pipeline deals in a historical quarter are still excluded
    from the weighted total."""
    snaps = [
        _snapshot_row("d1", stage_order=3),
        _snapshot_row("d2", stage_order=4, pipeline_id="866608541"),
    ]
    deals = [_deal_row("d1", new_arr=100000, expansion_arr=0),
             _deal_row("d2", new_arr=50000, expansion_arr=0, pipeline_id="866608541")]
    r = _run_historical(snaps, deals)
    assert r["qualified_pipeline"]["deal_count"] == 1
    assert r["renewal_not_weighted"]["deal_count"] == 1
    print("✓ historical quarter: renewal deals not weighted")


# ─── Wiring visibility tests (2026-09-30 task) ────────────────────────────

def test_router_fiscal_quarter_lists_pipeline_coverage():
    """The classifier prompt's fiscal_quarter param description must name
    query_pipeline_coverage so the model knows to pass it."""
    from api.router import build_intent_prompt
    prompt = build_intent_prompt("2026-09-30", "FY2027 Q3", "", "test")
    fq_lines = [l for l in prompt.splitlines()
                if l.strip().startswith('"fiscal_quarter"')]
    assert fq_lines, "fiscal_quarter param not found in classifier prompt"
    assert "query_pipeline_coverage" in fq_lines[0], \
        f"fiscal_quarter param description must list query_pipeline_coverage, got: {fq_lines[0]}"
    print("✓ router fiscal_quarter lists query_pipeline_coverage")


def test_agent_loop_prompt_lists_pipeline_coverage_fiscal_quarter():
    """The agent loop system prompt must tell the model that
    query_pipeline_coverage accepts a fiscal_quarter parameter."""
    from api.agent_loop import _SYSTEM_PROMPT
    coverage_line = [l for l in _SYSTEM_PROMPT.splitlines()
                     if "query_pipeline_coverage" in l and "fiscal_quarter" in l]
    assert coverage_line, \
        "agent loop prompt must list fiscal_quarter under query_pipeline_coverage"
    print("✓ agent loop prompt lists fiscal_quarter for query_pipeline_coverage")


def test_historical_quota_uses_past_quarter_period_key():
    """Item 11: quota lookup for a past quarter must use THAT quarter's
    period key ('FY2027_Q2'), not the current quarter's ('FY2027_Q3').
    Verifies by seeding targets for BOTH quarters and confirming only the
    past quarter's target appears in the result."""
    snaps = [_snapshot_row("d1", stage_order=3)]
    deals = [_deal_row("d1", new_arr=500000, expansion_arr=0)]
    targets = [
        {"period": "FY2027_Q2", "level": "team",
         "metric": "incremental_arr", "target_value": 800000},
        {"period": "FY2027_Q3", "level": "team",
         "metric": "incremental_arr", "target_value": 1550000},
    ]
    r = _run_historical(snaps, deals, fiscal_quarter="FY2027 Q2", targets=targets)
    assert r["real_target"]["quota"] == 800000, \
        f"expected Q2 quota 800000, got {r['real_target']['quota']}"
    print("✓ historical quota uses past quarter's period key, not current")


def test_agent_loop_prompt_includes_date_context():
    """The agent loop system prompt must inject today's date and the current
    fiscal quarter so the model can resolve 'last quarter' without guessing."""
    from unittest.mock import patch
    from api.agent_loop import _build_system_prompt
    with patch("api.agent_loop._agent_loop_today", return_value="2026-09-30"), \
         patch("api.agent_loop._agent_loop_current_quarter", return_value="FY2027 Q3"):
        prompt = _build_system_prompt(schema_context="")
    assert "Today is 2026-09-30" in prompt, \
        "agent loop prompt must include today's date"
    assert "FY2027 Q3" in prompt, \
        "agent loop prompt must include current fiscal quarter"
    assert "fy_start_month" in prompt.lower() or "February" in prompt, \
        "agent loop prompt must mention fiscal year start month"
    print("✓ agent loop prompt includes date context")


def test_PLANTED_BUG_agent_loop_no_date_without_injection():
    """CONTROL: _SYSTEM_PROMPT (the static template) must NOT hard-code a date.
    The date is injected at build time, not baked in."""
    from api.agent_loop import _SYSTEM_PROMPT
    assert "Today is" not in _SYSTEM_PROMPT, \
        "PLANTED BUG: _SYSTEM_PROMPT must not hard-code 'Today is' — it is injected"
    print("✓ PLANTED BUG control: _SYSTEM_PROMPT has no hard-coded date")



# ─── Planted-bug controls ────────────────────────────────────────────────

def test_PLANTED_BUG_historical_must_read_snapshot():
    """CONTROL: if the historical path read live deals instead of snapshot,
    it would find nothing (no active deals from Q2 in the deals table)."""
    snaps = [_snapshot_row("d1", stage_order=3)]
    deals = [_deal_row("d1", new_arr=100000, expansion_arr=0,
                       deal_status="won", close_date="2026-07-15")]
    # The snapshot says "active" at snapshot time; the deal is now "won"
    # in the deals table.  If code incorrectly reads deals table with
    # deal_status=active filter, it finds nothing.
    r = _run_historical(snaps, deals)
    assert r["qualified_pipeline"]["deal_count"] == 1, \
        "PLANTED BUG: historical path must read snapshot state, not live deal_status"
    print("✓ PLANTED BUG control: historical reads snapshot, not live deal_status")


if __name__ == "__main__":
    test_historical_quarter_reads_snapshot()
    test_historical_quarter_joins_arr_from_deals()
    test_historical_quarter_uses_latest_snapshot_week()
    test_historical_quarter_no_target_discloses()
    test_historical_quarter_with_target()
    test_current_quarter_regression()
    test_normalize_quarter_label()
    test_historical_renewal_not_weighted()
    test_router_fiscal_quarter_lists_pipeline_coverage()
    test_agent_loop_prompt_lists_pipeline_coverage_fiscal_quarter()
    test_historical_quota_uses_past_quarter_period_key()
    test_agent_loop_prompt_includes_date_context()
    test_PLANTED_BUG_agent_loop_no_date_without_injection()
    test_PLANTED_BUG_historical_must_read_snapshot()
    print("\n✅ All pipeline_coverage fiscal_quarter tests passed")
