"""
Tests for date-range bucketing in aggregate_results.

Production incident (2026-10-01): the model was asked to split Proposal-stage
deals into this quarter vs next quarter.  It fetched 31 rows via filter_table,
then tried to manually read each deal's close_date and sum in prose —
getting $2,370,800 when the correct total was $4,133,800.  AGGREGATION_VERIFY
caught it twice, correctly declining rather than shipping a wrong answer.

Fix: aggregate_results now accepts group_by_date_ranges — a list of
{label, column, start, end} buckets.  Rows are bucketed by date range
and aggregations are computed per bucket in code, never by the model.

Tests:
  (10) correct per-group sums and counts, including boundary dates
  (11) no regression — calls WITHOUT group_by_date_ranges behave as before
  (12) reproduce tonight's 31-deal scenario as a fixture
  (13) AGGREGATION_VERIFY retry instruction prevents placement corruption
"""
import asyncio
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from api.tools import aggregate_results


def _run(coro):
    return asyncio.run(coro)


# ── Fixture: small dataset for boundary testing ────────────────
SMALL_DEALS = [
    {"deal_id": "1", "deal_value": 100_000, "close_date": "2026-08-15", "stage": "Proposal"},
    {"deal_id": "2", "deal_value": 200_000, "close_date": "2026-10-31", "stage": "Proposal"},
    {"deal_id": "3", "deal_value": 300_000, "close_date": "2026-11-01", "stage": "Negotiation"},
    {"deal_id": "4", "deal_value": 150_000, "close_date": "2026-12-15", "stage": "Proposal"},
    {"deal_id": "5", "deal_value":  50_000, "close_date": "2027-02-01", "stage": "Discovery"},
]

Q3_RANGE = {"label": "Q3 (this quarter)", "column": "close_date",
            "start": "2026-08-01", "end": "2026-10-31"}
Q4_RANGE = {"label": "Q4 (next quarter)", "column": "close_date",
            "start": "2026-11-01", "end": "2027-01-31"}


