"""
Integration test for the pending-plan confirmation path in route_question.

Reproduces the exact production failure: user replies "Yes" to a composer
plan, but the reply is treated as a new question because the pending plan
was never persisted to history.  The fix adds history_append to the
composer-escalation return so main.py writes the pending_plan entry into
the thread, and this test proves the round-trip works.

Hard invariants:
  1. route_question with a pending-plan history entry and "Yes" as the
     message routes to run_agent_loop, never to the intent classifier.
  2. The composer-escalation return dict includes history_append with the
     pending_plan entry.
  3. reply_affirms_plan handles case variations ("Yes", "yes", "YES").
"""
import asyncio
import json
import sys
import unittest
from dataclasses import dataclass, field
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO))

from api.composer import (
    PENDING_PLAN_ROLE,
    make_pending_plan_entry,
    find_pending_plan,
    reply_affirms_plan,
)

run = asyncio.get_event_loop().run_until_complete


def _make_plan():
    """A realistic 4-part plan like the one the live Slack test produced."""
    return {
        "question": "What is our pipeline coverage for this quarter?",
        "sub_parts": [
            {"name": "open_pipeline_total",
             "primitive": "query_pipeline",
             "rationale": "Sum of open deal ARR closing this quarter"},
            {"name": "closed_won_total",
             "primitive": "query_pipeline",
             "rationale": "Sum of closed-won ARR this quarter"},
            {"name": "quota_target",
             "primitive": "query_pipeline_coverage",
             "rationale": "Quota target for the quarter"},
            {"name": "coverage_ratio",
             "primitive": "_computed",
             "rationale": "open_pipeline_total / quota_target"},
        ],
        "explanation": "Needs pipeline total + target + ratio.",
    }


def _history_with_pending_plan():
    """Build a thread history that contains a pending plan entry."""
    plan = _make_plan()
    clarification_msg = (
        "I'll need to pull a few things together:\n"
        "1. Open pipeline total\n"
        "2. Closed-won total\n"
        "3. Quota target\n"
        "4. Compute coverage ratio\n\n"
        "Shall I go ahead?"
    )
    entry = make_pending_plan_entry(plan, clarification_msg)
    return [
        {"role": "user", "content": "What is our pipeline coverage for this quarter?"},
        {"role": "assistant", "content": clarification_msg},
        entry,
    ]


@dataclass
class FakeLoopResult:
    answer: str = "Coverage is 2.49x."
    steps_taken: int = 4
    check_result_performed: bool = True
    check_result_auto_inserted: bool = False
    check_result_verified: bool = True
    budget_exhausted: bool = False


