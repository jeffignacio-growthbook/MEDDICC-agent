"""
Test suite for api/agent_loop.py — the model-driven reasoning loop
that replaces the fixed compositional pipeline.

All tests assert OUTCOMES, never a fixed tool-call sequence.

The mock client is FakeClient(steps) — each call returns the next
pre-scripted tool call in JSON text form, matching the prompt-based
JSON dispatch pattern used by dynamic_query_loop.

Planted-bug controls (classes with 'Planted' in the name) feed the loop
a sequence that VIOLATES a hard constraint, then assert the gate fired:
  - deliver without prior check_result → gate auto-inserts check_result
  - state_assumption on sensitive category → blocked, ask_user substituted
"""

import sys
import json
import unittest
from pathlib import Path
from unittest.mock import MagicMock

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO))

from api.agent_loop import (
    run_agent_loop,
    AgentLoopResult,
    SENSITIVE_ASSUMPTION_CATEGORIES,
    MAX_STEPS,
)


# ---------------------------------------------------------------------------
# Mock infrastructure

class _FakeResponse:
    def __init__(self, text, stop_reason="end_turn"):
        self.text = text
        self.stop_reason = stop_reason


class FakeClient:
    """
    Mock LLMClient.  Returns scripted tool calls (JSON text) in order.
    When the script is exhausted the loop gets a safety deliver().
    """

    def __init__(self, steps: list[dict]):
        """
        steps: list of {"tool": str, "params": dict} dicts.
        Each complete() call pops the next step and returns it as JSON text.
        """
        self._steps = list(steps)
        self._idx = 0

    def complete(self, messages, system=None, max_tokens=1000, temperature=None):
        if self._idx < len(self._steps):
            step = self._steps[self._idx]
            self._idx += 1
            return _FakeResponse(json.dumps(step))
        # Safety fallback
        return _FakeResponse(json.dumps({
            "tool": "deliver",
            "params": {
                "answer": "script exhausted",
                "sources": [],
                "plan_used": [],
            },
        }))

    @property
    def calls_made(self) -> int:
        return self._idx


def _sb():
    return MagicMock()


# ---------------------------------------------------------------------------
# Helpers for building scripted tool-call sequences

def _call_primitive(name: str, params: dict = None) -> dict:
    return {"tool": "call_primitive", "params": {"name": name, "params": params or {}}}

def _check_result(claim: str, supporting_data: dict = None) -> dict:
    return {"tool": "check_result", "params": {
        "claim": claim, "supporting_data": supporting_data or {}
    }}

def _deliver(answer: str, sources: list = None, plan_used: list = None) -> dict:
    return {"tool": "deliver", "params": {
        "answer": answer,
        "sources": sources or [],
        "plan_used": plan_used or [],
    }}

def _state_assumption(assumption: str, category: str = "general") -> dict:
    return {"tool": "state_assumption", "params": {
        "assumption": assumption,
        "category": category,
    }}

def _ask_user(question: str, context: str = "") -> dict:
    return {"tool": "ask_user", "params": {"question": question, "context": context}}

def _fetch_data(query: str) -> dict:
    return {"tool": "fetch_data", "params": {"query": query}}


# ---------------------------------------------------------------------------
# Category A: Quantitative answer must show check_result evidence

class TestQuantitativeAnswerRequiresCheckResult(unittest.TestCase):
    """
    When the model delivers a quantitative answer, check_result must have
    been called in the same session.  Tests in this class provide a sequence
    that DOES call check_result — confirming the happy path works.
    """

    def _run(self, steps):
        import asyncio
        client = FakeClient(steps)
        return asyncio.get_event_loop().run_until_complete(
            run_agent_loop(
                question="How is our Q4 pipeline coverage?",
                client=client,
                sb=_sb(),
            )
        )

    def test_check_result_performed_flag_set(self):
        """check_result_performed is True when the loop called check_result."""
        steps = [
            _call_primitive("query_pipeline_coverage", {"quarter": "Q4"}),
            _check_result("Q4 coverage is 2.49x", {"coverage_ratio": 2.49}),
            _deliver("Q4 pipeline coverage is 2.49x — $4.86M vs $1.95M target.",
                     sources=["query_pipeline_coverage"]),
        ]
        result = self._run(steps)
        self.assertTrue(
            result.check_result_performed,
            "check_result_performed must be True when the loop called check_result",
        )

    def test_quantitative_answer_delivered_correctly(self):
        """Answer text is preserved when check_result was called."""
        steps = [
            _call_primitive("query_pipeline_coverage"),
            _check_result("coverage is 2.49x", {"coverage_ratio": 2.49}),
            _deliver("Q4 pipeline coverage is 2.49x.", sources=["query_pipeline_coverage"]),
        ]
        result = self._run(steps)
        self.assertIn("2.49", result.answer)

    def test_sources_passed_through(self):
        """sources list from deliver() is on the result."""
        steps = [
            _call_primitive("query_waterfall"),
            _check_result("$4M new ARR", {"total": 4_000_000}),
            _deliver("New ARR is $4M.", sources=["query_waterfall", "query_path_to_target"]),
        ]
        result = self._run(steps)
        self.assertIn("query_waterfall", result.sources)


