"""
Regression tests for promoting the false-completeness-claim check (aka
`false_segment_partial_claim`, `false_region_partial_claim`,
`false_week_ending_partial_claim`) from log-only to a forced-resynthesis
gate.

History: SYNTHESIS_FIX_TEST_RESULTS.md (2026-09-09) documents this exact
defect — a live answer said "Sep 7: Enterprise flat, other segments
pending" when the retrieved rows actually had all 4 segments present
(with $0 activity, not missing data). The check that detects this
(api/router.py, inside dynamic_query_loop's synthesis-verification
block) correctly logged `false_segment_partial_claim` at the time, but
the code right next to it said, verbatim, "Don't block the answer, just
log for monitoring" — so the false claim shipped to Slack anyway. A
live run two nights later (2026-09-11) reproduced exactly that: the
check fired again, on a win-rate-by-segment question, and there was no
code path that could have stopped the false claim from reaching the
user if the model's own wording happened to repeat it.

This closes that gap the same way the aggregation-completeness gate
(test_aggregation_verification.py) closes its own: detect
deterministically from the retrieved rows, force exactly one
resynthesis naming the problem explicitly, escalate to
_finalize_from_data only if the retry doesn't fix it.

A second, independent fix travels with it: the original check used a
global substring search for "partial"/"pending"/"incomplete" ANYWHERE
in the answer text. That's a false-positive trap — an answer can
legitimately say "3 deals pending signature" without claiming anything
about segment/region/week completeness, and the old check would have
"detected" that as a false claim requiring correction. The gate is now
sentence-scoped: a completeness word only counts if it appears in the
SAME sentence as the dimension's own name. test_unrelated_pending_
language_does_not_trigger_the_gate pins this directly — it's the
reason this fix was safe to make blocking at all; blocking a check that
still had that false-positive shape would have turned every incidental
"pending" into a wasted resynthesis loop.
"""
import asyncio
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

import api.router as router
import api.tools as tools_module
import api.table_classifier as table_classifier_module
import api.schema_context as schema_context_module

# All 4 expected segments present, every one with real (here: zero)
# activity — the exact shape of the 2026-09-09/2026-09-11 incidents.
FOUR_SEGMENT_ROWS = [
    {"week_ending": "2026-09-07", "segment": "Enterprise", "net_change": 0},
    {"week_ending": "2026-09-07", "segment": "Mid-Market", "net_change": 0},
    {"week_ending": "2026-09-07", "segment": "SMB", "net_change": 0},
    {"week_ending": "2026-09-07", "segment": "Unknown", "net_change": 0},
]

FALSE_CLAIM_ANSWER = "Sep 7: Enterprise flat, other segments pending."
CORRECTED_ANSWER = "Sep 7: All segments flat ($0 movement)."


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


def _make_filter_table_stub(rows, call_log):
    async def fake_filter_table(sb, table=None, columns=None, filters=None,
                                 limit=200, order_by=None):
        call_log.append({"table": table, "columns": columns, "filters": filters})
        return {"rows": rows, "table": table}
    return fake_filter_table


def _run(fake_client, rows=FOUR_SEGMENT_ROWS):
    filter_table_calls = []
    orig_filter_table = tools_module.filter_table
    orig_classify = table_classifier_module.classify_relevant_tables
    orig_get_schema = schema_context_module.get_schema_context

    tools_module.filter_table = _make_filter_table_stub(rows, filter_table_calls)
    table_classifier_module.classify_relevant_tables = (
        lambda question, client: ["waterfall_weekly"])
    schema_context_module.get_schema_context = (
        lambda sb, tables_with_descriptions=None, lightweight=False:
            "TABLE: waterfall_weekly\n  week_ending, segment, net_change\n")

    try:
        result = asyncio.run(router.dynamic_query_loop(
            question="how did win rate move by segment this week?",
            history=[],
            params={"time_window": {"label": "this week",
                                     "start": "2026-09-01", "end": "2026-09-08"}},
            sb=_FakeSupabase(),
            client=fake_client,
        ))
    finally:
        tools_module.filter_table = orig_filter_table
        table_classifier_module.classify_relevant_tables = orig_classify
        schema_context_module.get_schema_context = orig_get_schema

    return result, fake_client, filter_table_calls


def test_false_partial_claim_forces_exactly_one_resynthesis():
    tool_call = json.dumps({"tool": "filter_table", "params": {
        "table": "waterfall_weekly",
        "columns": ["week_ending", "segment", "net_change"],
        "filters": [],
    }})
    wrong_answer = json.dumps({"answer": FALSE_CLAIM_ANSWER})
    corrected_answer = json.dumps({"answer": CORRECTED_ANSWER})

    fake_client = _FakeClient([tool_call, wrong_answer, corrected_answer])
    result, fake_client, _ = _run(fake_client)

    assert len(fake_client.calls) == 3, (
        f"expected exactly 3 completion calls (tool call, false-claim "
        f"answer, one forced resynthesis) — got {len(fake_client.calls)}"
    )
    retry_message = fake_client.calls[-1]["messages"][-1]["content"]
    assert "pending" in retry_message.lower() or "partial" in retry_message.lower()
    assert "4" in retry_message, (
        "the correction must name how many values the dimension actually "
        f"has — got: {retry_message!r}"
    )
    assert result["answered"] is True
    assert result["answer"] == CORRECTED_ANSWER, (
        "the corrected second answer must be what ships, not the false "
        "claim from the first draft"
    )
    print("✓ a false 'partial/pending' claim about a fully-covered "
          "dimension forces exactly one resynthesis and the corrected "
          "answer ships")


