"""
2026-09-11 (PRIMITIVE_CHECKLIST.md follow-up): the zero-rows suspicion
note (api/router.py, fires when a "which/show/list" enumeration question
returns zero rows from filter_table) injects a directive telling the
model to broaden its filter or state what was checked instead of
asserting absence — but nothing ever verified either happened, exactly
the "detect, log, ship anyway" gap PRIMITIVE_CHECKLIST.md exists to
catch. It wasn't caught by test_primitive_contract.py's structural scan
because it's inline code with no function name matching that test's
detection-style naming patterns.

Fixed with the same compliance-check shape as ambiguous_dimension_
unaddressed (see test_ambiguous_dimension_compliance.py): if the
suspicion fired and no LATER tool call in the same loop found real rows
(self-correction), the final answer must at least acknowledge the check
was made — a bare absence claim with no acknowledgment gets a caveat
appended, and the outcome gets its own queryable bucket
(answered_with_unresolved_zero_row_suspicion). If a later, broader
query DOES find real rows, that's treated as self-correction (same
allowance as false_partial_claim_caught / scratchpad_rejection_fired)
and no caveat is needed.

Heuristic, not exact — consistent with the explicit "naming/pattern
convention, not deep semantic analysis" scope for this whole class of
check.
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

REAL_ROWS = [
    {"deal_id": "2001", "owner_email": "christian@growthbook.io",
     "stage_id": "qualifiedtobuy", "deal_value": 0, "component_arr": 50000},
]
SILENT_ABSENCE_ANSWER = "There are no deals with missing ARR."
ACKNOWLEDGING_ANSWER = (
    "I checked the deal_value field and found no rows — that field may "
    "be defaulted to zero rather than left null, so this isn't a "
    "confirmed absence, just nothing under that specific filter."
)


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
        return _FakeResponse(self._responses[idx])


class _CapturingTable:
    def __init__(self, sink):
        self._sink = sink
        self._pending = None

    def insert(self, data):
        self._pending = data
        return self

    def execute(self):
        self._sink.append(self._pending)
        class _Result:
            data = [self._pending]
        return _Result()


class _FakeSupabaseWithCostLog:
    def __init__(self):
        self.query_cost_log_inserts = []

    def table(self, name):
        if name == "query_cost_log":
            return _CapturingTable(self.query_cost_log_inserts)
        raise AttributeError(f"no fake support for table {name!r}")


def _make_sequenced_filter_table_stub(row_sequence, call_log):
    """Returns row_sequence[i] on the i-th filter_table call (clamped to
    the last entry once exhausted) — needed to simulate a first call
    finding nothing and a later, broader call finding real rows."""
    async def fake_filter_table(sb, table=None, columns=None, filters=None,
                                 limit=200, order_by=None):
        idx = min(len(call_log), len(row_sequence) - 1)
        call_log.append({"table": table, "columns": columns, "filters": filters})
        return {"rows": row_sequence[idx], "table": table}
    return fake_filter_table


def _run(fake_client, row_sequence, sb=None):
    filter_table_calls = []
    orig_filter_table = tools_module.filter_table
    orig_classify = table_classifier_module.classify_relevant_tables
    orig_get_schema = schema_context_module.get_schema_context

    tools_module.filter_table = _make_sequenced_filter_table_stub(row_sequence, filter_table_calls)
    table_classifier_module.classify_relevant_tables = (
        lambda question, client: ["deals"])
    schema_context_module.get_schema_context = (
        lambda sb, tables_with_descriptions=None, lightweight=False:
            "TABLE: deals\n  deal_id, owner_email, stage_id, deal_value\n")

    try:
        result = asyncio.run(router.dynamic_query_loop(
            question="Which deals have no ARR recorded?",
            history=[],
            params={"time_window": {"label": "current",
                                     "start": "2026-08-01", "end": "2026-09-08"}},
            sb=sb if sb is not None else _FakeSupabaseWithCostLog(),
            client=fake_client,
        ))
    finally:
        tools_module.filter_table = orig_filter_table
        table_classifier_module.classify_relevant_tables = orig_classify
        schema_context_module.get_schema_context = orig_get_schema

    return result, fake_client, filter_table_calls


def _tool_call(filters):
    return json.dumps({"tool": "filter_table", "params": {
        "table": "deals",
        "columns": ["deal_id", "owner_email", "stage_id", "deal_value"],
        "filters": filters,
    }})


def test_silent_absence_claim_gets_a_caveat_and_its_own_outcome_bucket():
    tool_call = _tool_call([("is_", "deal_value", "null")])
    silent_answer = json.dumps({"answer": SILENT_ABSENCE_ANSWER})

    fake_client = _FakeClient([tool_call, silent_answer])
    fake_sb = _FakeSupabaseWithCostLog()
    result, fake_client, _ = _run(fake_client, [[]], fake_sb)

    assert result["answered"] is True
    assert SILENT_ABSENCE_ANSWER in result["answer"], (
        "the original answer must still be present — this is a caveat, not a rewrite"
    )
    assert "may be defaulted" in result["answer"].lower() or "defaulted" in result["answer"].lower()

    assert len(fake_sb.query_cost_log_inserts) == 1
    logged = fake_sb.query_cost_log_inserts[0]
    assert logged["outcome"] == "answered_with_unresolved_zero_row_suspicion", (
        f"expected the distinct outcome bucket — got: {logged['outcome']!r}"
    )
    assert logged["primitives_fired"]["zero_rows_suspicion_unresolved"] is True
    assert logged["primitives_fired"]["zero_rows_suspicion_flagged"] is True
    print("✓ a silent absence claim after zero-rows suspicion gets a caveat "
          "and its own queryable outcome bucket")


def test_answer_that_already_acknowledges_the_check_gets_no_spurious_caveat():
    """False-positive check: an answer that already acknowledges the
    filter/defaulted-field caveat itself must not get a redundant one
    piled on top."""
    tool_call = _tool_call([("is_", "deal_value", "null")])
    acknowledging_answer = json.dumps({"answer": ACKNOWLEDGING_ANSWER})

    fake_client = _FakeClient([tool_call, acknowledging_answer])
    fake_sb = _FakeSupabaseWithCostLog()
    result, fake_client, _ = _run(fake_client, [[]], fake_sb)

    assert result["answered"] is True
    assert result["answer"] == ACKNOWLEDGING_ANSWER, (
        f"an answer that already acknowledges the check must ship unchanged — "
        f"got: {result['answer']!r}"
    )
    logged = fake_sb.query_cost_log_inserts[0]
    assert logged["primitives_fired"]["zero_rows_suspicion_unresolved"] is False
    print("✓ an answer that already acknowledges the check gets no redundant caveat")


def test_self_correction_via_a_later_broader_query_needs_no_caveat():
    """The suspicion note's whole point is to prompt the model to
    broaden its filter. If a LATER tool call in the same loop finds
    real rows, that's the suspicion resolving itself — no caveat should
    be appended even though the answer doesn't use any acknowledgment
    language, since there's no unresolved absence claim to caveat."""
    narrow_filter_call = _tool_call([("is_", "component_arr", "null")])
    broad_filter_call = _tool_call([("eq", "deal_value", 0)])
    found_answer = json.dumps({
        "answer": "Found 1 deal with $0 recorded ARR: the Acme deal."
    })

    fake_client = _FakeClient([narrow_filter_call, broad_filter_call, found_answer])
    fake_sb = _FakeSupabaseWithCostLog()
    result, fake_client, calls = _run(fake_client, [[], REAL_ROWS], fake_sb)

    assert result["answered"] is True
    assert "Acme" in result["answer"]
    logged = fake_sb.query_cost_log_inserts[0]
    assert logged["primitives_fired"]["zero_rows_suspicion_flagged"] is True, (
        "the suspicion should still have fired once, on the first empty call"
    )
    assert logged["primitives_fired"]["zero_rows_suspicion_unresolved"] is False, (
        "a later broader query finding real rows should count as self-correction "
        "— no caveat, no unresolved outcome"
    )
    assert logged["outcome"] != "answered_with_unresolved_zero_row_suspicion"
    print("✓ a later broader query finding real rows self-corrects the "
          "suspicion — no spurious caveat")


if __name__ == "__main__":
    tests = [
        test_silent_absence_claim_gets_a_caveat_and_its_own_outcome_bucket,
        test_answer_that_already_acknowledges_the_check_gets_no_spurious_caveat,
        test_self_correction_via_a_later_broader_query_needs_no_caveat,
    ]
    failed = 0
    for t in tests:
        try:
            t()
        except AssertionError as e:
            failed += 1
            print(f"✗ {t.__name__}: {e}")
    if failed:
        print(f"\n{failed}/{len(tests)} tests FAILED")
        sys.exit(1)
    print(f"\n✅ All {len(tests)} tests passed")
