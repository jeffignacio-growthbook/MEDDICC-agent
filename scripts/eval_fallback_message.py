#!/usr/bin/env python3
"""
Eval: the dynamic fallback fails fast and diagnostically
(FIX_DYNAMIC_FALLBACK_PATTERN, PART 1 + PART 2).

PART 1 — when the loop gives up, the reply NAMES what fell through in plain
language, and a greppable `[FALLBACK] handler=X reason=Y question=Z` line is
logged. The technical reason (e.g. KeyError) stays in the log, never the reply.

PART 2a — the loop returns an explicit `answered` flag; the caller no longer
sniffs the text for "couldn't".

PART 2b — a repeated tool call ends the loop and synthesises from data already
gathered, instead of burning the remaining budget re-emitting the same query.

Runs fully offline: the heavy imports the loop makes (schema_context,
table_classifier, tools) are stubbed, and the LLM client is scripted.
"""
import sys
import types
import asyncio
import logging
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
for p in ("", "scripts", "api"):
    sys.path.insert(0, str(REPO / p) if p else str(REPO))

# ── stub supabase + the loop's inner imports BEFORE importing api.router ──
if "supabase" not in sys.modules:
    _sb = types.ModuleType("supabase")
    _sb.create_client = lambda *a, **k: None
    _sb.Client = type("Client", (), {})
    sys.modules["supabase"] = _sb

_HUGE_SCHEMA = "col " * 30000  # ~120k chars → ~30k est tokens, over the budget

_schema_mod = types.ModuleType("api.schema_context")
_schema_mod.get_schema_context = lambda sb, tables_with_descriptions=None: ""
sys.modules["api.schema_context"] = _schema_mod

_tc_mod = types.ModuleType("api.table_classifier")
_tc_mod.classify_relevant_tables = lambda q, client: []
sys.modules["api.table_classifier"] = _tc_mod

_tools_mod = types.ModuleType("api.tools")
async def _filter_table(sb, **kw):
    return {"rows": [{"deal_id": "1", "company_name": "LiveSport Media"}],
            "table": kw.get("table", "deals")}
async def _join_tables(sb, **kw):
    return {"rows": [], "table": "join"}
async def _aggregate_results(**kw):
    return {"rows": [{"n": 1}], "table": "agg"}
async def _compare_periods(sb, **kw):
    return {"rows": [], "table": "cmp"}
_tools_mod.filter_table = _filter_table
_tools_mod.join_tables = _join_tables
_tools_mod.aggregate_results = _aggregate_results
_tools_mod.compare_periods = _compare_periods
sys.modules["api.tools"] = _tools_mod


class Resp:
    def __init__(self, text, it=200, ot=100):
        self.text = text
        self.input_tokens = it
        self.output_tokens = ot


class ScriptedClient:
    """Returns queued responses in order; last one repeats."""
    def __init__(self, responses):
        self._responses = list(responses)
        self.calls = 0

    def complete(self, messages=None, system=None, max_tokens=None):
        self.calls += 1
        idx = min(self.calls - 1, len(self._responses) - 1)
        return self._responses[idx]


class _CaptureLog(logging.Handler):
    def __init__(self):
        super().__init__()
        self.lines = []

    def emit(self, record):
        self.lines.append(record.getMessage())


def _capture():
    from api.router import logger
    h = _CaptureLog()
    logger.addHandler(h)
    return h


def run():
    import api.router as R

    print("=" * 72)
    print("DYNAMIC FALLBACK — diagnostic message + fail-fast")
    print("=" * 72)
    passed = failed = 0

    def check(name, cond):
        nonlocal passed, failed
        if cond:
            passed += 1; print(f"  ✓ {name}")
        else:
            failed += 1; print(f"  ❌ {name}")

    params = {"time_window": {"label": "this quarter",
                              "start": "2026-08-01", "end": "2026-10-31"}}

    # ── Scenario A: budget exhausted immediately (huge schema) ──
    # A fell-through handler with a real KeyError reason. The reply must name
    # what fell through in plain words; the KeyError goes only to the log.
    R.DYNAMIC_SYSTEM_PROMPT = "{schema_context}{roster_text}" + _HUGE_SCHEMA
    log = _capture()
    client = ScriptedClient([Resp('{"tool": "filter_table", "params": {}}')])
    result = asyncio.run(R.dynamic_query_loop(
        question="score the LiveSport deal on MEDDICC",
        history=[], params=params, sb=object(), client=client,
        classifier_client=client,
        origin_handler="query_rubric_scores_bulk",
        origin_reason="KeyError: 'deal_ids'"))

    print("\n[Scenario A] handler fell through, fallback ran out of budget:")
    print(f"    reply → {result['answer']}")
    fallback_lines = [ln for ln in log.lines if ln.startswith("[FALLBACK]")]
    print(f"    log   → {fallback_lines[0] if fallback_lines else '(none)'}")

    check("answered=False on give-up", result.get("answered") is False)
    check("reply names what fell through (plain, mentions MEDDICC scores)",
          "MEDDICC scores" in result["answer"])
    check("reply hides the technical reason (no 'KeyError')",
          "KeyError" not in result["answer"])
    check("[FALLBACK] log line emitted", bool(fallback_lines))
    check("[FALLBACK] carries handler name",
          fallback_lines and "handler=query_rubric_scores_bulk" in fallback_lines[0])
    check("[FALLBACK] carries technical reason",
          fallback_lines and "KeyError: 'deal_ids'" in fallback_lines[0])
    check("[FALLBACK] carries the question",
          fallback_lines and "LiveSport" in fallback_lines[0])

    # ── Scenario B: repeated tool call ends the loop and synthesises ──
    # Model emits the SAME filter_table call every turn. It should NOT run all
    # 5 iterations: after the stall it finalises from gathered data.
    R.DYNAMIC_SYSTEM_PROMPT = "{schema_context}{roster_text}"
    dup = '{"tool": "filter_table", "params": {"table": "deals", "columns": "deal_id", "filters": []}}'
    # After the stall, the forced-synthesis call returns a real answer.
    client2 = ScriptedClient([Resp(dup), Resp(dup), Resp(dup),
                              Resp('{"answer": "LiveSport is in Discovery."}')])
    result2 = asyncio.run(R.dynamic_query_loop(
        question="which of my deals moved this week",
        history=[], params=params, sb=object(), client=client2,
        classifier_client=client2))

    print("\n[Scenario B] model repeats a query — loop stops early:")
    print(f"    llm calls used = {client2.calls} (max would be 5 tool turns)")
    print(f"    answered = {result2.get('answered')}")
    check("duplicate abort stops well before 5 tool iterations",
          client2.calls <= 4)
    check("synthesised an answer from gathered data",
          result2.get("answered") is True and "LiveSport" in result2["answer"])

    print("\n" + "=" * 72)
    print(f"RESULTS: {passed} passed, {failed} failed")
    print("=" * 72)
    return 0 if failed == 0 else 1


if __name__ == "__main__":
    sys.exit(run())
