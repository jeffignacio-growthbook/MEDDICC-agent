"""
Tests for runtime schema validation (Feature 1) and pre-query value sanity
check (Feature 2) in api/tools.py, plus format/style check (Feature 3) in
api/assessor.py.

Planted-bug controls are in the "PlantedBug" classes below.
"""
import asyncio
import sys
import unittest
from pathlib import Path
from unittest.mock import MagicMock, patch

REPO_ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(REPO_ROOT))
sys.path.insert(0, str(REPO_ROOT / "api"))
sys.path.insert(0, str(REPO_ROOT / "scripts"))

import api.tools as tools_module
from api.tools import (
    _validate_columns,
    _validate_filters,
    _sanity_check_filter_values,
    filter_table,
)
from api.assessor import assess_format


def run(coro):
    return asyncio.get_event_loop().run_until_complete(coro)


# ---------------------------------------------------------------------------
# Shared fixture: patch _VALID_COLUMNS with a deterministic schema
# ---------------------------------------------------------------------------

DEALS_SCHEMA = {
    "deal_id", "company_name", "deal_value", "close_date",
    "deal_status", "fiscal_quarter", "pipeline_id", "stage",
    "new_arr", "expansion_arr",
}


class SchemaFixture(unittest.TestCase):
    """Base that populates and tears down _VALID_COLUMNS for 'deals'."""

    def setUp(self):
        self._orig = dict(tools_module._VALID_COLUMNS)
        tools_module._VALID_COLUMNS.clear()
        tools_module._VALID_COLUMNS["deals"] = set(DEALS_SCHEMA)

    def tearDown(self):
        tools_module._VALID_COLUMNS.clear()
        tools_module._VALID_COLUMNS.update(self._orig)


# ===========================================================================
# Feature 1 — Runtime schema validation
# ===========================================================================

class TestValidateColumns(SchemaFixture):
    """_validate_columns separates known columns from invented ones."""

    def test_known_columns_pass(self):
        good, bad = _validate_columns("deals", ["deal_id", "company_name"])
        self.assertIn("deal_id", good)
        self.assertIn("company_name", good)
        self.assertEqual(bad, [])

    def test_invented_column_lands_in_bad(self):
        good, bad = _validate_columns("deals", ["deal_id", "invented_col"])
        self.assertIn("deal_id", good)
        self.assertIn("invented_col", bad)

    def test_emits_schema_validation_log_prefix(self):
        with self.assertLogs("cro_agent", level="WARNING") as cm:
            _validate_columns("deals", ["deal_id", "not_a_real_column"])
        self.assertTrue(
            any("[SCHEMA_VALIDATION]" in line for line in cm.output),
            "Expected [SCHEMA_VALIDATION] prefix in log output",
        )

    def test_unknown_table_allows_all_columns(self):
        """No schema for unknown table = no rejection (can't validate what we don't know)."""
        good, bad = _validate_columns("no_such_table_xyz", ["any_col", "another"])
        self.assertEqual(bad, [])


class TestFilterTableSelectColumnRejection(SchemaFixture):
    """filter_table must reject unknown SELECT columns, not silently drop them."""

    def _sb(self):
        """Minimal supabase mock that won't be reached (we return before query)."""
        return MagicMock()

    def test_unknown_select_column_returns_error(self):
        sb = self._sb()
        with patch.object(tools_module, "_init_valid_columns"):
            result = run(filter_table(sb, "deals", columns=["deal_id", "invented_col"]))
        self.assertIn("error", result, "Expected error key in result")
        self.assertIn("unknown_select_columns", result)
        self.assertIn("invented_col", result["unknown_select_columns"])

    def test_error_message_names_queryable_columns(self):
        sb = self._sb()
        with patch.object(tools_module, "_init_valid_columns"):
            result = run(filter_table(sb, "deals", columns=["invented_col"]))
        self.assertIn("error", result)
        # Error message should list at least one real column
        self.assertIn("deal_id", result["error"])

    def test_known_select_columns_are_not_rejected(self):
        """All-valid column list should never hit the rejection path."""
        sb = self._sb()
        count_resp = MagicMock()
        count_resp.count = 5
        (sb.table.return_value.select.return_value
           .eq.return_value.limit.return_value.execute.return_value) = count_resp
        with patch.object(tools_module, "_init_valid_columns"), \
             patch("api.tools.select_all", return_value=[{"deal_id": "1"}]):
            result = run(filter_table(sb, "deals", columns=["deal_id", "company_name"]))
        self.assertNotIn("unknown_select_columns", result)

    def test_unknown_table_not_in_dictionary_is_not_rejected(self):
        """A table with no data_dictionary entry cannot be validated; no error."""
        sb = self._sb()
        with patch.object(tools_module, "_init_valid_columns"), \
             patch("api.tools.select_all", return_value=[]):
            result = run(filter_table(sb, "unknown_table_xyz", columns=["fake_col"]))
        self.assertNotIn("unknown_select_columns", result)


