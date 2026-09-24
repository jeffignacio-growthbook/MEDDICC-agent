"""
Regression tests for the 2026-09-19 synthesis-truncation fix.

BACKGROUND: the Handler 4 (query_rep_pipeline) truncation bug — 94 real
deals silently reduced to 16-25 in the synthesized answer — was fixed by
detecting "complete structured datasets" and skipping the [:3000] hard
truncation applied to every tool result before it reaches the LLM. That
detection was a pattern-match on query_rep_pipeline's OWN return shape
("summary" in result and "total_deals" in result["summary"]), not a real
"is this a finished, structured result" test.

Auditing the three OTHER already-migrated handlers against that exact
condition (see PENDING_WORK.md, "SYSTEMIC FINDING: Synthesis-truncation
bug is pipeline-wide") found all three fail it structurally — none of
them nests its totals under a literal "summary" key — and confirmed,
using their own previously-captured production baselines
(tests/fixtures/query_pipeline_baseline.json,
tests/fixtures/query_stale_deals_baseline.json), that this is not a
theoretical exposure: query_pipeline's realistic "show me pipeline"
payload is 7,654 chars and query_stale_deals' realistic "what deals are
stale" payload is 14,207 chars — both routinely truncated to 3,000 chars
before an LLM ever saw them, exactly the Handler 4 bug, in production,
independent of Handler 5/6 migration work.

THE FIX (api/router.py, api/evaluator.py): the detection condition is now
structural instead of shape-specific — `tool_name in
api.evaluator.STRUCTURED_HANDLERS` (the same registry evaluate_result()
already uses to know a handler's return isn't raw "rows" to sample).
Extracted into one shared helper, _serialize_tool_result_for_synthesis(),
used at both truncation sites that existed in api/router.py (the main
loop body, and _append_tool_result_message() — the second site was
"discovered along the way": it had its own independent, unconditional
[:3000] cut that the original Handler 4 fix never touched, used by three
early-return synthesis shortcuts).

These tests drive the REAL dynamic_query_loop end-to-end (scripted LLM
responses; only the DB-touching handler functions themselves are
stubbed, returning the EXACT captured production baseline data — not
synthetic fixtures), reproducing query_pipeline's and query_stale_deals'
own worst-case realistic payloads and confirming the full data — not a
sample — now reaches the message the LLM actually synthesizes from.

NOT independently confirmable in this environment: an actual LLM
producing correct English from that data (no ANTHROPIC_API_KEY / live
Supabase credentials available here) — these tests instead prove the
exact thing that was broken: the CONTENT handed to the model. A model
given the real, complete total_deals=313 (or 64 stale deals summing to
$987,194.02) and told explicitly "this is the complete dataset, state it
exactly" has what it needs; a model handed the same payload cut off
mid-list at char 3000 (the pre-fix behavior, reproduced here as a
negative control) structurally cannot, no matter how good the model is —
which is exactly how Handler 4's 94-deals-became-16 was possible with no
prompting change at all.
"""
import asyncio
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

import api.router as router
import api.handlers as handlers_module
import api.evaluator as evaluator_module
import api.tools as tools_module
import api.table_classifier as table_classifier_module
import api.schema_context as schema_context_module

FIXTURES_DIR = Path(__file__).parent / "fixtures"

QUERY_PIPELINE_RESULT = json.load(
    open(FIXTURES_DIR / "query_pipeline_baseline.json")
)["test_cases"][0]["result"]  # "no_filters" — the realistic default question
QUERY_STALE_DEALS_RESULT = json.load(
    open(FIXTURES_DIR / "query_stale_deals_baseline.json")
)["test_cases"][0]["result"]  # "no_filters_default_21_days" — realistic default

# Confirmed markers: real company names from the actual captured payload
# that sit PAST byte 3000 of json.dumps(result) — i.e. exactly what the
# old [:3000] truncation silently discarded. Not synthetic canaries;
# these are the 7th of 20 listed deals (query_pipeline) and the 15th of
# 64 stale deals (query_stale_deals) in real, previously-captured
# production data.
QUERY_PIPELINE_JSON = json.dumps(QUERY_PIPELINE_RESULT, default=str)
QUERY_STALE_DEALS_JSON = json.dumps(QUERY_STALE_DEALS_RESULT, default=str)
assert len(QUERY_PIPELINE_JSON) == 7654, (
    "fixture changed size — re-derive PIPELINE_MARKER's position")
assert len(QUERY_STALE_DEALS_JSON) == 14207, (
    "fixture changed size — re-derive STALE_MARKER's position")
