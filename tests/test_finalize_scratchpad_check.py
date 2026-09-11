"""
2026-09-11 (primitive-contract retroactive audit): the scratchpad-
narration check (_looks_like_unfinished_scratchpad(), TEST 0f/0i) runs
at two sites in the main loop's own answer path, but was never
re-applied to _finalize_from_data's OWN synthesis call — exactly the
one place scratchpad narration is most likely to leak (a last-resort
synthesis under pressure, already escalated here because something
upstream went wrong twice). A scratchpad-y finalize answer would have
shipped as answered=True, indistinguishable in the coarse outcome field
from an ordinary clean success, with raw internal reasoning delivered
to Slack verbatim.

Fixed by re-applying the same check to _finalize_from_data's own
parsed answer: if it looks like unfinished scratchpad narration, this
doesn't try to salvage or retry it — it hands off to the same give-up
path any other finalize failure uses (answered=False, a real reason_tag
column, and _diagnostic_answer's plain-language text), which is already
both queryable and user-visible by construction. An honest "couldn't
produce a clean answer" beats shipping leaked reasoning as if it were
a finished one.

This test drives the real dynamic_query_loop end-to-end: the model
narrates scratchpad prose twice in the main loop (escalating to
_finalize_from_data), and THEN the finalize synthesis call itself also
comes back scratchpad-y — the worst case, proving the new check catches
it where nothing did before.
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
    {"week_ending": "2026-08-24", "segment": "Enterprise", "net_change": -75000},
]
SCRATCHPAD_ANSWER = "Let me now compute the final total and present it clearly."
CLEAN_ANSWER = "Pipeline moved -$75K the week of Aug 24."


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


class _FakeSupabase:
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
        lambda question, client: ["waterfall_weekly"])
    schema_context_module.get_schema_context = (
        lambda sb, tables_with_descriptions=None, lightweight=False:
            "TABLE: waterfall_weekly\n  week_ending, segment, net_change\n")

    try:
        result = asyncio.run(router.dynamic_query_loop(
            question="how did pipeline move last week?",
            history=[],
            params={"time_window": {"label": "last week",
                                     "start": "2026-08-17", "end": "2026-08-24"}},
            sb=sb if sb is not None else _FakeSupabase(),
            client=fake_client,
        ))
    finally:
        tools_module.filter_table = orig_filter_table
        table_classifier_module.classify_relevant_tables = orig_classify
        schema_context_module.get_schema_context = orig_get_schema

    return result, fake_client, filter_table_calls


def test_scratchpad_finalize_answer_gives_up_honestly_instead_of_shipping():
    tool_call = json.dumps({"tool": "filter_table", "params": {
        "table": "waterfall_weekly",
        "columns": ["week_ending", "segment", "net_change"],
        "filters": [],
    }})
    scratchpad_answer = json.dumps({"answer": SCRATCHPAD_ANSWER})

    # tool call, 2 scratchpad-rejected main-loop attempts (escalates to
    # _finalize_from_data), then finalize's OWN synthesis also comes
    # back scratchpad-y.
    fake_client = _FakeClient(
        [tool_call, scratchpad_answer, scratchpad_answer, scratchpad_answer])
    fake_sb = _FakeSupabase()
    result, fake_client, _ = _run(fake_client, fake_sb)

    assert result["answered"] is False, (
        "a scratchpad-y finalize answer must never ship as a success"
    )
    assert SCRATCHPAD_ANSWER not in result["answer"], (
        f"the raw scratchpad narration must never reach the user — got: "
        f"{result['answer']!r}"
    )
    assert "let me now" not in result["answer"].lower()

    assert len(fake_sb.query_cost_log_inserts) == 1
    logged = fake_sb.query_cost_log_inserts[0]
    assert logged["reason_tag"] == "finalize_synthesis_scratchpad", (
        f"expected a distinct, directly-queryable reason_tag (not the "
        f"ambient escalation reason) — got: {logged['reason_tag']!r}"
    )
    assert logged["primitives_fired"]["finalize_scratchpad_caught"] is True
    print("✓ a scratchpad-y finalize synthesis gives up honestly instead "
          "of shipping leaked reasoning as a success, with a distinct "
          "queryable reason_tag")


def test_clean_finalize_answer_still_ships_normally():
    """False-positive check: a genuinely clean finalize answer must
    still ship as answered=True — this fix must not make finalize
    stricter than it needs to be."""
    tool_call = json.dumps({"tool": "filter_table", "params": {
        "table": "waterfall_weekly",
        "columns": ["week_ending", "segment", "net_change"],
        "filters": [],
    }})
    scratchpad_answer = json.dumps({"answer": SCRATCHPAD_ANSWER})
    clean_finalize_answer = json.dumps({"answer": CLEAN_ANSWER})

    fake_client = _FakeClient(
        [tool_call, scratchpad_answer, scratchpad_answer, clean_finalize_answer])
    result, fake_client, _ = _run(fake_client)

    assert result["answered"] is True
    assert result["answer"] == CLEAN_ANSWER
    print("✓ a genuinely clean finalize answer still ships as a success")


if __name__ == "__main__":
    tests = [
        test_scratchpad_finalize_answer_gives_up_honestly_instead_of_shipping,
        test_clean_finalize_answer_still_ships_normally,
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