def test_correct_first_answer_never_triggers_the_gate():
    """False-positive check on the live wiring: an answer that correctly
    states '$0'/'flat' instead of inventing 'pending' must ship on the
    first try — no wasted resynthesis call."""
    tool_call = json.dumps({"tool": "filter_table", "params": {
        "table": "waterfall_weekly",
        "columns": ["week_ending", "segment", "net_change"],
        "filters": [],
    }})
    correct_answer = json.dumps({"answer": CORRECTED_ANSWER})

    fake_client = _FakeClient([tool_call, correct_answer])
    result, fake_client, _ = _run(fake_client)

    assert len(fake_client.calls) == 2, (
        f"a correct first answer must ship without any forced "
        f"resynthesis — got {len(fake_client.calls)} calls"
    )
    assert result["answered"] is True
    assert result["answer"] == CORRECTED_ANSWER
    print("✓ a correct first answer ships immediately with no wasted resynthesis call")


def test_unrelated_pending_language_does_not_trigger_the_gate():
    """The old, log-only check did a bare substring search for 'pending'
    anywhere in the answer. This answer legitimately uses 'pending' in a
    sentence that has nothing to do with segment coverage — the new,
    sentence-scoped check must NOT treat it as a false completeness
    claim, or every ordinary use of the word would burn a resynthesis
    round-trip for nothing."""
    tool_call = json.dumps({"tool": "filter_table", "params": {
        "table": "waterfall_weekly",
        "columns": ["week_ending", "segment", "net_change"],
        "filters": [],
    }})
    benign_answer = (
        "3 deals are pending signature this week. "
        "All 4 segments are accounted for with $0 net movement."
    )
    answer_json = json.dumps({"answer": benign_answer})

    fake_client = _FakeClient([tool_call, answer_json])
    result, fake_client, _ = _run(fake_client)

    assert len(fake_client.calls) == 2, (
        f"an incidental, unrelated use of 'pending' must not trigger a "
        f"forced resynthesis — got {len(fake_client.calls)} calls"
    )
    assert result["answered"] is True
    assert result["answer"] == benign_answer
    print("✓ 'pending' used in an unrelated sentence does not falsely "
          "trigger the completeness-claim gate")


def test_gate_escalates_to_finalize_after_two_unresolved_attempts():
    """If the model repeats the false claim even after correction, the
    loop must not keep asking indefinitely — it escalates to
    _finalize_from_data after the second unresolved attempt, same
    2-strike pattern as the scratchpad-rejection and aggregation-
    completeness gates. _finalize_from_data does its own synthesis call
    from the already-gathered data, so the bound is 3 rejected/attempt
    calls (tool call, 2 false-claim attempts) + 1 finalize synthesis —
    never an unbounded retry loop."""
    tool_call = json.dumps({"tool": "filter_table", "params": {
        "table": "waterfall_weekly",
        "columns": ["week_ending", "segment", "net_change"],
        "filters": [],
    }})
    still_wrong = json.dumps({"answer": FALSE_CLAIM_ANSWER})
    finalize_answer = json.dumps({"answer": CORRECTED_ANSWER})

    # tool call, first false claim, second false claim (still wrong),
    # then _finalize_from_data's own synthesis call from the gathered data.
    fake_client = _FakeClient([tool_call, still_wrong, still_wrong, finalize_answer])
    result, fake_client, _ = _run(fake_client)

    assert len(fake_client.calls) == 4, (
        f"expected the loop to stop asking after 2 unresolved attempts "
        f"and finalize (one bounded extra synthesis call) instead of "
        f"looping indefinitely — got {len(fake_client.calls)} completion calls"
    )
    assert result["answered"] is True
    assert result["answer"] == CORRECTED_ANSWER, (
        "finalize must synthesize its own answer from the gathered data, "
        "not ship the repeated false claim"
    )
    print("✓ two consecutive unresolved false claims escalate to "
          "_finalize_from_data (one bounded extra call) instead of "
          "looping forever")


if __name__ == "__main__":
    test_false_partial_claim_forces_exactly_one_resynthesis()
    test_correct_first_answer_never_triggers_the_gate()
    test_unrelated_pending_language_does_not_trigger_the_gate()
    test_gate_escalates_to_finalize_after_two_unresolved_attempts()
    print("\n✅ All tests passed")
