#!/usr/bin/env python3
"""
Live incident, 2026-09-25 06:22 UTC: "are we in good shape this quarter?"
crashed before any reply. The first answer after the quarter-health reframe
(PR #64) raised

    AttributeError: 'int' object has no attribute 'lower'
      api/plausibility.py check_rate_bounds -> check_value -> key.lower()

query_stage_close_rate() returns by_stage_order keyed by int stage order in
production. The composer compacts it into
stage_weighting.win_rate_by_stage_order with the same keys, and the
pre-synthesis plausibility checks assumed every dict key is a string. Every
test fixture had been through JSON, which turns int keys into strings, so
nothing caught it. query_pipeline_coverage's own result carries the same
int-keyed table, so a direct coverage question could hit the same crash.

Fixed twice: the plausibility checks treat any key as text, and the composer
writes the compact table with string keys (as a JSON payload would have).
These tests use the production shape: int keys.
"""
import copy
import json
import sys
from pathlib import Path

REPO = Path(__file__).parent.parent
sys.path.insert(0, str(REPO / "tests"))
sys.path.insert(0, str(REPO))
sys.path.insert(0, str(REPO / "scripts"))
sys.path.insert(0, str(REPO / "scripts" / "analytics"))
sys.path.insert(0, str(REPO / "api"))

import logging  # noqa: E402
logging.disable(logging.CRITICAL)

import api.quarter_health as qh  # noqa: E402
from api.plausibility import run_all_checks  # noqa: E402
import quarter_health_inputs as qi  # noqa: E402


def _int_keyed(table: dict) -> dict:
    return {int(k): v for k, v in table.items()}


def test_plausibility_accepts_non_string_keys():
    data = {"stage_weighting": {"by_stage_order": {5: {"win_rate": 0.65}, 3: {"win_rate": 0.11}},
                                "counts": {1: 4, 2: 7}},
            "by_week": {8: {"classified": 91, "win_rate": 0.32}}}
    for handler in ("query_pipeline_coverage", "query_quarter_health", "query_forecast_trust"):
        violations, _ = run_all_checks(copy.deepcopy(data), handler)
        assert not violations, [v.message for v in violations]
    bad = {"by_stage_order": {5: {"win_rate": 1.7}}, "rows": {2: {"count": -3}}}
    msgs = [v.message for v in run_all_checks(bad, "query_pipeline_coverage")[0]]
    assert any("win_rate exceeds 1.0" in m for m in msgs) and any("count is negative" in m for m in msgs), msgs
    print("✓ plausibility checks run over int-keyed tables (no AttributeError) and still flag a bad "
          "rate or count under them")


def test_composed_views_with_the_production_int_keyed_stage_table():
    raw = copy.deepcopy(qi.RAW)
    sw = raw["query_pipeline_coverage"]["stage_weighting"]
    sw["by_stage_order"] = _int_keyed(sw["by_stage_order"])
    rates = copy.deepcopy(qi.PRIMS["stage_close_rate"])
    rates["by_stage_order"] = _int_keyed(rates["by_stage_order"])
    for scenario in qh.SCENARIOS:
        c = qh.compose_from_results(copy.deepcopy(raw), scenario, stage_rates=rates,
                                    deal_rows=qi.PRIMS["high_risk_deal_rows"], as_of=qi.AS_OF,
                                    seasonality=qi.SEASONALITY)
        table = c["primitives"]["query_pipeline_coverage"]["stage_weighting"]["win_rate_by_stage_order"]
        assert table and all(isinstance(k, str) for k in table), table
        violations, _ = run_all_checks(c, qh.ENTRY_POINTS[scenario])
        assert not violations, [v.message for v in violations]
        assert c["figures"]["coverage"]["line"] == qi.compose(scenario)["figures"]["coverage"]["line"]
        if scenario == "downside":
            assert round(c["downside"]["weighted_arr_if_lost"], 2) == 590532.67
        json.dumps(c)
    print("✓ both composed views on the int-keyed stage table: compact table written with string "
          "keys, plausibility passes, same coverage and downside figures")


def test_semantic_gap_check_walks_int_keyed_tables():
    """Same assumption in router._detect_semantic_gap's dollar-field search:
    a direct coverage question that mentions dollars walked
    stage_weighting.by_stage_order (int keys) before any dollar field."""
    import api.router as router
    result = {"status": "ok", "stage_weighting": {"by_stage_order": {5: {"win_rate": 0.65}}},
              "qualified_pipeline": {"raw_value": 4907065.68}}
    assert router._detect_semantic_gap("how much ARR coverage do we have", result,
                                       "query_pipeline_coverage") is not None   # no dollar-named field
    result["stage_weighting"]["weighted_arr"] = 701825.86
    assert router._detect_semantic_gap("how much ARR coverage do we have", result,
                                       "query_pipeline_coverage") is None
    print("✓ the router's dollar-field gap check walks int-keyed tables too")


if __name__ == "__main__":
    test_plausibility_accepts_non_string_keys()
    test_composed_views_with_the_production_int_keyed_stage_table()
    test_semantic_gap_check_walks_int_keyed_tables()
    print("\n✅ All tests passed")