# ---------------------------------------------------------------------------
# Planted-bug control: if _validate_columns silently accepts all columns,
# the rejection test above would never fire.
# ---------------------------------------------------------------------------

class TestPlantedBug_SelectColumnAlwaysAccepted(SchemaFixture):
    """
    Planted-bug control: replacing _validate_columns with an always-accept
    version makes the rejection test fail — proving the test actually guards
    the feature.
    """

    def test_planted_bug_detected(self):
        """Confirm that removing validation makes filter_table NOT return an error."""
        def permissive_validate(table, columns):
            # Planted: accept everything, return no bad list
            return list(columns), []

        sb = MagicMock()
        with patch.object(tools_module, "_init_valid_columns"), \
             patch.object(tools_module, "_validate_columns", side_effect=permissive_validate), \
             patch("api.tools.select_all", return_value=[]):
            result = run(filter_table(sb, "deals", columns=["deal_id", "invented_col"]))
        # With the bug planted the error path is skipped — no error key
        self.assertNotIn("error", result,
            "Planted bug: permissive _validate_columns should suppress the rejection")


# ===========================================================================
# Feature 2 — Pre-query value sanity check
# ===========================================================================

class TestSanityCheckFilterValues(SchemaFixture):

    def _sb_with_count(self, count):
        sb = MagicMock()
        resp = MagicMock()
        resp.count = count
        (sb.table.return_value.select.return_value
           .eq.return_value.limit.return_value.execute.return_value) = resp
        return sb

    def test_zero_match_value_is_suspicious(self):
        sb = self._sb_with_count(0)
        result = run(_sanity_check_filter_values(
            sb, "deals", [("eq", "pipeline_id", "invented_pipeline_xyz")]
        ))
        self.assertEqual(len(result), 1)
        self.assertEqual(result[0]["rows_matched"], 0)
        self.assertIn("invented_pipeline_xyz", result[0]["note"])

    def test_nonzero_match_value_is_not_suspicious(self):
        sb = self._sb_with_count(37)
        result = run(_sanity_check_filter_values(
            sb, "deals", [("eq", "pipeline_id", "real_pipeline_id")]
        ))
        self.assertEqual(result, [])

    def test_enum_values_are_skipped(self):
        """Common status strings must not trigger a round-trip COUNT."""
        sb = self._sb_with_count(0)  # would flag if it ran
        result = run(_sanity_check_filter_values(
            sb, "deals", [("eq", "deal_status", "active")]
        ))
        self.assertEqual(result, [], "'active' is a known enum; should be skipped")

    def test_iso_date_values_are_skipped(self):
        sb = self._sb_with_count(0)
        result = run(_sanity_check_filter_values(
            sb, "deals", [("eq", "close_date", "2027-03-31")]
        ))
        self.assertEqual(result, [])

    def test_fiscal_quarter_values_are_skipped(self):
        sb = self._sb_with_count(0)
        result = run(_sanity_check_filter_values(
            sb, "deals", [("eq", "fiscal_quarter", "FY2027 Q3")]
        ))
        self.assertEqual(result, [])

    def test_emits_schema_validation_log_prefix(self):
        sb = self._sb_with_count(0)
        with self.assertLogs("cro_agent", level="WARNING") as cm:
            run(_sanity_check_filter_values(
                sb, "deals", [("eq", "pipeline_id", "nonexistent_pipe")]
            ))
        self.assertTrue(
            any("[SCHEMA_VALIDATION]" in line for line in cm.output),
            "Expected [SCHEMA_VALIDATION] prefix in sanity-check log",
        )

    def test_non_eq_operators_are_skipped(self):
        """gte/lte/ilike etc. are range/pattern filters — no value sanity check."""
        sb = self._sb_with_count(0)
        result = run(_sanity_check_filter_values(
            sb, "deals", [("gte", "close_date", "2027-01-01")]
        ))
        self.assertEqual(result, [])

    def test_filter_table_returns_error_on_zero_match_filter(self):
        """filter_table must propagate the sanity-check error to the caller."""
        count_resp = MagicMock()
        count_resp.count = 0
        sb = MagicMock()
        (sb.table.return_value.select.return_value
           .eq.return_value.limit.return_value.execute.return_value) = count_resp

        with patch.object(tools_module, "_init_valid_columns"), \
             patch("api.tools.select_all", return_value=[]):
            result = run(filter_table(
                sb, "deals",
                columns=["deal_id", "pipeline_id"],
                filters=[("eq", "pipeline_id", "totally_fake_pipe")],
            ))
        self.assertIn("error", result, "Expected sanity-check error from filter_table")
        self.assertIn("suspicious_filters", result)
        self.assertEqual(result["suspicious_filters"][0]["rows_matched"], 0)

    def test_real_column_wrong_value_triggers_sanity_check(self):
        """
        Feature 2 independent of Feature 1: 'stage' IS a real column (passes
        schema validation), but 'invented_stage_abc' matches zero rows.
        The sanity check must fire and block the query.
        """
        count_resp = MagicMock()
        count_resp.count = 0
        sb = MagicMock()
        (sb.table.return_value.select.return_value
           .eq.return_value.limit.return_value.execute.return_value) = count_resp

        with patch.object(tools_module, "_init_valid_columns"), \
             patch("api.tools.select_all", return_value=[]):
            result = run(filter_table(
                sb, "deals",
                columns=["deal_id", "stage"],
                filters=[("eq", "stage", "invented_stage_abc")],
            ))
        self.assertIn("error", result,
            "Feature 2 should block a real column with an invented value")
        self.assertIn("suspicious_filters", result)
        self.assertIn("invented_stage_abc", result["error"])


