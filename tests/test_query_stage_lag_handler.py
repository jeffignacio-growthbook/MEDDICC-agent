"""
query_stage_lag handler — Step A/B/D tests (tests-first, offline-capable).

Follows the migration pattern from test_query_win_loss_migration.py:
  STEP A — parameter completeness: handler callable with just a params dict
  STEP B — registration: appears in _HANDLER_REGISTRY with a meaningful description
  STEP D — planted-bug control: the substance gate (no_scoreable_call) must fire;
            also a full scenario: pre-commercial deal with EB>=6 AND DP>=6 flagged,
            deal with no scoreable analysis excluded, deal below threshold not flagged.

Step C (live baseline vs dynamic-loop) and Step E (CI gate) run separately.

Implementation contract:
  - Wraps detect_stage_call_lag() from scripts/analytics/stage_call_lag.py
  - Fetches from Supabase: "deals" (active, default pipeline, pre-commercial stages)
    and "analyses" (economic_buyer_score, decision_process_score) for those deal_ids
  - Returns the detect_stage_call_lag() result dict verbatim (no additional prose)
  - No params are *required*; optional: eb_threshold, dp_threshold
"""
import asyncio
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).parent.parent))
sys.path.insert(0, str(Path(__file__).parent.parent / "scripts" / "analytics"))

import api.handlers as handlers_module
import api.router as router
from stage_call_lag import detect_stage_call_lag, classify_deal


# ---------------------------------------------------------------------------
# Strict fake Supabase for offline tests
# ---------------------------------------------------------------------------

class _FakeSupabase:
    """Minimal strict Supabase fake — raises on unexpected method calls."""

    def __init__(self, deal_rows=None, analysis_rows=None):
        self._deal_rows = deal_rows or []
        self._analysis_rows = analysis_rows or []
        self._call_count = 0

    def table(self, name):
        self._current_table = name
        return self

    def select(self, *args, **kwargs):
        return self

    def eq(self, col, val):
        return self

    def in_(self, col, vals):
        return self

    def range(self, start, end):
        self._range_start = start
        self._range_end = end
        return self

    def execute(self):
        class _Result:
            pass
        r = _Result()
        if self._current_table == "deals":
            rows = self._deal_rows
        elif self._current_table == "analyses":
            rows = self._analysis_rows
        else:
            rows = []
        # If a range was requested, return that slice (select_all pagination)
        start = getattr(self, "_range_start", 0)
        end = getattr(self, "_range_end", len(rows) - 1)
        r.data = rows[start:end + 1]
        return r


def _run(coro):
    return asyncio.run(coro)


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

# A pre-commercial deal with high EB+DP — should be flagged
DEAL_PRECOMMERCIAL_HIGH = {
    "deal_id": "deal-001",
    "company_name": "AlphaCorp",
    "stage": "79653122",  # Discovery (pre-commercial)
    "deal_status": "active",
    "pipeline_id": "default",
}

# A pre-commercial deal with no scoreable analysis — should be excluded
DEAL_PRECOMMERCIAL_NO_SIGNAL = {
    "deal_id": "deal-002",
    "company_name": "BetaCorp",
    "stage": "79653122",
    "deal_status": "active",
    "pipeline_id": "default",
}

# A pre-commercial deal below threshold — not flagged
DEAL_PRECOMMERCIAL_LOW = {
    "deal_id": "deal-003",
    "company_name": "GammaCorp",
    "stage": "79653122",
    "deal_status": "active",
    "pipeline_id": "default",
}

# A later-stage deal — should not be considered (not pre-commercial)
DEAL_COMMERCIAL = {
    "deal_id": "deal-004",
    "company_name": "DeltaCorp",
    "stage": "presentationscheduled",  # not pre-commercial
    "deal_status": "active",
    "pipeline_id": "default",
}

ANALYSIS_HIGH_EB_DP = {
    "deal_id": "deal-001",
    "economic_buyer_score": 8,
    "decision_process_score": 7,
}
ANALYSIS_ALL_ZERO = {
    "deal_id": "deal-002",
    "economic_buyer_score": 0,
    "decision_process_score": 0,
}
ANALYSIS_LOW_DP = {
    "deal_id": "deal-003",
    "economic_buyer_score": 8,
    "decision_process_score": 3,  # below threshold — one axis strong, one weak
}


# ---------------------------------------------------------------------------
# Step A — parameter completeness
# ---------------------------------------------------------------------------