PIPELINE_MARKER = "UPS"
assert QUERY_PIPELINE_JSON.find(f'"{PIPELINE_MARKER}"') > 3000
STALE_MARKER = "Opera"
assert QUERY_STALE_DEALS_JSON.find(json.dumps(STALE_MARKER)) > 3000

FINAL_ANSWER_TEXT = "Here is the full pipeline breakdown."


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
    """No real DB access — the handler under test is stubbed directly,
    so nothing here should ever be touched by the mechanism under test."""
    pass


def _run(fake_client, question, tool_call_json):
    """Drives ONE tool call (a migrated handler) then a final answer
    through the real dynamic_query_loop, with only the classification/
    schema-context scaffolding stubbed — matching the pattern established
    in test_finalize_shortcut_message_gap.py."""
    orig_classify = table_classifier_module.classify_relevant_tables
    orig_get_schema = schema_context_module.get_schema_context
    table_classifier_module.classify_relevant_tables = (
        lambda question, client: ["deals"])
    schema_context_module.get_schema_context = (
        lambda sb, tables_with_descriptions=None, lightweight=False:
            "TABLE: deals\n  deal_id, company_name, arr_usd, stage, owner_email\n")
    try:
        result = asyncio.run(router.dynamic_query_loop(
            question=question, history=[],
            params={"time_window": {
                "label": "current quarter",
                "start": "2026-08-01",
                "end": "2026-10-31",
            }},
            sb=_FakeSupabase(), client=fake_client,
        ))
    finally:
        table_classifier_module.classify_relevant_tables = orig_classify
        schema_context_module.get_schema_context = orig_get_schema
    return result


def test_query_pipeline_full_payload_reaches_synthesis():
    """The core fix, for query_pipeline: its real 313-deal/7,654-char
    baseline result must reach the synthesis call whole — including the
    marker deal (UPS) that sits past the old [:3000] cutoff."""
    orig_handler = handlers_module.query_pipeline

    async def fake_query_pipeline(params, sb):
        return QUERY_PIPELINE_RESULT

    handlers_module.query_pipeline = fake_query_pipeline
    try:
        tool_call = json.dumps({"tool": "query_pipeline", "params": {}})
        final_answer = json.dumps({"answer": FINAL_ANSWER_TEXT})
        fake_client = _FakeClient([tool_call, final_answer])
        result = _run(fake_client, "show me our pipeline", tool_call)
    finally:
        handlers_module.query_pipeline = orig_handler

    assert len(fake_client.calls) == 2, (
        f"expected 2 completion calls (tool call, synthesis) — got "
        f"{len(fake_client.calls)}: this usually means the handler was "
        f"treated as low-quality and the loop fell through to a "
        f"different path instead of synthesizing directly"
    )
    synthesis_messages = fake_client.calls[-1]["messages"]
    serialized = json.dumps(synthesis_messages, default=str)

    assert '"313"' in serialized or "313" in serialized, (
        "the true total_deals (313) must reach the synthesis context"
    )
    assert f'\\"{PIPELINE_MARKER}\\"' in serialized or f'"{PIPELINE_MARKER}"' in serialized, (
        f"deal {PIPELINE_MARKER!r} sits past byte 3000 of the real "
        f"7,654-char query_pipeline payload — under the pre-fix "
        f"[:3000] truncation this and every deal after it (14 of the "
        f"20 listed, plus the by_owner breakdown and synthesis notes) "
        f"would be silently absent from what the LLM sees. It must be "
        f"present now."
    )
    assert "COMPLETE DATASET" in serialized, (
        "expected the explicit 'this is the complete dataset' instruction "
        "now that query_pipeline is recognized as a structured handler"
    )
    print("✓ query_pipeline's full 7,654-char / 313-deal payload (including "
          f"the {PIPELINE_MARKER!r} marker past the old 3000-char cutoff) "
          "reaches the synthesis call intact")


