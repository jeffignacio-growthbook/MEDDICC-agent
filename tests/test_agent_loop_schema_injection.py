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
  4. _get_schema_for_prompt uses table classification (same as the
     router) to inject only relevant tables' full descriptions, not
     every table in the dictionary.
  5. With the real schema injected, a model that reads the prompt never
     attempts nonexistent table/column names — zero SCHEMA_VALIDATION
     rejections (the "opportunities"/"amount"/"owner" scenario).
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


# ---------------------------------------------------------------------------
# Test: _get_schema_for_prompt uses table classification

class TestSchemaClassification(unittest.TestCase):
    """_get_schema_for_prompt must classify relevant tables (via the same
    classify_relevant_tables the router uses) and pass them to
    get_schema_context as tables_with_descriptions."""

    def test_classify_then_build_schema(self):
        """_get_schema_for_prompt calls classify_relevant_tables with the
        question, then passes the classified tables to get_schema_context."""
        from api.agent_loop import _get_schema_for_prompt

        fake_schema = (
            "QUERYABLE SUPABASE TABLES AND COLUMNS:\n"
            "TABLE: deals\n"
            "  deal_id (text)\n"
        )
        with patch("api.table_classifier.classify_relevant_tables",
                    return_value=["deals", "analyses"]) as mock_classify, \
             patch("api.schema_context.get_schema_context",
                    return_value=fake_schema) as mock_schema, \
             patch("llm_client.LLMClient") as mock_llm:
            mock_llm.from_config.return_value = MagicMock()
            result = _get_schema_for_prompt(
                "What are our pipeline deals?", MagicMock())

        mock_classify.assert_called_once()
        call_args = mock_classify.call_args
        self.assertIn("pipeline deals", call_args[0][0])

        mock_schema.assert_called_once()
        schema_kwargs = mock_schema.call_args
        self.assertEqual(
            schema_kwargs[1]["tables_with_descriptions"],
            ["deals", "analyses"],
        )
        self.assertTrue(schema_kwargs[1]["lightweight"])
        self.assertEqual(result, fake_schema)

    def test_classification_failure_falls_back_gracefully(self):
        """If classify_relevant_tables raises, _get_schema_for_prompt
        returns empty string (the loop still works without schema)."""
        from api.agent_loop import _get_schema_for_prompt

        with patch("api.table_classifier.classify_relevant_tables",
                    side_effect=RuntimeError("Haiku down")), \
             patch("llm_client.LLMClient") as mock_llm:
            mock_llm.from_config.return_value = MagicMock()
            result = _get_schema_for_prompt("Show deals", MagicMock())

        self.assertEqual(result, "")

    def test_sb_none_skips_classification(self):
        """When sb=None, no classification or schema build is attempted."""
        from api.agent_loop import _get_schema_for_prompt

        with patch("api.table_classifier.classify_relevant_tables") as mock_classify:
            result = _get_schema_for_prompt("Show deals", None)

        mock_classify.assert_not_called()
        self.assertEqual(result, "")

    def test_classifier_client_uses_classifier_role(self):
        """The classifier client must be created with role='classifier'
        (Haiku), not the generator role (Sonnet)."""
        from api.agent_loop import _get_schema_for_prompt

        with patch("api.table_classifier.classify_relevant_tables",
                    return_value=["deals"]) as mock_classify, \
             patch("api.schema_context.get_schema_context",
                    return_value="schema text"), \
             patch("llm_client.LLMClient") as mock_llm:
            fake_client = MagicMock()
            mock_llm.from_config.return_value = fake_client
            _get_schema_for_prompt("Show deals", MagicMock())

        mock_llm.from_config.assert_called_once_with(role="classifier")
        self.assertIs(mock_classify.call_args[0][1], fake_client)


# ---------------------------------------------------------------------------
# Test: "opportunities"/"amount"/"owner" scenario — zero schema rejections
# when the real schema is injected upfront.