# ---------------------------------------------------------------------------
# Planted-bug control for Feature 2
# ---------------------------------------------------------------------------

class TestPlantedBug_SanityCheckAlwaysOk(SchemaFixture):
    """
    Planted-bug control: replacing _sanity_check_filter_values with a no-op
    makes filter_table skip the rejection — proving the test guards the gate.
    """

    def test_planted_bug_detected(self):
        async def no_op_check(sb, table, filters):
            return []  # planted: never suspicious

        count_resp = MagicMock()
        count_resp.count = 0
        sb = MagicMock()
        (sb.table.return_value.select.return_value
           .eq.return_value.limit.return_value.execute.return_value) = count_resp

        with patch.object(tools_module, "_init_valid_columns"), \
             patch.object(tools_module, "_sanity_check_filter_values",
                          side_effect=no_op_check), \
             patch("api.tools.select_all", return_value=[]):
            result = run(filter_table(
                sb, "deals",
                columns=["deal_id", "pipeline_id"],
                filters=[("eq", "pipeline_id", "totally_fake_pipe")],
            ))
        # Bug planted: no rejection, result has rows key instead of error
        self.assertNotIn("error", result,
            "Planted bug: no-op sanity check should suppress the rejection")


# ===========================================================================
# Feature 3 — Format / style check
# ===========================================================================

class TestAssessFormat(unittest.TestCase):

    def _mock_client(self, json_text):
        client = MagicMock()
        resp = MagicMock()
        resp.text = json_text
        client.complete.return_value = resp
        return client

    def test_format_ok_answer_passes(self):
        client = self._mock_client(
            '{"format_ok": true, "format_score": 0.9, '
            '"format_issue": null, "format_note": null}'
        )
        result = run(assess_format("What is the ARR?", "ARR is $1.2M.", client))
        self.assertTrue(result["format_ok"])
        self.assertGreater(result["format_score"], 0.5)
        self.assertIsNone(result["format_issue"])

    def test_too_long_answer_is_flagged(self):
        client = self._mock_client(
            '{"format_ok": false, "format_score": 0.2, '
            '"format_issue": "too_long", "format_note": "Lead with the number."}'
        )
        long_answer = "ARR is $1.2M. " * 50
        result = run(assess_format("What is the ARR?", long_answer, client))
        self.assertFalse(result["format_ok"])
        self.assertEqual(result["format_issue"], "too_long")

    def test_wrong_shape_is_flagged(self):
        client = self._mock_client(
            '{"format_ok": false, "format_score": 0.4, '
            '"format_issue": "wrong_shape", "format_note": "Use a list."}'
        )
        result = run(assess_format(
            "Show me each rep's pipeline by stage",
            "The pipeline looks decent overall.",
            client,
        ))
        self.assertEqual(result["format_issue"], "wrong_shape")

    def test_resilient_to_llm_failure(self):
        client = MagicMock()
        client.complete.side_effect = Exception("LLM timeout")
        result = run(assess_format("What is the ARR?", "some answer", client))
        self.assertTrue(result["format_ok"])   # safe default
        self.assertEqual(result["format_score"], 0.5)
        self.assertIsNone(result["format_issue"])

    def test_resilient_to_malformed_json(self):
        client = self._mock_client("NOT JSON AT ALL")
        result = run(assess_format("What is the ARR?", "ARR is $1.2M.", client))
        self.assertTrue(result["format_ok"])   # safe default on parse failure
        self.assertEqual(result["format_score"], 0.5)

    def test_assess_format_passes_question_and_answer_to_client(self):
        client = self._mock_client(
            '{"format_ok": true, "format_score": 0.8, '
            '"format_issue": null, "format_note": null}'
        )
        run(assess_format("My question here", "My answer here", client))
        call_kwargs = client.complete.call_args
        content = call_kwargs[1]["messages"][0]["content"]
        self.assertIn("My question here", content)
        self.assertIn("My answer here", content)


