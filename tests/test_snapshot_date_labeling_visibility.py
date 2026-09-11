"""
2026-09-11 (primitive-contract retroactive audit): verify_snapshot_
date_labeling()'s mismatch signal was pure log-only at BOTH of its call
sites in api/router.py — the exact "Don't block the answer, just log
for monitoring" shape the aggregation-completeness check had before
that one was fixed. An answer could label matched deals "as of
2026-09-08" when the data actually came from a different snapshot, and
nothing but a log line anyone would have to go looking for ever
reflected that.

Not promoted to a forced-resynthesis gate like aggregation was, though
— verify_snapshot_date_labeling()'s own docstring documents a real
false-positive risk (a close_date/create_date narrated with "as of"
phrasing that happens not to match a queried snapshot_date), so forcing
a correction loop on every mismatch risks wasted or actively wrong
retries against a plausible false alarm. The proportionate fix instead:
append a caveat directly to what ships, and make the mismatch queryable
via its own outcome bucket, at BOTH call sites (the main loop's happy
path, and _finalize_from_data's own last-resort check) — never silent,
without the false-positive blast radius a hard block would carry.

These tests drive the real dynamic_query_loop end-to-end and confirm:
the caveat reaches the shipped Slack answer, no internal jargon leaks
into it, a correct answer (dates that DO match) never gets a spurious
caveat, and query_cost_log's outcome field gets its own distinct,
queryable bucket — the same standing contract just proven for
aggregation verification.
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

MISMATCHED_ROWS = [
    {"deal_id": "1001", "snapshot_date": "2026-08-24",
     "stage_id": "qualifiedtobuy"},
]
WRONG_DATE_ANSWER = "As of 2026-09-08, 1 deal is in Qualified to Buy."
CORRECT_DATE_ANSWER = "As of 2026-08-24, 1 deal is in Qualified to Buy."


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

    tools_module.filter_table = _make_filter_table_stub(MISMATCHED_ROWS, filter_table_calls)
    table_classifier_module.classify_relevant_tables = (
        lambda question, client: ["deals_snapshot"])
    schema_context_module.get_schema_context = (
        lambda sb, tables_with_descriptions=None, lightweight=False:
            "TABLE: deals_snapshot\n  snapshot_date, stage_id\n")

    try:
        result = asyncio.run(router.dynamic_query_loop(
            question="how many deals are in Qualified to Buy right now?",
            history=[],
            params={"time_window": {"label": "today",
                                     "start": "2026-08-24", "end": "2026-09-08"}},
            sb=sb if sb is not None else _FakeSupabaseWithCostLog(),
            client=fake_client,
        ))
    finally:
        tools_module.filter_table = orig_filter_table
        table_classifier_module.classify_relevant_tables = orig_classify
        schema_context_module.get_schema_context = orig_get_schema

    return result, fake_client, filter_table_calls


def test_mismatched_date_gets_a_caveat_and_its_own_outcome_bucket():
    tool_call = json.dumps({"tool": "filter_table", "params": {
        "table": "deals_snapshot",
        "columns": ["deal_id", "snapshot_date", "stage_id"],
        "filters": [],
    }})
    wrong_answer = json.dumps({"answer": WRONG_DATE_ANSWER})

    fake_client = _FakeClient([tool_call, wrong_answer])
    fake_sb = _FakeSupabaseWithCostLog()
    result, fake_client, _ = _run(fake_client, fake_sb)

    assert result["answered"] is True
    assert WRONG_DATE_ANSWER in result["answer"], (
        "the original answer text must still be present — this is a "
        "caveat, not a rewrite"
    )
    assert "could not be fully verified" not in result["answer"], (
        "must use the date-specific caveat wording, not the aggregation one"
    )
    assert "double-check" in result["answer"].lower()
    for banned in ("resynthesis", "budget", "token", "primitive"):
        assert banned not in result["answer"].lower(), (
            f"internal jargon {banned!r} leaked into the caveat: {result['answer']!r}"
        )

    assert len(fake_sb.query_cost_log_inserts) == 1
    logged = fake_sb.query_cost_log_inserts[0]
    assert logged["outcome"] == "answered_with_unverified_date_labeling", (
        f"expected the distinct outcome bucket — got: {logged['outcome']!r}"
    )
    assert logged["primitives_fired"]["snapshot_date_labeling_unverified"] is True
    print("✓ a mismatched 'as of' date gets a caveat in the shipped answer "
          "and its own queryable outcome bucket")


def test_correct_date_never_gets_a_spurious_caveat():
    """False-positive check on the live wiring: a date that DOES match a
    queried row's snapshot_date must ship clean, no caveat, ordinary
    outcome bucket."""
    tool_call = json.dumps({"tool": "filter_table", "params": {
        "table": "deals_snapshot",
        "columns": ["deal_id", "snapshot_date", "stage_id"],
        "filters": [],
    }})
    correct_answer = json.dumps({"answer": CORRECT_DATE_ANSWER})

    fake_client = _FakeClient([tool_call, correct_answer])
    fake_sb = _FakeSupabaseWithCostLog()
    result, fake_client, _ = _run(fake_client, fake_sb)

    assert result["answered"] is True
    assert result["answer"] == CORRECT_DATE_ANSWER, (
        f"a correct date must ship with no caveat appended — got: {result['answer']!r}"
    )
    logged = fake_sb.query_cost_log_inserts[0]
    assert logged["outcome"] == "answered_cleanly"
    assert logged["primitives_fired"]["snapshot_date_labeling_unverified"] is False
    print("✓ a correctly-labeled date never gets a spurious caveat or "
          "outcome-bucket demotion")


if __name__ == "__main__":
    tests = [
        test_mismatched_date_gets_a_caveat_and_its_own_outcome_bucket,
        test_correct_date_never_gets_a_spurious_caveat,
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
