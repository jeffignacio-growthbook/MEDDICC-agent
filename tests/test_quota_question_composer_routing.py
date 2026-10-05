"""
Tests for the exact real-world fixture that started this investigation:
"Who's on track to hit quota?" was escalated (by api/assessor.py's
assess_correctness judging the correct query_rep_attainment answer a
scope_mismatch — out of scope for this PR, untouched here) into
api/composer.py's decompose_question(), whose then-hardcoded primitive
whitelist did not include query_rep_attainment and instead offered a fake
primitive, "query_rep_scorecard". The resulting plan sent
api/agent_loop.py::run_agent_loop's call_primitive() to a name that
doesn't resolve, which fell back to a raw fetch_data/filter_table sum over
deals.deal_value — see api/composer.py's _build_available_primitives_block
docstring and tests/test_composer_primitive_drift.py for the general fix
and drift-detection suite this file complements.

This file is specific to the real fixture question, asserting the
decompose step itself, not just the static primitive list:

  OFFLINE (deterministic, no live LLM — always runnable in CI):
    1. The available-primitives block built for ANY decompose call already
       contains query_rep_attainment and omits query_rep_scorecard (belt
       and suspenders alongside test_composer_primitive_drift.py).
    2. With a mocked LLM client, decompose_question() is called with the
       exact fixture question and the prompt actually SENT to the client
       is inspected: it must contain query_rep_attainment, must not
       contain query_rep_scorecard, and must contain the question
       verbatim.
    3. _valid_plan() accepts a plan the mocked client returns that correctly
       names query_rep_attainment for this question, and decompose_question
       returns that exact plan (not a parse-failure dynamic_query fallback).

  LIVE (calls the real decompose_question → real LLM; matches this repo's
  existing convention for tests that need a live model — see
  tests/test_explain_prior_answer_routing.py's own LIVE section — expected
  to fail in a credential-less sandbox with no ANTHROPIC_API_KEY/.env;
  validated by the real Pre-Merge Gate CI run, which has the real secret):
    4. decompose_question() on the real fixture question routes to
       query_rep_attainment, never query_rep_scorecard or a raw
       dynamic_query-only fallback.
"""
import asyncio
import json
import sys
import types
import unittest
from pathlib import Path
from unittest.mock import MagicMock

REPO = Path(__file__).resolve().parents[1]
for p in ("", "scripts", "scripts/analytics", "api"):
    sys.path.insert(0, str(REPO / p) if p else str(REPO))

if "supabase" not in sys.modules:
    _fake = types.ModuleType("supabase")
    _fake.create_client = lambda *a, **k: None
    _fake.Client = type("Client", (), {})
    sys.modules["supabase"] = _fake

from api.composer import (  # noqa: E402
    decompose_question,
    _build_available_primitives_block,
    _valid_plan,
)

# Tonight's exact exchange, reproduced as a fixture.
THE_QUESTION = "Who's on track to hit quota?"
HANDLER_TRIED = "query_rep_attainment"  # the correct handler assess_correctness flagged anyway


# ══════════════════════════════════════════════════════════════
# OFFLINE — deterministic, no live LLM
# ══════════════════════════════════════════════════════════════