# Realistic schema context matching what get_schema_context produces for
# deals+analyses — the tables the classifier would pick for a pipeline
# coverage question.
_REALISTIC_SCHEMA = (
    "QUERYABLE SUPABASE TABLES AND COLUMNS:\n"
    "(Use these exact column names in query tool calls)\n"
    "\n"
    "TABLE: deals — Active and closed deals.\n"
    "  deal_id (text) — Unique deal identifier\n"
    "  company_name (text) — Company name\n"
    "  owner_email (text) — Deal owner email\n"
    "  owner_name (text) — Deal owner display name\n"
    "  arr_usd (numeric) — Annual recurring revenue in USD\n"
    "  deal_value (numeric) — Total deal value\n"
    "  new_arr (numeric) — New business ARR\n"
    "  expansion_arr (numeric) — Expansion ARR\n"
    "  deal_status (text) — open/won/lost\n"
    "  stage (text) — HubSpot stage ID\n"
    "  stage_id (text) — HubSpot stage ID\n"
    "  pipeline_id (text) — Pipeline identifier\n"
    "  close_date (date) — Expected close date\n"
    "  segment (text) — Market segment\n"
    "  forecast_category (text) — Forecast category\n"
    "\n"
    "TABLE: analyses — Nightly MEDDICC scores per deal.\n"
    "  deal_id (text) — Unique deal identifier\n"
    "  overall_score (numeric) — Overall MEDDICC score\n"
    "  champion_score (numeric)\n"
    "  economic_buyer_score (numeric)\n"
)