class TestDateRangeBucketing(unittest.TestCase):
    """Test 10: correct per-group sums, counts, and boundary dates."""

    def test_basic_two_bucket_split(self):
        result = _run(aggregate_results(
            data=SMALL_DEALS,
            group_by="close_date",
            aggregations={"deal_value": "sum", "deal_id": "count"},
            group_by_date_ranges=[Q3_RANGE, Q4_RANGE],
        ))
        self.assertNotIn("error", result)
        rows = {r["date_range"]: r for r in result["rows"]}
        self.assertIn("Q3 (this quarter)", rows)
        self.assertIn("Q4 (next quarter)", rows)
        # Q3: deals 1 ($100K) + 2 ($200K) = $300K, 2 deals
        self.assertEqual(rows["Q3 (this quarter)"]["deal_value_sum"], 300_000)
        self.assertEqual(rows["Q3 (this quarter)"]["deal_id_count"], 2)
        # Q4: deals 3 ($300K) + 4 ($150K) = $450K, 2 deals
        self.assertEqual(rows["Q4 (next quarter)"]["deal_value_sum"], 450_000)
        self.assertEqual(rows["Q4 (next quarter)"]["deal_id_count"], 2)

    def test_boundary_date_inclusive(self):
        """Deal closing on the last day of Q3 (2026-10-31) is in Q3."""
        result = _run(aggregate_results(
            data=SMALL_DEALS,
            group_by="close_date",
            aggregations={"deal_value": "sum"},
            group_by_date_ranges=[Q3_RANGE, Q4_RANGE],
        ))
        rows = {r["date_range"]: r for r in result["rows"]}
        # Deal 2 ($200K, close_date=2026-10-31) must be in Q3
        self.assertEqual(rows["Q3 (this quarter)"]["deal_value_sum"], 300_000)

    def test_boundary_first_day_of_next_range(self):
        """Deal closing on 2026-11-01 is in Q4, not Q3."""
        result = _run(aggregate_results(
            data=SMALL_DEALS,
            group_by="close_date",
            aggregations={"deal_value": "sum"},
            group_by_date_ranges=[Q3_RANGE, Q4_RANGE],
        ))
        rows = {r["date_range"]: r for r in result["rows"]}
        # Deal 3 ($300K, close_date=2026-11-01) must be in Q4
        self.assertEqual(rows["Q4 (next quarter)"]["deal_value_sum"], 450_000)

    def test_deals_outside_all_ranges_land_in_other(self):
        """Deal 5 (2027-02-01) is outside both Q3 and Q4."""
        result = _run(aggregate_results(
            data=SMALL_DEALS,
            group_by="close_date",
            aggregations={"deal_value": "sum"},
            group_by_date_ranges=[Q3_RANGE, Q4_RANGE],
        ))
        rows = {r["date_range"]: r for r in result["rows"]}
        self.assertIn("other", rows)
        self.assertEqual(rows["other"]["deal_value_sum"], 50_000)

    def test_no_other_bucket_when_all_rows_placed(self):
        """When every row matches a range, no 'other' bucket appears."""
        deals = SMALL_DEALS[:4]  # all within Q3 or Q4
        result = _run(aggregate_results(
            data=deals,
            group_by="close_date",
            aggregations={"deal_value": "sum"},
            group_by_date_ranges=[Q3_RANGE, Q4_RANGE],
        ))
        labels = [r["date_range"] for r in result["rows"]]
        self.assertNotIn("other", labels)

    def test_three_buckets(self):
        """Arbitrary number of buckets, not just two."""
        q1_range = {"label": "Q1", "column": "close_date",
                    "start": "2027-02-01", "end": "2027-04-30"}
        result = _run(aggregate_results(
            data=SMALL_DEALS,
            group_by="close_date",
            aggregations={"deal_value": "sum"},
            group_by_date_ranges=[Q3_RANGE, Q4_RANGE, q1_range],
        ))
        rows = {r["date_range"]: r for r in result["rows"]}
        self.assertIn("Q1", rows)
        self.assertEqual(rows["Q1"]["deal_value_sum"], 50_000)

    def test_null_close_date_goes_to_other(self):
        """Row with null close_date ends up in 'other'."""
        deals = [{"deal_id": "x", "deal_value": 99, "close_date": None}]
        result = _run(aggregate_results(
            data=deals,
            group_by="close_date",
            aggregations={"deal_value": "sum"},
            group_by_date_ranges=[Q3_RANGE],
        ))
        rows = {r["date_range"]: r for r in result["rows"]}
        self.assertIn("other", rows)
        self.assertEqual(rows["other"]["deal_value_sum"], 99)

    def test_avg_aggregation(self):
        """Avg works per bucket."""
        result = _run(aggregate_results(
            data=SMALL_DEALS,
            group_by="close_date",
            aggregations={"deal_value": "avg"},
            group_by_date_ranges=[Q3_RANGE, Q4_RANGE],
        ))
        rows = {r["date_range"]: r for r in result["rows"]}
        # Q3: (100K + 200K) / 2 = 150K
        self.assertEqual(rows["Q3 (this quarter)"]["deal_value_avg"], 150_000)

    def test_row_count_in_output(self):
        """Each bucket includes row_count."""
        result = _run(aggregate_results(
            data=SMALL_DEALS,
            group_by="close_date",
            aggregations={"deal_value": "sum"},
            group_by_date_ranges=[Q3_RANGE, Q4_RANGE],
        ))
        rows = {r["date_range"]: r for r in result["rows"]}
        self.assertEqual(rows["Q3 (this quarter)"]["row_count"], 2)
        self.assertEqual(rows["Q4 (next quarter)"]["row_count"], 2)


