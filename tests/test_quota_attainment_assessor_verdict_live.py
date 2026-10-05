"""
LIVE test (credential-gated): runs the REAL attainment payload through the
REAL api.assessor.assess_correctness() call and stores the actual verdict
JSON as a committed fixture file, so a future assessor-prompt change that
silently reintroduces the exact misjudgment this PR fixes (a correct
query_rep_attainment answer scored low with issue="wrong_handler",
suggested_handler="query_rep_attainment" — the SAME handler that ran) is
caught by diffing against this stored verdict, even in a sandbox with no
live credentials to reproduce the call itself.

Matches this repo's existing convention for a credential-gated live test —
see tests/test_explain_prior_answer_routing.py's LIVE section and
tests/test_quota_question_composer_routing.py's LIVE sub-test (PR #125):
gated on ANTHROPIC_API_KEY, expected to skip/fail cleanly without it,
validated by the real Pre-Merge Gate CI run, which has the real secret —
not by this offline suite.

First-run bootstrap: if tests/fixtures/quota_attainment_assessor_verdict.json
does not yet exist, a live run captures the real verdict, writes it there,
and FAILS (not skips) with an explicit message asking a human to commit the
new fixture file — this sandbox has no ANTHROPIC_API_KEY, so that capture
step could not be run here; the fixture file is intentionally NOT
committed with fabricated content. See the PR body for this flag.
"""
import asyncio
import json
import os
import sys
import unittest
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
for p in ("", "scripts", "scripts/analytics", "api"):
    sys.path.insert(0, str(REPO / p) if p else str(REPO))

FIXTURE_PATH = REPO / "tests" / "fixtures" / "quota_attainment_assessor_verdict.json"

THE_QUESTION = "Who's on track to hit quota?"
HANDLER_USED = "query_rep_attainment"

# The real synthesized answer shape for this question (a plain-language
# rendering of a real-shaped attainment result) — stable across runs so the
# assessor's verdict on it is a fair thing to snapshot and diff.
REAL_ANSWER = (
    "Team attainment this quarter: $160,000 of $200,000 combined quota "
    "(80% attainment). A is at 40% ($40,000 of $100,000); B is at 120% "
    "($120,000 of $100,000) and already past quota. 1 of 2 reps is above "
    "100% attainment, 1 of 2 is above 50%."
)

REAL_TOOL_RESULTS = {
    "period": "FY2027_Q3",
    "reps": [
        {"owner_email": "a@x.com", "name": "A", "quota": 100000, "won_arr": 40000,
         "attainment_pct": 40.0, "deals_won": 4},
        {"owner_email": "b@x.com", "name": "B", "quota": 100000, "won_arr": 120000,
         "attainment_pct": 120.0, "deals_won": 8},
    ],
    "team_summary": {
        "closed_won_qtd": 160000, "deals_won": 12, "unassigned_deals_won": 0,
        "total_quota": 200000, "total_stretch": 0, "total_combined": 200000,
        "quota_attainment": {"value": 80.0},
        "stretch_attainment": {"value": None, "data_gap": True},
        "combined_attainment": {"value": 80.0},
        "reps_above_50pct": 1, "reps_above_100pct": 1,
    },
}


def _live_assess():
    from llm_client import LLMClient
    from api.assessor import assess_correctness
    client = LLMClient.from_config(role="classifier")
    return asyncio.run(assess_correctness(
        question=THE_QUESTION,
        handler_used=HANDLER_USED,
        tool_results=REAL_TOOL_RESULTS,
        answer=REAL_ANSWER,
        client=client,
        budget_used=0.0,
    ))


class TestQuotaAttainmentAssessorVerdictLive(unittest.TestCase):

    def test_live_verdict_matches_committed_fixture(self):
        print("\n[LIVE TEST] assess_correctness on the real quota-attainment fixture")
        verdict = _live_assess()

        # Only the fields that matter for routing/retry decisions are
        # pinned — tone_score/learning_note prose can vary run to run
        # without being a regression.
        stable = {
            "correct": verdict.get("correct"),
            "issue": verdict.get("issue"),
            "suggested_handler": verdict.get("suggested_handler"),
        }

        if not FIXTURE_PATH.exists():
            FIXTURE_PATH.parent.mkdir(parents=True, exist_ok=True)
            FIXTURE_PATH.write_text(json.dumps(stable, indent=2, sort_keys=True) + "\n")
            self.fail(
                f"No committed fixture existed — captured the real live "
                f"verdict and wrote it to {FIXTURE_PATH}. A human must "
                f"review and commit this file; this test fails on first "
                f"capture so that step is never skipped silently. "
                f"Captured verdict: {stable}"
            )

        expected = json.loads(FIXTURE_PATH.read_text())
        self.assertEqual(
            stable, expected,
            f"Live assess_correctness() verdict on the quota-attainment "
            f"fixture changed from the committed snapshot "
            f"({FIXTURE_PATH}). If this is an intentional assessor-prompt "
            f"change, review whether it reintroduces the 2026-10 "
            f"misjudgment (issue='wrong_handler', "
            f"suggested_handler='query_rep_attainment' — the SAME handler "
            f"that ran) before updating the fixture.\n"
            f"expected={expected}\ngot={stable}"
        )
        print(f"  ✓ live verdict matches committed fixture: {stable}")


if __name__ == "__main__":
    unittest.main()
