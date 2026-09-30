"""
Schema injection and fetch_data error propagation in the agent loop.

The agent loop's system prompt used to be completely static — no table
names, no column lists, no data dictionary content.  The model had to
guess table and column names, wasting budget steps on schema-validation
rejections (e.g. trying 'opportunities' table, or 'deals' with invented
columns ['id', 'name', 'amount', 'owner']).

These tests verify:
  1. The system prompt includes schema context (table names and columns)
     when a Supabase client is available, so the model knows the schema
     before its first fetch_data call.
  2. _execute_fetch_data propagates error dicts from filter_table at the
     top level (not nested under "rows").
  3. A fetch_data call that returns a schema-validation error does NOT
     count as a full budget step — the model gets a free retry.
"""

import asyncio
import json
import sys
import unittest
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO))

from api.agent_loop import (
    run_agent_loop,
    AgentLoopResult,
    MAX_STEPS,
    _execute_fetch_data,
)


# ---------------------------------------------------------------------------
# Mock infrastructure (same pattern as test_agent_loop.py)

class _FakeResponse:
    def __init__(self, text):
        self.text = text


class FakeClient:
    def __init__(self, steps):
        self._steps = list(steps)
        self._idx = 0
        self.system_prompts = []

    def complete(self, messages, system=None, max_tokens=1000, temperature=None):
        self.system_prompts.append(system)
        if self._idx < len(self._steps):
            step = self._steps[self._idx]
            self._idx += 1
            return _FakeResponse(json.dumps(step))
        return _FakeResponse(json.dumps({
            "tool": "deliver",
            "params": {"answer": "script exhausted", "sources": [], "plan_used": []},
        }))

    @property
    def calls_made(self):
        return self._idx


def _deliver(answer):
    return {"tool": "deliver", "params": {
        "answer": answer, "sources": [], "plan_used": [],
    }}


def _fetch_data(table, columns=None, filters=None):
    params = {"query": "get data", "table": table}
    if columns:
        params["columns"] = columns
    if filters:
        params["filters"] = filters
    return {"tool": "fetch_data", "params": params}


run = asyncio.get_event_loop().run_until_complete


# ---------------------------------------------------------------------------
# Test: schema context appears in system prompt

class TestSchemaInjection(unittest.TestCase):
    """The system prompt must include table/column schema when sb is available."""

    def test_system_prompt_includes_schema_context(self):
        """When a Supabase client is provided, the system prompt must contain
        table names and column lists from the data dictionary."""
        steps = [_deliver("Done.")]
        client = FakeClient(steps)

        fake_schema = (
            "QUERYABLE SUPABASE TABLES AND COLUMNS:\n"
            "TABLE: deals\n"
            "  deal_id (text)\n"
            "  company_name (text)\n"
            "  arr_usd (numeric)\n"
        )
        with patch("api.agent_loop._get_schema_for_prompt", return_value=fake_schema):
            run(run_agent_loop(
                question="Show me deals",
                client=client,
                sb=MagicMock(),
            ))

        self.assertTrue(len(client.system_prompts) > 0)
        system = client.system_prompts[0]
        self.assertIn("QUERYABLE SUPABASE TABLES", system)
        self.assertIn("deals", system)
        self.assertIn("arr_usd", system)

    def test_system_prompt_still_works_without_sb(self):
        """When sb=None, the loop still works — no schema injected."""
        steps = [_deliver("Done.")]
        client = FakeClient(steps)

        result = run(run_agent_loop(
            question="Show me deals",
            client=client,
            sb=None,
        ))
        self.assertEqual(result.answer, "Done.")

    def test_schema_context_failure_does_not_crash_loop(self):
        """If get_schema_context raises, the loop proceeds without schema."""
        steps = [_deliver("Done.")]
        client = FakeClient(steps)

        with patch("api.agent_loop._get_schema_for_prompt", side_effect=Exception("db error")):
            result = run(run_agent_loop(
                question="Show me deals",
                client=client,
                sb=MagicMock(),
            ))
        self.assertEqual(result.answer, "Done.")


# ---------------------------------------------------------------------------
# Test: _execute_fetch_data propagates error dicts