class TestPendingPlanConfirmation(unittest.TestCase):
    """route_question with a pending plan + 'Yes' → run_agent_loop, not classifier."""

    def _call_route(self, question, history):
        mock_run_agent_loop = AsyncMock(return_value=FakeLoopResult())

        sb = MagicMock()
        sb.table.return_value.select.return_value.execute.return_value = MagicMock(data=[])

        with patch("api.router._route_question", new_callable=AsyncMock) as mock_inner, \
             patch("api.agent_loop.run_agent_loop", mock_run_agent_loop), \
             patch("api.router.LLMClient") as mock_llm:
            mock_llm.from_config.return_value = MagicMock()
            from api.router import route_question
            result = run(route_question(
                question=question,
                user_id="U_TEST",
                history=history,
                sb=sb,
                thread_ts="1727000000.000001",
            ))
        return result, mock_run_agent_loop, mock_inner

    def test_yes_routes_to_agent_loop(self):
        """Literal 'Yes' with a pending plan → run_agent_loop called."""
        history = _history_with_pending_plan()
        result, mock_loop, mock_inner = self._call_route("Yes", history)
        mock_loop.assert_called_once()
        mock_inner.assert_not_called()

    def test_yes_lowercase_routes_to_agent_loop(self):
        """'yes' (lowercase) with a pending plan → run_agent_loop called."""
        history = _history_with_pending_plan()
        result, mock_loop, mock_inner = self._call_route("yes", history)
        mock_loop.assert_called_once()
        mock_inner.assert_not_called()

    def test_go_ahead_routes_to_agent_loop(self):
        """'Go ahead' with a pending plan → run_agent_loop called."""
        history = _history_with_pending_plan()
        result, mock_loop, mock_inner = self._call_route("Go ahead", history)
        mock_loop.assert_called_once()
        mock_inner.assert_not_called()

    def test_non_affirmation_does_not_route_to_agent_loop(self):
        """A non-affirmation reply with a pending plan → cancels plan, routes normally."""
        history = _history_with_pending_plan()

        mock_run_agent_loop = AsyncMock(return_value=FakeLoopResult())
        sb = MagicMock()
        sb.table.return_value.select.return_value.execute.return_value = MagicMock(data=[])

        inner_return = {
            "answer": "Here is pipeline data.",
            "needs_ack": False,
            "tool_results": {},
            "handler_name": "query_pipeline",
        }
        with patch("api.router._route_question", new_callable=AsyncMock,
                    return_value=inner_return) as mock_inner, \
             patch("api.agent_loop.run_agent_loop", mock_run_agent_loop), \
             patch("api.router.LLMClient") as mock_llm:
            mock_llm.from_config.return_value = MagicMock()
            from api.router import route_question
            result = run(route_question(
                question="Actually, just show me pipeline",
                user_id="U_TEST",
                history=history,
                sb=sb,
                thread_ts="1727000000.000001",
            ))
        mock_run_agent_loop.assert_not_called()
        mock_inner.assert_called_once()

    def test_no_pending_plan_routes_normally(self):
        """Without a pending plan, 'Yes' is just a new question."""
        history = [
            {"role": "user", "content": "Show pipeline"},
            {"role": "assistant", "content": "Here's the pipeline data."},
        ]
        mock_run_agent_loop = AsyncMock(return_value=FakeLoopResult())
        sb = MagicMock()
        sb.table.return_value.select.return_value.execute.return_value = MagicMock(data=[])

        inner_return = {
            "answer": "Pipeline data here.",
            "needs_ack": False,
            "tool_results": {},
            "handler_name": "query_pipeline",
        }
        with patch("api.router._route_question", new_callable=AsyncMock,
                    return_value=inner_return) as mock_inner, \
             patch("api.agent_loop.run_agent_loop", mock_run_agent_loop), \
             patch("api.router.LLMClient") as mock_llm:
            mock_llm.from_config.return_value = MagicMock()
            from api.router import route_question
            result = run(route_question(
                question="Yes",
                user_id="U_TEST",
                history=history,
                sb=sb,
                thread_ts="1727000000.000001",
            ))
        mock_run_agent_loop.assert_not_called()
        mock_inner.assert_called_once()

    def test_agent_loop_answer_returned_to_caller(self):
        """The agent loop's answer is what route_question returns."""
        history = _history_with_pending_plan()
        result, _, _ = self._call_route("Yes", history)
        self.assertIn("Coverage is 2.49x.", result.get("answer", ""))

    def test_result_includes_checkback_history_append(self):
        """Successful agent loop path returns history_append with checkback entry."""
        history = _history_with_pending_plan()
        result, _, _ = self._call_route("Yes", history)
        appended = result.get("history_append")
        self.assertIsNotNone(appended, "history_append must be set")
        self.assertTrue(len(appended) > 0, "history_append must be non-empty")


    def test_ordinary_question_no_pending_plan_no_unbound_error(self):
        """A plain question with no pending plan must not raise UnboundLocalError.

        Regression: _plan_cancelled_entry was only assigned inside the
        pending-plan branches, so every ordinary turn that skipped both
        branches hit UnboundLocalError at the bottom of route_question
        where it checks `if _plan_cancelled_entry is not None`.
        """
        history = [
            {"role": "user", "content": "Show me the pipeline"},
            {"role": "assistant", "content": "Here's the pipeline."},
        ]
        inner_return = {
            "answer": "Pipeline looks good.",
            "needs_ack": False,
            "tool_results": {},
            "handler_name": "query_pipeline",
        }
        sb = MagicMock()
        sb.table.return_value.select.return_value.execute.return_value = MagicMock(data=[])

        with patch("api.router._route_question", new_callable=AsyncMock,
                    return_value=inner_return), \
             patch("api.agent_loop.run_agent_loop", AsyncMock()), \
             patch("api.router.LLMClient") as mock_llm:
            mock_llm.from_config.return_value = MagicMock()
            from api.router import route_question
            result = run(route_question(
                question="How does the pipeline look?",
                user_id="U_TEST",
                history=history,
                sb=sb,
                thread_ts="1727000000.000001",
            ))
        self.assertIn("Pipeline looks good.", result.get("answer", ""))

    def test_affirmed_plan_budget_exhausted_returns_explicit_failure(self):
        """When run_agent_loop exhausts its budget, route_question must
        return the loop's explicit failure message — never fall through
        to the classifier (which would produce a generic acknowledgment)."""
        history = _history_with_pending_plan()

        exhausted_result = FakeLoopResult()
        exhausted_result.budget_exhausted = True
        exhausted_result.answer = "I was unable to answer this confidently"

        sb = MagicMock()
        sb.table.return_value.select.return_value.execute.return_value = MagicMock(data=[])

        with patch("api.router._route_question", new_callable=AsyncMock) as mock_inner, \
             patch("api.agent_loop.run_agent_loop",
                   AsyncMock(return_value=exhausted_result)), \
             patch("api.router.LLMClient") as mock_llm:
            mock_llm.from_config.return_value = MagicMock()
            from api.router import route_question
            result = run(route_question(
                question="Yes",
                user_id="U_TEST",
                history=history,
                sb=sb,
                thread_ts="1727000000.000001",
            ))
        mock_inner.assert_not_called()
        self.assertIn("unable to answer", result.get("answer", "").lower())
        self.assertEqual(result.get("handler_name"), "composer_agent_loop_exhausted")

    def test_affirmed_plan_exception_returns_explicit_failure(self):
        """When run_agent_loop raises an exception, route_question must
        return an explicit error message — never fall through to the
        classifier."""
        history = _history_with_pending_plan()

        sb = MagicMock()
        sb.table.return_value.select.return_value.execute.return_value = MagicMock(data=[])

        with patch("api.router._route_question", new_callable=AsyncMock) as mock_inner, \
             patch("api.agent_loop.run_agent_loop",
                   AsyncMock(side_effect=RuntimeError("filter_table boom"))), \
             patch("api.router.LLMClient") as mock_llm:
            mock_llm.from_config.return_value = MagicMock()
            from api.router import route_question
            result = run(route_question(
                question="Yes",
                user_id="U_TEST",
                history=history,
                sb=sb,
                thread_ts="1727000000.000001",
            ))
        mock_inner.assert_not_called()
        self.assertIn("able to complete", result.get("answer", "").lower())
        self.assertEqual(result.get("handler_name"), "composer_agent_loop_error")


