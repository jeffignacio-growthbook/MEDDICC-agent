"""
Regression test for PENDING_WORK.md Low Priority #12: the dimension-
verification dead-end.

Symptom (real, reported): a question mentioning "New Business" produced
"⚠️ Verification failed: Question asked about New Business (pipeline)
but query never filtered for it. Retrieved data may be unfiltered.
Required query: filter_table with filters [['eq', 'pipeline_id',
'default'], ['gte', 'week_ending', '2026-08-21'], ['lte', 'week_ending',
'2026-09-11'], ['eq', 'pipeline', 'New Business']]" and then stopped —
no corrected answer ever followed.

Root cause (found via exact-string match against format_verification_
error()'s only call site, api/router.py's finalization-path dimension-
verification gate inside _finalize_from_data): that gate's own log
line said "Cannot retry (budget exhausted)" as if reaching it always
meant the loop's iteration/token budget was exhausted. It doesn't —
_finalize_from_data is invoked with 10 different reason_tags (no_
progress, duplicate_tool_call, id_scoped_enrichment_lookup, no_new_
data, etc.), and only "iterations_exhausted" genuinely correlates to
budget exhaustion. This test reproduces the exact reported scenario via
the "no_progress" reason_tag (two malformed responses in a row) —
budget is nowhere near exhausted — and confirms the gate no longer
gives up unconditionally: required_query is fully deterministic (an
exact filter_table call), so the fix forces it directly, one retry,
before ever giving up.

Two behaviors are proven:
1. When the forced corrective fetch succeeds and the resynthesis then
   verifies cleanly, the loop ships a real, corrected, answered=True
   answer — never the bare warning.
2. When the forced fetch itself fails, the loop gives up with an
   HONEST, COMPLETE message: the original diagnostic AND an explicit
   statement that an automatic retry was attempted and still could not
   produce a verified answer — never a bare warning with nothing after
   it.
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

QUESTION = "How much New Business pipeline moved between 2026-08-21 and 2026-09-11?"

# Mirrors the exact required_query filters from the real reported incident.
BASE_FILTERS = [
    ["eq", "pipeline_id", "default"],
    ["gte", "week_ending", "2026-08-21"],
    ["lte", "week_ending", "2026-09-11"],
]
CORRECTED_FILTERS = BASE_FILTERS + [["eq", "pipeline", "New Business"]]

UNFILTERED_ROWS = [
    {"week_ending": "2026-08-28", "pipeline": "New Business", "net_change": -30000},
    {"week_ending": "2026-08-28", "pipeline": "Renewal", "net_change": -20000},
]
FILTERED_ROWS = [
    {"week_ending": "2026-08-28", "pipeline": "New Business", "net_change": -30000},
]


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
    def table(self, name):
        raise AttributeError(f"no fake support for table {name!r}")


def _make_filter_table_stub(call_log, forced_fetch_should_error=False):
    async def fake_filter_table(sb, table=None, columns=None, filters=None,
                                 limit=200, order_by=None):
        call_log.append({"table": table, "columns": columns, "filters": filters})
        is_corrected = any(
            len(f) >= 3 and f[0] == "eq" and f[1] == "pipeline" and f[2] == "New Business"
            for f in (filters or [])
        )
        if is_corrected:
            if forced_fetch_should_error:
                return {"error": "simulated forced-fetch failure"}
            return {"rows": FILTERED_ROWS, "table": table}
        return {"rows": UNFILTERED_ROWS, "table": table}
    return fake_filter_table


def _run(fake_client, forced_fetch_should_error=False):
    fake_sb = _FakeSupabase()
    filter_table_calls = []
    orig_filter_table = tools_module.filter_table
    orig_classify = table_classifier_module.classify_relevant_tables
    orig_get_schema = schema_context_module.get_schema_context
    orig_resolve_anchor_dates = router.resolve_snapshot_anchor_dates

    tools_module.filter_table = _make_filter_table_stub(
        filter_table_calls, forced_fetch_should_error=forced_fetch_should_error)
    table_classifier_module.classify_relevant_tables = (
        lambda q, client: ["waterfall_weekly"])
    schema_context_module.get_schema_context = (
        lambda sb, tables_with_descriptions=None, lightweight=False:
            "TABLE: waterfall_weekly\n  week_ending, pipeline, pipeline_id, net_change\n")
    router.resolve_snapshot_anchor_dates = (
        lambda sb, time_window: (None, None))

    try:
        result = asyncio.run(router.dynamic_query_loop(
            question=QUESTION,
            history=[],
            params={"time_window": {"label": "3 weeks",
                                     "start": "2026-08-21", "end": "2026-09-11"}},
            sb=fake_sb,
            client=fake_client,
        ))
        return result, filter_table_calls
    finally:
        tools_module.filter_table = orig_filter_table
        table_classifier_module.classify_relevant_tables = orig_classify
        schema_context_module.get_schema_context = orig_get_schema
        router.resolve_snapshot_anchor_dates = orig_resolve_anchor_dates


def _reach_finalize_via_no_progress(forced_fetch_should_error, final_answers):
    """Scripts: one unfiltered tool call, two malformed responses (forcing
    _finalize_from_data("no_progress") — a non-budget reason_tag, exactly
    the case the old code mislabeled as budget-exhausted), then whatever
    finalize-synthesis answers the caller wants scripted after that."""
    initial_call = json.dumps({"tool": "filter_table", "params": {
        "table": "waterfall_weekly",
        "columns": ["week_ending", "pipeline", "net_change"],
        "filters": BASE_FILTERS,
    }})
    malformed = "hmm"  # <=50 chars, no braces: _extract_json returns None,
                        # and it's too short to be treated as a prose answer.
    responses = [initial_call, malformed, malformed] + list(final_answers)
    return _FakeClient(responses)


def test_forced_fetch_succeeds_and_ships_corrected_answer():
    """The core fix: dimension verification fails inside the finalize
    path via a non-budget reason_tag (no_progress), the required_query
    is forced directly (a real filter_table call with the corrective
    pipeline='New Business' filter), and once the resynthesis verifies
    cleanly, a real answered=True answer ships — never the bare warning."""
    unfiltered_answer = json.dumps({
        "answer": "New Business pipeline moved -$50,000 this period."
    })
    corrected_answer = json.dumps({
        "answer": "New Business pipeline (filtered specifically to New "
                   "Business) moved -$30,000 this period."
    })
    fake_client = _reach_finalize_via_no_progress(
        forced_fetch_should_error=False,
        final_answers=[unfiltered_answer, corrected_answer])

    result, filter_calls = _run(fake_client)

    assert result["answered"] is True, (
        f"expected the forced retry to produce a real answer, got: {result}"
    )
    assert "Verification failed" not in result["answer"], (
        "the bare diagnostic warning must never be the final shipped "
        "answer when an automatic retry can resolve it"
    )
    assert "-$30,000" in result["answer"], (
        f"expected the CORRECTED (post-retry) answer to ship, not the "
        f"original unfiltered one — got: {result['answer']!r}"
    )

    corrective_calls = [
        c for c in filter_calls
        if any(f[:3] == ["eq", "pipeline", "New Business"] for f in (c["filters"] or []))
    ]
    assert len(corrective_calls) == 1, (
        f"expected exactly one forced corrective filter_table call with "
        f"the required pipeline filter — got {len(corrective_calls)}: "
        f"{filter_calls}"
    )
    print("✓ dimension-verification failure inside the finalize path "
          "(reached via a non-budget reason_tag) forces the deterministic "
          "corrective query and ships a real, corrected answer")


def test_forced_fetch_failure_gives_honest_complete_message():
    """When the forced corrective fetch itself fails, the loop must NOT
    dead-end on a bare warning: the final message states BOTH that
    verification failed AND that an automatic retry was attempted and
    still could not produce a verified answer."""
    unfiltered_answer = json.dumps({
        "answer": "New Business pipeline moved -$50,000 this period."
    })
    fake_client = _reach_finalize_via_no_progress(
        forced_fetch_should_error=True,
        final_answers=[unfiltered_answer])

    result, _ = _run(fake_client, forced_fetch_should_error=True)

    assert result["answered"] is False
    answer = result["answer"]
    assert "Verification failed" in answer, (
        "the original diagnostic content must still be present"
    )
    assert "automatic retry" in answer.lower(), (
        f"the message must honestly explain a retry was attempted and "
        f"still failed — never a bare warning with nothing after it. "
        f"Got: {answer!r}"
    )
    print("✓ a forced-fetch failure inside the finalize path produces an "
          "honest, complete give-up message — never a bare dead-end warning")


if __name__ == "__main__":
    test_forced_fetch_succeeds_and_ships_corrected_answer()
    test_forced_fetch_failure_gives_honest_complete_message()
    print("\n✅ All tests passed")
