"""
Permanent regression test: nothing a handler computes is silently dropped
between the handler and what reaches synthesis.

Drives the REAL dynamic_query_loop once per unified-routing handler (all 7
that route_question sends to the loop) plus the dynamic_query primitive
fallback (filter_table, at a small and a large result size), with a canary
key appended as the LAST key of each tool result — see
tests/canary_harness.py for the mechanism and the three channels checked.

This is a RATCHET, not a snapshot:
  - Any drop not listed in KNOWN_DROPS fails the test — a new narrowing
    point anywhere between a handler and the model is caught the first
    time it appears, not on a live question.
  - Any KNOWN_DROPS entry that no longer drops ALSO fails — when one is
    fixed, its entry must be deleted here, so the list can only shrink.

Each KNOWN_DROPS entry names the exact narrowing point; they were found by
this test's first run (2026-09-23), not by live incidents.
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
sys.path.insert(0, str(Path(__file__).parent.parent))

import logging
logging.disable(logging.CRITICAL)

import api.evaluator as evaluator
import api.router as router
from canary_harness import CHANNELS, run_canary_case
from canary_fixtures import CASES, QUERY_REP_PIPELINE

_CASES_BY_LABEL = {c[0]: c for c in CASES}

_RETURNED_PAYLOAD_NARROWING = (
    "_extract_rows_from_accumulated() only considers steps with a non-empty "
    "'rows' key, so a structured result without one returns {}; save_thread() "
    "consumes by_stage (named sets for follow-ups) and cache_payload (thread "
    "deal cache) from this payload")

# (case label, channel) -> narrowing point responsible
KNOWN_DROPS = {
    # Structured handlers with no top-level "rows" key: f9b2bf6 made
    # _extract_rows_from_accumulated pass step keys through, but only for
    # steps that HAVE rows, so these still come back as {}.
    **{(label, "returned_payload"): _RETURNED_PAYLOAD_NARROWING
       for label in ("query_pipeline", "query_stale_deals", "query_waterfall",
                     "query_rep_pipeline", "query_win_loss", "query_deals_at_risk")},
}


def _run_all():
    report = {}
    for label, question, tool_name, tool_params, fixture in CASES:
        r = run_canary_case(question, tool_name, tool_params, fixture)
        assert r["tool_executed"], (
            f"[{label}] harness did not reach tool execution — the scripted "
            f"tool call never ran, so this case proves nothing")
        assert r["answered"], (
            f"[{label}] loop did not produce an answer: {r['answer']!r}")
        report[label] = r
    return report


def test_canary_reaches_every_channel_except_known_drops():
    report = _run_all()

    new_drops, fixed_drops = [], []
    print(f"\n{'case':40s} " + " ".join(f"{c:17s}" for c in CHANNELS))
    for label, r in report.items():
        cells = []
        for channel in CHANNELS:
            ok = r["channels"][channel]
            known = (label, channel) in KNOWN_DROPS
            cells.append(f"{'ok' if ok else ('DROP(known)' if known else 'DROP(NEW)'):17s}")
            if not ok and not known:
                new_drops.append((label, channel, r["keys_missing_from_synthesis"]))
            if ok and known:
                fixed_drops.append((label, channel))
        print(f"{label:40s} " + " ".join(cells))

    assert not new_drops, (
        "NEW silent drop(s) — a value computed upstream no longer reaches "
        "this channel. Find the narrowing point; do not add it to KNOWN_DROPS "
        "without a fix plan:\n" + "\n".join(
            f"  {l} / {c}  (top-level keys missing from synthesis input: {m})"
            for l, c, m in new_drops))
    assert not fixed_drops, (
        "KNOWN_DROPS entries that no longer drop — delete them from "
        "KNOWN_DROPS so the ratchet holds:\n" + "\n".join(
            f"  {l} / {c}" for l, c in fixed_drops))
    print("✓ canary reached every channel except the listed known drops")


def test_every_unified_routing_handler_is_covered():
    """If route_question's unified-routing list grows, this test must grow
    with it — an uncovered handler is exactly where the next drop hides."""
    import inspect
    src = inspect.getsource(router)
    marker = 'if handler_name in ("query_pipeline_movement"'
    start = src.index(marker) + len("if handler_name in ")
    routed = set(eval(src[start:src.index(":", start)]))
    covered = {tool for _, _, tool, _, _ in CASES if tool.startswith("query_")}
    assert routed == covered, (
        f"unified-routing handlers without a canary case: {routed - covered}; "
        f"canary cases for handlers no longer routed: {covered - routed}")
    print(f"✓ all {len(routed)} unified-routing handlers have a canary case")


def test_negative_control_harness_detects_a_drop():
    """Proves the harness can fail: narrow the serializer so it drops the
    canary key, and a case that normally passes must report the drop."""
    orig = router._serialize_tool_result_for_synthesis

    def narrowing_serializer(result, tool_name, aggregated=None):
        narrowed = {k: v for k, v in result.items() if not k.startswith("__")}
        return orig(narrowed, tool_name)

    router._serialize_tool_result_for_synthesis = narrowing_serializer
    try:
        r = run_canary_case("what's in Cary's pipeline?", "query_rep_pipeline",
                            {"owner_email": "cary@growthbook.io"}, QUERY_REP_PIPELINE)
    finally:
        router._serialize_tool_result_for_synthesis = orig

    assert r["tool_executed"]
    assert r["channels"]["synthesis_input"] is False, (
        "negative control failed: a serializer that drops the canary was "
        "NOT detected — the harness is not actually checking synthesis input")
    print("✓ negative control: a narrowing serializer is detected as a drop")


def _assert_reintroduced_drop_is_caught(label, channel, revert, restore):
    """Revert one fix in-process and confirm that exact (case, channel)
    drops again and is NOT in KNOWN_DROPS — i.e. the ratchet would fail
    as a NEW drop. Proves each fix is guarded, not just currently passing."""
    assert (label, channel) not in KNOWN_DROPS, (
        f"{label} / {channel} is listed in KNOWN_DROPS — a reintroduced "
        f"drop there would be silently accepted")
    _, question, tool_name, tool_params, fixture = _CASES_BY_LABEL[label]
    revert()
    try:
        r = run_canary_case(question, tool_name, tool_params, fixture)
    finally:
        restore()
    assert r["channels"][channel] is False, (
        f"reverting the fix for {label} / {channel} did not reintroduce the "
        f"drop — this guard no longer proves the fix holds")


def test_fix_structured_pipeline_movement_is_guarded():
    """Fix 1: query_pipeline_movement registered in STRUCTURED_HANDLERS.

    Since fix 2 an unregistered handler no longer loses its extra keys —
    it's sent as its complete aggregated view — so the canary alone can't
    tell fix 1 apart. What only fix 1 provides is EVERY deal row: this
    handler exists to name the deals that moved, and unregistered it is
    sampled down to 20 of 64. So the guard checks the last deal row."""
    from canary_harness import _message_text
    label = "query_pipeline_movement"
    _, question, tool_name, tool_params, fixture = _CASES_BY_LABEL[label]
    last_deal = fixture["rows"][-1]["company_name"]

    import canary_harness
    orig_complete = canary_harness.ScriptedClient.complete
    seen = []

    def recording_complete(self, messages=None, system=None, max_tokens=None):
        seen.append(_message_text(messages))
        return orig_complete(self, messages, system, max_tokens)

    canary_harness.ScriptedClient.complete = recording_complete
    saved = evaluator.STRUCTURED_HANDLERS[label]
    try:
        run_canary_case(question, tool_name, tool_params, fixture)
        with_fix = f'"company_name": "{last_deal}"' in seen[-1]
        seen.clear()
        evaluator.STRUCTURED_HANDLERS.pop(label)
        try:
            run_canary_case(question, tool_name, tool_params, fixture)
        finally:
            evaluator.STRUCTURED_HANDLERS[label] = saved
        without_fix = f'"company_name": "{last_deal}"' in seen[-1]
    finally:
        canary_harness.ScriptedClient.complete = orig_complete

    assert with_fix, (
        f"{label}: the last of {len(fixture['rows'])} deal rows ({last_deal}) "
        f"does not reach synthesis — the handler's full row list is being cut")
    assert not without_fix, (
        f"reverting fix 1 still delivers {last_deal} — this guard no longer "
        f"proves the STRUCTURED_HANDLERS registration matters")
    print(f"✓ fix 1 guarded: all {len(fixture['rows'])} deal rows reach synthesis; "
          f"unregistering query_pipeline_movement drops them to a sample")


def _pre_fix2_serializer(result, tool_name, aggregated=None):
    """The serializer as it was before fix 2: raw result, [:3000] cut."""
    import json
    from api.evaluator import STRUCTURED_HANDLERS
    if tool_name in STRUCTURED_HANDLERS and "error" not in result:
        return json.dumps(result, default=str), ""
    return json.dumps(result, default=str)[:3000], ""


def _pre_fix2_aggregate(orig):
    """_aggregate_and_sample as it was before fix 2: a >20-row result keeps
    only the keys the function itself builds."""
    built = {"rows", "row_count", "aggregates", "sample", "sample_basis",
             "truncated", "complete", "_note", "table"}

    def narrowed(result, *args, **kwargs):
        out = orig(result, *args, **kwargs)
        if out.get("truncated"):
            out = {k: v for k, v in out.items() if k in built}
        return out
    return narrowed


def test_fix_aggregate_view_reaches_synthesis_is_guarded():
    """Fix 2a: a large row result reaches the model as its aggregated view
    (all-row totals + row_count), not a [:3000] cut of raw rows."""
    import canary_harness
    from canary_harness import _message_text
    label = "dynamic_query:filter_table(60 rows)"
    _, question, tool_name, tool_params, fixture = _CASES_BY_LABEL[label]

    orig_complete = canary_harness.ScriptedClient.complete
    seen = []

    def recording_complete(self, messages=None, system=None, max_tokens=None):
        seen.append(_message_text(messages))
        return orig_complete(self, messages, system, max_tokens)

    canary_harness.ScriptedClient.complete = recording_complete
    try:
        run_canary_case(question, tool_name, tool_params, fixture)
    finally:
        canary_harness.ScriptedClient.complete = orig_complete
    text = seen[-1]
    assert '"row_count": 60' in text and '"aggregates":' in text, (
        "the 60-row result's row_count/aggregates (computed over every row) "
        "did not reach synthesis")
    assert '"new_arr": {"sum": 1800000' in text, (
        "the all-row new_arr sum (60 x 30,000) did not reach synthesis")

    orig = router._serialize_tool_result_for_synthesis
    _assert_reintroduced_drop_is_caught(
        label, "synthesis_input",
        revert=lambda: setattr(router, "_serialize_tool_result_for_synthesis",
                               _pre_fix2_serializer),
        restore=lambda: setattr(router, "_serialize_tool_result_for_synthesis", orig))
    print("✓ fix 2a guarded: the 60-row aggregate (row_count=60, all-row sums) "
          "reaches synthesis; restoring the raw [:3000] cut is caught as a NEW drop")


def test_fix_aggregate_passthrough_is_guarded():
    """Fix 2b: _aggregate_and_sample passes through keys it doesn't compute."""
    orig = router._aggregate_and_sample
    for label in ("query_pipeline_movement", "dynamic_query:filter_table(60 rows)"):
        _assert_reintroduced_drop_is_caught(
            label, "stored_step",
            revert=lambda: setattr(router, "_aggregate_and_sample", _pre_fix2_aggregate(orig)),
            restore=lambda: setattr(router, "_aggregate_and_sample", orig))
    print("✓ fix 2b guarded: restoring the fixed-key rebuild in "
          "_aggregate_and_sample is caught as a NEW stored_step drop")


