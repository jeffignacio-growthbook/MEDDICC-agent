"""
Tests for the hybrid rounding tolerance in AGGREGATION_VERIFY.

Production incident (2026-09-30): a stated pipeline total of $26.8M
was flagged as a mismatch against actual rows summing to $26,778,381.05
(0.08% off — a presentation-rounding choice, not a computation error).
Meanwhile, a stated $1.55M against actual $5,045,827.20 (226% off) was
correctly rejected.

The fix uses max(abs_tolerance, 1% of actual) so that:
  - Large totals tolerate presentation rounding (case a)
  - Wildly wrong figures are still caught (case b)
  - Small totals still use the absolute floor ($0.50)
"""
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from api.aggregation_verification import (
    _within_tolerance,
    _RELATIVE_TOLERANCE,
    verify_aggregation_completeness,
    verify_aggregation_by_population,
)


class TestWithinTolerance(unittest.TestCase):
    """Direct tests for the _within_tolerance helper."""

    def test_case_a_rounding_on_large_total_accepted(self):
        """stated=26,800,000 vs actual=26,778,381.05 (~0.08%) → match."""
        self.assertTrue(_within_tolerance(26_800_000.0, 26_778_381.049996))

    def test_case_b_wildly_wrong_rejected(self):
        """stated=1,550,000 vs actual=5,045,827.20 (~226%) → no match."""
        self.assertFalse(_within_tolerance(1_550_000.0, 5_045_827.2))

    def test_exact_match(self):
        self.assertTrue(_within_tolerance(100_000.0, 100_000.0))

    def test_small_absolute_diff_on_small_total(self):
        """$0.30 diff on a $50 total → within abs floor ($0.50)."""
        self.assertTrue(_within_tolerance(50.30, 50.0))

    def test_small_total_beyond_abs_floor(self):
        """$0.60 diff on a $50 total → exceeds both abs ($0.50) and 1% ($0.50)."""
        self.assertFalse(_within_tolerance(50.60, 50.0))

    def test_boundary_exactly_at_one_percent(self):
        """Exactly at the 1% relative boundary → match (<=, not <)."""
        actual = 1_000_000.0
        stated = actual * (1 + _RELATIVE_TOLERANCE)  # exactly 1% over
        self.assertTrue(_within_tolerance(stated, actual))

    def test_boundary_just_over_one_percent(self):
        """Just over the 1% relative boundary → no match."""
        actual = 1_000_000.0
        stated = actual * (1 + _RELATIVE_TOLERANCE) + 1.0  # 1% + $1
        self.assertFalse(_within_tolerance(stated, actual))

    def test_negative_values(self):
        """Tolerance works for negative sums (net losses)."""
        self.assertTrue(_within_tolerance(-500_000.0, -503_000.0))
        self.assertFalse(_within_tolerance(-500_000.0, -600_000.0))

    def test_zero_actual(self):
        """When actual is 0, only the absolute floor applies."""
        self.assertTrue(_within_tolerance(0.3, 0.0))
        self.assertFalse(_within_tolerance(1.0, 0.0))


class TestVerifyAggregationCompletenessWithTolerance(unittest.TestCase):
    """Integration: verify_aggregation_completeness with the new tolerance."""

    def _make_rows(self, values):
        return [{"deal_value": v} for v in values]

    def test_case_a_presentation_rounding_passes(self):
        """stated $26.8M, actual rows sum to $26,778,381.05 → match."""
        rows = self._make_rows([13_000_000, 10_000_000, 3_778_381.049996])
        result = verify_aggregation_completeness(
            rows, {"total": 26_800_000.0}, value_column="deal_value")
        self.assertTrue(result["match"],
                        f"Rounding mismatch should be accepted: {result}")

    def test_case_b_wrong_total_rejected(self):
        """stated $1.55M, actual rows sum to $5,045,827.20 → mismatch."""
        rows = self._make_rows([3_000_000, 2_045_827.2])
        result = verify_aggregation_completeness(
            rows, {"total": 1_550_000.0}, value_column="deal_value")
        self.assertFalse(result["match"],
                         "Wildly wrong total must be rejected")

    def test_old_absolute_tolerance_still_works(self):
        """A $0.30 rounding diff on a small total still passes."""
        rows = self._make_rows([25.0, 25.0])
        result = verify_aggregation_completeness(
            rows, {"total": 50.30}, value_column="deal_value")
        self.assertTrue(result["match"])


class TestVerifyByPopulationWithTolerance(unittest.TestCase):
    """Integration: verify_aggregation_by_population with the new tolerance."""

    def test_case_a_passes_by_population(self):
        """stated $26.8M matches a population summing to $26,778,381.05."""
        populations = {
            "deals on 2026-09-30": [
                {"deal_value": 13_000_000},
                {"deal_value": 10_000_000},
                {"deal_value": 3_778_381.049996},
            ]
        }
        result = verify_aggregation_by_population(
            populations, {"total": 26_800_000.0})
        self.assertTrue(result["match"],
                        f"Rounding mismatch should be accepted: {result}")

    def test_case_b_rejected_by_population(self):
        """stated $1.55M against population summing to $5M+ → mismatch."""
        populations = {
            "deals on 2026-09-30": [
                {"deal_value": 3_000_000},
                {"deal_value": 2_045_827.2},
            ]
        }
        result = verify_aggregation_by_population(
            populations, {"total": 1_550_000.0})
        self.assertFalse(result["match"],
                         "Wildly wrong total must be rejected")


if __name__ == "__main__":
    unittest.main()
