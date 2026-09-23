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

import api.router as router
from canary_harness import CHANNELS, run_canary_case
from canary_fixtures import CASES, QUERY_REP_PIPELINE

_RETURNED_PAYLOAD_NARROWING = (
    "_extract_rows_from_accumulated() rebuilds tool_results as "
    "{'rows', 'table'} only; save_thread() consumes by_stage (named sets for "
    "follow-ups) and cache_payload (thread deal cache) from this payload")
_SERIALIZE_3000 = (
    "_serialize_tool_result_for_synthesis() hard-cuts non-STRUCTURED_HANDLERS "
    "results to [:3000] chars of the RAW result — the aggregated view is never "
    "sent to the model")
_AGGREGATE_REBUILD = (
    "_aggregate_and_sample() rebuilds results with >20 rows from a fixed key "
    "set, dropping every other key")

# (case label, channel) -> narrowing point responsible
KNOWN_DROPS = {
    ("query_pipeline_movement", "synthesis_input"): _SERIALIZE_3000 + " (not in STRUCTURED_HANDLERS; 3 of 64 rows and data_gaps reach the model)",
    ("query_pipeline_movement", "stored_step"): _AGGREGATE_REBUILD,
    ("dynamic_query:filter_table(60 rows)", "synthesis_input"): _SERIALIZE_3000 + " (13 of 60 rows reach the model, no aggregates/row_count)",
    ("dynamic_query:filter_table(60 rows)", "stored_step"): _AGGREGATE_REBUILD,
    **{(label, "returned_payload"): _RETURNED_PAYLOAD_NARROWING
       for label, *_ in CASES},
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

    def narrowing_serializer(result, tool_name):
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


if __name__ == "__main__":
    test_every_unified_routing_handler_is_covered()
    test_negative_control_harness_detects_a_drop()
    test_canary_reaches_every_channel_except_known_drops()
    print("\n✅ All tests passed")
