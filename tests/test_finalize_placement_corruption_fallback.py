"""
Regression test: _finalize_from_data's placement-corruption fallback must
actually fire (2026-09-23).

Since 8bae539 (2026-09-15) the finalize retry's placement gate read:

    return _diagnostic_answer(
        tail, "aggregation_placement_corruption"
    )

`tail` was never defined in that scope. The NameError was raised inside
the retry's `try:` and swallowed by its `except Exception` (logged only as
"[AGGREGATION_VERIFY] resynthesis retry raised: name 'tail' is not
defined"). Execution then fell through and shipped final_answer_text, which
already held the corrupted retry answer. There was a second defect on the
same line: _diagnostic_answer() returns a bare string, not the
{"answer", "tool_results", "answered"} dict this function must return. So
the safety net never protected a single answer.

The existing placement tests (test_aggregation_placement_corruption.py
etc.) only unit-test the DETECTOR (verify_total_placement), never what the
loop does once it fires, which is why this went unnoticed.

Primary test: the faithful 2026-09-14 route. An EMEA question is answered
by filter_table WITH the region filter, so dimension verification passes on
its own merits; the main loop's detection hands off to finalize, and
finalize's own retry is corrupted again (see _run_incident_route).

Secondary test: the same corruption reached through the
query_pipeline_movement fast path, a different real entry into
_finalize_from_data. Its question omits "EMEA" deliberately: that path
never runs a region filter, so dimension verification would (correctly)
reject the answer before the aggregation check ever runs:
  1. the first answer states a wrong total ($50,000 vs a real $6,890,371.78),
  2. AGGREGATION_VERIFY forces one retry with the correct value,
  3. the retry puts $6,890,371.78 on Creative CX's line item (the incident),
  4. the placement gate must now replace that with an honest diagnostic.

The planted-bug control compiles a copy of the real api/router.py with the
old `_diagnostic_answer(tail, ...)` call restored and runs the identical
scenario: the corrupted answer must ship there. That proves this test would
have caught the bug from day one.
"""
import asyncio
import copy
import importlib.util
import json
import sys
from pathlib import Path

REPO = Path(__file__).parent.parent
sys.path.insert(0, str(Path(__file__).parent))
sys.path.insert(0, str(REPO))

import logging
logging.disable(logging.CRITICAL)

import api.router as router
import canary_harness as H
from canary_fixtures import QUERY_PIPELINE_MOVEMENT

QUESTION = "show me closed won and closed lost deals since January"
CORRECTED_TOTAL = 6890371.78

DEALS = [
    {"deal_id": "1", "company_name": "Acme Corp", "deal_value": 1200000},
    {"deal_id": "2", "company_name": "Beta Systems", "deal_value": 800000},
    {"deal_id": "3", "company_name": "Creative CX", "deal_value": 50000},
    {"deal_id": "4", "company_name": "Delta Inc", "deal_value": -500000},
    {"deal_id": "5", "company_name": "Echo Ltd", "deal_value": -300000},
]
DEALS.append({"deal_id": "6", "company_name": "Other deals",
              "deal_value": round(CORRECTED_TOTAL - sum(d["deal_value"] for d in DEALS), 2)})

WRONG_FIRST_ANSWER = (
    "Closed deals: Acme Corp at $1.2M, Beta Systems at $800K and "
    "Creative CX at $50K won; Delta Inc at $500K and Echo Ltd at $300K lost. "
    "Total closed deal value: $50,000")
CORRUPTED_RETRY = (
    "Closed deals: Acme Corp at $1.2M, Beta Systems at $800K and "
    "Creative CX at $6,890,371.78 won; Delta Inc at $500K and Echo Ltd at "
    "$300K lost. Total closed deal value: $6,890,371.78")

OLD_BUGGY_CALL = '''                                    return _diagnostic_answer(
                                        tail, "aggregation_placement_corruption"
                                    )
'''


def _handler_result():
    r = copy.deepcopy(QUERY_PIPELINE_MOVEMENT)
    r["rows"] = copy.deepcopy(DEALS)
    return r