class TestFetchDataErrorPropagation(unittest.TestCase):
    """filter_table returns {"error": ...} for schema rejections —
    _execute_fetch_data must propagate that at the top level, not nest it."""

    def test_schema_rejection_error_at_top_level(self):
        """When filter_table returns an error dict, _execute_fetch_data must
        return it with 'error' as a top-level key."""
        error_dict = {
            "error": "Unknown SELECT columns for table 'deals': ['id', 'name']. "
                     "Queryable columns: ['arr_usd', 'company_name', 'deal_id']",
            "unknown_select_columns": ["id", "name"],
        }

        with patch("api.tools.filter_table", new_callable=AsyncMock,
                    return_value=error_dict):
            result = run(_execute_fetch_data(
                query="get deals",
                tool_params={"table": "deals", "columns": ["id", "name"]},
                sb=MagicMock(),
            ))

        self.assertIn("error", result)
        self.assertNotIn("rows", result)
        self.assertIn("Unknown SELECT columns", result["error"])

    def test_filter_rejection_error_at_top_level(self):
        """When filter_table rejects a filter column, the error is top-level."""
        error_dict = {
            "error": "Can't filter deals on ['pipeline']: not a queryable column",
            "unknown_filter_columns": ["pipeline"],
        }

        with patch("api.tools.filter_table", new_callable=AsyncMock,
                    return_value=error_dict):
            result = run(_execute_fetch_data(
                query="get deals",
                tool_params={"table": "deals", "filters": [["eq", "pipeline", "x"]]},
                sb=MagicMock(),
            ))

        self.assertIn("error", result)
        self.assertNotIn("rows", result)

    def test_successful_fetch_still_returns_rows(self):
        """A successful filter_table call still returns rows correctly."""
        success_dict = {
            "rows": [{"deal_id": "1", "arr_usd": 100}],
        }

        with patch("api.tools.filter_table", new_callable=AsyncMock,
                    return_value=success_dict):
            result = run(_execute_fetch_data(
                query="get deals",
                tool_params={"table": "deals", "columns": ["deal_id", "arr_usd"]},
                sb=MagicMock(),
            ))

        self.assertIn("rows", result)
        self.assertEqual(len(result["rows"]), 1)
        self.assertNotIn("error", result)


# ---------------------------------------------------------------------------
# Test: schema-rejection fetch_data doesn't burn a full budget step

class TestSchemaRejectionDoesNotBurnStep(unittest.TestCase):
    """A fetch_data that gets a schema-validation error should not consume
    a full step of the 12-step budget. The model gets a free retry so it
    can correct the table/column names without wasting budget."""

    def test_schema_errors_do_not_count_as_steps(self):
        """If every fetch_data call returns a schema error, the loop should
        take more than MAX_STEPS iterations (because errors are free retries)
        before hitting budget exhaustion."""
        # Script: MAX_STEPS + 5 fetch_data calls with bad columns, then deliver.
        # If errors DON'T burn steps, the loop can do more than 12 iterations.
        # If errors DO burn steps, it would stop at exactly 12.
        total_calls = MAX_STEPS + 4
        steps = [
            _fetch_data("deals", columns=["id", "name"])
            for _ in range(total_calls)
        ] + [_deliver("Got it.")]

        client = FakeClient(steps)

        error_dict = {
            "error": "Unknown SELECT columns for table 'deals': ['id', 'name']. "
                     "Queryable columns: ['arr_usd', 'company_name', 'deal_id']",
            "unknown_select_columns": ["id", "name"],
        }

        with patch("api.tools.filter_table", new_callable=AsyncMock,
                    return_value=error_dict):
            with patch("api.agent_loop._get_schema_for_prompt", return_value=""):
                result = run(run_agent_loop(
                    question="Show me deals",
                    client=client,
                    sb=MagicMock(),
                ))

        # The loop should have processed more calls than MAX_STEPS
        # because schema errors are free retries
        self.assertGreater(client.calls_made, MAX_STEPS,
                           f"Expected > {MAX_STEPS} calls but got {client.calls_made} — "
                           "schema errors are burning full steps")

    def test_successful_fetch_still_counts_as_step(self):
        """A successful fetch_data call still counts as a normal step."""
        steps = [
            _fetch_data("deals", columns=["deal_id", "arr_usd"]),
            _deliver("Pipeline total: $1M"),
        ]
        client = FakeClient(steps)

        success_dict = {
            "rows": [{"deal_id": "1", "arr_usd": 100000}],
        }

        with patch("api.tools.filter_table", new_callable=AsyncMock,
                    return_value=success_dict):
            with patch("api.agent_loop._get_schema_for_prompt", return_value=""):
                result = run(run_agent_loop(
                    question="Show me deals",
                    client=client,
                    sb=MagicMock(),
                ))

        self.assertEqual(result.answer, "Pipeline total: $1M")
        self.assertEqual(result.steps_taken, 2)

    def test_mixed_errors_and_success_counts_correctly(self):
        """Schema errors are free, but real steps count. 2 errors + 2 real
        steps should report steps_taken=2, not 4."""
        steps = [
            _fetch_data("deals", columns=["id"]),       # schema error (free)
            _fetch_data("deals", columns=["name"]),      # schema error (free)
            _fetch_data("deals", columns=["deal_id"]),   # success (step 1)
            _deliver("Got $1M."),                         # step 2
        ]
        client = FakeClient(steps)

        call_count = 0
        async def mock_filter_table(sb, table, **kwargs):
            nonlocal call_count
            call_count += 1
            cols = kwargs.get("columns") or []
            if cols and cols[0] in ("id", "name"):
                return {
                    "error": f"Unknown SELECT columns for table 'deals': {cols}",
                    "unknown_select_columns": cols,
                }
            return {"rows": [{"deal_id": "1"}]}

        with patch("api.tools.filter_table", side_effect=mock_filter_table):
            with patch("api.agent_loop._get_schema_for_prompt", return_value=""):
                result = run(run_agent_loop(
                    question="Show me deals",
                    client=client,
                    sb=MagicMock(),
                ))

        self.assertEqual(result.answer, "Got $1M.")
        self.assertEqual(result.steps_taken, 2,
                         "Schema errors should not count as steps")


if __name__ == "__main__":
    unittest.main()
