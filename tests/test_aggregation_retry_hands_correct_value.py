"""
2026-09-11: two live incidents the same night both failed the
aggregation-completeness gate's resynthesis retry — not by evading
detection, but by getting the SAME wrong answer back after being told
it was wrong:

  - stated 11.0, actual -1,417,100.0 — retry still said 11.
  - stated 4.0, actual 35,771,117.85 — retry still said 4.

Both times the retry's own correction message ALREADY named the
correct value ("the rows actually retrieved for that category sum to
X"), but the instruction asked the model to "recheck your aggregation"
— i.e. recompute its own already-wrong math a second time — rather
than telling it to stop computing and use the number that's already
correct. The primitive caught the mistake reliably; it never actually
fixed it.

_aggregation_correction_message() (api/router.py) closes the gap: the
correct value — already computed deterministically in code by
verify_aggregation_completeness() to DETECT the mismatch — is now
handed to the model as a definitive fact ("do NOT recompute or
re-derive them yourself... replace... with its exact corrected number,
verbatim"), at both call sites that build a resynthesis retry (the main
loop's happy path, and _finalize_from_data's own last-resort check).

These tests reproduce both of tonight's exact number pairs as fixtures,
confirm the correction message contains the exact correct value
formatted precisely (whole numbers un-decimaled, fractional cents
preserved), and drive the real dynamic_query_loop end-to-end proving
the corrected number actually reaches the shipped answer this time —
not just that the mismatch gets detected again.
"""
import asyncio
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from api.router import _format_agg_number, _aggregation_correction_message
from api.aggregation_verification import (
    verify_aggregation_completeness,
    extract_stated_totals_from_answer,
)

# Tonight's exact incident #1: a coverage-style stated figure (11) vs a
# real net_change sum that's off by five orders of magnitude.
INCIDENT_1_ROWS = [
    {"week_ending": "2026-08-17", "segment": "Enterprise", "net_change": -900000},
    {"week_ending": "2026-08-24", "segment": "Enterprise", "net_change": -517100},
]
INCIDENT_1_WRONG_ANSWER = "Total pipeline movement this period was 11."
INCIDENT_1_CORRECT_ANSWER = "Total pipeline movement this period was -1,417,100."

# Tonight's exact incident #2: stated 4 vs a real ARR sum carrying cents.
INCIDENT_2_ROWS = [
    {"week_ending": "2026-08-17", "segment": "Enterprise", "net_change": 20000000.00},
    {"week_ending": "2026-08-24", "segment": "Enterprise", "net_change": 15771117.85},
]
INCIDENT_2_WRONG_ANSWER = "Total ARR pipeline is 4."
INCIDENT_2_CORRECT_ANSWER = "Total ARR pipeline is 35,771,117.85."


def test_format_agg_number_whole_vs_fractional():
    assert _format_agg_number(-1417100.0) == "-1,417,100"
    assert _format_agg_number(35771117.85) == "35,771,117.85"
    assert _format_agg_number(11.0) == "11"
    assert _format_agg_number(4.0) == "4"


def test_incident_1_discrepancy_reproduced_exactly():
    stated = extract_stated_totals_from_answer(INCIDENT_1_WRONG_ANSWER)
    result = verify_aggregation_completeness(INCIDENT_1_ROWS, stated)
    assert result["match"] is False
    d = result["discrepancy"]
    assert d["stated"] == 11.0
    assert d["actual_sum"] == -1417100.0


def test_incident_2_discrepancy_reproduced_exactly():
    stated = extract_stated_totals_from_answer(INCIDENT_2_WRONG_ANSWER)
    result = verify_aggregation_completeness(INCIDENT_2_ROWS, stated)
    assert result["match"] is False
    d = result["discrepancy"]
    assert d["stated"] == 4.0
    assert d["actual_sum"] == 35771117.85