def test_query_stale_deals_full_payload_reaches_synthesis():
    """Same proof for query_stale_deals: its real 64-deal/14,207-char
    default-question baseline (nearly 5x the old truncation threshold)
    must reach synthesis whole."""
    orig_handler = handlers_module.query_stale_deals

    async def fake_query_stale_deals(params, sb):
        return QUERY_STALE_DEALS_RESULT

    handlers_module.query_stale_deals = fake_query_stale_deals
    try:
        tool_call = json.dumps({"tool": "query_stale_deals", "params": {}})
        final_answer = json.dumps({"answer": FINAL_ANSWER_TEXT})
        fake_client = _FakeClient([tool_call, final_answer])
        result = _run(fake_client, "what deals are stale", tool_call)
    finally:
        handlers_module.query_stale_deals = orig_handler

    assert len(fake_client.calls) == 2, (
        f"expected 2 completion calls (tool call, synthesis) — got "
        f"{len(fake_client.calls)}"
    )
    synthesis_messages = fake_client.calls[-1]["messages"]
    serialized = json.dumps(synthesis_messages, default=str)

    assert "987194.02" in serialized or "987,194.02" in serialized, (
        "the true total_stale_pipeline ($987,194.02, matching PENDING_WORK"
        ".md's documented 64-deal baseline) must reach the synthesis context"
    )
    assert f'\\"{STALE_MARKER}\\"' in serialized or f'"{STALE_MARKER}"' in serialized, (
        f"deal {STALE_MARKER!r} is the 15th of 64 stale deals and sits "
        f"past byte 3000 of the real 14,207-char payload — nearly 5x "
        f"the old truncation cutoff, this and every deal after it would "
        f"be silently dropped pre-fix. It must be present now."
    )
    print("✓ query_stale_deals' full 14,207-char / 64-deal default-question "
          f"payload (including the {STALE_MARKER!r} marker) reaches the "
          "synthesis call intact")


def test_without_the_fix_the_markers_would_be_truncated_away():
    """Negative-control / mechanism proof: with STRUCTURED_HANDLERS
    neutralized (simulating query_pipeline/query_stale_deals never having
    been registered — i.e. the exact pre-fix state for these two
    handlers), both markers must be ABSENT from the synthesis context,
    proving the STRUCTURED_HANDLERS check — not the test harness — is
    what makes the data visible in the two tests above."""
    orig_structured = dict(evaluator_module.STRUCTURED_HANDLERS)
    # Remove just these two handlers — evaluate_result() falls back to its
    # row-based path, but that's irrelevant here: it only affects result
    # QUALITY classification, not truncation. STRUCTURED_HANDLERS is
    # mutated in place because api.router imports it via
    # `from api.evaluator import STRUCTURED_HANDLERS` *inside* the
    # function body on each call (see _serialize_tool_result_for_
    # synthesis) — so mutating the dict evaluator_module holds is visible
    # to router.py without needing to patch router's own namespace.
    del evaluator_module.STRUCTURED_HANDLERS["query_pipeline"]
    del evaluator_module.STRUCTURED_HANDLERS["query_stale_deals"]

    orig_qp = handlers_module.query_pipeline
    orig_qsd = handlers_module.query_stale_deals

    async def fake_query_pipeline(params, sb):
        return QUERY_PIPELINE_RESULT

    async def fake_query_stale_deals(params, sb):
        return QUERY_STALE_DEALS_RESULT

    handlers_module.query_pipeline = fake_query_pipeline
    handlers_module.query_stale_deals = fake_query_stale_deals
    # 2026-09-23: since the aggregated-view fix, an unregistered handler's
    # result is no longer cut to [:3000] either (see
    # test_unregistered_handler_is_still_not_truncated below), so the
    # real pre-fix state needs the original serializer back too.
    orig_serialize = router._serialize_tool_result_for_synthesis
    router._serialize_tool_result_for_synthesis = (
        lambda result, tool_name, aggregated=None: (
            (json.dumps(result, default=str), "")
            if tool_name in evaluator_module.STRUCTURED_HANDLERS
            else (json.dumps(result, default=str)[:3000], "")))
    try:
        tool_call = json.dumps({"tool": "query_pipeline", "params": {}})
        final_answer = json.dumps({"answer": FINAL_ANSWER_TEXT})
        fake_client = _FakeClient([tool_call, final_answer])
        _run(fake_client, "show me our pipeline", tool_call)
        pipeline_serialized = json.dumps(fake_client.calls[-1]["messages"], default=str)

        tool_call2 = json.dumps({"tool": "query_stale_deals", "params": {}})
        fake_client2 = _FakeClient([tool_call2, final_answer])
        _run(fake_client2, "what deals are stale", tool_call2)
        stale_serialized = json.dumps(fake_client2.calls[-1]["messages"], default=str)
    finally:
        handlers_module.query_pipeline = orig_qp
        handlers_module.query_stale_deals = orig_qsd
        router._serialize_tool_result_for_synthesis = orig_serialize
        evaluator_module.STRUCTURED_HANDLERS.clear()
        evaluator_module.STRUCTURED_HANDLERS.update(orig_structured)

    # Escape-aware: the synthesis messages are JSON-dumped here, so the
    # marker appears as \"UPS\" — the unescaped-only check this used to
    # make could never match, so it passed without proving anything.
    def _present(marker, text):
        return f'\\"{marker}\\"' in text or f'"{marker}"' in text

    assert not _present(PIPELINE_MARKER, pipeline_serialized), (
        f"with query_pipeline removed from STRUCTURED_HANDLERS "
        f"(simulating the pre-fix state), {PIPELINE_MARKER!r} must be "
        f"absent — this proves the STRUCTURED_HANDLERS check, not the "
        f"test harness, is what makes it visible in the test above"
    )
    assert not _present(STALE_MARKER, stale_serialized), (
        f"same proof for query_stale_deals — {STALE_MARKER!r} must be "
        f"absent with the handler unregistered"
    )
    print("✓ confirmed: without STRUCTURED_HANDLERS registration, both "
          "markers are genuinely truncated away — this is the exact "
          "mechanism behind the live query_pipeline/query_stale_deals "
          "exposure this fix closes")