def _run(router_module):
    client = H.ScriptedClient([
        json.dumps({"tool": "query_pipeline_movement", "params": {"view": "movement"}}),
        json.dumps({"answer": WRONG_FIRST_ANSWER}),
        json.dumps({"answer": CORRUPTED_RETRY}),
    ])
    handlers = router_module.handlers
    saved = {
        "handler": handlers.query_pipeline_movement,
        "classify": H.table_classifier_module.classify_relevant_tables,
        "schema": H.schema_context_module.get_schema_context,
        "anchors": router_module.resolve_snapshot_anchor_dates,
    }

    async def fake(params, sb):
        return _handler_result()

    handlers.query_pipeline_movement = fake
    H.table_classifier_module.classify_relevant_tables = lambda q, c: ["deals"]
    H.schema_context_module.get_schema_context = (
        lambda sb, tables_with_descriptions=None, lightweight=False: "TABLE: deals\n  deal_id\n")
    router_module.resolve_snapshot_anchor_dates = lambda sb, tw: (None, None)
    try:
        return asyncio.run(router_module.dynamic_query_loop(
            question=QUESTION, history=[],
            params={"time_window": H.DEFAULT_TIME_WINDOW},
            sb=H._FakeSupabase(), client=client)), client
    finally:
        handlers.query_pipeline_movement = saved["handler"]
        H.table_classifier_module.classify_relevant_tables = saved["classify"]
        H.schema_context_module.get_schema_context = saved["schema"]
        router_module.resolve_snapshot_anchor_dates = saved["anchors"]


def _planted_bug_router():
    """A copy of the real api/router.py with the pre-fix call restored."""
    src = (REPO / "api" / "router.py").read_text()
    start = src.index('                                    # Force honest fallback instead of shipping corrupted data.')
    end = src.index('                                    )\n', src.index('return _give_up(\n                                        "aggregation_placement_corruption"', start)) + len('                                    )\n')
    planted = src[:start] + OLD_BUGGY_CALL + src[end:]
    assert "tail, \"aggregation_placement_corruption\"" in planted
    spec = importlib.util.spec_from_loader("router_planted_bug", loader=None)
    mod = importlib.util.module_from_spec(spec)
    mod.__file__ = str(REPO / "api" / "router.py")
    exec(compile(planted, "router_planted_bug", "exec"), mod.__dict__)
    return mod


INCIDENT_QUESTION = "show me EMEA closed won and closed lost deals since January"
EMEA_ROWS = [dict(d, region="EMEA") for d in DEALS]


def _run_incident_route(router_module):
    """The faithful 2026-09-14 route, every gate real and none bypassed:
    an EMEA question answered by filter_table WITH the region filter (so
    dimension verification passes on its own merits), then the main loop's
    AGGREGATION_VERIFY forces a retry, the main loop's placement gate
    detects the corrupted retry and hands off to _finalize_from_data,
    whose own aggregation check forces its one retry, and that retry is
    corrupted again. Five LLM calls, each triggered by a real detection."""
    wrong = "EMEA " + WRONG_FIRST_ANSWER[0].lower() + WRONG_FIRST_ANSWER[1:]
    corrupted = "EMEA " + CORRUPTED_RETRY[0].lower() + CORRUPTED_RETRY[1:]
    client = H.ScriptedClient([
        json.dumps({"tool": "filter_table", "params": {
            "table": "deals", "columns": ["deal_id", "company_name", "deal_value", "region"],
            "filters": [["eq", "region", "EMEA"]]}}),
        json.dumps({"answer": wrong}),       # main loop: wrong total
        json.dumps({"answer": corrupted}),   # main loop retry: corrupted
        json.dumps({"answer": wrong}),       # finalize synthesis: wrong total
        json.dumps({"answer": corrupted}),   # finalize retry: corrupted again
    ])
    saved = {
        "filter_table": H.tools_module.filter_table,
        "classify": H.table_classifier_module.classify_relevant_tables,
        "schema": H.schema_context_module.get_schema_context,
        "anchors": router_module.resolve_snapshot_anchor_dates,
        "log": router_module._log_query_cost,
    }
    logged = {}

    def capture_log(sb, question, cost_state, result, exc_raised):
        # The outcome query_cost_log would record (the fake Supabase
        # can't take the insert itself).
        logged["outcome"] = router_module._compute_query_cost_outcome(
            result, cost_state, exc_raised)
        logged["reason_tag"] = cost_state.get("reason_tag")

    async def fake_filter_table(sb, **kwargs):
        return {"rows": copy.deepcopy(EMEA_ROWS), "table": "deals"}

    H.tools_module.filter_table = fake_filter_table
    H.table_classifier_module.classify_relevant_tables = lambda q, c: ["deals"]
    H.schema_context_module.get_schema_context = (
        lambda sb, tables_with_descriptions=None, lightweight=False:
            "TABLE: deals\n  deal_id, company_name, deal_value, region\n")
    router_module.resolve_snapshot_anchor_dates = lambda sb, tw: (None, None)
    router_module._log_query_cost = capture_log
    try:
        result = asyncio.run(router_module.dynamic_query_loop(
            question=INCIDENT_QUESTION, history=[],
            params={"time_window": H.DEFAULT_TIME_WINDOW},
            sb=H._FakeSupabase(), client=client))
        result["_logged"] = logged
        return result, client
    finally:
        router_module._log_query_cost = saved["log"]
        H.tools_module.filter_table = saved["filter_table"]
        H.table_classifier_module.classify_relevant_tables = saved["classify"]
        H.schema_context_module.get_schema_context = saved["schema"]
        router_module.resolve_snapshot_anchor_dates = saved["anchors"]