# ---------------------------------------------------------------------------
# Planted-bug B: deliver without prior check_result — gate must auto-insert

class TestPlantedBugDeliverWithoutCheckResult(unittest.TestCase):
    """
    The model attempts to deliver a quantitative answer WITHOUT calling
    check_result first.  The gate must:
      1. Auto-insert a check_result call.
      2. Set check_result_auto_inserted = True on the result.
      3. Still return an answer (not crash).
    """

    def _run(self, answer_text: str):
        import asyncio
        steps = [
            _call_primitive("query_pipeline_coverage"),
            # SKIP check_result — jump straight to deliver with a number
            _deliver(answer_text, sources=["query_pipeline_coverage"]),
        ]
        client = FakeClient(steps)
        return asyncio.get_event_loop().run_until_complete(
            run_agent_loop(
                question="What is our pipeline coverage?",
                client=client,
                sb=_sb(),
            )
        )

    def test_gate_auto_inserts_check_result(self):
        """Gate sets check_result_auto_inserted=True when deliver skips check."""
        result = self._run("Coverage is 2.49x — pipeline $4.86M, target $1.95M.")
        self.assertTrue(
            result.check_result_auto_inserted,
            "Gate must set check_result_auto_inserted=True when deliver skips check_result",
        )

    def test_answer_still_delivered_after_auto_insert(self):
        """Auto-inserting check_result does not discard the answer."""
        result = self._run("Coverage is 2.49x.")
        self.assertFalse(result.budget_exhausted)
        self.assertIn("2.49", result.answer)

    def test_non_quantitative_deliver_does_not_auto_insert(self):
        """
        If the answer has no numbers, the gate must NOT flag check_result_auto_inserted.
        (The constraint is for quantitative answers only.)
        """
        import asyncio
        steps = [
            _call_primitive("query_win_loss"),
            _deliver("No loss data available for Q4.", sources=[]),
        ]
        client = FakeClient(steps)
        result = asyncio.get_event_loop().run_until_complete(
            run_agent_loop(
                question="Why are we losing deals?",
                client=client,
                sb=_sb(),
            )
        )
        self.assertFalse(
            result.check_result_auto_inserted,
            "Non-quantitative answer must not trigger check_result auto-insert",
        )


# ---------------------------------------------------------------------------
# Category C: Low-stakes ambiguity → state_assumption visible in answer

class TestLowStakesAmbiguityStateAssumption(unittest.TestCase):
    """
    When the model calls state_assumption for a non-sensitive category,
    the assumption must appear verbatim in the final answer so the user
    can see what was assumed.
    """

    def _run(self, assumption_text: str, category: str = "time_window"):
        import asyncio
        steps = [
            _state_assumption(assumption_text, category=category),
            _call_primitive("query_waterfall", {"quarter": "Q4"}),
            _check_result("$4.86M total ARR", {"total": 4_860_000}),
            _deliver(
                f"Assuming {assumption_text}: total Q4 ARR is $4.86M.",
                sources=["query_waterfall"],
            ),
        ]
        client = FakeClient(steps)
        return asyncio.get_event_loop().run_until_complete(
            run_agent_loop(
                question="What's our total Q4 ARR?",
                client=client,
                sb=_sb(),
            )
        )

    def test_assumption_captured_in_result(self):
        """state_assumption text appears in result.assumptions."""
        assumption = "Q4 means the fiscal quarter ending December 31"
        result = self._run(assumption)
        self.assertTrue(
            any(assumption in a for a in result.assumptions),
            f"Assumption {assumption!r} must appear in result.assumptions",
        )

    def test_assumption_in_answer_text(self):
        """
        The assumption text must appear verbatim (or substantially) in the
        delivered answer — so the user sees it, not just the log.
        """
        assumption = "includes both new and expansion ARR"
        result = self._run(assumption)
        self.assertIn(
            assumption, result.answer,
            "Assumption text must appear verbatim in the delivered answer",
        )

    def test_multiple_assumptions_all_captured(self):
        """All state_assumption calls accumulate in result.assumptions."""
        import asyncio
        a1 = "using fiscal Q4 (Oct-Dec)"
        a2 = "including expansion ARR"
        steps = [
            _state_assumption(a1, category="time_window"),
            _state_assumption(a2, category="arr_scope"),
            _call_primitive("query_waterfall"),
            _check_result("$4.86M", {"total": 4_860_000}),
            _deliver(
                f"Assuming {a1} and {a2}: total is $4.86M.",
                sources=["query_waterfall"],
            ),
        ]
        client = FakeClient(steps)
        result = asyncio.get_event_loop().run_until_complete(
            run_agent_loop(
                question="What's total Q4 ARR including expansion?",
                client=client,
                sb=_sb(),
            )
        )
        self.assertGreaterEqual(len(result.assumptions), 2)
        self.assertTrue(any(a1 in a for a in result.assumptions))
        self.assertTrue(any(a2 in a for a in result.assumptions))


