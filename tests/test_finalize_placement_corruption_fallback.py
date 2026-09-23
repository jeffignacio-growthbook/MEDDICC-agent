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

This test replays the 2026-09-14 EMEA incident shape end-to-end through
the REAL dynamic_query_loop, reaching _finalize_from_data via the
query_pipeline_movement fast path:
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
    test_placement_corruption_at_finalize_ships_the_fallback_not_the_corruption()
    test_planted_bug_reproduces_the_silent_ship()
    print("\n✅ All tests passed")
