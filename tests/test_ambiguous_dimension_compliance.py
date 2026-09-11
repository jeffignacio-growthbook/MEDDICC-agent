"""
2026-09-11 (primitive-contract retroactive audit): scan_question_for_
ambiguous_dimension_terms() (added earlier the same night, for the
"Jake's deals" incident) injects a directive telling the model to say
so or ask when a term matches more than one governed value — but
nothing ever verified the model actually DID either, instead of
silently picking one candidate and answering as if there were no
ambiguity at all. That's exactly the failure mode this whole mechanism
exists to prevent, left unchecked: detection without a compliance
check is not the same as a closed loop.

Fixed by adding a compliance check, at both the main loop's happy path
and _finalize_from_data's own synthesis: if an ambiguous term was
flagged and NONE of its candidate names show up anywhere in the
answer, the model didn't address it — a caveat naming the candidates
gets appended, and the outcome gets its own queryable bucket
(answered_with_unaddressed_ambiguity), same contract as every other
detection primitive fixed tonight.

Heuristic, not exact (a model could theoretically address the
ambiguity without literally naming either candidate) — consistent with
the explicit "naming/pattern convention, not deep semantic analysis"
scope for this whole class of check.
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

ROWS = [
    {"deal_id": "1001", "owner_email": "jake.stangl@growthbook.io",
     "stage_id": "qualifiedtobuy", "deal_value": 50000},
]
SILENT_PICK_ANSWER = "This rep has 1 deal worth $50K in Qualified to Buy."
COMPLIANT_ANSWER = (
    "There are two reps named Jake (Jake Stangl and Jake H) — which one "
    "did you mean? Jake Stangl currently has 1 deal worth $50K."
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


def _make_filter_table_stub(rows, call_log):
    async def fake_filter_table(sb, table=None, columns=None, filters=None,
                                 limit=200, order_by=None):
        call_log.append({"table": table, "columns": columns, "filters": filters})
        return {"rows": rows, "table": table}
    return fake_filter_table


def _run(fake_client, sb=None):
    filter_table_calls = []
    orig_filter_table = tools_module.filter_table
    orig_classify = table_classifier_module.classify_relevant_tables
    orig_get_schema = schema_context_module.get_schema_context

    tools_module.filter_table = _make_filter_table_stub(ROWS, filter_table_calls)
    table_classifier_module.classify_relevant_tables = (
        lambda question, client: ["deals"])
    schema_context_module.get_schema_context = (
        lambda sb, tables_with_descriptions=None, lightweight=False:
            "TABLE: deals\n  deal_id, owner_email, stage_id, deal_value\n")

    try:
        result = asyncio.run(router.dynamic_query_loop(
            question="What are Jake's deals?",
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


def test_silent_pick_gets_a_caveat_and_its_own_outcome_bucket():
    tool_call = json.dumps({"tool": "filter_table", "params": {
        "table": "deals",
        "columns": ["deal_id", "owner_email", "stage_id", "deal_value"],
        "filters": [],
    }})
    silent_answer = json.dumps({"answer": SILENT_PICK_ANSWER})

    fake_client = _FakeClient([tool_call, silent_answer])
    fake_sb = _FakeSupabaseWithCostLog()
    result, fake_client, _ = _run(fake_client, fake_sb)

    assert result["answered"] is True
    assert SILENT_PICK_ANSWER in result["answer"], (
        "the original answer must still be present — this is a caveat, "
        "not a rewrite"
    )
    assert "Jake Stangl" in result["answer"]
    assert "Jake H" in result["answer"]
    assert "confirm which" in result["answer"].lower()

    assert len(fake_sb.query_cost_log_inserts) == 1
    logged = fake_sb.query_cost_log_inserts[0]
    assert logged["outcome"] == "answered_with_unaddressed_ambiguity", (
        f"expected the distinct outcome bucket — got: {logged['outcome']!r}"
    )
    assert logged["primitives_fired"]["ambiguous_dimension_unaddressed"] is True
    assert logged["primitives_fired"]["ambiguous_dimension_term_flagged"] is True
    print("✓ a silently-picked ambiguous term gets a caveat naming both "
          "candidates and its own queryable outcome bucket")


def test_compliant_answer_never_gets_a_spurious_caveat():
    """False-positive check: an answer that already names a candidate
    (addressing the ambiguity itself) must not get a redundant caveat
    piled on top."""
    tool_call = json.dumps({"tool": "filter_table", "params": {
        "table": "deals",
        "columns": ["deal_id", "owner_email", "stage_id", "deal_value"],
        "filters": [],
    }})
    compliant_answer = json.dumps({"answer": COMPLIANT_ANSWER})

    fake_client = _FakeClient([tool_call, compliant_answer])
    fake_sb = _FakeSupabaseWithCostLog()
    result, fake_client, _ = _run(fake_client, fake_sb)

    assert result["answered"] is True
    assert result["answer"] == COMPLIANT_ANSWER, (
        f"an answer that already names a candidate must ship unchanged "
        f"— got: {result['answer']!r}"
    )
    logged = fake_sb.query_cost_log_inserts[0]
    assert logged["primitives_fired"]["ambiguous_dimension_unaddressed"] is False
    print("✓ an answer that already addresses the ambiguity gets no "
          "redundant caveat")


if __name__ == "__main__":
    tests = [
        test_silent_pick_gets_a_caveat_and_its_own_outcome_bucket,
        test_compliant_answer_never_gets_a_spurious_caveat,
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