def test_query_waterfall_is_covered_by_the_same_structural_fix():
    """query_waterfall has no baseline fixture (unlike query_pipeline and
    query_stale_deals — see PENDING_WORK.md's systemic finding), so its
    real production payload size isn't empirically confirmed here. But it
    IS already registered in api.evaluator.STRUCTURED_HANDLERS
    (["pipeline_summary", "waterfall"]), so the structural fix covers it
    automatically — this test proves that directly, using a large
    synthetic payload shaped like its actual return value (top-level keys
    pipeline_summary/waterfall/period/report_shape/cache_payload, an
    uncapped cache_payload.deals list — see api/handlers.py's
    query_waterfall(), which has no [:20]-style limit on that list).

    2026-09-24: cache_payload itself is now dropped before synthesis
    (router._model_view; the model computed an unstated-basis "Wins to
    date" from its raw rows). So "not truncated" is measured on everything
    else, made large through the per-week by_slice rows, and cache_payload
    must be absent."""
    big_deals = [{"deal_id": str(i), "company_name": f"WaterfallCo{i}",
                  "arr_usd": 10000 + i} for i in range(150)]
    synthetic_waterfall_result = {
        "pipeline_summary": {
            "total_incremental_arr": 5_000_000, "total_open_count": 150,
            "population_statement": "150 qualified new-business deals.",
            "by_stage": [{"stage_name": f"Stage{i}", "count": 10, "arr": 100000}
                         for i in range(10)],
            "needs_attention": {"no_arr_count": 0, "no_arr_deals": [],
                                 "at_risk_count": 0, "at_risk_deals": []},
        },
        "waterfall": [{"week_ending": f"2026-0{i%9+1}-01", "new_pipeline_value": 100000,
                       "by_slice": [{"region": f"Region{i}_{j}", "segment": "SMB",
                                     "new_pipeline_value": 1000 + j} for j in range(12)]}
                      for i in range(13)],
        "period": "FY2027 Q3",
        "report_shape": "snapshot",
        "cache_payload": {"deals": big_deals},
    }
    assert "summary" not in synthetic_waterfall_result, (
        "sanity check on the fixture itself: query_waterfall's real "
        "return has no top-level 'summary' key (pipeline_summary is a "
        "different key) — this must stay true for this test to mean "
        "anything"
    )
    model_visible = {k: v for k, v in synthetic_waterfall_result.items() if k != "cache_payload"}
    payload_size = len(json.dumps(model_visible, default=str))
    assert payload_size > 3000, (
        f"fixture must exceed the old truncation threshold to prove "
        f"anything — got {payload_size} chars"
    )

    result_json, complete_instruction = router._serialize_tool_result_for_synthesis(
        synthetic_waterfall_result, "query_waterfall")

    assert len(result_json) == payload_size, (
        f"query_waterfall must NOT be truncated — got {len(result_json)} "
        f"chars of a {payload_size}-char payload"
    )
    assert "Region12_11" in result_json, (
        "the last slice of the last week must survive — this is exactly "
        "the kind of entry the old [:3000] cut would have silently dropped"
    )
    assert "WaterfallCo" not in result_json and '"cache_payload"' not in result_json, (
        "cache_payload is for save_thread, never for the model"
    )
    assert complete_instruction, (
        "expected the 'complete dataset' instruction for a recognized "
        "structured handler"
    )
    print("✓ query_waterfall (no baseline fixture, but already registered "
          "in STRUCTURED_HANDLERS) is covered by the same structural fix — "
          "confirmed against a large synthetic payload shaped like its "
          "real, uncapped return value")


