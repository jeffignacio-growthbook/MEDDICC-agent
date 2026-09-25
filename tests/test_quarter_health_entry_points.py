#!/usr/bin/env python3
"""
The two routed entry points on the quarter-health composer:

  query_quarter_health    "are we in good shape this quarter?"   scenario base
  query_quarter_downside  "what's the downside this quarter?"   scenario downside

Both are thin: one call to api.quarter_health.compose_quarter_health with
their scenario, always for the current quarter (every primitive defaults
to it; a classifier-extracted time_window or owner is not passed through,
so the four figures can't end up covering different periods). No other
logic.

Registration, per the survival test's findings:
  - HANDLER_DESCRIPTIONS (the classifier's menu), with wording that does
    not overlap the four primitives they compose or each other;
  - api.evaluator.STRUCTURED_HANDLERS, keyed on "status" (unregistered, the
    loop reads the result through its 8,000-char row-aggregation view and
    drops 14 disclosures);
  - the dynamic loop's tool map and its tool list (DYNAMIC_SYSTEM_PROMPT).

End to end: each real entry point runs on the real captured primitive
outputs (tests/fixtures/quarter_health_primitives_2026_09_25.json; the four
primitives, the stage table and the deals read are served from it), then
the REAL dynamic_query_loop calls it as a tool with a scripted model
(tests/canary_harness.py). Every disclosure and the four headline numbers
must reach the final synthesis call, and the canary every channel.
"""
import asyncio
import copy
import json
import re
import sys
from pathlib import Path
from unittest.mock import patch

REPO = Path(__file__).parent.parent
sys.path.insert(0, str(REPO / "tests"))
sys.path.insert(0, str(REPO))
sys.path.insert(0, str(REPO / "scripts"))
sys.path.insert(0, str(REPO / "scripts" / "analytics"))

import logging  # noqa: E402
logging.disable(logging.CRITICAL)

import api.evaluator as evaluator  # noqa: E402
import api.handlers as handlers  # noqa: E402
import api.quarter_health as qh  # noqa: E402
import api.router as router  # noqa: E402
from canary_harness import run_canary_case  # noqa: E402
from test_pipeline_routing_split import claimed_phrases, tool_entries  # noqa: E402
import test_quarter_health_disclosure_survival as surv  # noqa: E402

FIXTURE = surv.FIXTURE
ENTRY = {"base": "query_quarter_health", "downside": "query_quarter_downside"}
QUESTION = {"base": "Are we in good shape this quarter?",
            "downside": "What's the downside this quarter?"}
NEIGHBOURS = ("query_forecast_trust", "query_pipeline", "query_high_priority_deal_risk",
              "query_loss_concentration", "query_pipeline_coverage", "query_rep_attainment")


class _SB:
    """Serves the downside's one deals read from the capture."""
    def table(self, name):
        assert name == "deals", name
        rows = FIXTURE["high_risk_deal_rows"]

        class Q:
            def select(self, *a, **k): return self
            def in_(self, col, ids):
                self._ids = set(map(str, ids)); return self
            def execute(self):
                class R: pass
                r = R(); r.data = [x for x in rows if str(x["deal_id"]) in self._ids]; return r
        return Q()


def _real_primitives(calls=None):
    def rec(name):
        async def fn(params, sb):
            if calls is not None:
                calls.append((name, dict(params)))
            return copy.deepcopy(FIXTURE[name])
        return fn
    return patch.multiple(handlers, **{n: rec(n) for n in qh.PRIMITIVE_ORDER})


def _run_entry(scenario, params=None, calls=None):
    with _real_primitives(calls), \
         patch("forecast_analyses.query_stage_close_rate",
               side_effect=lambda sb=None: copy.deepcopy(FIXTURE["stage_close_rate"])):
        return asyncio.run(getattr(handlers, ENTRY[scenario])(params or {}, _SB()))