# ---------------------------------------------------------------------------
# Planted-bug D: Sensitive-category state_assumption → blocked, ask_user used

class TestPlantedBugSensitiveAssumptionBlocked(unittest.TestCase):
    """
    The model attempts state_assumption with a sensitive disclosure category
    (ARR vs. deal value, quota vs. stretch, renewals in/out).  The gate must:
      1. Block the state_assumption call.
      2. Emit ask_user instead (or return the result with ask_user_question set).
      3. NOT include the sensitive assumption in result.assumptions.
    """

    def _run_sensitive(self, category: str):
        import asyncio
        steps = [
            # Model tries to assume something in a sensitive category
            _state_assumption(
                "treating deal value as ARR since ARR is not in CRM",
                category=category,
            ),
            # Model follows up with data (this should be bypassed by the gate)
            _call_primitive("query_pipeline_coverage"),
            _deliver("Coverage is 2.49x.", sources=["query_pipeline_coverage"]),
        ]
        client = FakeClient(steps)
        return asyncio.get_event_loop().run_until_complete(
            run_agent_loop(
                question="What is pipeline coverage vs ARR target?",
                client=client,
                sb=_sb(),
            )
        )

    def test_arr_vs_deal_value_blocks_assumption(self):
        """arr_vs_deal_value category blocks state_assumption."""
        result = self._run_sensitive("arr_vs_deal_value")
        # Must not contain the sensitive assumption
        self.assertFalse(
            any("treating deal value as ARR" in a for a in result.assumptions),
            "Sensitive assumption must not appear in result.assumptions",
        )

    def test_sensitive_category_triggers_ask_user(self):
        """Blocked sensitive assumption must produce an ask_user question."""
        result = self._run_sensitive("arr_vs_deal_value")
        self.assertIsNotNone(
            result.ask_user_question,
            "Blocked sensitive assumption must set result.ask_user_question",
        )

    def test_quota_vs_stretch_blocks_assumption(self):
        """quota_vs_stretch is also a sensitive category."""
        result = self._run_sensitive("quota_vs_stretch")
        self.assertFalse(
            any("treating deal value" in a for a in result.assumptions),
        )

    def test_renewals_in_out_blocks_assumption(self):
        """renewals_in_out is also a sensitive category."""
        result = self._run_sensitive("renewals_in_out")
        self.assertFalse(
            any("treating deal value" in a for a in result.assumptions),
        )

    def test_sensitive_categories_set_is_correct(self):
        """SENSITIVE_ASSUMPTION_CATEGORIES must contain the three documented categories."""
        required = {"arr_vs_deal_value", "quota_vs_stretch", "renewals_in_out"}
        self.assertTrue(
            required.issubset(SENSITIVE_ASSUMPTION_CATEGORIES),
            f"Missing from SENSITIVE_ASSUMPTION_CATEGORIES: {required - SENSITIVE_ASSUMPTION_CATEGORIES}",
        )


# ---------------------------------------------------------------------------
# Category E: Step budget is respected

class TestStepBudgetEnforced(unittest.TestCase):
    """
    When the loop reaches MAX_STEPS without a deliver(), it must:
      1. Return budget_exhausted = True.
      2. Return a safe "insufficient information" answer, never silently fail.
    """

    def _run_budget_test(self, n_steps: int):
        import asyncio
        # Feed n_steps call_primitive calls with no deliver
        steps = [
            _call_primitive("query_pipeline_coverage", {"step": i})
            for i in range(n_steps)
        ]
        client = FakeClient(steps)
        return asyncio.get_event_loop().run_until_complete(
            run_agent_loop(
                question="How is our Q4 pipeline coverage?",
                client=client,
                sb=_sb(),
            )
        )

    def test_budget_exhausted_flag_set(self):
        """budget_exhausted is True when MAX_STEPS reached without deliver."""
        result = self._run_budget_test(MAX_STEPS + 5)
        self.assertTrue(result.budget_exhausted)

    def test_budget_exhausted_returns_safe_answer(self):
        """Budget exhaustion returns "insufficient information", not an empty string."""
        result = self._run_budget_test(MAX_STEPS + 5)
        answer = result.answer.lower()
        self.assertTrue(
            "insufficient" in answer or "unable" in answer or "couldn't" in answer,
            f"Budget-exhausted answer must signal inability, got: {result.answer!r}",
        )

    def test_budget_not_triggered_within_budget(self):
        """A 3-step sequence does not trigger budget exhaustion."""
        import asyncio
        steps = [
            _call_primitive("query_pipeline_coverage"),
            _check_result("coverage 2.49x", {"ratio": 2.49}),
            _deliver("Coverage is 2.49x.", sources=["query_pipeline_coverage"]),
        ]
        client = FakeClient(steps)
        result = asyncio.get_event_loop().run_until_complete(
            run_agent_loop(
                question="Coverage?",
                client=client,
                sb=_sb(),
            )
        )
        self.assertFalse(result.budget_exhausted)

    def test_max_steps_is_reasonable(self):
        """MAX_STEPS must be at least 5 (a complex multi-part question needs room)."""
        self.assertGreaterEqual(MAX_STEPS, 5)