def test_correction_message_hands_the_value_and_forbids_recomputing():
    stated = extract_stated_totals_from_answer(INCIDENT_1_WRONG_ANSWER)
    result = verify_aggregation_completeness(INCIDENT_1_ROWS, stated)
    message = _aggregation_correction_message(result["all_discrepancies"])

    assert "-1,417,100" in message, (
        f"the exact correct value must appear verbatim in the correction "
        f"— got: {message!r}"
    )
    assert "11" in message, "the wrong stated value must also be named"
    assert "DEFINITIVE" in message
    assert "do NOT recompute" in message or "do not recompute" in message.lower()
    assert "recheck your aggregation" not in message.lower(), (
        "the old wording ('recheck your aggregation') is exactly what "
        "invited the model to re-derive its own wrong math a second "
        "time — it must not survive in the new message"
    )


def test_correction_message_preserves_cents_for_fractional_values():
    stated = extract_stated_totals_from_answer(INCIDENT_2_WRONG_ANSWER)
    result = verify_aggregation_completeness(INCIDENT_2_ROWS, stated)
    message = _aggregation_correction_message(result["all_discrepancies"])
    assert "35,771,117.85" in message, (
        f"cents must be preserved verbatim, not rounded away — got: {message!r}"
    )


def test_correction_message_handles_multiple_discrepancies_at_once():
    combined_rows = INCIDENT_1_ROWS  # reuse; only "total" category matters here
    d1 = {"category": "total", "stated": 11.0, "actual_sum": -1417100.0}
    d2 = {"category": "Enterprise", "stated": 4.0, "actual_sum": 35771117.85}
    message = _aggregation_correction_message([d1, d2])
    assert "categories" in message  # plural wording
    assert "-1,417,100" in message
    assert "35,771,117.85" in message


# --- End-to-end: the corrected value must actually reach the shipped answer ---

import api.router as router
import api.tools as tools_module
import api.table_classifier as table_classifier_module
import api.schema_context as schema_context_module


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
    """The REAL filter_table against a strict fake (tests/strict_supabase.py)
    holding the fixture rows in waterfall_weekly: only selected columns come back and
    every filter applies. (Until 2026-09-24 a stub returned the fixture for
    any call, whatever it selected or filtered.)"""
    sys.path.insert(0, str(Path(__file__).parent))
    from strict_supabase import with_data_dictionary, real_filter_table_on
    return real_filter_table_on(with_data_dictionary({"waterfall_weekly": rows}), call_log)


def _run(fake_client, rows):
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
            question="how much did pipeline move this period?",
            history=[],
            params={"time_window": {"label": "this period",
                                     "start": "2026-08-01", "end": "2026-09-08"}},
            sb=_FakeSupabase(),
            client=fake_client,
        ))
    finally:
        tools_module.filter_table = orig_filter_table
        table_classifier_module.classify_relevant_tables = orig_classify
        schema_context_module.get_schema_context = orig_get_schema

    return result, fake_client, filter_table_calls


def test_incident_1_corrected_value_ships_end_to_end():
    """Reproduces the exact -1,417,100 incident end-to-end: once the
    model's retry uses the value it was handed, that value — not the
    original wrong '11' — is what actually ships."""
    tool_call = json.dumps({"tool": "filter_table", "params": {
        "table": "waterfall_weekly",
        "columns": ["week_ending", "segment", "net_change"],
        "filters": [],
    }})
    wrong_answer = json.dumps({"answer": INCIDENT_1_WRONG_ANSWER})
    corrected_answer = json.dumps({"answer": INCIDENT_1_CORRECT_ANSWER})

    fake_client = _FakeClient([tool_call, wrong_answer, corrected_answer])
    result, fake_client, _ = _run(fake_client, INCIDENT_1_ROWS)

    assert len(fake_client.calls) == 3
    retry_message = fake_client.calls[-1]["messages"][-1]["content"]
    assert "-1,417,100" in retry_message
    assert "recheck your aggregation" not in retry_message.lower()
    assert result["answered"] is True
    assert result["answer"] == INCIDENT_1_CORRECT_ANSWER, (
        "the corrected -1,417,100 answer must be what ships"
    )
    print("✓ incident #1 (stated 11 vs actual -1,417,100) — corrected "
          "value ships end-to-end")