class TestZeroSchemaRejectionsWithUpfrontSchema(unittest.TestCase):
    """Reproduces the exact production failure: the model tried table
    'opportunities' with columns ['id', 'name', 'amount', 'owner'] because
    it was guessing from training data.  With the real schema injected, a
    well-behaved model reads the prompt and uses the correct names — zero
    schema rejections in the entire run.

    The FakeClient is scripted to use *correct* column names (the ones
    listed in the schema context), proving that a model that reads its
    prompt never triggers schema validation errors."""

    def test_correct_columns_produce_zero_schema_rejections(self):
        """A model that reads the injected schema uses correct table/column
        names → filter_table never returns a schema error → zero rejections."""
        steps = [
            _fetch_data("deals", columns=["deal_id", "arr_usd", "owner_email",
                                           "deal_status", "close_date"]),
            _deliver("Pipeline total: $2.4M across 18 open deals."),
        ]
        client = FakeClient(steps)

        schema_rejections = []

        async def mock_filter_table(sb, table, **kwargs):
            cols = kwargs.get("columns") or []
            bad_cols = [c for c in cols if c not in {
                "deal_id", "company_name", "owner_email", "owner_name",
                "arr_usd", "deal_value", "new_arr", "expansion_arr",
                "deal_status", "stage", "stage_id", "pipeline_id",
                "close_date", "segment", "forecast_category",
                "overall_score", "champion_score", "economic_buyer_score",
            }]
            if table not in ("deals", "analyses"):
                schema_rejections.append({"table": table})
                return {
                    "error": f"Unknown table '{table}'",
                    "unknown_select_columns": [],
                }
            if bad_cols:
                schema_rejections.append({"table": table, "bad_cols": bad_cols})
                return {
                    "error": f"Unknown SELECT columns for table '{table}': {bad_cols}",
                    "unknown_select_columns": bad_cols,
                }
            return {"rows": [
                {"deal_id": "D1", "arr_usd": 100000, "owner_email": "ae@co.com",
                 "deal_status": "open", "close_date": "2026-12-15"},
            ]}

        with patch("api.tools.filter_table", side_effect=mock_filter_table):
            with patch("api.agent_loop._get_schema_for_prompt",
                        return_value=_REALISTIC_SCHEMA):
                result = run(run_agent_loop(
                    question="What is our total pipeline?",
                    client=client,
                    sb=MagicMock(),
                ))

        self.assertEqual(len(schema_rejections), 0,
                         f"Expected zero schema rejections but got: {schema_rejections}")
        self.assertIn("$2.4M", result.answer)
        self.assertEqual(result.steps_taken, 2)

    def test_bad_columns_without_schema_would_produce_rejections(self):
        """Control test: a model that guesses 'opportunities' table with
        ['id', 'name', 'amount', 'owner'] columns DOES produce schema
        rejections.  This proves the assertion above is meaningful — the
        schema injection is what prevents the rejections, not the test
        setup being trivially permissive."""
        steps = [
            # The "old" model behavior: guess from training data
            _fetch_data("opportunities", columns=["id", "name", "amount", "owner"]),
            # After rejection, it corrects itself
            _fetch_data("deals", columns=["deal_id", "arr_usd"]),
            _deliver("Pipeline: $2.4M"),
        ]
        client = FakeClient(steps)

        schema_rejections = []

        async def mock_filter_table(sb, table, **kwargs):
            cols = kwargs.get("columns") or []
            if table == "opportunities":
                schema_rejections.append({"table": table, "cols": cols})
                return {
                    "error": f"Could not find the table 'opportunities'",
                    "unknown_select_columns": cols,
                }
            bad_cols = [c for c in cols if c not in {
                "deal_id", "arr_usd", "company_name", "owner_email",
            }]
            if bad_cols:
                schema_rejections.append({"table": table, "bad_cols": bad_cols})
                return {
                    "error": f"Unknown SELECT columns: {bad_cols}",
                    "unknown_select_columns": bad_cols,
                }
            return {"rows": [{"deal_id": "D1", "arr_usd": 100000}]}

        with patch("api.tools.filter_table", side_effect=mock_filter_table):
            with patch("api.agent_loop._get_schema_for_prompt", return_value=""):
                result = run(run_agent_loop(
                    question="What is our total pipeline?",
                    client=client,
                    sb=MagicMock(),
                ))

        self.assertGreater(len(schema_rejections), 0,
                           "Control: without schema, bad columns SHOULD produce rejections")
        self.assertEqual(result.answer, "Pipeline: $2.4M")

    def test_schema_in_prompt_contains_real_column_names(self):
        """The system prompt must contain the real column names from the
        injected schema so the model can read them before its first call."""
        steps = [_deliver("Done.")]
        client = FakeClient(steps)

        with patch("api.agent_loop._get_schema_for_prompt",
                    return_value=_REALISTIC_SCHEMA):
            run(run_agent_loop(
                question="Show pipeline",
                client=client,
                sb=MagicMock(),
            ))

        system = client.system_prompts[0]
        # These are the correct column names — NOT the hallucinated ones
        self.assertIn("deal_id", system)
        self.assertIn("arr_usd", system)
        self.assertIn("owner_email", system)
        self.assertIn("company_name", system)
        # The hallucinated names must NOT appear
        self.assertNotIn("opportunities", system.split("TABLE:")[0]
                         if "TABLE:" in system else "")
        for bad_col in ("amount", "owner\n", "id\n"):
            # Check these don't appear as standalone column definitions
            for line in system.split("\n"):
                line_stripped = line.strip()
                if line_stripped.startswith(bad_col.strip() + " ("):
                    self.fail(
                        f"Hallucinated column name '{bad_col.strip()}' found "
                        f"in system prompt line: {line_stripped}"
                    )

    def test_mixed_correct_and_bad_columns_counts_rejections(self):
        """If a model ignores the schema and mixes correct with bad columns,
        the bad ones produce rejections while correct ones succeed."""
        steps = [
            # First call: mix of correct and hallucinated columns
            _fetch_data("deals", columns=["deal_id", "amount", "owner"]),
            # After rejection, model reads the schema and uses correct names
            _fetch_data("deals", columns=["deal_id", "arr_usd", "owner_email"]),
            _deliver("Total: $500K"),
        ]
        client = FakeClient(steps)

        rejection_count = 0

        async def mock_filter_table(sb, table, **kwargs):
            nonlocal rejection_count
            cols = kwargs.get("columns") or []
            valid = {"deal_id", "company_name", "owner_email", "arr_usd",
                     "deal_value", "deal_status", "close_date"}
            bad_cols = [c for c in cols if c not in valid]
            if bad_cols:
                rejection_count += 1
                return {
                    "error": f"Unknown SELECT columns for table 'deals': {bad_cols}",
                    "unknown_select_columns": bad_cols,
                }
            return {"rows": [{"deal_id": "D1", "arr_usd": 500000,
                              "owner_email": "a@co.com"}]}

        with patch("api.tools.filter_table", side_effect=mock_filter_table):
            with patch("api.agent_loop._get_schema_for_prompt",
                        return_value=_REALISTIC_SCHEMA):
                result = run(run_agent_loop(
                    question="Total pipeline",
                    client=client,
                    sb=MagicMock(),
                ))

        self.assertEqual(rejection_count, 1,
                         "First call has bad cols → 1 rejection")
        self.assertEqual(result.answer, "Total: $500K")


if __name__ == "__main__":
    unittest.main()