class TestQuotaQuestionRoutingOffline(unittest.TestCase):

    def test_available_primitives_offer_rep_attainment_not_fake_scorecard(self):
        print("\n[TEST] available-primitives block for the quota fixture question")
        block = _build_available_primitives_block()
        self.assertIn("query_rep_attainment", block)
        self.assertNotIn("query_rep_scorecard", block)

    def test_decompose_prompt_sent_to_llm_contains_rep_attainment(self):
        """Inspect the ACTUAL prompt text decompose_question sends the
        client for this exact question — not just the block in isolation —
        so a future refactor that stops wiring available_primitives into
        the prompt (e.g. reverting to a literal string) is caught here."""
        print("\n[TEST] decompose_question's sent prompt contains "
              "query_rep_attainment for the quota fixture")
        mock_client = MagicMock()
        mock_resp = MagicMock()
        mock_resp.text = json.dumps({
            "question": THE_QUESTION,
            "explanation": "needs rep-level attainment",
            "sub_parts": [
                {"name": "attainment", "primitive": "query_rep_attainment",
                 "rationale": "won revenue vs quota for every rep"},
            ],
        })
        mock_client.complete.return_value = mock_resp

        plan = asyncio.run(decompose_question(
            question=THE_QUESTION,
            handler_used=HANDLER_TRIED,
            tool_results={},
            client=mock_client,
        ))

        mock_client.complete.assert_called_once()
        sent_prompt = mock_client.complete.call_args.kwargs["messages"][0]["content"]

        self.assertIn("query_rep_attainment", sent_prompt)
        self.assertNotIn("query_rep_scorecard", sent_prompt)
        self.assertIn(THE_QUESTION, sent_prompt)

        # And the plan returned is the one the (mocked) model produced —
        # not a parse-failure dynamic_query-only fallback.
        sub_parts = plan.get("sub_parts") or []
        primitives_in_plan = {p.get("primitive") for p in sub_parts}
        self.assertIn("query_rep_attainment", primitives_in_plan)
        self.assertNotIn("query_rep_scorecard", primitives_in_plan)
        self.assertNotEqual(
            primitives_in_plan, {"dynamic_query"},
            "decompose_question fell back to its dynamic_query-only "
            "fallback plan instead of using the model's real plan"
        )
        print("  ✓ sent prompt offers query_rep_attainment, omits the fake "
              "primitive, and the returned plan names it")

    def test_valid_plan_accepts_the_real_plan_for_this_question(self):
        """_valid_plan() is a structural check only — see its docstring for
        why it deliberately does not also enforce the KNOWN_PRIMITIVES
        allow-list (that enforcement lives at the prompt-generation source,
        _build_available_primitives_block, tested above and in
        tests/test_composer_primitive_drift.py)."""
        plan = {
            "question": THE_QUESTION,
            "sub_parts": [
                {"name": "attainment", "primitive": "query_rep_attainment",
                 "rationale": "won revenue vs quota for every rep"},
            ],
        }
        self.assertTrue(_valid_plan(plan))


# ══════════════════════════════════════════════════════════════
# LIVE — real decompose_question → real LLM.
# Matches tests/test_explain_prior_answer_routing.py's existing convention:
# exercises the ACTUAL model, because "does decompose_question now route
# this question correctly" is a behavioral claim about the live model a
# mock cannot verify. Expected to fail in a credential-less sandbox (no
# ANTHROPIC_API_KEY/.env) — validated by the real Pre-Merge Gate CI run,
# which has the real secret, not by this offline suite.
# ══════════════════════════════════════════════════════════════

def _live_decompose(question: str, handler_used: str) -> dict:
    from llm_client import LLMClient
    client = LLMClient.from_config(role="classifier")
    return asyncio.run(decompose_question(
        question=question, handler_used=handler_used,
        tool_results={}, client=client,
    ))


class TestQuotaQuestionRoutingLive(unittest.TestCase):

    def test_live_decompose_routes_quota_question_to_rep_attainment(self):
        print("\n[LIVE TEST] decompose_question on the real quota fixture question")
        plan = _live_decompose(THE_QUESTION, HANDLER_TRIED)
        primitives_in_plan = {p.get("primitive") for p in (plan.get("sub_parts") or [])}
        self.assertIn(
            "query_rep_attainment", primitives_in_plan,
            f"live decompose_question did not route to query_rep_attainment "
            f"for {THE_QUESTION!r}; got sub_parts={plan.get('sub_parts')}"
        )
        self.assertNotIn("query_rep_scorecard", primitives_in_plan)


if __name__ == "__main__":
    unittest.main()