def test_incident_2_corrected_value_ships_end_to_end():
    """Reproduces the exact 35,771,117.85 incident end-to-end."""
    tool_call = json.dumps({"tool": "filter_table", "params": {
        "table": "waterfall_weekly",
        "columns": ["week_ending", "segment", "net_change"],
        "filters": [],
    }})
    wrong_answer = json.dumps({"answer": INCIDENT_2_WRONG_ANSWER})
    corrected_answer = json.dumps({"answer": INCIDENT_2_CORRECT_ANSWER})

    fake_client = _FakeClient([tool_call, wrong_answer, corrected_answer])
    result, fake_client, _ = _run(fake_client, INCIDENT_2_ROWS)

    assert len(fake_client.calls) == 3
    retry_message = fake_client.calls[-1]["messages"][-1]["content"]
    assert "35,771,117.85" in retry_message
    assert result["answered"] is True
    assert result["answer"] == INCIDENT_2_CORRECT_ANSWER, (
        "the corrected 35,771,117.85 answer must be what ships"
    )
    print("✓ incident #2 (stated 4 vs actual 35,771,117.85) — corrected "
          "value ships end-to-end")


def test_identical_wrong_answer_on_retry_hard_declines_not_loops_forever():
    """The exact failure mode from tonight, worst case: the model
    repeats the SAME wrong answer even after being handed the correct
    value. The loop must not spin forever — after the second unresolved
    attempt it now hard-declines (answered=False) with the real numbers
    stated plainly, rather than shipping a caveat-laden wrong answer."""
    tool_call = json.dumps({"tool": "filter_table", "params": {
        "table": "waterfall_weekly",
        "columns": ["week_ending", "segment", "net_change"],
        "filters": [],
    }})
    still_wrong = json.dumps({"answer": INCIDENT_1_WRONG_ANSWER})

    # Only 3 responses consumed: tool call + 2 wrong attempts (no finalize call).
    fake_client = _FakeClient([tool_call, still_wrong, still_wrong])
    result, fake_client, _ = _run(fake_client, INCIDENT_1_ROWS)

    assert len(fake_client.calls) == 3, (
        f"expected tool call + 2 unresolved attempts — got {len(fake_client.calls)}"
    )
    assert result["answered"] is False, (
        "after two unresolved aggregation mismatches the loop must hard-decline, "
        f"not deliver — got answered={result.get('answered')!r}"
    )
    print("✓ two identical wrong answers in a row hard-decline rather than "
          "looping forever or shipping a caveat-laden wrong answer")


# --- The unresolved-after-retry signal must be visible, not silent ---

class _CapturingTable:
    """Minimal stand-in for supabase-py's table().insert().execute()
    chain, capturing exactly what gets inserted — same pattern as
    tests/test_query_cost_logging.py."""
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
    """Only query_cost_log works — every other table raises, so those
    call sites hit their pre-existing try/except and degrade gracefully."""
    def __init__(self):
        self.query_cost_log_inserts = []

    def table(self, name):
        if name == "query_cost_log":
            return _CapturingTable(self.query_cost_log_inserts)
        raise AttributeError(f"no fake support for table {name!r}")