def test_unregistered_handler_is_still_not_truncated():
    """Second line of defense (2026-09-23): even a handler missing from
    STRUCTURED_HANDLERS now reaches synthesis as its complete aggregated
    view (a rows-free structured result passes through whole) instead of
    a [:3000] cut — so forgetting to register the next handler no longer
    silently truncates it."""
    orig_structured = dict(evaluator_module.STRUCTURED_HANDLERS)
    del evaluator_module.STRUCTURED_HANDLERS["query_pipeline"]
    orig_qp = handlers_module.query_pipeline

    async def fake_query_pipeline(params, sb):
        return QUERY_PIPELINE_RESULT

    handlers_module.query_pipeline = fake_query_pipeline
    try:
        tool_call = json.dumps({"tool": "query_pipeline", "params": {}})
        final_answer = json.dumps({"answer": FINAL_ANSWER_TEXT})
        fake_client = _FakeClient([tool_call, final_answer])
        _run(fake_client, "show me our pipeline", tool_call)
        serialized = json.dumps(fake_client.calls[-1]["messages"], default=str)
    finally:
        handlers_module.query_pipeline = orig_qp
        evaluator_module.STRUCTURED_HANDLERS.clear()
        evaluator_module.STRUCTURED_HANDLERS.update(orig_structured)

    assert f'\\"{PIPELINE_MARKER}\\"' in serialized, (
        f"an unregistered handler's {PIPELINE_MARKER!r} marker (past byte "
        f"3000) must still reach synthesis via the aggregated-view path")
    print("✓ an unregistered handler is no longer truncated either — the "
          "aggregated-view fix backs up STRUCTURED_HANDLERS registration")


def test_unstructured_raw_results_are_still_truncated():
    """Safety net in the other direction: the fix must not disable
    bounding universally. A genuinely unbounded raw-row result (e.g.
    filter_table, never in STRUCTURED_HANDLERS) must still be bounded —
    that data is unbounded by construction (a bare SELECT), unlike a
    handler's finished, purpose-built return shape.

    2026-09-23: the bound is now the already-computed aggregated view
    (a 20-row sample plus totals over EVERY row), not a [:3000] cut of
    the raw rows — the old cut sent ~13 raw rows and no totals at all
    (tests/test_canary_no_silent_drop.py). So the tail rows stay out,
    AND the all-row row_count must now be visible."""
    big_rows = [{"deal_id": str(i), "company_name": f"Company{i}",
                 "notes": "x" * 100} for i in range(200)]

    # the REAL filter_table against a strict fake (tests/strict_supabase.py):
    # the unselected `notes` blob stays in the table and out of the result, as
    # in Postgres (until 2026-09-24 a stub returned it with every row)
    sys.path.insert(0, str(Path(__file__).parent))
    from strict_supabase import with_data_dictionary, real_filter_table_on
    fake_filter_table = real_filter_table_on(with_data_dictionary({"deals": big_rows}))

    orig_filter_table = tools_module.filter_table
    tools_module.filter_table = fake_filter_table
    try:
        tool_call = json.dumps({
            "tool": "filter_table",
            "params": {"table": "deals", "columns": ["deal_id", "company_name"]},
        })
        final_answer = json.dumps({"answer": FINAL_ANSWER_TEXT})
        fake_client = _FakeClient([tool_call, final_answer])
        _run(fake_client, "list every deal", tool_call)
    finally:
        tools_module.filter_table = orig_filter_table

    synthesis_messages = fake_client.calls[-1]["messages"]
    serialized = json.dumps(synthesis_messages, default=str)
    assert "Company199" not in serialized, (
        "a raw, unstructured filter_table result (200 rows, never "
        "registered in STRUCTURED_HANDLERS) must still be truncated "
        "before reaching synthesis — this fix targets finished handler "
        "results specifically, not every large tool result"
    )
    assert "x" * 100 not in serialized, "a column the call never selected must not reach synthesis"
    assert '\\"row_count\\": 200' in serialized, (
        "the bounded view must carry the all-row row_count (200) so the "
        "model can state the true total, not just the sample size"
    )
    print("✓ a genuinely unstructured raw-row result is still bounded (20-row "
          "sample) and now carries its all-row row_count")


if __name__ == "__main__":
    test_query_pipeline_full_payload_reaches_synthesis()
    test_query_stale_deals_full_payload_reaches_synthesis()
    test_without_the_fix_the_markers_would_be_truncated_away()
    test_query_waterfall_is_covered_by_the_same_structural_fix()
    test_unregistered_handler_is_still_not_truncated()
    test_unstructured_raw_results_are_still_truncated()
    print("\n✅ All tests passed")
