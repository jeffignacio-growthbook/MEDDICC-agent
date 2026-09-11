"""
Regression tests for the 2026-09-11 aggregation-completeness gate: the
original synthesis-aggregation bug from days ago (dropping a week,
dropping a segment from a stated total) was fixed only at the prompt
level — api/router.py's "CRITICAL AGGREGATION RULE" instructs the model
to "report data from EVERY row/week/segment" and gives worked examples
of the exact two historical incidents:

  MISSING WEEK:   an answer anchored on the most recent week only,
                  dropping earlier weeks from a stated total.
  MISSING SEGMENT: "Aug 28: -$20K" when the real week-28 activity, across
                  BOTH segments retrieved that week, was "$20K won +
                  $100K lost" (net -$80K) — the $100K from the other
                  segment never made it into the stated figure.

A prompt instruction asking the model to be careful is the same category
of fix as asking it not to narrate a scratchpad — it doesn't hold up
(see api/snapshot_diff.py's module docstring for that whole story).
verify_aggregation_completeness() (api/aggregation_verification.py)
closes it at the code level: given the rows actually retrieved and
whatever totals the model's draft answer states, it recomputes the real
sum per stated category and compares, deterministically.

These tests reconstruct both historical incidents (and a correct,
complete aggregation as a false-positive check) as fixtures directly
from the prompt's own worked examples, cover the companion regex-based
extract_stated_totals_from_answer(), and prove the mandatory-gate wiring
end-to-end: a wrong stated total forces exactly one resynthesis with the
discrepancy named explicitly, same escalation pattern as the scratchpad-
rejection gate.
"""
import asyncio
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from api.aggregation_verification import (
    verify_aggregation_completeness,
    extract_stated_totals_from_answer,
)

# The exact retrieved-row shape behind both incidents, reconstructed
# from the prompt's own worked examples in api/router.py's "CRITICAL
# AGGREGATION RULE": three weeks, the last of which has activity in TWO
# segments (Mid-Market won $20K, Enterprise lost $100K — net -$80K for
# that week, not the -$20K the incident's wrong answer stated).
WATERFALL_ROWS = [
    {"week_ending": "2026-08-17", "segment": "Enterprise", "net_change": -75000},
    {"week_ending": "2026-08-24", "segment": "Enterprise", "net_change": 0},
    {"week_ending": "2026-08-28", "segment": "Mid-Market", "net_change": 20000},
    {"week_ending": "2026-08-28", "segment": "Enterprise", "net_change": -100000},
]

# The prompt's own "Correct" example.
CORRECT_ANSWER_TEXT = "Aug 17: $75K lost, Aug 24: $0, Aug 28: $20K won + $100K lost"
# The prompt's own "Wrong" example — the exact missing-segment incident.
MISSING_SEGMENT_ANSWER_TEXT = "Aug 28: -$20K"
# The missing-week incident: a stated PERIOD TOTAL that only reflects
# the most recent week's won figure, dropping the two earlier weeks and
# the loss in the same week entirely.
MISSING_WEEK_ANSWER_TEXT = "Total pipeline movement this period was $20K."
CORRECT_TOTAL_ANSWER_TEXT = "Total pipeline movement this period was -$155K."


def test_missing_segment_incident_is_caught():
    stated = extract_stated_totals_from_answer(MISSING_SEGMENT_ANSWER_TEXT)
    result = verify_aggregation_completeness(WATERFALL_ROWS, stated)
    assert result["match"] is False, (
        f"the missing-segment incident (stated -$20K, real -$80K across "
        f"both segments) must be caught — got {result!r}"
    )
    discrepancy = result["discrepancy"]
    assert discrepancy["category"] == "Aug 28"
    assert discrepancy["stated"] == -20000.0
    assert discrepancy["actual_sum"] == -80000
    assert len(discrepancy["missing_rows"]) == 2, (
        "both Aug 28 rows (Mid-Market won, Enterprise lost) must be "
        "surfaced so a resynthesis retry can show the model exactly "
        "what it needs to account for"
    )
    print("✓ the missing-segment incident ('Aug 28: -$20K' vs the real "
          "-$80K across both segments) is caught")