# ---------------------------------------------------------------------------
# Category F: ask_user ends the loop cleanly

class TestAskUserEndsLoop(unittest.TestCase):
    """
    When the model calls ask_user, the loop ends immediately (no further
    tool calls), returns ask_user_question, and delivers the clarifying
    message — not an answer.
    """

    def _run(self):
        import asyncio
        steps = [
            _ask_user(
                "Do you mean pipeline vs ARR quota or vs stretch goal?",
                context="Q4 pipeline coverage question",
            ),
            # This should never execute:
            _deliver("Some answer.", sources=[]),
        ]
        client = FakeClient(steps)
        return client, asyncio.get_event_loop().run_until_complete(
            run_agent_loop(
                question="How is our Q4 pipeline coverage?",
                client=client,
                sb=_sb(),
            )
        )

    def test_ask_user_sets_result_question(self):
        """ask_user question is captured in result.ask_user_question."""
        _, result = self._run()
        self.assertIsNotNone(result.ask_user_question)
        self.assertIn("quota or vs stretch", result.ask_user_question)

    def test_ask_user_ends_loop_before_deliver(self):
        """Loop stops at ask_user — deliver step is never executed."""
        client, result = self._run()
        # Only one step was consumed (ask_user), not two
        self.assertEqual(client.calls_made, 1,
                         "Loop must stop at ask_user, not consume the deliver step")

    def test_ask_user_not_budget_exhausted(self):
        """ask_user is a clean exit, not a budget exhaustion."""
        _, result = self._run()
        self.assertFalse(result.budget_exhausted)


# ---------------------------------------------------------------------------
# Category G: fetch_data is a valid data source for check_result

class TestFetchDataAsDataSource(unittest.TestCase):
    """
    fetch_data (raw table retrieval) is a legitimate data source.
    A number sourced from fetch_data satisfies the "no invented numbers" gate
    in the same way call_primitive does.
    """

    def _run(self):
        import asyncio
        steps = [
            _fetch_data("SELECT SUM(arr) FROM deals WHERE quarter='Q4'"),
            _check_result("Q4 ARR is $4.86M", {"total": 4_860_000}),
            _deliver("Total Q4 ARR from raw query: $4.86M.", sources=["fetch_data"]),
        ]
        client = FakeClient(steps)
        return asyncio.get_event_loop().run_until_complete(
            run_agent_loop(
                question="What's total Q4 ARR?",
                client=client,
                sb=_sb(),
            )
        )

    def test_fetch_data_then_deliver_is_valid(self):
        """fetch_data → check_result → deliver is a valid path."""
        result = self._run()
        self.assertFalse(result.budget_exhausted)
        self.assertTrue(result.check_result_performed)

    def test_answer_contains_fetched_value(self):
        """Answer references the value from fetch_data."""
        result = self._run()
        self.assertIn("4.86", result.answer)


# ---------------------------------------------------------------------------
# Category H: steps_taken is tracked accurately

class TestStepCountAccurate(unittest.TestCase):
    """steps_taken on the result must equal the number of tool calls made."""

    def _run(self, steps):
        import asyncio
        client = FakeClient(steps)
        return asyncio.get_event_loop().run_until_complete(
            run_agent_loop(
                question="Coverage?",
                client=client,
                sb=_sb(),
            )
        ), client

    def test_three_step_sequence(self):
        steps = [
            _call_primitive("query_pipeline_coverage"),
            _check_result("2.49x", {"ratio": 2.49}),
            _deliver("2.49x.", sources=["query_pipeline_coverage"]),
        ]
        result, client = self._run(steps)
        self.assertEqual(result.steps_taken, 3)

    def test_single_step_ask_user(self):
        steps = [_ask_user("Clarify?")]
        result, client = self._run(steps)
        self.assertEqual(result.steps_taken, 1)


if __name__ == "__main__":
    unittest.main()