def test_wide_rows_trim_whole_rows_never_characters():
    """Fix 2 bound: an oversized aggregated view drops whole sample rows,
    stays valid JSON (no mid-row cut), and keeps row_count + aggregates."""
    import json
    wide = {"rows": [{"deal_id": str(i), "new_arr": 1000, "notes": "x" * 2000}
                     for i in range(60)], "table": "calls"}
    view = router._aggregate_and_sample(wide)
    text = router._serialize_aggregated_view(view)
    parsed = json.loads(text)  # raises if cut mid-JSON
    assert len(text) <= router.LOOP_STEP_VIEW_CHARS
    assert parsed["row_count"] == 60
    assert parsed["aggregates"]["new_arr"]["sum"] == 60000
    assert 0 < len(parsed["rows"]) < 20 and "_rows_trimmed_for_context" in parsed
    assert "sample" not in parsed, "duplicate sample list should not be sent"
    print(f"✓ wide rows: trimmed to {len(parsed['rows'])} whole rows, "
          f"{len(text)} chars, valid JSON, row_count/aggregates intact")


if __name__ == "__main__":
    test_every_unified_routing_handler_is_covered()
    test_negative_control_harness_detects_a_drop()
    test_fix_structured_pipeline_movement_is_guarded()
    test_fix_aggregate_view_reaches_synthesis_is_guarded()
    test_fix_aggregate_passthrough_is_guarded()
    test_wide_rows_trim_whole_rows_never_characters()
    test_canary_reaches_every_channel_except_known_drops()
    print("\n✅ All tests passed")