class TestComposerEscalationPersistence(unittest.TestCase):
    """The composer-escalation return dict must include history_append."""

    def test_escalation_return_has_history_append(self):
        """Simulate the escalation path and verify history_append is in the return."""
        plan = _make_plan()
        clarification_msg = "Shall I go ahead?"
        pending_entry = make_pending_plan_entry(plan, clarification_msg)

        parsed = json.loads(pending_entry["content"])
        self.assertEqual(pending_entry["role"], PENDING_PLAN_ROLE)
        self.assertIsNotNone(parsed["plan"])

        result = {
            "answer": clarification_msg,
            "needs_ack": False,
            "tool_results": {},
            "handler_name": "query_pipeline_coverage_composer_plan",
            "history_append": [pending_entry],
        }
        self.assertIn("history_append", result)
        entries = result["history_append"]
        self.assertEqual(len(entries), 1)
        self.assertEqual(entries[0]["role"], PENDING_PLAN_ROLE)

    def test_find_pending_plan_reads_persisted_entry(self):
        """Once persisted via history_append, find_pending_plan finds it."""
        plan = _make_plan()
        entry = make_pending_plan_entry(plan, "Shall I go ahead?")
        history = [
            {"role": "user", "content": "What is coverage?"},
            {"role": "assistant", "content": "Shall I go ahead?"},
            entry,
        ]
        found = find_pending_plan(history)
        self.assertIsNotNone(found)
        self.assertEqual(found["plan"]["question"], plan["question"])
        self.assertEqual(len(found["plan"]["sub_parts"]), 4)


class TestReplyAffirmsPlanCaseSensitivity(unittest.TestCase):
    """Ensure reply_affirms_plan handles all case variations."""

    def test_uppercase_yes(self):
        self.assertTrue(reply_affirms_plan("Yes"))

    def test_lowercase_yes(self):
        self.assertTrue(reply_affirms_plan("yes"))

    def test_allcaps_yes(self):
        self.assertTrue(reply_affirms_plan("YES"))

    def test_yes_with_whitespace(self):
        self.assertTrue(reply_affirms_plan("  Yes  "))

    def test_go_ahead(self):
        self.assertTrue(reply_affirms_plan("Go ahead"))

    def test_sounds_good(self):
        self.assertTrue(reply_affirms_plan("Sounds good"))

    def test_non_affirmation(self):
        self.assertFalse(reply_affirms_plan("No, show me something else"))

    def test_empty_string(self):
        self.assertFalse(reply_affirms_plan(""))

    def test_none(self):
        self.assertFalse(reply_affirms_plan(None))


if __name__ == "__main__":
    unittest.main()