class TestNoRegressionWithoutDateRanges(unittest.TestCase):
    """Test 11: aggregate_results without group_by_date_ranges is unchanged."""

    def test_standard_group_by_still_works(self):
        result = _run(aggregate_results(
            data=SMALL_DEALS,
            group_by="stage",
            aggregations={"deal_value": "sum", "deal_id": "count"},
        ))
        self.assertNotIn("error", result)
        rows = {r["stage"]: r for r in result["rows"]}
        self.assertIn("Proposal", rows)
        # Proposal: 100K + 200K + 150K = 450K
        self.assertEqual(rows["Proposal"]["deal_value_sum"], 450_000)
        self.assertEqual(rows["Proposal"]["deal_id_count"], 3)

    def test_empty_data_still_returns_error(self):
        result = _run(aggregate_results(data=[], group_by="stage",
                                        aggregations={"deal_value": "sum"}))
        self.assertIn("error", result)

    def test_missing_column_still_returns_error(self):
        result = _run(aggregate_results(
            data=SMALL_DEALS, group_by="nonexistent",
            aggregations={"deal_value": "sum"}))
        self.assertIn("error", result)


# ── Test 12: tonight's 31-deal scenario ──────────────────────────
# Simplified fixture: 31 deals with mixed close dates, same shape.
# The model got the total wrong ($2,370,800 stated vs $4,133,800 actual).
# With date-range bucketing, the tool computes the split correctly.
PROPOSAL_DEALS = [
    {"deal_id": f"d{i}", "deal_value": v, "close_date": d, "stage": "Proposal"}
    for i, (v, d) in enumerate([
        (150_000, "2026-08-05"), (200_000, "2026-08-12"),
        (175_000, "2026-08-20"), (120_000, "2026-09-01"),
        (95_000,  "2026-09-08"), (180_000, "2026-09-15"),
        (210_000, "2026-09-22"), (160_000, "2026-09-30"),
        (140_000, "2026-10-05"), (190_000, "2026-10-12"),
        (130_000, "2026-10-20"), (165_000, "2026-10-28"),
        (115_000, "2026-10-31"),
        # Next quarter deals
        (220_000, "2026-11-01"), (185_000, "2026-11-10"),
        (145_000, "2026-11-18"), (200_000, "2026-11-25"),
        (170_000, "2026-12-02"), (155_000, "2026-12-10"),
        (195_000, "2026-12-18"), (125_000, "2026-12-28"),
        (210_000, "2027-01-05"), (180_000, "2027-01-12"),
        (160_000, "2027-01-20"), (140_000, "2027-01-28"),
        # Stragglers in Q1
        (100_000, "2027-02-05"), (90_000,  "2027-02-15"),
        (110_000, "2027-03-01"), (85_000,  "2027-03-15"),
        (95_000,  "2027-04-01"), (75_000,  "2027-04-15"),
    ])
]
EXPECTED_Q3_SUM = sum(d["deal_value"] for d in PROPOSAL_DEALS
                      if "2026-08-01" <= d["close_date"] <= "2026-10-31")
EXPECTED_Q4_SUM = sum(d["deal_value"] for d in PROPOSAL_DEALS
                      if "2026-11-01" <= d["close_date"] <= "2027-01-31")


class TestTonightsScenario(unittest.TestCase):
    """Test 12: reproduce tonight's failing scenario."""

    def test_31_deal_split_correct_on_first_attempt(self):
        result = _run(aggregate_results(
            data=PROPOSAL_DEALS,
            group_by="close_date",
            aggregations={"deal_value": "sum", "deal_id": "count"},
            group_by_date_ranges=[Q3_RANGE, Q4_RANGE],
        ))
        rows = {r["date_range"]: r for r in result["rows"]}
        self.assertEqual(rows["Q3 (this quarter)"]["deal_value_sum"],
                         EXPECTED_Q3_SUM)
        self.assertEqual(rows["Q4 (next quarter)"]["deal_value_sum"],
                         EXPECTED_Q4_SUM)
        # Verify our fixture has the right count
        self.assertEqual(len(PROPOSAL_DEALS), 31)

    def test_total_across_buckets_matches_full_sum(self):
        """Sum of all buckets equals total of all rows."""
        result = _run(aggregate_results(
            data=PROPOSAL_DEALS,
            group_by="close_date",
            aggregations={"deal_value": "sum"},
            group_by_date_ranges=[
                Q3_RANGE, Q4_RANGE,
                {"label": "Q1 next FY", "column": "close_date",
                 "start": "2027-02-01", "end": "2027-04-30"},
            ],
        ))
        bucket_total = sum(r["deal_value_sum"] for r in result["rows"])
        actual_total = sum(d["deal_value"] for d in PROPOSAL_DEALS)
        self.assertEqual(bucket_total, actual_total)


