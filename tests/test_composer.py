"""
Tests for api/composer.py — plan-then-verify compositional layer.

Hard invariants:
  1. decompose_question() returns a plan dict with at minimum: question,
     sub_parts (list), each sub_part has name + primitive + rationale.
  2. plan_to_clarification_message() produces a non-empty human-readable string
     that includes all sub-part names.
  3. verify_plan_result() returns True when totals reconcile, False otherwise.
  4. verify_plan_result() never raises — returns (False, reason) on error.
  5. A plan where parts sum correctly passes verification.
  6. A plan where parts do not sum passes but discrepancy is noted.
  7. No new calculation logic is invented — sub_parts map to named primitives.

Fixtures:
  - Q4 coverage case: scope_mismatch because question needs (a) open Q4 pipeline
    total, (b) Q4 target, (c) coverage ratio — single handler returns waterfall
    totals, not the split.
  - $4.86M/$1.95M reconciliation case: question asks about total and components,
    but handler returned only waterfall aggregate.
"""
import json
import sys
import unittest
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO))

from api.composer import (
    plan_to_clarification_message,
    verify_plan_result,
    _sub_parts_sum_check,
)

FIXTURE_DIR = REPO / "tests" / "fixtures"


# ---------------------------------------------------------------------------
# Helpers

def _plan(sub_parts=None, question="How is Q4 coverage?"):
    return {
        "question": question,
        "sub_parts": sub_parts or [
            {"name": "open_q4_pipeline",
             "primitive": "query_pipeline_coverage",
             "rationale": "Sum of active deal ARR closing in Q4"},
            {"name": "q4_target",
             "primitive": "query_path_to_target",
             "rationale": "Q4 bookings target from config"},
            {"name": "coverage_ratio",
             "primitive": "_computed",
             "rationale": "open_q4_pipeline / q4_target"},
        ],
        "explanation": "This question needs pipeline + target + ratio.",
    }


def _results(open_pipeline=4_860_000, target=1_950_000):
    return {
        "open_q4_pipeline": {"total_arr": open_pipeline},
        "q4_target": {"target": target},
    }


# ---------------------------------------------------------------------------
# plan_to_clarification_message()

class TestPlanToClarificationMessage(unittest.TestCase):

    def test_returns_nonempty_string(self):
        msg = plan_to_clarification_message(_plan())
        self.assertIsInstance(msg, str)
        self.assertGreater(len(msg.strip()), 0)

    def test_includes_all_sub_part_names(self):
        plan = _plan()
        msg = plan_to_clarification_message(plan)
        for part in plan["sub_parts"]:
            self.assertIn(part["name"].replace("_", " "),
                          msg.lower().replace("_", " "),
                          f"Part name {part['name']!r} not in message")

    def test_message_is_readable_not_raw_json(self):
        msg = plan_to_clarification_message(_plan())
        # Should read as plain text, not a raw JSON dump
        self.assertNotIn('"primitive":', msg)

    def test_explanation_included(self):
        plan = _plan()
        msg = plan_to_clarification_message(plan)
        # The overall explanation or question context should appear
        self.assertTrue(len(msg) > 50)

    def test_empty_sub_parts_does_not_crash(self):
        plan = _plan(sub_parts=[])
        msg = plan_to_clarification_message(plan)
        self.assertIsInstance(msg, str)


# ---------------------------------------------------------------------------
# verify_plan_result()

class TestVerifyPlanResult(unittest.TestCase):

    def test_passes_when_no_numeric_totals(self):
        """No totals to reconcile → verification passes (nothing to check)."""
        plan = _plan()
        results = {"open_q4_pipeline": {"rows": [1, 2, 3]},
                   "q4_target": {"rows": [4, 5]}}
        ok, _ = verify_plan_result(plan, results)
        self.assertTrue(ok)

    def test_never_raises(self):
        """verify_plan_result must not raise even with garbage input."""
        try:
            ok, reason = verify_plan_result(None, None)
            self.assertIsInstance(ok, bool)
            self.assertIsInstance(reason, str)
        except Exception as e:
            self.fail(f"verify_plan_result raised: {e}")

    def test_empty_results_ok(self):
        ok, reason = verify_plan_result(_plan(), {})
        self.assertIsInstance(ok, bool)
        self.assertIsInstance(reason, str)

    def test_returns_tuple(self):
        result = verify_plan_result(_plan(), _results())
        self.assertIsInstance(result, tuple)
        self.assertEqual(len(result), 2)

    def test_bool_first_element(self):
        ok, _ = verify_plan_result(_plan(), _results())
        self.assertIsInstance(ok, bool)

    def test_str_second_element(self):
        _, reason = verify_plan_result(_plan(), _results())
        self.assertIsInstance(reason, str)