def test_step_a_handler_exists():
    """query_stage_lag must be importable from handlers module."""
    assert hasattr(handlers_module, "query_stage_lag"), (
        "query_stage_lag not found in handlers module — implement it"
    )


def test_step_a_accepts_empty_params():
    """Handler must run with an empty params dict (no required params)."""
    fn = getattr(handlers_module, "query_stage_lag", None)
    if fn is None:
        pytest.skip("handler not yet implemented")
    sb = _FakeSupabase(deal_rows=[], analysis_rows=[])
    result = _run(fn({}, sb))
    assert isinstance(result, dict), "handler must return a dict"


def test_step_a_accepts_optional_thresholds():
    """Handler must accept optional eb_threshold and dp_threshold params."""
    fn = getattr(handlers_module, "query_stage_lag", None)
    if fn is None:
        pytest.skip("handler not yet implemented")
    sb = _FakeSupabase(deal_rows=[], analysis_rows=[])
    result = _run(fn({"eb_threshold": 7, "dp_threshold": 7}, sb))
    assert isinstance(result, dict)


# ---------------------------------------------------------------------------
# Step B — registry registration
# ---------------------------------------------------------------------------

def test_step_b_in_handler_registry():
    """query_stage_lag must appear in HANDLER_DESCRIPTIONS in router.py."""
    registry = getattr(router, "HANDLER_DESCRIPTIONS", {})
    assert "query_stage_lag" in registry, (
        f"'query_stage_lag' missing from HANDLER_DESCRIPTIONS. "
        f"Current keys: {sorted(registry.keys())}"
    )


def test_step_b_registry_description_meaningful():
    """Registry description must reference stage lag / mis-staged / call evidence."""
    registry = getattr(router, "HANDLER_DESCRIPTIONS", {})
    desc = registry.get("query_stage_lag", "")
    desc_lower = desc.lower()
    assert any(kw in desc_lower for kw in ["stage", "lag", "mis-stage", "call evidence", "meddicc"]), (
        f"Registry description for query_stage_lag is not meaningful: {desc!r}"
    )


# ---------------------------------------------------------------------------
# Step D — planted-bug control + full scenario
# ---------------------------------------------------------------------------

def test_step_d_substance_gate_excludes_no_signal_deal():
    """Planted-bug: a deal with no scoreable analysis (all zeros) must be EXCLUDED,
    not silently counted as 'no mismatch'. Tests the substance gate from stage_call_lag.py."""
    result = detect_stage_call_lag(
        deals=[DEAL_PRECOMMERCIAL_NO_SIGNAL],
        analyses_by_deal={"deal-002": [ANALYSIS_ALL_ZERO]},
        precommercial_stages=("79653122",),
    )
    assert result["excluded_no_scoreable_call"] == 1, (
        "Deal with all-zero analysis should be counted in excluded_no_scoreable_call"
    )
    assert result["flagged_count"] == 0
    assert result["flagged"] == []


def test_step_d_below_threshold_not_flagged():
    """A deal with one strong axis (EB>=6) but DP below threshold is NOT flagged.
    Single strong axis is not commercial readiness — BOTH must exceed threshold."""
    result = detect_stage_call_lag(
        deals=[DEAL_PRECOMMERCIAL_LOW],
        analyses_by_deal={"deal-003": [ANALYSIS_LOW_DP]},
        precommercial_stages=("79653122",),
    )
    assert result["flagged_count"] == 0
    assert result["below_threshold_count"] == 1


def test_step_d_high_eb_dp_flagged():
    """A pre-commercial deal with EB>=6 AND DP>=6 must appear in flagged list."""
    result = detect_stage_call_lag(
        deals=[DEAL_PRECOMMERCIAL_HIGH],
        analyses_by_deal={"deal-001": [ANALYSIS_HIGH_EB_DP]},
        precommercial_stages=("79653122",),
    )
    assert result["flagged_count"] == 1
    flagged = result["flagged"]
    assert len(flagged) == 1
    assert flagged[0]["deal_id"] == "deal-001"
    assert flagged[0]["economic_buyer_score"] == 8
    assert flagged[0]["decision_process_score"] == 7


def test_step_d_commercial_stage_not_considered():
    """A deal NOT at a pre-commercial stage must not appear in 'considered'."""
    result = detect_stage_call_lag(
        deals=[DEAL_COMMERCIAL],
        analyses_by_deal={"deal-004": [ANALYSIS_HIGH_EB_DP]},
        precommercial_stages=("79653122",),
    )
    assert result["considered"] == 0
    assert result["flagged_count"] == 0