def test_missing_week_incident_is_caught():
    stated = extract_stated_totals_from_answer(MISSING_WEEK_ANSWER_TEXT)
    result = verify_aggregation_completeness(WATERFALL_ROWS, stated)
    assert result["match"] is False, (
        f"the missing-week incident (stated $20K total, real -$155K "
        f"across all three weeks) must be caught — got {result!r}"
    )
    discrepancy = result["discrepancy"]
    assert discrepancy["category"] == "total"
    assert discrepancy["stated"] == 20000.0
    assert discrepancy["actual_sum"] == -155000
    assert len(discrepancy["missing_rows"]) == 4, (
        "a 'total' discrepancy must be checked against ALL retrieved "
        "rows, not just the most recent week"
    )
    print("✓ the missing-week incident (stated $20K total vs the real "
          "-$155K across all three weeks) is caught")


def test_correct_complete_aggregation_is_not_a_false_positive():
    stated = extract_stated_totals_from_answer(CORRECT_ANSWER_TEXT)
    result = verify_aggregation_completeness(WATERFALL_ROWS, stated)
    assert result == {"match": True}, (
        f"the prompt's own 'Correct' worked example must pass cleanly "
        f"— got {result!r}"
    )
    print("✓ the correct, complete per-week/per-segment breakdown does not false-positive")


def test_correct_total_is_not_a_false_positive():
    stated = extract_stated_totals_from_answer(CORRECT_TOTAL_ANSWER_TEXT)
    result = verify_aggregation_completeness(WATERFALL_ROWS, stated)
    assert result == {"match": True}
    print("✓ a correctly stated grand total does not false-positive")


def test_extraction_nets_multiple_amounts_on_one_line():
    stated = extract_stated_totals_from_answer(CORRECT_ANSWER_TEXT)
    assert stated["Aug 17"] == -75000.0
    assert stated["Aug 24"] == 0.0
    assert stated["Aug 28"] == -80000.0, (
        "'$20K won + $100K lost' must net to -80000 (won is positive, "
        "lost is negative), matching what verify_aggregation_"
        "completeness() compares against a single recomputed row-sum"
    )
    print("✓ extraction nets multiple signed amounts on one line ('$20K won + $100K lost' -> -80000)")


def test_no_rows_or_no_stated_totals_is_not_a_false_positive():
    assert verify_aggregation_completeness([], {"total": 100}) == {"match": True}
    assert verify_aggregation_completeness(WATERFALL_ROWS, {}) == {"match": True}
    print("✓ missing rows or missing stated totals degrade to 'nothing to disprove', not a false alarm")


def test_tolerance_absorbs_rounding_noise():
    # $75K rounds an exact $74,850 — within the default 0.5 tolerance is
    # too strict for that; use a stated figure within actual rounding
    # noise a model's "$K" formatting would introduce.
    rows = [{"week_ending": "2026-08-17", "net_change": -75000.3}]
    result = verify_aggregation_completeness(rows, {"total": -75000.3}, tolerance=0.5)
    assert result == {"match": True}
    print("✓ a stated figure within tolerance of the real sum is not flagged")


# --- End-to-end: the mandatory gate forces exactly one resynthesis ---

import api.router as router
import api.tools as tools_module
import api.table_classifier as table_classifier_module
import api.schema_context as schema_context_module


class _FakeResponse:
    def __init__(self, text, input_tokens=1000, output_tokens=100):
        self.text = text
        self.input_tokens = input_tokens
        self.output_tokens = output_tokens


class _FakeClient:
    def __init__(self, responses):
        self._responses = list(responses)
        self.calls = []

    def complete(self, messages=None, system=None, max_tokens=None):
        idx = len(self.calls)
        self.calls.append({"messages": messages, "system": system})
        assert idx < len(self._responses), (
            f"FakeClient received more complete() calls ({idx + 1}) than "
            f"scripted responses ({len(self._responses)})."
        )
        return _FakeResponse(self._responses[idx])


class _FakeSupabase:
    pass


def _make_filter_table_stub(call_log):
    async def fake_filter_table(sb, table=None, columns=None, filters=None,
                                 limit=200, order_by=None):
        call_log.append({"table": table, "columns": columns, "filters": filters})
        return {"rows": WATERFALL_ROWS, "table": table}
    return fake_filter_table


