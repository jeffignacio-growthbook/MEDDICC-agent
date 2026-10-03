"""
LIVE verification for the 2026-10-03 coverage-answer omissions fix
(api/handlers.py::query_pipeline_coverage's _synthesis_note).

Context: production dropped the three-operand subtraction, the week's
expectation/ahead-behind read, and the renewal-expansion clause from a
real week-10 (late-phase) answer, even though the guidance for all three
reached the model uncapped (confirmed offline in
tests/test_pipeline_coverage_gap_arithmetic.py and
scripts/test_pipeline_coverage.py — this file is the live counterpart:
does a REAL model, under the REAL synthesis system prompt
(api.router.build_synthesis_prompt — includes the real "_synthesis_note:
ALWAYS follow" instruction, TABLE_FORMAT_RULE, and the 5-8 line
guideline), actually comply on the exact production payload.

Credential-gated (ANTHROPIC_API_KEY), excluded from gate-tests.yml's
curated list for the same reason the other LIVE tests are (see
tests/test_explain_prior_answer_routing.py,
tests/test_explain_prior_answer_citation.py) — not included in main()'s
test list below, so a bare `python3 tests/test_pipeline_coverage_answer_
omissions.py` invocation (the gate's own style) never runs it; pytest
still discovers it directly.

Run manually once credentials are available:
    PYTHONPATH=.:scripts:api:scripts/analytics python3 -m pytest \\
        tests/test_pipeline_coverage_answer_omissions.py -v
"""
import json
import sys
from pathlib import Path
from unittest.mock import MagicMock, patch

REPO = Path(__file__).resolve().parents[1]
for p in ("", "scripts", "scripts/analytics", "api"):
    sys.path.insert(0, str(REPO / p) if p else str(REPO))

import types  # noqa: E402
if "supabase" not in sys.modules:
    _fake = types.ModuleType("supabase")
    _fake.create_client = lambda *a, **k: None
    _fake.Client = type("Client", (), {})
    sys.modules["supabase"] = _fake

import asyncio  # noqa: E402
from api import handlers  # noqa: E402

# The exact payload from the real week-10 production Slack answer this
# fix addresses (Jeff's "What's our current pipeline coverage?" question,
# 2026-10-03 3:54pm).
_FIXTURE = {
    "status": "ok",
    "fiscal_quarter": "FY2027 Q3",
    "current_week": 10,
    "quarter_time_left": {"days_left": 28, "weeks_left": 4, "label": "4 weeks left"},
    "is_historical": False,
    "scope": "New+Expansion ARR only; qualified pipeline only",
    "qualified_pipeline": {"raw_value": 4429916.0, "deal_count": 43},
    "renewal_not_weighted": {"deal_count": 7, "value": 256000.0,
                              "note": "Renewal-pipeline expansion ARR closing this quarter: "
                                      "no governed stage rate, so it is not in the weighted "
                                      "total and is not given a Sales stage's rate."},
    "stage_weighting": {
        "weighted_value": 799782.0, "weighted_deal_count": 19,
        "unweighted_value": 0.0, "unweighted_deal_count": 0,
        "by_stage_order": {}, "min_evidence_count": 30, "note": "...",
    },
    "real_target": {
        "quota": 1550000.0, "stretch": 2100000.0, "goal": 1550000.0,
        "stretch_note": "Ryan's personal aspiration.",
        "note": "Stated target for FY2027 Q3 — team quota from rep_targets.",
    },
    "qtd_won": {"value": 520060.0, "deal_count": 12, "note": "test qtd note"},
    "coverage": {
        "remaining_gap": 1029940.0,
        "nominal_coverage": 4429916.0 / 1029940.0,
        "weighted_coverage": 799782.0 / 1029940.0,
        "quota_met": False,
        "expected_multiple": None, "ahead_behind": None,
        "phase": "late",
        "equations": {
            "remaining": "$1,550,000 quota - $520,060 won = $1,029,940 remaining",
            "nominal": "$4,429,916 raw qualified pipeline / $1,029,940 remaining = 4.30x",
            "weighted": "$799,782 weighted pipeline / $1,029,940 remaining = 0.78x",
        },
        "note": "test coverage note",
    },
    "historical_heuristic_curve": {"by_week": {}, "proxy_targets": {},
                                   "heuristic": True, "label": "HEURISTIC",
                                   "note": "HEURISTIC."},
    "note": "HEURISTIC curve note.",
}

QUESTION = "What's our current pipeline coverage?"


async def _tool_results():
    with patch("pipeline_coverage.assess_pipeline_coverage", return_value=dict(_FIXTURE)):
        result = await handlers.query_pipeline_coverage({}, MagicMock())
    result.pop("cache_payload", None)
    return result


def _ask_real_model(client):
    from api.router import build_synthesis_prompt

    tool_results = asyncio.run(_tool_results())
    system = build_synthesis_prompt({"name": "Jeff", "role_group": "leadership"})
    user = (
        f"Tool result: {json.dumps(tool_results)}\n\n"
        f"Answer this question now: {QUESTION}\n\n"
        'Respond as {"answer": "..."}.'
    )
    resp = client.complete(messages=[{"role": "user", "content": user}],
                            system=system, max_tokens=800)
    from api.router import _extract_json
    parsed = _extract_json(resp.text)
    return (parsed or {}).get("answer") or resp.text


def test_live_five_samples_contain_equation_expectation_and_renewal_clause():
    """Phase 2 item 8: ask the question against the fixed production
    payload 5 times; each output must contain the equation, the 1x
    expectation/ahead-behind read, and the renewal clause. If a live
    sample still drops the equation after this guidance, STOP and report
    — the fallback (appending that line in code) is a decision for Jeff,
    not made here."""
    print("\n[TEST] LIVE: 5 real-model samples contain equation, 1x expectation, renewal clause")
    from llm_client import LLMClient

    client = LLMClient.from_config(role="generator")
    failures = []
    for i in range(5):
        answer = _ask_real_model(client)
        print(f"\n  sample {i + 1}: {answer[:400]}")
        has_equation = ("1,029,940" in answer and (
            "1,550,000" in answer or "520,060" in answer))
        has_expectation = ("1x" in answer.lower() or "1.0x" in answer)
        has_renewal_clause = ("renewal" in answer.lower() and
                              ("qtd" in answer.lower() or "won" in answer.lower() or
                               "includ" in answer.lower()))
        if not (has_equation and has_expectation and has_renewal_clause):
            failures.append({
                "sample": i + 1, "has_equation": has_equation,
                "has_expectation": has_expectation,
                "has_renewal_clause": has_renewal_clause, "answer": answer,
            })

    if failures:
        raise AssertionError(
            f"{len(failures)}/5 samples dropped a required item after the guidance "
            f"fix — STOP, do not patch further here; report to Jeff for the "
            f"code-level fallback decision. Failures: {json.dumps(failures, indent=2)}")
    print("\n  ✓ all 5 samples contain the equation, the 1x expectation, and the renewal clause")


def main():
    print("This file's one test is LIVE (ANTHROPIC_API_KEY) and intentionally "
          "excluded from this file's own offline runner — run it directly with pytest:\n"
          "  PYTHONPATH=.:scripts:api:scripts/analytics python3 -m pytest "
          "tests/test_pipeline_coverage_answer_omissions.py -v")
    return 0


if __name__ == "__main__":
    sys.exit(main())
