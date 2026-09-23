"""
Canary harness: proves nothing a handler computes is silently dropped
between the handler and the model that writes the final answer.

Four separate incidents (SNAPSHOT_DIFF discarded from the return payload,
SNAPSHOT_DIFF chopped by blind truncation, the enrichment-shortcut message
gap, the structured-handler [:3000] truncation) all had the same shape: a
value was computed correctly upstream and then fell out of the payload at a
narrowing point nobody was watching. Each was found by accident, on a live
question.

This harness finds them mechanically. It appends a uniquely-named key
(CANARY_KEY: CANARY_VALUE) as the LAST key of a tool's result — the worst
position, since every truncation cuts from the end and every late addition
(snapshot_diff, _plausibility_warnings, ...) lands there — then drives the
REAL dynamic_query_loop end-to-end with a scripted LLM, and reports which
channels the canary survived:

  synthesis_input   — the messages passed to the LLM call that produced
                      the final answer. This is the channel that decides
                      whether the answer can be right.
  stored_step       — accumulated_data[step_N], the aggregated view the
                      loop's own checks and finalize logic read.
  returned_payload  — the tool_results dict dynamic_query_loop returns to
                      route_question (thread context, entity cache,
                      follow-up questions).

Only DB access, table classification, schema context and snapshot-anchor
resolution are stubbed — every router function between the tool call and
the synthesis call is the real code.
"""
import asyncio
import copy
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

import api.handlers as handlers_module
import api.router as router
import api.schema_context as schema_context_module
import api.table_classifier as table_classifier_module
import api.tools as tools_module

CANARY_KEY = "__canary_field__"
CANARY_VALUE = "CANARY_VALUE_12345"

CHANNELS = ("synthesis_input", "stored_step", "returned_payload")

# route_question always hands the loop a resolved time_window.
DEFAULT_TIME_WINDOW = {"label": "this quarter", "start": "2026-08-01", "end": "2026-10-31"}


def inject_canary(result: dict) -> dict:
    """Return a copy of `result` with the canary appended as its last key."""
    out = copy.deepcopy(result)
    out.pop(CANARY_KEY, None)
    out[CANARY_KEY] = CANARY_VALUE
    return out


def _contains_canary(obj) -> bool:
    return CANARY_VALUE in json.dumps(obj, default=str)


def _message_text(messages) -> str:
    """The literal text the model reads — message contents joined, not
    re-serialized (re-serializing would escape the embedded JSON's quotes)."""
    return "\n".join(str(m.get("content", "")) for m in (messages or []))


def keys_missing_from(text: str, result: dict) -> list:
    """Top-level keys of `result` whose `"key":` never appears in `text` —
    real handler fields that did not reach the model, not just the canary."""
    return [k for k in result if f'"{k}":' not in text]


class _FakeResponse:
    def __init__(self, text):
        self.text = text
        self.input_tokens = 1000
        self.output_tokens = 100


class ScriptedClient:
    """LLM stand-in: returns scripted responses in order, records every call.
    Once the script runs out it keeps answering with the last response, so a
    retry/verify pass inside the loop never crashes the harness."""

    def __init__(self, responses):
        self._responses = list(responses)
        self.calls = []

    def complete(self, messages=None, system=None, max_tokens=None):
        idx = min(len(self.calls), len(self._responses) - 1)
        self.calls.append({"messages": copy.deepcopy(messages), "system": system})
        return _FakeResponse(self._responses[idx])


class _FakeSupabase:
    """No .table() — every DB touch outside the mechanism under test is
    already behind a try/except in the router and degrades gracefully."""


def run_canary_case(question: str, tool_name: str, tool_params: dict,
                    tool_result: dict, answer_text: str = "Canary answer.",
                    time_window: dict = None) -> dict:
    """Drive dynamic_query_loop through one tool call that returns
    `tool_result` + canary, then one answer. Returns a report dict:
      {"channels": {channel: bool}, "answered": bool, "answer": str,
       "llm_calls": int, "result": <loop return value>}
    """
    canaried = inject_canary(tool_result)
    stored_steps = []

    orig = {
        "handler": getattr(handlers_module, tool_name, None),
        "filter_table": tools_module.filter_table,
        "classify": table_classifier_module.classify_relevant_tables,
        "schema": schema_context_module.get_schema_context,
        "anchors": router.resolve_snapshot_anchor_dates,
        "aggregate": router._aggregate_and_sample,
    }

    if tool_name.startswith("query_"):
        async def fake_handler(params, sb):
            return copy.deepcopy(canaried)
        setattr(handlers_module, tool_name, fake_handler)
    elif tool_name == "filter_table":
        async def fake_filter_table(sb, **kwargs):
            return copy.deepcopy(canaried)
        tools_module.filter_table = fake_filter_table
    else:
        raise ValueError(f"canary harness does not support tool {tool_name!r}")

    def recording_aggregate(result, *args, **kwargs):
        aggregated = orig["aggregate"](result, *args, **kwargs)
        stored_steps.append(aggregated)
        return aggregated

    router._aggregate_and_sample = recording_aggregate
    table_classifier_module.classify_relevant_tables = (
        lambda question, client: ["deals"])
    schema_context_module.get_schema_context = (
        lambda sb, tables_with_descriptions=None, lightweight=False:
            "TABLE: deals\n  deal_id, company_name, stage, owner_email, close_date, "
            "new_arr, expansion_arr, renewal_revenue, pipeline_id\n")
    router.resolve_snapshot_anchor_dates = lambda sb, tw: (None, None)

    client = ScriptedClient([
        json.dumps({"tool": tool_name, "params": tool_params}),
        json.dumps({"answer": answer_text}),
    ])

    try:
        result = asyncio.run(router.dynamic_query_loop(
            question=question,
            history=[],
            params={"time_window": time_window or DEFAULT_TIME_WINDOW},
            sb=_FakeSupabase(),
            client=client,
        ))
    finally:
        if orig["handler"] is not None:
            setattr(handlers_module, tool_name, orig["handler"])
        tools_module.filter_table = orig["filter_table"]
        table_classifier_module.classify_relevant_tables = orig["classify"]
        schema_context_module.get_schema_context = orig["schema"]
        router.resolve_snapshot_anchor_dates = orig["anchors"]
        router._aggregate_and_sample = orig["aggregate"]

    # The synthesis call is the LAST LLM call made after the tool executed.
    synthesis_messages = client.calls[-1]["messages"] if len(client.calls) >= 2 else []
    synthesis_text = _message_text(synthesis_messages)

    return {
        "channels": {
            "synthesis_input": CANARY_VALUE in synthesis_text,
            "stored_step": bool(stored_steps) and _contains_canary(stored_steps[-1]),
            "returned_payload": _contains_canary(result.get("tool_results", {})),
        },
        "tool_executed": bool(stored_steps),
        "keys_missing_from_synthesis": keys_missing_from(synthesis_text, canaried),
        "answered": result.get("answered"),
        "answer": result.get("answer", ""),
        "llm_calls": len(client.calls),
        "result": result,
    }