def test_incident_route_main_loop_then_finalize_ships_the_fallback():
    result, client = _run_incident_route(router)
    assert len(client.calls) == 5, (
        f"the incident route must reach the finalize retry through real "
        f"detections (tool, answer, main-loop retry, finalize synthesis, "
        f"finalize retry) — got {len(client.calls)} LLM calls")
    assert result["answered"] is False
    assert "Creative CX at $6,890,371.78" not in result["answer"], (
        f"the corrupted retry answer shipped: {result['answer']!r}")
    assert "could not state the corrected total reliably" in result["answer"]
    assert result["_logged"] == {"outcome": "blocked_placement_corruption",
                                 "reason_tag": "aggregation_placement_corruption"}, (
        f"query_cost_log must record the blocked corruption in its own "
        f"outcome bucket — got {result['_logged']}")
    print("✓ incident route (EMEA, real region filter, main-loop detection "
          "→ finalize): the honest fallback ships, not the corruption; "
          "query_cost_log outcome = blocked_placement_corruption")


def test_incident_route_planted_bug_ships_the_corruption():
    result, client = _run_incident_route(_planted_bug_router())
    assert len(client.calls) == 5
    assert "Creative CX at $6,890,371.78" in result["answer"] and result["answered"] is True, (
        f"with the old undefined-`tail` call restored, the incident route "
        f"should ship the corrupted answer as answered=True — got "
        f"answered={result.get('answered')}: {result['answer']!r}")
    assert result["_logged"]["outcome"] != "blocked_placement_corruption"
    print(f"✓ incident route, planted bug: the corrupted answer ships as "
          f"answered=True, logged as outcome={result['_logged']['outcome']!r} "
          f"— exactly the pre-fix production behavior")


def test_placement_corruption_at_finalize_ships_the_fallback_not_the_corruption():
    result, client = _run(router)
    assert len(client.calls) == 3, (
        f"scenario must reach the finalize retry (tool call, first answer, "
        f"retry) — got {len(client.calls)} LLM calls")
    assert isinstance(result, dict) and set(result) >= {"answer", "tool_results", "answered"}, (
        f"finalize must return the result dict, got {type(result).__name__}: {result!r}")
    assert result["answered"] is False
    assert "Creative CX at $6,890,371.78" not in result["answer"], (
        f"the corrupted retry answer shipped: {result['answer']!r}")
    assert "could not state the corrected total reliably" in result["answer"]
    print("✓ placement corruption at finalize ships the honest fallback "
          "(answered=False, proper result dict), not the corrupted answer")


def test_planted_bug_reproduces_the_silent_ship():
    buggy = _planted_bug_router()
    result, client = _run(buggy)
    assert len(client.calls) == 3
    assert "Creative CX at $6,890,371.78" in result["answer"], (
        f"with the old undefined-`tail` call restored, the corrupted answer "
        f"should ship (the pre-fix behavior) — got {result['answer']!r}")
    print("✓ planted bug (undefined `tail` restored): the corrupted answer ships "
          "silently — this test would have caught it since 2026-09-15")


if __name__ == "__main__":
    test_incident_route_main_loop_then_finalize_ships_the_fallback()
    test_incident_route_planted_bug_ships_the_corruption()
    test_placement_corruption_at_finalize_ships_the_fallback_not_the_corruption()
    test_planted_bug_reproduces_the_silent_ship()
    print("\n✅ All tests passed")
