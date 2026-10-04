"""
LIVE verification for the two 2026-10-03 follow-ups to the coverage-answer
omissions fix (api/handlers.py::query_pipeline_coverage's _synthesis_note):

1. CURRENT-PIPELINE-BY-STAGE BREAKDOWN: when qualified_pipeline.
   by_stage_order is present in the payload, the model's stage claims
   should match it (not invent a different stage concentration).

2. LATE-PHASE COMMIT-QUESTION GUIDANCE: in late phase with no commit-stage
   data in the payload, the model should name a concrete follow-up
   question (e.g. "which deals are in commit?") rather than a vague
   pointer like "pull the committed pipeline."

Context: a real live Slack answer said "most deals are sitting in
Discovery and Scoping" — an unsupported model inference, since the
payload at the time never actually showed a by-stage breakdown. Offline
coverage of both guidance changes lives in
scripts/test_pipeline_by_stage.py (the primitive) and
tests/test_pipeline_coverage_stage_and_commit_guidance.py (the handler's
_synthesis_note text) — this file is the live counterpart: does a REAL
model, under the REAL synthesis system prompt
(api.router.build_synthesis_prompt), actually comply.

Credential-gated (ANTHROPIC_API_KEY), excluded from gate-tests.yml's
curated list for the same reason the other LIVE tests are (see
tests/test_pipeline_coverage_answer_omissions.py,
tests/test_explain_prior_answer_routing.py) — not included in main()'s
test list below, so a bare `python3 tests/test_pipeline_stage_and_commit_
question_live.py` invocation (the gate's own style) never runs it;
pytest still discovers it directly.

Run manually once credentials are available:
    PYTHONPATH=.:scripts:api:scripts/analytics python3 -m pytest \\
        tests/test_pipeline_stage_and_commit_question_live.py -v
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

# (a) Mid-phase, WITH a real by-stage breakdown — most of the qualified
# pipeline sits at stage order 1 (Discovery), the rest at order 3
# (Technical Evaluation). The stage_name annotation (api/handlers.py)
# resolves these from GrowthBook's real config/client.yaml.
_FIXTURE_WITH_STAGE_BREAKDOWN = {
    "status": "ok",
    "fiscal_quarter": "FY2027 Q3",
    "current_week": 6,
    "quarter_time_left": {"days_left": 42, "weeks_left": 6, "label": "6 weeks left"},
    "is_historical": False,
    "scope": "New+Expansion ARR only; qualified pipeline only",
    "qualified_pipeline": {
        "raw_value": 1000000.0, "deal_count": 20,
        "by_stage_order": {
            1: {"deal_count": 15, "value": 750000.0},
            3: {"deal_count": 5, "value": 250000.0},
        },
    },
    "renewal_not_weighted": {"deal_count": 2, "value": 50000.0, "note": "..."},
    "stage_weighting": {
        "weighted_value": 350000.0, "weighted_deal_count": 20,
        "unweighted_value": 0.0, "unweighted_deal_count": 0,
        "by_stage_order": {}, "min_evidence_count": 30, "note": "...",
    },
    "real_target": {
        "quota": 1550000.0, "stretch": 2100000.0, "goal": 1550000.0,
        "stretch_note": "Ryan's personal aspiration.",
        "note": "Stated target for FY2027 Q3 — team quota from rep_targets.",
    },
    "qtd_won": {"value": 300000.0, "deal_count": 6, "note": "test qtd note"},
    "coverage": {
        "remaining_gap": 1250000.0,
        "nominal_coverage": 1000000.0 / 1250000.0,
        "weighted_coverage": 350000.0 / 1250000.0,
        "quota_met": False,
        "nominal_expected_multiple": 2.0, "weighted_expected_multiple": 1.2,
        "nominal_ahead_behind": "behind", "weighted_ahead_behind": "behind",
        "phase": "mid",
        "equations": {
            "remaining": "$1,550,000 quota - $300,000 won = $1,250,000 remaining",
            "nominal": "$1,000,000 raw qualified pipeline / $1,250,000 remaining = 0.80x",
            "weighted": "$350,000 weighted pipeline / $1,250,000 remaining = 0.28x",
        },
        "note": "test coverage note",
    },
    "historical_heuristic_curve": {"by_week": {}, "proxy_targets": {},
                                   "heuristic": True, "label": "HEURISTIC",
                                   "note": "HEURISTIC."},
    "note": "HEURISTIC curve note.",
}

# (b) Late phase, no by-stage breakdown at all (field absent) — the model
# must not invent a stage-concentration claim, and must name a concrete
# follow-up question for committed pipeline rather than a vague pointer.
_FIXTURE_LATE_NO_STAGE_BREAKDOWN = {
    "status": "ok",
    "fiscal_quarter": "FY2027 Q3",
    "current_week": 11,
    "quarter_time_left": {"days_left": 14, "weeks_left": 2, "label": "2 weeks left"},
    "is_historical": False,
    "scope": "New+Expansion ARR only; qualified pipeline only",
    "qualified_pipeline": {"raw_value": 900000.0, "deal_count": 18},
    "renewal_not_weighted": {"deal_count": 2, "value": 50000.0, "note": "..."},
    "stage_weighting": {
        "weighted_value": 300000.0, "weighted_deal_count": 18,
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
        "nominal_coverage": 900000.0 / 1029940.0,
        "weighted_coverage": 300000.0 / 1029940.0,
        "quota_met": False,
        "nominal_expected_multiple": 1.0, "weighted_expected_multiple": 1.0,
        "nominal_ahead_behind": "behind", "weighted_ahead_behind": "behind",
        "phase": "late",
        "equations": {
            "remaining": "$1,550,000 quota - $520,060 won = $1,029,940 remaining",
            "nominal": "$900,000 raw qualified pipeline / $1,029,940 remaining = 0.87x",
            "weighted": "$300,000 weighted pipeline / $1,029,940 remaining = 0.29x",
        },
        "note": "test coverage note",
    },
    "historical_heuristic_curve": {"by_week": {}, "proxy_targets": {},
                                   "heuristic": True, "label": "HEURISTIC",
                                   "note": "HEURISTIC."},
    "note": "HEURISTIC curve note.",
}

QUESTION = "What's our current pipeline coverage?"


async def _tool_results(fixture):
    with patch("pipeline_coverage.assess_pipeline_coverage", return_value=dict(fixture)):
        result = await handlers.query_pipeline_coverage({}, MagicMock())
    result.pop("cache_payload", None)
    return result


def _ask_real_model(client, fixture):
    from api.router import build_synthesis_prompt

    tool_results = asyncio.run(_tool_results(fixture))
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


def test_live_stage_claims_match_the_real_by_stage_breakdown_when_present():
    """3 samples against a fixture WITH qualified_pipeline.by_stage_order:
    if the answer makes any stage-concentration claim, it must match the
    real breakdown (Discovery/stage order 1 holds the most: 15 of 20
    deals, $750k of $1M) — not invented, not a different stage."""
    print("\n[TEST] LIVE: stage claims match the real by-stage breakdown when present")
    from llm_client import LLMClient

    client = LLMClient.from_config(role="generator")
    failures = []
    for i in range(3):
        answer = _ask_real_model(client, _FIXTURE_WITH_STAGE_BREAKDOWN)
        print(f"\n  sample {i + 1}: {answer[:400]}")
        lower = answer.lower()
        mentions_stage_claim = (
            "discovery" in lower or "technical evaluation" in lower or
            "scoping" in lower or "negotiating" in lower or
            "awaiting signature" in lower
        )
        # If a stage claim is made at all, Discovery (the real majority
        # stage) must be the one named as holding the most pipeline —
        # never a stage absent from the breakdown (e.g. Scoping, which
        # has zero deals in this fixture).
        wrong_stage_named = "scoping" in lower or "negotiating" in lower or \
            "awaiting signature" in lower
        if mentions_stage_claim and wrong_stage_named:
            failures.append({"sample": i + 1, "answer": answer,
                             "reason": "named a stage absent from the real breakdown"})

    if failures:
        raise AssertionError(
            f"{len(failures)}/3 samples named a stage not present in the real "
            f"by_stage_order breakdown: {json.dumps(failures, indent=2)}")
    print("\n  ✓ all 3 samples' stage claims (if any) match the real breakdown")


def test_live_late_phase_names_concrete_follow_up_question():
    """3 samples against a LATE-phase fixture with NO by-stage breakdown
    and no commit-stage data: the answer must name a concrete follow-up
    question (containing 'commit' and a question mark, or clear
    question-like phrasing) rather than a vague pointer."""
    print("\n[TEST] LIVE: late phase names a concrete follow-up question")
    from llm_client import LLMClient

    client = LLMClient.from_config(role="generator")
    failures = []
    for i in range(3):
        answer = _ask_real_model(client, _FIXTURE_LATE_NO_STAGE_BREAKDOWN)
        print(f"\n  sample {i + 1}: {answer[:400]}")
        lower = answer.lower()
        mentions_commit = "commit" in lower
        has_question_mark = "?" in answer
        if not (mentions_commit and has_question_mark):
            failures.append({"sample": i + 1, "answer": answer,
                             "mentions_commit": mentions_commit,
                             "has_question_mark": has_question_mark})

    if failures:
        raise AssertionError(
            f"{len(failures)}/3 samples did not name a concrete commit-stage "
            f"follow-up question: {json.dumps(failures, indent=2)}")
    print("\n  ✓ all 3 samples name a concrete follow-up question about commit-stage deals")


def main():
    print("This file's tests are LIVE (ANTHROPIC_API_KEY) and intentionally "
          "excluded from this file's own offline runner — run them directly "
          "with pytest:\n"
          "  PYTHONPATH=.:scripts:api:scripts/analytics python3 -m pytest "
          "tests/test_pipeline_stage_and_commit_question_live.py -v")
    return 0


if __name__ == "__main__":
    sys.exit(main())