def test_entry_points_are_thin_and_current_quarter_only():
    for scenario, name in ENTRY.items():
        seen = []

        async def fake(sb, params=None, scenario_arg="base"):
            seen.append((params, scenario_arg))
            return {"status": "ok"}
        with patch.object(qh, "compose_quarter_health", fake):
            out = asyncio.run(getattr(handlers, name)(
                {"time_window": {"start": "2025-01-01", "end": "2025-03-31"}, "owner_email": "x@y"}, None))
        assert out == {"status": "ok"} and seen == [({}, scenario)], (name, seen)
        assert qh.ENTRY_POINTS[scenario] == name
    calls = []
    _run_entry("downside", {"time_window": {"start": "2025-01-01", "end": "2025-03-31"}}, calls)
    assert [c[0] for c in calls] == list(qh.PRIMITIVE_ORDER) and all(p == {} for _, p in calls), calls
    print("✓ both entry points make one composer call with their scenario; incoming time_window/owner "
          "are not passed on, so all four primitives answer for the current quarter")


def test_entry_point_error_is_a_result_not_a_raise():
    async def boom(*a, **k):
        raise RuntimeError("composer down")
    for name in ENTRY.values():
        with patch.object(qh, "compose_quarter_health", boom):
            out = asyncio.run(getattr(handlers, name)({}, None))
        assert out["status"] == "error" and "composer down" in out["error"], out
    print("✓ a composer failure comes back as status error, never a raise")


def test_registered_where_the_findings_require():
    for name in ENTRY.values():
        assert name in router.HANDLER_DESCRIPTIONS, name
        assert evaluator.STRUCTURED_HANDLERS.get(name) == ["status"], name
        assert name in tool_entries(), f"{name} not in the dynamic loop's tool list"
        assert evaluator.evaluate_result({"status": "ok"}, name) != "empty"
    print("✓ both in HANDLER_DESCRIPTIONS, STRUCTURED_HANDLERS (status) and the loop's tool list")


def test_routing_wording_does_not_overlap_the_primitives_or_each_other():
    d = router.HANDLER_DESCRIPTIONS
    health, down = d["query_quarter_health"].lower(), d["query_quarter_downside"].lower()
    assert "good shape" in health and "downside" in down and "worst case" in down
    for n in NEIGHBOURS:
        text = d[n].lower() if isinstance(d[n], str) else " ".join(d[n]).lower()
        for phrase in ("good shape", "downside", "worst case"):
            assert phrase not in text, (n, phrase)
    entries = tool_entries()
    claims = {n: set(claimed_phrases(entries[n])) for n in ENTRY.values()}
    assert "are we in good shape this quarter" in claims["query_quarter_health"], claims
    assert "what's the downside this quarter" in claims["query_quarter_downside"], claims
    assert not (claims["query_quarter_health"] & claims["query_quarter_downside"])
    for n in entries:
        if n not in ENTRY.values():
            assert not (set(claimed_phrases(entries[n])) & (claims["query_quarter_health"] |
                                                          claims["query_quarter_downside"])), n
    print("✓ 'good shape' / 'downside' / 'worst case' belong to the entry points only; no loop tool "
          "claims their example phrases")


def test_end_to_end_through_the_real_dynamic_loop():
    for scenario, name in ENTRY.items():
        result = _run_entry(scenario)
        assert result["status"] == "ok" and result["scenario"] == scenario
        rep = run_canary_case(QUESTION[scenario], name, {}, result)
        assert rep["tool_executed"], f"{name}: the loop never ran the tool"
        assert all(rep["channels"].values()), (name, rep["channels"])
        text = rep["synthesis_text"]
        missing = [p for _, p, s in surv.DISCLOSURES if not surv._present(s, text)]
        assert not missing, (name, missing[:5])
        for label, needle in surv.HEADLINE.items():
            assert needle in text, (name, label)
        assert rep["answered"], name
        if scenario == "downside":
            assert '"worst_case_arr"' in text and "1 moderate_risk deal" in text
    print(f"✓ end to end, each entry point through the real dynamic loop: all {len(surv.DISCLOSURES)} "
          "disclosures, the 4 headline numbers and the canary reach the synthesis call")


if __name__ == "__main__":
    test_entry_points_are_thin_and_current_quarter_only()
    test_entry_point_error_is_a_result_not_a_raise()
    test_registered_where_the_findings_require()
    test_routing_wording_does_not_overlap_the_primitives_or_each_other()
    test_end_to_end_through_the_real_dynamic_loop()
    print("\n✅ All tests passed")