def test_unresolved_after_retry_hard_declines_and_is_not_a_silent_success():
    """2026-09-29: the caveat-with-delivery approach (shipping a wrong number
    with a ⚠️ note) is replaced by a hard decline (answered=False) that
    states the REAL verified figure(s) plainly. A wrong number delivered
    confidently — even with a caveat — is worse than an honest refusal.

    This proves the hard-decline behaviour end-to-end:
    1. answered=False — the loop terminates without delivering an answer.
    2. The answer text names the real number from the retrieved rows, not
       the model's unverified figure.
    3. query_cost_log's reason_tag is "aggregation_mismatch_unresolved"
       — queryable independently from a generic give-up bucket.

    Scenario: the model repeats the same wrong total through the main
    loop's two allowed attempts. The hard-decline fires immediately; there
    is no finalize call.
    """
    tool_call = json.dumps({"tool": "filter_table", "params": {
        "table": "waterfall_weekly",
        "columns": ["week_ending", "segment", "net_change"],
        "filters": [],
    }})
    still_wrong = json.dumps({"answer": INCIDENT_1_WRONG_ANSWER})

    # tool call + 2 unresolved main-loop attempts; no finalize call.
    fake_client = _FakeClient([tool_call, still_wrong, still_wrong])
    fake_sb = _FakeSupabaseWithCostLog()

    filter_table_calls = []
    orig_filter_table = tools_module.filter_table
    orig_classify = table_classifier_module.classify_relevant_tables
    orig_get_schema = schema_context_module.get_schema_context
    tools_module.filter_table = _make_filter_table_stub(INCIDENT_1_ROWS, filter_table_calls)
    table_classifier_module.classify_relevant_tables = (
        lambda question, client: ["waterfall_weekly"])
    schema_context_module.get_schema_context = (
        lambda sb, tables_with_descriptions=None, lightweight=False:
            "TABLE: waterfall_weekly\n  week_ending, segment, net_change\n")

    try:
        result = asyncio.run(router.dynamic_query_loop(
            question="how much did pipeline move this period?",
            history=[],
            params={"time_window": {"label": "this period",
                                     "start": "2026-08-01", "end": "2026-09-08"}},
            sb=fake_sb,
            client=fake_client,
        ))
    finally:
        tools_module.filter_table = orig_filter_table
        table_classifier_module.classify_relevant_tables = orig_classify
        schema_context_module.get_schema_context = orig_get_schema

    # 1. Hard decline — not delivered.
    assert result["answered"] is False, (
        f"expected answered=False (hard decline) — got: {result.get('answered')!r}"
    )
    # 2. The real figure from the rows is named in the decline message.
    # INCIDENT_1 actual_sum = -1,417,100
    assert "-1,417,100" in result["answer"], (
        f"hard-decline message must state the real verified figure — got: "
        f"{result['answer']!r}"
    )
    # No internal jargon leaked into the user-facing text.
    for banned in ("resynthesis", "budget", "token", "primitive"):
        assert banned not in result["answer"].lower(), (
            f"internal jargon {banned!r} leaked into the user-facing "
            f"decline: {result['answer']!r}"
        )

    # 3. query_cost_log records the aggregation_mismatch_unresolved reason.
    assert len(fake_sb.query_cost_log_inserts) == 1
    logged = fake_sb.query_cost_log_inserts[0]
    assert logged["reason_tag"] == "aggregation_mismatch_unresolved", (
        f"expected reason_tag 'aggregation_mismatch_unresolved' — got: "
        f"{logged.get('reason_tag')!r}"
    )

    print("✓ an unresolved aggregation mismatch hard-declines (answered=False) "
          "with the real figure stated — never a silently-wrong delivered answer")


if __name__ == "__main__":
    tests = [
        test_format_agg_number_whole_vs_fractional,
        test_incident_1_discrepancy_reproduced_exactly,
        test_incident_2_discrepancy_reproduced_exactly,
        test_correction_message_hands_the_value_and_forbids_recomputing,
        test_correction_message_preserves_cents_for_fractional_values,
        test_correction_message_handles_multiple_discrepancies_at_once,
        test_incident_1_corrected_value_ships_end_to_end,
        test_incident_2_corrected_value_ships_end_to_end,
        test_identical_wrong_answer_on_retry_hard_declines_not_loops_forever,
        test_unresolved_after_retry_hard_declines_and_is_not_a_silent_success,
    ]
    failed = 0
    for t in tests:
        try:
            t()
            print(f"✓ {t.__name__}")
        except AssertionError as e:
            failed += 1
            print(f"✗ {t.__name__}: {e}")
    if failed:
        print(f"\n{failed}/{len(tests)} tests FAILED")
        sys.exit(1)
    print(f"\n✅ All {len(tests)} tests passed")
