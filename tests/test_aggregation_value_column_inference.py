"""
Regression test for the 2026-09-23 live verification of Ryan's question:
"Tell me the amount of pipeline in $ and number of deals we've added to
the pipeline in the last two weeks".

With the canary-drop fixes in (PR #29), the handler's computed figures
reached synthesis intact and the model's first answer was right (~$2.78M
added across 24 new deals). Then the AGGREGATION_VERIFY gate "corrected"
it: _infer_value_column() fell back to the single numeric column in
query_pipeline_movement's rows — week_of_quarter — summed week numbers
(176 rows -> 1408), and forced a resynthesis that shipped
"adding $1,408 in ARR".

The fix: the single-numeric-column fallback only applies to a column
whose name looks like money, never a week/order/id/count/score column.
This test reproduces the live incident through the REAL dynamic_query_loop
(the same fast-path finalize), and a negative control restores the old
fallback to prove it reproduces the $1,408 rewrite.
"""
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
sys.path.insert(0, str(Path(__file__).parent.parent))

import logging
logging.disable(logging.CRITICAL)

import api.aggregation_verification as agg
import canary_harness as H
from canary_fixtures import QUERY_PIPELINE_MOVEMENT

RYAN_QUESTION = ("Tell me the amount of pipeline in $ and number of deals we've "
                 "added to the pipeline in the last two weeks")
CORRECT_ANSWER = ("*24 new deals* entered the pipeline, adding *$2,776,296* in ARR. "
                  "10 deals exited ($977,500), so net pipeline change is +$1,798,796. "
                  "Total added: $2,776,296")

# Live row shape: deal_id/company_name/stage/owner_email/close_date are
# strings, week_of_quarter is the ONLY numeric field.
PM_ROWS = [{"deal_id": str(64000000000 + i), "company_name": f"Company{i}",
            "stage": "Discovery", "owner_email": "dan@growthbook.io",
            "close_date": "2026-10-15", "week_of_quarter": 8,
            "backfill_confidence": "high"} for i in range(176)]


def _pm_result():
    r = dict(QUERY_PIPELINE_MOVEMENT)
    r["rows"] = PM_ROWS
    r["summary"] = {"new_to_pipeline": 24, "left_pipeline": 10,
                    "added_arr_total": 2776296, "exited_arr_total": 977500,
                    "net_arr_change": 1798796}
    return r


def _run():
    client = H.ScriptedClient([
        json.dumps({"tool": "query_pipeline_movement",
                    "params": {"view": "movement", "weeks": 2}}),
        json.dumps({"answer": CORRECT_ANSWER}),
        # What the model says if a resynthesis is forced with the bogus value.
        json.dumps({"answer": "24 new deals entered the pipeline, adding $1,408 in ARR."}),
    ])
    orig_handler = H.handlers_module.query_pipeline_movement
    orig = {"classify": H.table_classifier_module.classify_relevant_tables,
            "schema": H.schema_context_module.get_schema_context,
            "anchors": H.router.resolve_snapshot_anchor_dates}

    async def fake(params, sb):
        return _pm_result()

    H.handlers_module.query_pipeline_movement = fake
    H.table_classifier_module.classify_relevant_tables = lambda q, c: ["deals_snapshot"]
    H.schema_context_module.get_schema_context = (
        lambda sb, tables_with_descriptions=None, lightweight=False: "TABLE: deals_snapshot\n  deal_id\n")
    H.router.resolve_snapshot_anchor_dates = lambda sb, tw: (None, None)
    try:
        import asyncio
        result = asyncio.run(H.router.dynamic_query_loop(
            question=RYAN_QUESTION, history=[],
            params={"time_window": {"label": "last 2 weeks",
                                    "start": "2026-09-09", "end": "2026-09-23"}},
            sb=H._FakeSupabase(), client=client))
    finally:
        H.handlers_module.query_pipeline_movement = orig_handler
        H.table_classifier_module.classify_relevant_tables = orig["classify"]
        H.schema_context_module.get_schema_context = orig["schema"]
        H.router.resolve_snapshot_anchor_dates = orig["anchors"]
    return result, client


def test_ordinal_column_is_never_inferred_as_value():
    assert agg._infer_value_column(PM_ROWS) is None
    for name in ("week_of_quarter", "stage_order", "days_since_activity",
                 "overall_score", "deal_count", "pipeline_id"):
        assert agg._infer_value_column([{"k": "x", name: 5}]) is None, name
    assert agg._infer_value_column([{"k": "x", "new_arr": 5}]) == "new_arr"
    assert agg._infer_value_column([{"k": "x", "net_change": 5, "week": 1}]) == "net_change"
    print("✓ week/order/days/score/count/id columns are never summed as a value column")


def test_ryans_question_ships_the_correct_total():
    result, client = _run()
    assert result["answer"].startswith(CORRECT_ANSWER), (
        f"the correct first answer was rewritten: {result['answer']!r}")
    assert "$1,408" not in result["answer"]
    assert len(client.calls) == 2, (
        f"expected tool call + one synthesis, no forced resynthesis — got "
        f"{len(client.calls)} LLM calls")
    print("✓ Ryan's question: the correct $2,776,296 / 24-deal answer ships unchanged")


def test_negative_control_old_fallback_reproduces_the_1408_rewrite():
    orig = agg._looks_like_value_column
    agg._looks_like_value_column = lambda name: True   # the pre-fix fallback
    try:
        result, client = _run()
    finally:
        agg._looks_like_value_column = orig
    assert "$1,408" in result["answer"] and len(client.calls) == 3, (
        f"restoring the old fallback should reproduce the live $1,408 "
        f"rewrite — got {result['answer']!r} after {len(client.calls)} calls")
    print("✓ negative control: the old fallback reproduces the live $1,408 rewrite")


if __name__ == "__main__":
    test_ordinal_column_is_never_inferred_as_value()
    test_ryans_question_ships_the_correct_total()
    test_negative_control_old_fallback_reproduces_the_1408_rewrite()
    print("\n✅ All tests passed")