def test_step_d_full_scenario_three_deals():
    """Full scenario: flagged + excluded + below threshold — correct counts for each bucket."""
    all_deals = [
        DEAL_PRECOMMERCIAL_HIGH,
        DEAL_PRECOMMERCIAL_NO_SIGNAL,
        DEAL_PRECOMMERCIAL_LOW,
        DEAL_COMMERCIAL,  # not considered
    ]
    analyses = {
        "deal-001": [ANALYSIS_HIGH_EB_DP],
        "deal-002": [ANALYSIS_ALL_ZERO],
        "deal-003": [ANALYSIS_LOW_DP],
        "deal-004": [ANALYSIS_HIGH_EB_DP],  # not considered (not pre-commercial)
    }
    result = detect_stage_call_lag(
        deals=all_deals,
        analyses_by_deal=analyses,
        precommercial_stages=("79653122",),
    )
    assert result["considered"] == 3  # only pre-commercial active deals
    assert result["flagged_count"] == 1
    assert result["excluded_no_scoreable_call"] == 1
    assert result["below_threshold_count"] == 1
    assert result["flagged"][0]["deal_id"] == "deal-001"


def test_step_d_handler_returns_flagged_key():
    """Handler must return a dict with 'flagged' key from detect_stage_call_lag."""
    fn = getattr(handlers_module, "query_stage_lag", None)
    if fn is None:
        pytest.skip("handler not yet implemented")
    sb = _FakeSupabase(
        deal_rows=[DEAL_PRECOMMERCIAL_HIGH],
        analysis_rows=[ANALYSIS_HIGH_EB_DP],
    )
    result = _run(fn({}, sb))
    assert "flagged" in result, f"Missing 'flagged' key in result: {result.keys()}"
    assert "flagged_count" in result
    assert "recency_caveat" in result


def test_step_d_handler_custom_thresholds_passed_through():
    """When eb_threshold=7/dp_threshold=8 is passed, a deal with EB=8/DP=7 is NOT flagged
    (DP=7 < dp_threshold=8). Verifies params are passed to detect_stage_call_lag."""
    fn = getattr(handlers_module, "query_stage_lag", None)
    if fn is None:
        pytest.skip("handler not yet implemented")
    # EB=8, DP=7: above eb_threshold=6 default, but below dp_threshold=8
    sb = _FakeSupabase(
        deal_rows=[DEAL_PRECOMMERCIAL_HIGH],
        analysis_rows=[ANALYSIS_HIGH_EB_DP],  # EB=8, DP=7
    )
    result = _run(fn({"eb_threshold": 6, "dp_threshold": 8}, sb))
    # DP=7 < dp_threshold=8 → not flagged
    assert result["flagged_count"] == 0, (
        "With dp_threshold=8 and DP=7, deal should NOT be flagged"
    )


# ---------------------------------------------------------------------------
# classify_deal unit tests (planted-bug controls for the core primitive)
# ---------------------------------------------------------------------------

def test_classify_deal_no_analyses_returns_no_scoreable():
    assert classify_deal([])["status"] == "no_scoreable_call"


def test_classify_deal_all_zero_returns_no_scoreable():
    assert classify_deal([{"economic_buyer_score": 0, "decision_process_score": 0}])["status"] == "no_scoreable_call"


def test_classify_deal_only_eb_real_signal_below_threshold():
    # EB=8, DP=0 — has real signal but DP doesn't meet threshold
    result = classify_deal([{"economic_buyer_score": 8, "decision_process_score": 0}])
    assert result["status"] == "below_threshold"


def test_classify_deal_both_above_threshold_flag():
    result = classify_deal([{"economic_buyer_score": 7, "decision_process_score": 6}])
    assert result["status"] == "flag"
    assert result["peak_eb"] == 7
    assert result["peak_dp"] == 6


def test_classify_deal_uses_peak_across_analyses():
    """Peak EB/DP across ALL analyses, not the latest row."""
    analyses = [
        {"economic_buyer_score": 3, "decision_process_score": 2},
        {"economic_buyer_score": 8, "decision_process_score": 7},  # peak values
        {"economic_buyer_score": 1, "decision_process_score": 1},
    ]
    result = classify_deal(analyses)
    assert result["status"] == "flag"
    assert result["peak_eb"] == 8
    assert result["peak_dp"] == 7