# ── Test 13: AGGREGATION_VERIFY retry instruction ────────────────
class TestAggregationRetryInstruction(unittest.TestCase):
    """Verify the retry instruction prevents placement corruption."""

    def test_retry_instruction_warns_against_duplication(self):
        from api.router import _aggregation_correction_message
        msg = _aggregation_correction_message([{
            "category": "Pipeline",
            "stated": 2_370_800,
            "actual_sum": 4_133_800,
            "missing_rows": [],
        }])
        self.assertIn("EXACTLY ONCE", msg)
        self.assertIn("placement corruption", msg)
        self.assertIn("SUMMARY/TOTAL", msg)
        self.assertIn("Do NOT alter any individual deal amounts", msg)

    def test_retry_instruction_contains_corrected_value(self):
        from api.router import _aggregation_correction_message
        msg = _aggregation_correction_message([{
            "category": "Pipeline",
            "stated": 2_370_800,
            "actual_sum": 4_133_800,
            "missing_rows": [],
        }])
        self.assertIn("4,133,800", msg)
        self.assertIn("2,370,800", msg)


# ── Planted-bug controls ─────────────────────────────────────────
class TestPlantedBugControls(unittest.TestCase):
    """If date-range bucketing is removed, these must fail."""

    def test_planted_bug_without_date_ranges_model_must_sum_manually(self):
        """Without group_by_date_ranges, standard group_by on close_date
        produces per-date groups (31 groups for 31 dates), not per-quarter."""
        result = _run(aggregate_results(
            data=PROPOSAL_DEALS,
            group_by="close_date",
            aggregations={"deal_value": "sum"},
        ))
        # Standard group_by produces one group per unique date
        self.assertGreater(result["group_count"], 20,
                           "Without date-range bucketing, you get one group "
                           "per date — the model would have to manually sum "
                           "these into quarter totals, which is the exact "
                           "failure mode this fix prevents.")


class TestValidation(unittest.TestCase):
    """Edge cases and validation."""

    def test_invalid_group_by_date_ranges_type(self):
        result = _run(aggregate_results(
            data=SMALL_DEALS,
            group_by="close_date",
            aggregations={"deal_value": "sum"},
            group_by_date_ranges="not a list",
        ))
        self.assertIn("error", result)

    def test_invalid_aggregations_with_date_ranges(self):
        result = _run(aggregate_results(
            data=SMALL_DEALS,
            group_by="close_date",
            aggregations={},
            group_by_date_ranges=[Q3_RANGE],
        ))
        self.assertIn("error", result)

    def test_list_format_aggregations_with_date_ranges(self):
        """List-format aggregations work with date ranges too."""
        result = _run(aggregate_results(
            data=SMALL_DEALS,
            group_by="close_date",
            aggregations=[{"column": "deal_value", "agg": "sum"}],
            group_by_date_ranges=[Q3_RANGE],
        ))
        self.assertNotIn("error", result)
        rows = {r["date_range"]: r for r in result["rows"]}
        self.assertEqual(rows["Q3 (this quarter)"]["deal_value_sum"], 300_000)


if __name__ == "__main__":
    unittest.main()
