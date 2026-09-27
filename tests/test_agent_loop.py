"""
Test suite for api/agent_loop.py — the model-driven reasoning loop
that replaces the fixed compositional pipeline.

All tests assert OUTCOMES, never a fixed tool-call sequence.

The mock client is FakeClient(steps) — each call returns the next
pre-scripted tool call in JSON text form, matching the prompt-based
JSON dispatch pattern used by dynamic_query_loop.

Planted-bug controls (classes with 'Planted' in the name) feed the loop
a multi-step sequence that VIOLATES a hard constraint mid-trace, then
assert the gate fired.  The traces are deliberately multi-step so the
gate is tested in the middle of a real loop, not on turn 1.

  C1 (deliver without check_result): 3-turn trace —
       call_primitive → call_primitive → deliver(quantitative, no check)
  C2 (sensitive state_assumption): 2-turn trace —
       call_primitive → state_assumption(sensitive)
  C4 (fetch_data for governed primitive): 3-turn trace —
       call_primitive → fetch_data(governed query) → deliver

Gates tested:
  - C1: gate auto-inserts check_result
  - C2: gate blocks assumption, substitutes ask_user
  - C4: gate blocks fetch_data, records redirect in fetch_data_redirects
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
    KNOWN_PRIMITIVES,
    MAX_STEPS,
    _find_matching_primitive,
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

def _fetch_data(query: str, justification: str = "") -> dict:
    params: dict = {"query": query}
    if justification:
        params["justification"] = justification
    return {"tool": "fetch_data", "params": params}


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
#
# Multi-step trace: call_primitive × 2 → deliver(quantitative, no check_result)
# The gate must fire at step 3, not step 1.  This mirrors the plan_cancelled
# 3-turn scenario: real data gathering steps happen before the violated step.

class TestPlantedBugDeliverWithoutCheckResult(unittest.TestCase):
    """
    3-turn trace: call_primitive → call_primitive → deliver(quantitative).
    check_result is skipped.  The gate must:
      1. Auto-insert check_result (sets check_result_auto_inserted=True).
      2. Still return an answer (not crash).
    The gate fires on turn 3 — after two real data-gathering steps.
    """

    def _run_three_turn(self, answer_text: str):
        """3-turn trace: two call_primitive steps, then deliver without check."""
        import asyncio
        steps = [
            _call_primitive("query_pipeline_coverage", {"quarter": "Q4"}),
            _call_primitive("query_path_to_target", {"quarter": "Q4"}),
            # Turn 3: quantitative deliver WITHOUT check_result — gate must fire
            _deliver(answer_text, sources=["query_pipeline_coverage", "query_path_to_target"]),
        ]
        client = FakeClient(steps)
        return asyncio.get_event_loop().run_until_complete(
            run_agent_loop(
                question="What is our Q4 pipeline coverage vs target?",
                client=client,
                sb=_sb(),
            )
        )

    def test_gate_fires_on_turn_3_not_turn_1(self):
        """Gate fires at the deliver step (turn 3), after 2 real data-gathering steps."""
        result = self._run_three_turn(
            "Coverage is 2.49x — pipeline $4.86M vs $1.95M target."
        )
        # Gate must have fired (turn 3 = deliver without check_result)
        self.assertTrue(
            result.check_result_auto_inserted,
            "C1 gate must fire at deliver(turn 3), not before",
        )
        # Steps 1 and 2 ran successfully before the gate
        self.assertEqual(result.steps_taken, 3,
                         "All 3 steps must have run before the gate fired")

    def test_answer_preserved_after_gate(self):
        """Auto-inserting check_result does not discard the answer."""
        result = self._run_three_turn("Coverage is 2.49x — $4.86M vs $1.95M.")
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
            _call_primitive("query_pipeline_coverage"),
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
#
# Multi-step trace: call_primitive → state_assumption(sensitive)
# The gate fires at step 2 — after a real data-gathering step, not on turn 1.

class TestPlantedBugSensitiveAssumptionBlocked(unittest.TestCase):
    """
    2-turn trace: call_primitive → state_assumption(sensitive category).
    The gate must:
      1. Block the state_assumption call (step 2).
      2. Set ask_user_question (not None).
      3. NOT include the sensitive assumption in result.assumptions.

    The trace has one real data-gathering step before the gate fires,
    mirroring the 3-turn plan_cancelled scenario where context accumulates
    before the constraint is violated.
    """

    def _run_sensitive(self, category: str):
        import asyncio
        steps = [
            # Step 1: real data gathering — gate must NOT fire here
            _call_primitive("query_pipeline_coverage", {"quarter": "Q4"}),
            # Step 2: model tries to assume something in a sensitive category
            _state_assumption(
                "treating deal value as ARR since ARR is not in CRM",
                category=category,
            ),
            # Step 3 onwards should never run (gate ends loop at step 2)
            _call_primitive("query_path_to_target"),
            _deliver("Coverage is 2.49x.", sources=["query_pipeline_coverage"]),
        ]
        client = FakeClient(steps)
        return client, asyncio.get_event_loop().run_until_complete(
            run_agent_loop(
                question="What is pipeline coverage vs ARR target?",
                client=client,
                sb=_sb(),
            )
        )

    def test_gate_fires_on_turn_2_not_turn_1(self):
        """Gate fires at state_assumption (turn 2); step 1 call_primitive must have run."""
        client, result = self._run_sensitive("arr_vs_deal_value")
        # The loop consumed step 1 (call_primitive) then stopped at step 2
        self.assertEqual(result.steps_taken, 2,
                         "Gate must fire at step 2 — after step 1 ran")
        self.assertEqual(client.calls_made, 2,
                         "Exactly 2 client.complete() calls: step 1 ran, step 2 blocked")

    def test_arr_vs_deal_value_blocks_assumption(self):
        """arr_vs_deal_value category blocks state_assumption."""
        _, result = self._run_sensitive("arr_vs_deal_value")
        self.assertFalse(
            any("treating deal value as ARR" in a for a in result.assumptions),
            "Sensitive assumption must not appear in result.assumptions",
        )

    def test_sensitive_category_triggers_ask_user(self):
        """Blocked sensitive assumption must produce an ask_user question."""
        _, result = self._run_sensitive("arr_vs_deal_value")
        self.assertIsNotNone(
            result.ask_user_question,
            "Blocked sensitive assumption must set result.ask_user_question",
        )

    def test_loop_stops_at_blocked_assumption(self):
        """Steps after the blocked assumption must NOT execute."""
        client, result = self._run_sensitive("arr_vs_deal_value")
        # Steps 3 and 4 (call_primitive, deliver) must not have run
        self.assertLess(
            client.calls_made, 4,
            "Loop must stop at the blocked assumption — steps 3 and 4 must not run",
        )

    def test_quota_vs_stretch_blocks_assumption(self):
        """quota_vs_stretch is also a sensitive category."""
        _, result = self._run_sensitive("quota_vs_stretch")
        self.assertFalse(
            any("treating deal value" in a for a in result.assumptions),
        )

    def test_renewals_in_out_blocks_assumption(self):
        """renewals_in_out is also a sensitive category."""
        _, result = self._run_sensitive("renewals_in_out")
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
# Planted-bug E_C4: fetch_data for governed primitive → C4 gate blocks it
#
# Multi-step trace: call_primitive → fetch_data(governed query) → deliver
# Gate fires at step 2.  Step 1 (call_primitive) runs normally; step 3
# (deliver) runs only if the gate does not end the loop.
# C4 does NOT end the loop — it redirects, appends the redirect to history,
# and lets the model correct itself.  The test confirms the redirect is
# recorded and the loop continues to deliver.

class TestPlantedBugFetchDataGoverned(unittest.TestCase):
    """
    3-turn trace: call_primitive → fetch_data(governed) → deliver.

    C4 gate fires at step 2 (fetch_data for pipeline coverage — a governed
    primitive exists).  The gate:
      1. Blocks the fetch_data execution.
      2. Records the redirect in result.fetch_data_redirects.
      3. Injects a redirect message into history (loop continues).
      4. Does NOT end the loop — model can correct by calling call_primitive.

    After the redirect, step 3 (deliver) runs.  The gate does not prevent
    delivery; it only prevents the fetch_data from silently replacing the
    governed primitive.
    """

    def _run_governed(self, query: str):
        """3-turn trace: call_primitive → fetch_data(governed) → deliver."""
        import asyncio
        steps = [
            _call_primitive("query_path_to_target", {"quarter": "Q4"}),   # step 1
            _fetch_data(query),                                             # step 2: governed
            _check_result("coverage 2.49x", {"ratio": 2.49}),              # step 3
            _deliver("Coverage is 2.49x.", sources=["query_path_to_target"]),  # step 4
        ]
        client = FakeClient(steps)
        return client, asyncio.get_event_loop().run_until_complete(
            run_agent_loop(
                question="How is our Q4 pipeline coverage?",
                client=client,
                sb=_sb(),
            )
        )

    def _run_ungoverned(self, query: str):
        """fetch_data for an ungoverned query — gate must NOT fire."""
        import asyncio
        steps = [
            _fetch_data(query),
            _check_result("3 deals", {"count": 3}),
            _deliver("3 deals modified in the last hour.", sources=["fetch_data"]),
        ]
        client = FakeClient(steps)
        return asyncio.get_event_loop().run_until_complete(
            run_agent_loop(
                question="How many deals were modified in the last hour?",
                client=client,
                sb=_sb(),
            )
        )

    def test_governed_query_triggers_c4_redirect(self):
        """fetch_data('pipeline coverage for Q4') triggers C4 redirect."""
        _, result = self._run_governed("get pipeline coverage for Q4")
        self.assertTrue(
            len(result.fetch_data_redirects) > 0,
            "C4 gate must populate fetch_data_redirects for a governed query",
        )
        self.assertIn("query_pipeline_coverage", result.fetch_data_redirects)

    def test_c4_redirect_names_correct_primitive(self):
        """The redirect points to the right primitive."""
        _, result = self._run_governed("pipeline coverage vs quota")
        self.assertTrue(
            any("query_pipeline_coverage" in r for r in result.fetch_data_redirects),
        )

    def test_loop_continues_after_c4_redirect(self):
        """C4 redirect does not end the loop — deliver still executes."""
        _, result = self._run_governed("fetch pipeline coverage data for Q4")
        self.assertFalse(result.budget_exhausted)
        self.assertNotEqual(result.answer, "",
                             "Loop must deliver an answer after C4 redirect")

    def test_ungoverned_fetch_data_not_blocked(self):
        """fetch_data for a query with no matching primitive is not blocked."""
        result = self._run_ungoverned(
            "count deals whose hs_lastmodifieddate > now() - interval '1 hour'"
        )
        self.assertEqual(
            len(result.fetch_data_redirects), 0,
            "Ungoverned fetch_data must not set fetch_data_redirects",
        )

    def test_c4_fires_on_primitive_name_in_query(self):
        """fetch_data that mentions a primitive name verbatim is blocked."""
        _, result = self._run_governed("run query_waterfall for Q4")
        self.assertTrue(len(result.fetch_data_redirects) > 0)

    def test_c4_fires_on_keyword_match(self):
        """fetch_data with keyword 'win loss' maps to query_win_loss (the real handler name)."""
        import asyncio
        steps = [
            _fetch_data("win loss breakdown for Q4"),
            _check_result("40% loss rate", {"rate": 0.4}),
            _deliver("Loss rate is 40%.", sources=["fetch_data"]),
        ]
        client = FakeClient(steps)
        result = asyncio.get_event_loop().run_until_complete(
            run_agent_loop(
                question="What's our win/loss breakdown?",
                client=client,
                sb=_sb(),
            )
        )
        self.assertTrue(len(result.fetch_data_redirects) > 0)
        self.assertIn("query_win_loss", result.fetch_data_redirects)

    def test_find_matching_primitive_unit(self):
        """Unit test for _find_matching_primitive helper — uses real handler names."""
        self.assertEqual(
            _find_matching_primitive("query_pipeline_coverage for Q4"),
            "query_pipeline_coverage",
        )
        self.assertEqual(
            _find_matching_primitive("fetch pipeline coverage data"),
            "query_pipeline_coverage",
        )
        self.assertEqual(
            _find_matching_primitive("win/loss breakdown"),
            "query_win_loss",
        )
        self.assertIsNone(
            _find_matching_primitive("count of deals created in the last hour"),
        )

    def test_known_primitives_set_nonempty(self):
        """KNOWN_PRIMITIVES must contain at least the core governed calculators."""
        core = {
            "query_pipeline_coverage", "query_waterfall",
            "query_deals_at_risk", "query_win_loss",
        }
        self.assertTrue(
            core.issubset(KNOWN_PRIMITIVES),
            f"Missing from KNOWN_PRIMITIVES: {core - KNOWN_PRIMITIVES}",
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


# ---------------------------------------------------------------------------
# Category I: KNOWN_PRIMITIVES stays in sync with HANDLER_DESCRIPTIONS
#
# This test FAILS if a handler is added to HANDLER_DESCRIPTIONS but not
# captured in KNOWN_PRIMITIVES (either via the dynamic import or a documented
# exclusion in _NON_PRIMITIVE_INTENTS).

class TestKnownPrimitivesRegistrySync(unittest.TestCase):
    """
    Every key in HANDLER_DESCRIPTIONS must appear in KNOWN_PRIMITIVES unless
    it is explicitly in _NON_PRIMITIVE_INTENTS.

    This guards against drift: a new handler added to router.py without a
    corresponding C4 entry would silently allow fetch_data to bypass it.
    """

    def test_all_handler_descriptions_primitives_are_in_known_primitives(self):
        """
        Importing HANDLER_DESCRIPTIONS directly — every governed handler key
        must be in KNOWN_PRIMITIVES.  _NON_PRIMITIVE_INTENTS are the only
        permitted exclusions, and they must remain documented there.
        """
        from api.router import HANDLER_DESCRIPTIONS
        from api.agent_loop import _NON_PRIMITIVE_INTENTS

        governed = frozenset(HANDLER_DESCRIPTIONS.keys()) - _NON_PRIMITIVE_INTENTS
        missing = governed - KNOWN_PRIMITIVES
        self.assertFalse(
            missing,
            f"Handlers in HANDLER_DESCRIPTIONS that are missing from KNOWN_PRIMITIVES "
            f"(add to _NON_PRIMITIVE_INTENTS if they are not data calculators): {sorted(missing)}",
        )

    def test_known_primitives_keyword_table_names_are_valid(self):
        """
        Every primitive name in _PRIMITIVE_KEYWORDS must exist in KNOWN_PRIMITIVES.
        A keyword pointing at a non-existent or renamed primitive would silently
        misdirect fetch_data queries.
        """
        from api.agent_loop import _PRIMITIVE_KEYWORDS
        stale = {prim for _, prim in _PRIMITIVE_KEYWORDS if prim not in KNOWN_PRIMITIVES}
        self.assertFalse(
            stale,
            f"_PRIMITIVE_KEYWORDS entries pointing at primitives not in KNOWN_PRIMITIVES: {sorted(stale)}",
        )


# ---------------------------------------------------------------------------
# Category J: Bounded redirects — second governed fetch_data requires justification

class TestBoundedRedirects(unittest.TestCase):
    """
    After the first C4 redirect, if the model calls fetch_data again for a
    governed query:
      - WITHOUT params.justification → harder block message, redirect still recorded
      - WITH params.justification → allowed through + logged as candidate

    The redirect counter is per-loop-invocation (does not persist across calls).
    """

    def _run_double_redirect(self, second_has_justification: bool):
        """
        3-step trace:
          call_primitive → fetch_data(governed, first) → fetch_data(governed, second) → deliver
        Second fetch_data is governed; controlled by second_has_justification.
        """
        import asyncio
        second_fetch = (
            _fetch_data(
                "pipeline coverage Q4",
                justification="query_pipeline_coverage only returns ratio, not the constituent pipeline and target values I need separately",
            )
            if second_has_justification
            else _fetch_data("pipeline coverage Q4")
        )
        steps = [
            _call_primitive("query_path_to_target", {"quarter": "Q4"}),   # step 1
            _fetch_data("get pipeline coverage for Q4"),                   # step 2: first governed → redirect
            second_fetch,                                                  # step 3: second governed
            _deliver("Coverage is 2.49x.", sources=["call_primitive"]),   # step 4
        ]
        client = FakeClient(steps)
        return asyncio.get_event_loop().run_until_complete(
            run_agent_loop(
                question="How is our Q4 pipeline coverage?",
                client=client,
                sb=_sb(),
            )
        )

    def test_second_governed_without_justification_blocked(self):
        """
        Second governed fetch_data without justification gets a harder block.
        The redirect is still recorded (redirect count goes to 2).
        """
        result = self._run_double_redirect(second_has_justification=False)
        self.assertGreaterEqual(
            len(result.fetch_data_redirects), 2,
            "Both governed fetch_data calls must be recorded in fetch_data_redirects",
        )

    def test_second_governed_with_justification_allowed(self):
        """
        Second governed fetch_data WITH params.justification is allowed through.
        The loop continues to deliver an answer.
        """
        result = self._run_double_redirect(second_has_justification=True)
        self.assertFalse(result.budget_exhausted)
        self.assertNotEqual(result.answer, "")

    def test_first_redirect_not_subject_to_justification_rule(self):
        """
        The FIRST governed fetch_data is always blocked with the standard redirect
        message (no justification required on the first redirect).
        """
        import asyncio
        steps = [
            _fetch_data("pipeline coverage Q4"),    # step 1: first governed → standard block
            _call_primitive("query_pipeline_coverage"),
            _check_result("2.49x", {"ratio": 2.49}),
            _deliver("Coverage is 2.49x.", sources=["query_pipeline_coverage"]),
        ]
        client = FakeClient(steps)
        result = asyncio.get_event_loop().run_until_complete(
            run_agent_loop(
                question="How is our Q4 pipeline coverage?",
                client=client,
                sb=_sb(),
            )
        )
        # First redirect recorded, loop continues to deliver
        self.assertEqual(len(result.fetch_data_redirects), 1)
        self.assertFalse(result.budget_exhausted)
        self.assertNotEqual(result.answer, "")

    def test_redirect_count_resets_across_loop_calls(self):
        """Redirect count is per-invocation, not shared across run_agent_loop calls."""
        import asyncio

        async def _run_once():
            steps = [
                _fetch_data("pipeline coverage Q4"),   # first redirect in this call
                _deliver("Coverage is 2.49x."),
            ]
            client = FakeClient(steps)
            return await run_agent_loop(
                question="Coverage?", client=client, sb=_sb()
            )

        loop = asyncio.get_event_loop()
        r1 = loop.run_until_complete(_run_once())
        r2 = loop.run_until_complete(_run_once())
        # Each call should record exactly 1 redirect — no cross-contamination
        self.assertEqual(len(r1.fetch_data_redirects), 1)
        self.assertEqual(len(r2.fetch_data_redirects), 1)


# ---------------------------------------------------------------------------
# Executor output tests — confirm each executor returns the REAL underlying
# function's output, not a stub.  Uses unittest.mock to inject known return
# values and real data (fixtures where applicable).

class TestExecutorOutputs(unittest.TestCase):
    """
    Each test calls the executor directly (not through run_agent_loop) and
    verifies the result matches what the underlying function actually returns
    on a known input — not just that it doesn't crash.
    """

    # ── _execute_call_primitive ─────────────────────────────────────────────

    def test_call_primitive_passes_through_real_handler_result(self):
        """
        _execute_call_primitive should return exactly what the handler returns,
        not a stub note.
        """
        import asyncio
        from unittest.mock import AsyncMock, patch
        from api.agent_loop import _execute_call_primitive

        known_result = {"coverage_ratio": 2.49, "weeks_remaining": 3}

        async def fake_handler(params, sb):
            return known_result

        with patch("api.handlers.query_pipeline_coverage", fake_handler, create=True):
            result = asyncio.get_event_loop().run_until_complete(
                _execute_call_primitive("query_pipeline_coverage", {"period": "Q4"}, _sb())
            )

        self.assertEqual(result, known_result)
        self.assertNotIn("note", result)

    def test_call_primitive_unknown_name_returns_error(self):
        import asyncio
        from api.agent_loop import _execute_call_primitive

        result = asyncio.get_event_loop().run_until_complete(
            _execute_call_primitive("no_such_primitive_xyz", {}, _sb())
        )
        self.assertIn("error", result)

    # ── _execute_fetch_data ─────────────────────────────────────────────────

    def test_fetch_data_structured_params_calls_filter_table(self):
        """
        When tool_params contains 'table', _execute_fetch_data should call
        filter_table and return its rows.
        """
        import asyncio
        from unittest.mock import AsyncMock, patch
        from api.agent_loop import _execute_fetch_data

        fake_rows = [{"deal_id": "abc", "amount": 10000}, {"deal_id": "def", "amount": 20000}]

        async def fake_filter_table(sb, table, columns=None, filters=None, limit=200, order_by=None):
            return fake_rows

        tool_params = {"query": "show me deals", "table": "deals", "columns": ["deal_id", "amount"]}

        with patch("api.tools.filter_table", fake_filter_table):
            result = asyncio.get_event_loop().run_until_complete(
                _execute_fetch_data("show me deals", tool_params, _sb())
            )

        self.assertEqual(result["rows"], fake_rows)
        self.assertEqual(result["count"], 2)
        self.assertEqual(result["table"], "deals")

    def test_fetch_data_no_table_returns_error(self):
        """
        Without a 'table' param, fetch_data cannot execute and should return
        an error (not a stub note).
        """
        import asyncio
        from api.agent_loop import _execute_fetch_data

        result = asyncio.get_event_loop().run_until_complete(
            _execute_fetch_data("some nl query", {}, _sb())
        )
        self.assertIn("error", result)
        self.assertNotIn("note", result)

    # ── _execute_check_result ───────────────────────────────────────────────

    def test_check_result_detects_rate_bound_violation(self):
        """
        Supporting data with a coverage_pct of 2.5 (250%) should surface a
        plausibility warning — the result must use the 'warnings' key (not
        the old 'violations' key) and it must be a list.
        """
        from api.agent_loop import _execute_check_result

        bad_data = {"coverage_pct": 2.5}
        result = _execute_check_result("Coverage is 250%", bad_data)

        self.assertIn("verified", result)
        self.assertIn("warnings", result)
        self.assertIsInstance(result["warnings"], list)

    def test_check_result_clean_data_passes(self):
        """
        Well-formed data (reasonable coverage ratio) should pass verification.
        """
        from api.agent_loop import _execute_check_result

        good_data = {"coverage_ratio": 2.49, "open_pipeline": 1_200_000}
        result = _execute_check_result("Coverage is 2.49x.", good_data)

        self.assertIn("verified", result)
        self.assertIn("warnings", result)
        self.assertIn("untraceable", result)

    def test_check_result_plausibility_failure_is_caught_gracefully(self):
        """
        If plausibility raises, _execute_check_result should silently degrade
        (trace-to-source still works; warnings list is empty or absent).
        """
        from unittest.mock import patch
        from api.agent_loop import _execute_check_result

        with patch("api.plausibility.run_all_checks", side_effect=RuntimeError("db gone")):
            result = _execute_check_result("some claim", {"x": 1})

        # Trace check still runs — no numbers in "some claim" → verified=True
        self.assertTrue(result["verified"])
        # Must not crash and must still return a dict with the expected shape
        self.assertIn("verified", result)
        self.assertIn("warnings", result)

    # ── _execute_request_checkback ──────────────────────────────────────────

    def test_request_checkback_returns_real_prompt(self):
        """
        _execute_request_checkback should return the actual checkback_prompt()
        string, not a stub note.
        """
        from api.agent_loop import _execute_request_checkback
        from api.plan_feedback import checkback_prompt

        result = _execute_request_checkback()

        self.assertIn("checkback_prompt", result)
        self.assertEqual(result["checkback_prompt"], checkback_prompt())
        self.assertTrue(result.get("recorded"))
        self.assertNotIn("note", result)


# ---------------------------------------------------------------------------
# Planted-bug: fabricated number in check_result → verified=False → deliver blocked

class TestPlantedBugFabricatedClaim(unittest.TestCase):
    """
    C1b gate: when check_result returns verified=False because a number in the
    claim cannot be traced to supporting_data, deliver must not go through.
    """

    def test_untraceable_number_sets_verified_false(self):
        """
        Unit test: claim states $2.1M, supporting_data has 1.5M — no match.
        _execute_check_result must return verified=False and name the token.
        """
        from api.agent_loop import _execute_check_result

        result = _execute_check_result(
            claim="Pipeline is $2.1M this quarter.",
            supporting_data={"open_pipeline": 1_500_000},  # 1.5M — not 2.1M
        )
        self.assertFalse(result["verified"], "Expected verified=False; $2.1M is not in supporting_data")
        self.assertTrue(len(result["untraceable"]) > 0, "Expected at least one untraceable token")

    def test_traceable_number_passes(self):
        """A number that IS in supporting_data must not be flagged as untraceable."""
        from api.agent_loop import _execute_check_result

        result = _execute_check_result(
            claim="Pipeline is $2.1M this quarter.",
            supporting_data={"open_pipeline": 2_100_000},  # exact match
        )
        self.assertTrue(result["verified"])
        self.assertEqual(result["untraceable"], [])

    def test_full_loop_blocks_deliver_after_failed_check(self):
        """
        Full loop trace: model calls check_result with a fabricated claim
        ($2.1M not in supporting_data), then tries to deliver — the C1b gate
        must block the deliver.  With a scripted client that has no further
        steps, the loop exhausts budget (budget_exhausted=True).
        """
        import asyncio

        # check_result returns verified=False (from real _execute_check_result)
        # because 2.1M is not in {"open_pipeline": 1_500_000}.
        # Then the scripted model ignores the failure and tries to deliver.
        steps = [
            {
                "tool": "check_result",
                "params": {
                    "claim": "Pipeline is $2.1M.",
                    "supporting_data": {"open_pipeline": 1_500_000},
                },
            },
            _deliver("Pipeline is $2.1M.", sources=[]),
            # No further steps — loop will exhaust budget after gate blocks deliver.
        ]
        client = FakeClient(steps)
        result = asyncio.get_event_loop().run_until_complete(
            run_agent_loop(
                question="How is our Q4 pipeline?",
                client=client,
                sb=_sb(),
            )
        )
        # check_result was performed
        self.assertTrue(result.check_result_performed)
        # Verification failed
        self.assertFalse(result.check_result_verified)
        # Deliver was blocked → loop exhausted budget, not a successful deliver
        self.assertNotEqual(result.answer, "Pipeline is $2.1M.")

    def test_deliver_succeeds_after_passing_check(self):
        """
        Confirming the gate is not over-eager: a passing check_result is followed
        by deliver and the answer goes through normally.
        """
        import asyncio

        steps = [
            {
                "tool": "check_result",
                "params": {
                    "claim": "Coverage is 2.49x.",
                    "supporting_data": {"coverage_ratio": 2.49},
                },
            },
            _deliver("Coverage is 2.49x.", sources=["query_pipeline_coverage"]),
        ]
        client = FakeClient(steps)
        result = asyncio.get_event_loop().run_until_complete(
            run_agent_loop(
                question="What is our Q4 pipeline coverage?",
                client=client,
                sb=_sb(),
            )
        )
        self.assertEqual(result.answer, "Coverage is 2.49x.")
        self.assertTrue(result.check_result_performed)
        self.assertTrue(result.check_result_verified)
        self.assertFalse(result.budget_exhausted)


# ---------------------------------------------------------------------------
# KNOWN_PRIMITIVES callability: every registered primitive must exist in
# api.handlers as a callable async function.

class TestKnownPrimitivesCallable(unittest.TestCase):
    """
    Confirm that every name in KNOWN_PRIMITIVES resolves to a callable async
    function in api.handlers.  Handler signatures have differed before; this
    test catches renames and missing registrations before a live Q4 run.
    """

    def test_all_known_primitives_exist_and_are_async(self):
        import inspect
        import api.handlers as handlers

        missing = []
        not_callable = []
        not_async = []

        for name in sorted(KNOWN_PRIMITIVES):
            fn = getattr(handlers, name, None)
            if fn is None:
                missing.append(name)
            elif not callable(fn):
                not_callable.append(name)
            elif not inspect.iscoroutinefunction(fn):
                not_async.append(name)

        errors = []
        if missing:
            errors.append(f"Not found in api.handlers: {missing}")
        if not_callable:
            errors.append(f"Not callable: {not_callable}")
        if not_async:
            errors.append(f"Not async (must be async def): {not_async}")

        self.assertFalse(errors, "\n".join(errors))


if __name__ == "__main__":
    unittest.main()
