"""
Regression test for the 2026-09-11 round-3 conflict between two safety
mechanisms in dynamic_query_loop: scratchpad-rejection retries and the
"both snapshot anchors required" gate.

Root cause (see task report): when a model responds with unfinished
prose TWICE in a row on a snapshot-comparison question — narrating about
wanting to compute the diff instead of actually issuing the second
filter_table call — the shared no_progress_streak retry budget (2
strikes) exhausts before the model ever queries the missing anchor. The
loop then falls back to _finalize_from_data, which used to synthesize
straight from whatever data existed: in the live incident, that was only
ONE of the two required snapshots (only the current snapshot had ever
been queried; the prior one never was).

Two fixes, both exercised end-to-end here by actually driving
dynamic_query_loop (not just unit-testing the extracted helpers) with a
scripted FakeClient and a stubbed filter_table, so this test fails the
way the real incident did if either fix regresses:

1. The corrective message sent after a scratchpad rejection now includes
   a concrete "query this exact missing snapshot_date" instruction
   (_snapshot_anchor_redirect_instruction) instead of only "stop
   narrating, give me a clean answer" — which left the model nothing
   concrete to act on except narrate again.

2. If the redirect doesn't land in time and no_progress_streak still
   exhausts, _finalize_from_data itself now forces ONE direct,
   non-conversational filter_table call for the missing anchor
   (_build_missing_snapshot_fetch) before falling through to synthesis
   or giving up — the missing date is already known deterministically
   from resolve_snapshot_anchor_dates(), so this doesn't require the
   model to reason about anything.

This test reproduces the exact interaction shape: iteration 0 queries
the CURRENT snapshot only, iterations 1 and 2 both narrate instead of
tool-calling (matching the live incident's "let me diff them properly" /
"let me try recalculating this" shape), which exhausts the retry budget
and lands in _finalize_from_data("scratchpad_prose_rejected") with the
PRIOR snapshot never queried. It asserts outcome (b) from the task's own
framing: the fallback path forces the missing fetch directly, and the
loop still produces a real, complete answer rather than giving up with
only half the required data.

External dependencies not part of the mechanism under test — table
classification, schema-context building, and snapshot-anchor date
resolution — are stubbed for determinism and speed; nothing about the
scratchpad-rejection loop, the no_progress_streak accounting, or
_finalize_from_data's new forced-fetch logic is faked.
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

QUESTION = "which enterprise deals changed stage in the last 2 weeks in EMEA"
CURRENT_DATE = "2026-09-08"
PRIOR_DATE = "2026-07-27"

CURRENT_ROWS = [{
    "deal_id": "1001", "snapshot_date": CURRENT_DATE, "region": "EMEA",
    "segment": "Enterprise", "stage_id": "qualifiedtobuy",
}]
PRIOR_ROWS = [{
    "deal_id": "1001", "snapshot_date": PRIOR_DATE, "region": "EMEA",
    "segment": "Enterprise", "stage_id": "appointmentscheduled",
}]

FINAL_ANSWER_TEXT = (
    "*1 deal moved stage*: deal 1001 advanced from Discovery to Scoping "
    "between the two snapshots."
)


class _FakeResponse:
    def __init__(self, text, input_tokens=1000, output_tokens=100):
        self.text = text
        self.input_tokens = input_tokens
        self.output_tokens = output_tokens


class _FakeClient:
    """Scripts the exact model-response sequence from the live incident:
    a real tool call, then two scratchpad narrations in a row, then (once
    _finalize_from_data forces the missing fetch) a real finished answer.
    """
    def __init__(self, responses):
        self._responses = list(responses)
        self.calls = []

    def complete(self, messages=None, system=None, max_tokens=None):
        idx = len(self.calls)
        self.calls.append({"messages": messages, "system": system})
        assert idx < len(self._responses), (
            f"FakeClient received more complete() calls ({idx + 1}) than "
            f"scripted responses ({len(self._responses)}) — the loop "
            f"looped further than this test expected."
        )
        return _FakeResponse(self._responses[idx])


def _make_filter_table_stub(call_log):
    async def fake_filter_table(sb, table=None, columns=None, filters=None,
                                 limit=200, order_by=None):
        call_log.append({"table": table, "columns": columns, "filters": filters})
        snap_date = None
        for f in (filters or []):
            if len(f) >= 2 and f[1] == "snapshot_date":
                snap_date = f[2]
        if snap_date == CURRENT_DATE:
            rows = CURRENT_ROWS
        elif snap_date == PRIOR_DATE:
            rows = PRIOR_ROWS
        else:
            rows = []
        return {"rows": rows, "table": table}
    return fake_filter_table


class _FakeSupabase:
    """No .table() support — every real DB touch point in the loop that
    isn't part of the mechanism under test (entity_registry lookups,
    fallback logging) is wrapped in try/except and degrades gracefully,
    per the existing code. Anything that reaches this without that guard
    will raise AttributeError and fail the test loudly, which is the
    point."""
    pass


def _run_with_client(fake_client):
    """Drive the real dynamic_query_loop with the given scripted
    FakeClient, stubbing only what's not part of the mechanism under
    test (table classification, schema-context text, and snapshot-anchor
    date resolution)."""
    filter_table_calls = []

    orig_filter_table = tools_module.filter_table
    orig_classify = table_classifier_module.classify_relevant_tables
    orig_get_schema = schema_context_module.get_schema_context
    orig_resolve_anchor_dates = router.resolve_snapshot_anchor_dates

    tools_module.filter_table = _make_filter_table_stub(filter_table_calls)
    table_classifier_module.classify_relevant_tables = (
        lambda question, client: ["deals_snapshot"])
    schema_context_module.get_schema_context = (
        lambda sb, tables_with_descriptions=None, lightweight=False:
            "TABLE: deals_snapshot\n  deal_id, stage_id, region, segment, snapshot_date\n")
    router.resolve_snapshot_anchor_dates = (
        lambda sb, time_window: (CURRENT_DATE, PRIOR_DATE))

    try:
        result = asyncio.run(router.dynamic_query_loop(
            question=QUESTION,
            history=[],
            params={"time_window": {
                "label": "last 2 weeks",
                "start": "2026-08-25",
                "end": "2026-09-08",
            }},
            sb=_FakeSupabase(),
            client=fake_client,
        ))
    finally:
        tools_module.filter_table = orig_filter_table
        table_classifier_module.classify_relevant_tables = orig_classify
        schema_context_module.get_schema_context = orig_get_schema
        router.resolve_snapshot_anchor_dates = orig_resolve_anchor_dates

    return result, fake_client, filter_table_calls


def _run_test():
    """The exact incident shape: only the CURRENT snapshot is ever
    queried by the model before it narrates twice in a row."""
    iteration0_tool_call = json.dumps({
        "tool": "filter_table",
        "params": {
            "table": "deals_snapshot",
            "columns": ["deal_id", "stage_id", "region", "segment", "snapshot_date"],
            "filters": [
                ["eq", "snapshot_date", CURRENT_DATE],
                ["eq", "region", "EMEA"],
                ["eq", "segment", "Enterprise"],
            ],
        },
    })
    # Real incident shape: narration about wanting to diff, not a tool call.
    iteration1_narration = (
        "Now I have the current snapshot. Let me diff them properly "
        "once I have the prior one too."
    )
    # Second narration in a row — this is what exhausts no_progress_streak.
    iteration2_narration = (
        "Let me try recalculating this properly using both snapshots "
        "before I answer."
    )
    finalize_answer = json.dumps({"answer": FINAL_ANSWER_TEXT})

    fake_client = _FakeClient([
        iteration0_tool_call,
        iteration1_narration,
        iteration2_narration,
        finalize_answer,
    ])
    return _run_with_client(fake_client)


def _run_negative_test():
    """Both anchors ARE queried (two real tool calls) before the model
    narrates twice — the anchor gate is already satisfied by the time
    _finalize_from_data runs, so the forced-fetch logic must be a no-op
    here. Without this negative control, test_finalize_forces_the_
    missing_snapshot_fetch_directly alone couldn't rule out a bug where
    _finalize_from_data forces a fetch unconditionally on every
    scratchpad_prose_rejected, regardless of whether it's actually
    needed — which would silently double-query on every ordinary
    snapshot comparison that happens to hit a scratchpad rejection after
    both anchors are already in hand."""
    iteration0_tool_call = json.dumps({
        "tool": "filter_table",
        "params": {
            "table": "deals_snapshot",
            "columns": ["deal_id", "stage_id", "region", "segment", "snapshot_date"],
            "filters": [
                ["eq", "snapshot_date", CURRENT_DATE],
                ["eq", "region", "EMEA"],
                ["eq", "segment", "Enterprise"],
            ],
        },
    })
    iteration1_tool_call = json.dumps({
        "tool": "filter_table",
        "params": {
            "table": "deals_snapshot",
            "columns": ["deal_id", "stage_id", "region", "segment", "snapshot_date"],
            "filters": [
                ["eq", "snapshot_date", PRIOR_DATE],
                ["eq", "region", "EMEA"],
                ["eq", "segment", "Enterprise"],
            ],
        },
    })
    iteration2_narration = (
        "Let me diff them properly now that I have both snapshots in hand."
    )
    iteration3_narration = (
        "Let me try computing this once more before I answer."
    )
    finalize_answer = json.dumps({"answer": FINAL_ANSWER_TEXT})

    fake_client = _FakeClient([
        iteration0_tool_call,
        iteration1_tool_call,
        iteration2_narration,
        iteration3_narration,
        finalize_answer,
    ])
    return _run_with_client(fake_client)


def test_forced_fetch_is_a_noop_when_both_anchors_already_queried():
    result, fake_client, filter_table_calls = _run_negative_test()

    # 2 = the model's own current+prior snapshot calls. A 3rd call is
    # now expected too: the round-6 diff-company-name backfill
    # (api/snapshot_diff.py's collect_diff_deal_ids/attach_company_names)
    # always ensures every deal_id the diff surfaces gets a company_name
    # lookup, independent of the round-3 anchor-forcing logic this test
    # actually targets — deal "1001" has no company_name anywhere in
    # this fixture, so that backfill correctly fires once. What this
    # test still proves is that the ANCHOR-forcing fetch specifically
    # (a second snapshot query) is a no-op here — not that zero extra
    # calls of any kind ever happen.
    anchor_fetch_calls = [c for c in filter_table_calls if c["table"] == "deals_snapshot"]
    assert len(anchor_fetch_calls) == 2, (
        f"expected exactly the model's own 2 real snapshot tool calls "
        f"(current + prior) with no extra forced ANCHOR fetch — got "
        f"{len(anchor_fetch_calls)}. The anchor-forced-fetch logic must "
        f"only fire when an anchor is genuinely missing, not "
        f"unconditionally on every scratchpad_prose_rejected."
    )
    assert result["answered"] is True
    assert result["answer"] == FINAL_ANSWER_TEXT
    print("✓ the anchor-forced-fetch logic is a no-op when both anchors "
          "were already queried before the scratchpad rejection")


def test_both_scratchpad_narrations_are_caught_not_shipped():
    result, _, _ = _run_test()
    assert result["answer"] != "Now I have the current snapshot. Let me diff them properly once I have the prior one too.", (
        "The first scratchpad narration must never ship verbatim as the answer."
    )
    print("✓ neither scratchpad narration shipped verbatim as the final answer")


def test_finalize_forces_the_missing_snapshot_fetch_directly():
    """The core of the fix: after two narrations exhaust the retry
    budget, _finalize_from_data must issue ONE direct filter_table call
    for the prior snapshot itself — not give up, and not synthesize from
    only the current snapshot's data."""
    result, fake_client, filter_table_calls = _run_test()

    queried_snapshot_dates = set()
    for call in filter_table_calls:
        for f in call["filters"] or []:
            if len(f) >= 2 and f[1] == "snapshot_date":
                queried_snapshot_dates.add(f[2])

    assert CURRENT_DATE in queried_snapshot_dates, (
        "iteration 0's real tool call for the current snapshot should "
        "have happened — if this fails, the test harness itself is "
        "miswired, not the fix."
    )
    assert PRIOR_DATE in queried_snapshot_dates, (
        "the prior snapshot_date was NEVER queried by the model (it "
        "narrated twice instead) — _finalize_from_data must force this "
        "exact direct fetch before giving up or synthesizing partial "
        "data. This is the live incident's exact failure if it's missing."
    )
    # The forced fetch must reuse the model's own region/segment filters,
    # not guess fresh ones that could silently answer a different
    # population than the one asked about.
    prior_call = next(c for c in filter_table_calls
                       if any(f[1] == "snapshot_date" and f[2] == PRIOR_DATE
                              for f in c["filters"]))
    prior_filter_cols = {f[1] for f in prior_call["filters"]}
    assert "region" in prior_filter_cols and "segment" in prior_filter_cols, (
        "the forced fetch must carry over the region/segment filters "
        "from the model's own current-snapshot query, not drop them."
    )
    print("✓ _finalize_from_data forced the missing prior-snapshot fetch "
          "directly, reusing the model's own filters")