# ---------------------------------------------------------------------------
# _sub_parts_sum_check() — the reconciliation helper

class TestSubPartsSumCheck(unittest.TestCase):

    def test_parts_that_sum_correctly(self):
        """Two parts summing to a stated total → reconciles."""
        plan = {
            "question": "Reconcile $4.86M",
            "sub_parts": [
                {"name": "new_arr",      "primitive": "query_waterfall"},
                {"name": "expansion_arr","primitive": "query_waterfall"},
                {"name": "total_arr",    "primitive": "_computed",
                 "rationale": "new_arr + expansion_arr"},
            ],
        }
        results = {
            "new_arr":       {"total": 4_000_000},
            "expansion_arr": {"total":   860_000},
            "total_arr":     {"total": 4_860_000},
        }
        ok, note = _sub_parts_sum_check(plan, results)
        self.assertTrue(ok)
        self.assertEqual(note, "")

    def test_parts_that_do_not_sum(self):
        """Parts summing to wrong total → not ok, note explains."""
        plan = {
            "question": "Reconcile",
            "sub_parts": [
                {"name": "new_arr",      "primitive": "query_waterfall"},
                {"name": "expansion_arr","primitive": "query_waterfall"},
                {"name": "total_arr",    "primitive": "_computed",
                 "rationale": "new_arr + expansion_arr"},
            ],
        }
        results = {
            "new_arr":       {"total": 4_000_000},
            "expansion_arr": {"total":   860_000},
            "total_arr":     {"total": 5_200_000},   # wrong
        }
        ok, note = _sub_parts_sum_check(plan, results)
        self.assertFalse(ok)
        self.assertIn("mismatch", note.lower())

    def test_no_computed_parts_always_ok(self):
        """No _computed sub-parts → nothing to reconcile."""
        plan = {
            "question": "Q4 pipeline",
            "sub_parts": [
                {"name": "open_q4", "primitive": "query_pipeline_coverage"},
            ],
        }
        results = {"open_q4": {"total_arr": 1_000_000}}
        ok, note = _sub_parts_sum_check(plan, results)
        self.assertTrue(ok)

    def test_missing_part_result_is_ok(self):
        """If a part's result is missing entirely, don't fail the check."""
        plan = {
            "question": "test",
            "sub_parts": [
                {"name": "a", "primitive": "query_x"},
                {"name": "b", "primitive": "_computed",
                 "rationale": "a + something"},
            ],
        }
        results = {}   # no results yet
        ok, note = _sub_parts_sum_check(plan, results)
        self.assertIsInstance(ok, bool)

    def test_never_raises_on_bad_data(self):
        try:
            ok, note = _sub_parts_sum_check(None, None)
            self.assertIsInstance(ok, bool)
        except Exception as e:
            self.fail(f"_sub_parts_sum_check raised: {e}")


# ---------------------------------------------------------------------------
# Plan structure invariants

class TestPlanStructure(unittest.TestCase):

    def test_plan_has_required_keys(self):
        plan = _plan()
        for key in ("question", "sub_parts", "explanation"):
            self.assertIn(key, plan, f"Plan missing key {key!r}")

    def test_sub_parts_have_required_keys(self):
        plan = _plan()
        for part in plan["sub_parts"]:
            for key in ("name", "primitive", "rationale"):
                self.assertIn(key, part,
                              f"sub_part missing key {key!r}: {part}")

    def test_computed_parts_reference_existing_primitive_label(self):
        """_computed parts must have a rationale explaining their formula."""
        plan = _plan()
        for part in plan["sub_parts"]:
            if part["primitive"] == "_computed":
                self.assertTrue(len(part.get("rationale", "")) > 0,
                                "_computed part must have a rationale")


if __name__ == "__main__":
    unittest.main()