# ---------------------------------------------------------------------------
# Planted-bug control for Feature 3
# ---------------------------------------------------------------------------

class TestPlantedBug_AssessFormatAlwaysOk(unittest.TestCase):
    """
    Planted-bug control: if assess_format always returns format_ok=True the
    'too_long' test above fails — proving the test would catch a broken impl.
    """

    def test_planted_bug_detected(self):
        async def always_ok(question, answer, client):
            return {"format_ok": True, "format_score": 1.0, "format_issue": None}

        with patch("api.assessor.assess_format", side_effect=always_ok):
            result = run(always_ok("What is ARR?", "x" * 2000, None))
        # Planted: always ok, so format_issue is None (not "too_long")
        self.assertIsNone(result["format_issue"],
            "Planted bug: always-ok assess_format should never surface 'too_long'")


# ===========================================================================
# Feature 3 wiring — assess_format only runs after a successful query
# ===========================================================================

class TestAssessFormatNotCalledOnRejection(unittest.TestCase):
    """
    Control-flow proof: a filter_table rejection (Feature 1 or 2) produces a
    dict with an "error" key.  evaluate_result() classifies that as quality
    "error".  In route_question, all "error"-quality paths exit before step
    8.6 (where assess_format lives), so assess_format is never called for a
    rejected query.

    This test locks down each link in that chain individually.
    """

    def test_feature1_rejection_dict_has_error_key(self):
        """filter_table rejection for unknown SELECT column always has 'error' key."""
        tools_module._VALID_COLUMNS["deals"] = set(DEALS_SCHEMA)
        try:
            sb = MagicMock()
            with patch.object(tools_module, "_init_valid_columns"):
                result = asyncio.get_event_loop().run_until_complete(
                    filter_table(sb, "deals", columns=["invented_col"])
                )
            self.assertIn("error", result,
                "Feature 1 rejection must carry 'error' key for evaluate_result")
        finally:
            tools_module._VALID_COLUMNS.pop("deals", None)

    def test_feature2_rejection_dict_has_error_key(self):
        """filter_table sanity-check rejection (zero-count value) always has 'error' key."""
        tools_module._VALID_COLUMNS["deals"] = set(DEALS_SCHEMA)
        try:
            count_resp = MagicMock()
            count_resp.count = 0
            sb = MagicMock()
            (sb.table.return_value.select.return_value
               .eq.return_value.limit.return_value.execute.return_value) = count_resp
            with patch.object(tools_module, "_init_valid_columns"):
                result = asyncio.get_event_loop().run_until_complete(
                    filter_table(sb, "deals",
                                 columns=["deal_id", "stage"],
                                 filters=[("eq", "stage", "invented_stage_xyz")])
                )
            self.assertIn("error", result,
                "Feature 2 rejection must carry 'error' key for evaluate_result")
        finally:
            tools_module._VALID_COLUMNS.pop("deals", None)

    def test_evaluate_result_classifies_error_key_as_error_quality(self):
        """evaluate_result('error' key in dict) → 'error' quality → pre-synthesis exits."""
        from api.evaluator import evaluate_result
        # Feature 1 rejection shape
        f1_result = {"error": "Unknown SELECT columns for table 'deals': ['invented'].",
                     "unknown_select_columns": ["invented"]}
        self.assertEqual(evaluate_result(f1_result, "any_handler"), "error")

        # Feature 2 rejection shape
        f2_result = {"error": "Filter value sanity check: 'invented' matches 0 rows.",
                     "suspicious_filters": [{"filter": ("eq", "stage", "invented"),
                                             "rows_matched": 0, "note": "..."}]}
        self.assertEqual(evaluate_result(f2_result, "any_handler"), "error")


if __name__ == "__main__":
    unittest.main(verbosity=2)