def test_final_answer_is_real_and_complete_not_a_giveup_diagnostic():
    """The loop must not fall back to a partial-data or give-up
    diagnostic — with the forced fetch, both snapshots exist, so the
    finalize synthesis call should produce the SAME real answer this
    test scripted for it, proving the forced data actually reached
    synthesis rather than the loop giving up beforehand."""
    result, fake_client, _ = _run_test()

    assert result["answered"] is True, (
        f"expected a real, data-backed answer once the missing snapshot "
        f"was forced — got answered=False: {result.get('answer')!r}"
    )
    assert result["answer"] == FINAL_ANSWER_TEXT, (
        f"expected the scripted finalize answer (proving synthesis ran "
        f"with the forced data in context) — got {result['answer']!r}"
    )
    for banned in ("budget", "narrower scope", "could not find", "ran out"):
        assert banned not in result["answer"].lower(), (
            f"the final answer must not be a give-up/partial diagnostic "
            f"— found {banned!r} in {result['answer']!r}"
        )
    print("✓ the loop produced the real, complete answer instead of a "
          "give-up or partial-data diagnostic")


def test_finalize_synthesis_call_actually_saw_both_snapshots_in_context():
    """Forcing the fetch only fixes the incident if the model performing
    the final synthesis actually SEES the newly-fetched data — this
    codebase feeds tool results to the model as plain injected messages,
    not via accumulated_data directly, so the forced fetch's result must
    be injected into `messages` before the finalize completion call."""
    _, fake_client, _ = _run_test()

    assert len(fake_client.calls) == 4, (
        f"expected exactly 4 completion calls (tool call, 2 narrations, "
        f"1 finalize synthesis) — got {len(fake_client.calls)}. If this "
        f"is higher, the loop kept iterating instead of forcing the "
        f"fetch in the fallback path."
    )
    finalize_call_messages = fake_client.calls[-1]["messages"]
    serialized = json.dumps(finalize_call_messages, default=str)
    assert CURRENT_DATE in serialized, (
        "the finalize synthesis call's message context must still "
        "include the current snapshot's data"
    )
    assert PRIOR_DATE in serialized, (
        "the finalize synthesis call's message context must include the "
        "FORCED prior-snapshot fetch's data — otherwise the model is "
        "being asked to synthesize a diff it still can't see."
    )
    assert "1001" in serialized, (
        "the forced fetch's actual row data (deal_id 1001) must appear "
        "in the finalize context, not just a bare confirmation that a "
        "call happened."
    )
    print("✓ the finalize synthesis call's context includes both the "
          "original and the forced-fetch snapshot data")


if __name__ == "__main__":
    test_both_scratchpad_narrations_are_caught_not_shipped()
    test_finalize_forces_the_missing_snapshot_fetch_directly()
    test_final_answer_is_real_and_complete_not_a_giveup_diagnostic()
    test_finalize_synthesis_call_actually_saw_both_snapshots_in_context()
    test_forced_fetch_is_a_noop_when_both_anchors_already_queried()
    print("\n✅ All tests passed")