def _run(fake_client):
    filter_table_calls = []
    orig_filter_table = tools_module.filter_table
    orig_classify = table_classifier_module.classify_relevant_tables
    orig_get_schema = schema_context_module.get_schema_context

    tools_module.filter_table = _make_filter_table_stub(filter_table_calls)
    table_classifier_module.classify_relevant_tables = (
        lambda question, client: ["waterfall_weekly"])
    schema_context_module.get_schema_context = (
        lambda sb, tables_with_descriptions=None, lightweight=False:
            "TABLE: waterfall_weekly\n  week_ending, segment, net_change\n")

    try:
        result = asyncio.run(router.dynamic_query_loop(
            question="how much pipeline moved this quarter?",
            history=[],
            params={"time_window": {"label": "this quarter",
                                     "start": "2026-08-01", "end": "2026-09-08"}},
            sb=_FakeSupabase(),
            client=fake_client,
        ))
    finally:
        tools_module.filter_table = orig_filter_table
        table_classifier_module.classify_relevant_tables = orig_classify
        schema_context_module.get_schema_context = orig_get_schema

    return result, fake_client, filter_table_calls


def test_wrong_total_forces_exactly_one_resynthesis_with_discrepancy_named():
    tool_call = json.dumps({"tool": "filter_table", "params": {
        "table": "waterfall_weekly",
        "columns": ["week_ending", "segment", "net_change"],
        "filters": [],
    }})
    wrong_answer = json.dumps({"answer": MISSING_SEGMENT_ANSWER_TEXT})
    corrected_answer = json.dumps({"answer": CORRECT_ANSWER_TEXT})

    fake_client = _FakeClient([tool_call, wrong_answer, corrected_answer])
    result, fake_client, _ = _run(fake_client)

    assert len(fake_client.calls) == 3, (
        f"expected exactly 3 completion calls (tool call, wrong answer, "
        f"one forced resynthesis) — got {len(fake_client.calls)}"
    )
    retry_message = fake_client.calls[-1]["messages"][-1]["content"]
    assert "20,000" in retry_message or "-20,000" in retry_message, (
        f"the resynthesis retry must name the STATED figure explicitly "
        f"— got: {retry_message!r}"
    )
    assert "80,000" in retry_message or "-80,000" in retry_message, (
        f"the resynthesis retry must name the ACTUAL sum explicitly, "
        f"same escalation pattern as the scratchpad-rejection gate "
        f"('you said $120K total but the retrieved rows sum to $195K') "
        f"— got: {retry_message!r}"
    )
    assert result["answered"] is True
    assert result["answer"] == CORRECT_ANSWER_TEXT, (
        "the corrected second answer must be what ships, not the "
        "original wrong one"
    )
    print("✓ a wrong stated total forces exactly one resynthesis, "
          "naming both the stated and actual figures explicitly, and "
          "the corrected answer ships")


def test_correct_first_answer_never_triggers_a_resynthesis():
    """False-positive check on the live wiring, not just the pure
    function: a correct answer on the FIRST try must ship immediately —
    no wasted resynthesis call."""
    tool_call = json.dumps({"tool": "filter_table", "params": {
        "table": "waterfall_weekly",
        "columns": ["week_ending", "segment", "net_change"],
        "filters": [],
    }})
    correct_answer = json.dumps({"answer": CORRECT_ANSWER_TEXT})

    fake_client = _FakeClient([tool_call, correct_answer])
    result, fake_client, _ = _run(fake_client)

    assert len(fake_client.calls) == 2, (
        f"a correct first answer must ship without any forced "
        f"resynthesis — got {len(fake_client.calls)} calls"
    )
    assert result["answered"] is True
    assert result["answer"] == CORRECT_ANSWER_TEXT
    print("✓ a correct first answer ships immediately with no wasted resynthesis call")


if __name__ == "__main__":
    test_missing_segment_incident_is_caught()
    test_missing_week_incident_is_caught()
    test_correct_complete_aggregation_is_not_a_false_positive()
    test_correct_total_is_not_a_false_positive()
    test_extraction_nets_multiple_amounts_on_one_line()
    test_no_rows_or_no_stated_totals_is_not_a_false_positive()
    test_tolerance_absorbs_rounding_noise()
    test_wrong_total_forces_exactly_one_resynthesis_with_discrepancy_named()
    test_correct_first_answer_never_triggers_a_resynthesis()
    print("\n✅ All tests passed")
