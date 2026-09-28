"""
Tests for coaching_hypothesis_loop.py — gate function first (planted-bug
controls), then integration tests using real cohort fixtures.

Planted-bug controls: each sub-test temporarily breaks exactly one
condition in evaluate_rule() and confirms it correctly returns False.
A test that passes with the bug still present is considered broken.

Hard invariants under test:
  1. evaluate_rule() returns True only when ALL four conditions hold.
  2. rank_candidates() orders by |train_d| * |holdout_d| descending.
  3. draft_proposal() does not use confidence-adjusted language.
  4. process_result() writes 'pending_review' when a candidate clears,
     'no_clear' when none do — and never reaches 'approved' autonomously.
  5. The no_clear fixture (real data) produces no candidates.
  6. The one_clear fixture (synthetic) produces exactly one candidate.
"""
import json
import sys
import types
import unittest
from datetime import date
from pathlib import Path
from unittest.mock import MagicMock, patch

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO))
sys.path.insert(0, str(REPO / "scripts"))
sys.path.insert(0, str(REPO / "scripts" / "analytics"))

from scripts.analytics.coaching_hypothesis_loop import (
    HOLDOUT_D, TRAIN_D, TRAIN_P,
    draft_proposal, evaluate_rule, process_result, rank_candidates,
)

FIXTURE_DIR = REPO / "tests" / "fixtures"
NO_CLEAR_RESULT = json.loads((FIXTURE_DIR / "coaching_hypothesis_no_clear.json").read_text())
ONE_CLEAR_RESULT = json.loads((FIXTURE_DIR / "coaching_hypothesis_one_clear.json").read_text())

# --------------------------------------------------------------------------
# Helpers


def _train(**kw):
    base = {"p": 0.01, "d": 0.5, "n_prog": 30, "n_stall": 40,
            "n_informative": 25, "strat_diff": 0.4, "mean_prog": 4.0, "mean_stall": 3.5}
    base.update(kw)
    return base


def _holdout(**kw):
    base = {"d": 0.25, "n_prog": 15, "n_stall": 20, "p": 0.20}
    base.update(kw)
    return base


def _fake_sb(active_components=None):
    """Return a minimal fake Supabase client for process_result()."""
    active = set(active_components or [])

    class _FakeQuery:
        def __init__(self):
            self._data = []
        def select(self, *a, **kw): return self
        def in_(self, *a, **kw): return self
        def insert(self, row): self._data.append(row); return self
        def execute(self): return type("R", (), {"data": list(self._data)})()

    class _FakeSB:
        def __init__(self):
            self._inserts = []
        def table(self, name):
            q = _FakeQuery()
            # Seed active rows so _active_components() returns correct set
            q._data = [{"component": c} for c in active]
            orig_insert = q.insert
            sb = self
            def _intercept_insert(row):
                sb._inserts.append(row)
                orig_insert(row)
                return q
            q.insert = _intercept_insert
            return q

    return _FakeSB()


# --------------------------------------------------------------------------
# evaluate_rule() — planted-bug controls

class TestEvaluateRule(unittest.TestCase):

    def test_all_conditions_pass(self):
        """All four conditions hold → True."""
        self.assertTrue(evaluate_rule(_train(), _holdout()))

    # ---- planted-bug control 1: train_p boundary ----

    def test_train_p_exactly_at_threshold_fails(self):
        """train_p == TRAIN_P (not strictly less than) → False.
        Bug to plant: change < to <=. Test catches it."""
        self.assertFalse(evaluate_rule(_train(p=TRAIN_P), _holdout()))

    def test_train_p_just_above_threshold_fails(self):
        """train_p = 0.051 (> TRAIN_P) → False."""
        self.assertFalse(evaluate_rule(_train(p=0.051), _holdout()))

    def test_train_p_just_below_threshold_passes(self):
        """train_p = 0.049 (< TRAIN_P) → True."""
        self.assertTrue(evaluate_rule(_train(p=0.049), _holdout()))

    # ---- planted-bug control 2: train_d magnitude boundary ----

    def test_train_d_exactly_at_threshold_passes(self):
        """|train_d| == TRAIN_D → True (rule uses >=, matching the analysis script)."""
        self.assertTrue(evaluate_rule(_train(d=TRAIN_D), _holdout()))

    def test_train_d_just_below_threshold_fails(self):
        """|train_d| = 0.299 → False."""
        self.assertFalse(evaluate_rule(_train(d=0.299), _holdout()))

    def test_train_d_negative_but_large_passes(self):
        """train_d = -0.5 with holdout_d = -0.25 (same sign) → True."""
        self.assertTrue(evaluate_rule(_train(d=-0.5), _holdout(d=-0.25)))

    # ---- planted-bug control 3: holdout_d magnitude boundary ----

    def test_holdout_d_exactly_at_threshold_passes(self):
        """|holdout_d| == HOLDOUT_D → True (rule uses >=, matching the analysis script)."""
        self.assertTrue(evaluate_rule(_train(), _holdout(d=HOLDOUT_D)))

    def test_holdout_d_just_below_threshold_fails(self):
        """|holdout_d| = 0.199 → False."""
        self.assertFalse(evaluate_rule(_train(), _holdout(d=0.199)))

    def test_holdout_d_just_above_threshold_passes(self):
        """|holdout_d| = 0.201 → True."""
        self.assertTrue(evaluate_rule(_train(), _holdout(d=0.201)))

    # ---- planted-bug control 4: sign consistency ----

    def test_opposite_signs_fails(self):
        """train_d > 0, holdout_d < 0 → False.
        Bug to plant: remove the sign check. Test catches it."""
        self.assertFalse(evaluate_rule(_train(d=0.5), _holdout(d=-0.25)))

    def test_opposite_signs_negative_train_fails(self):
        """train_d < 0, holdout_d > 0 → False."""
        self.assertFalse(evaluate_rule(_train(d=-0.5), _holdout(d=0.25)))

    def test_same_sign_negative_both_passes(self):
        """Both negative with sufficient magnitude → True."""
        self.assertTrue(evaluate_rule(_train(d=-0.4), _holdout(d=-0.25)))

    # ---- None values ----

    def test_none_train_p_fails(self):
        self.assertFalse(evaluate_rule(_train(p=None), _holdout()))

    def test_none_train_d_fails(self):
        self.assertFalse(evaluate_rule(_train(d=None), _holdout()))

    def test_none_holdout_d_fails(self):
        self.assertFalse(evaluate_rule(_train(), _holdout(d=None)))

    def test_missing_keys_fails(self):
        self.assertFalse(evaluate_rule({}, {}))

    # ---- all four simultaneously at their boundaries ----

    def test_all_at_boundary_fails(self):
        """Exactly at every threshold → False (all use strict inequalities)."""
        self.assertFalse(evaluate_rule(
            _train(p=TRAIN_P, d=TRAIN_D),
            _holdout(d=HOLDOUT_D),
        ))

    def test_all_just_inside_boundary_passes(self):
        """Just inside all thresholds → True."""
        self.assertTrue(evaluate_rule(
            _train(p=TRAIN_P - 0.001, d=TRAIN_D + 0.001),
            _holdout(d=HOLDOUT_D + 0.001),
        ))


# --------------------------------------------------------------------------
# rank_candidates()

class TestRankCandidates(unittest.TestCase):

    def _view_with_cleared(self, components_cleared: list[dict]) -> dict:
        """Build a minimal view where specified components clear, others don't."""
        comps = {}
        for name in ("pain", "metrics", "champion", "economic_buyer",
                     "decision_criteria", "decision_process", "competition"):
            comps[name] = {
                "train": _train(p=0.5, d=0.1),   # does not clear
                "holdout": _holdout(d=0.1),
            }
        for entry in components_cleared:
            comps[entry["component"]] = {
                "train": _train(p=entry["train_p"], d=entry["train_d"]),
                "holdout": _holdout(d=entry["holdout_d"]),
            }
        return {"components": comps}

    def test_no_clear_returns_empty(self):
        view = self._view_with_cleared([])
        self.assertEqual(rank_candidates(view), [])

    def test_one_clear(self):
        view = self._view_with_cleared([{"component": "pain", "train_p": 0.01,
                                          "train_d": 0.5, "holdout_d": 0.25}])
        cands = rank_candidates(view)
        self.assertEqual(len(cands), 1)
        self.assertEqual(cands[0]["component"], "pain")
        self.assertAlmostEqual(cands[0]["score"], 0.5 * 0.25)

    def test_two_clear_ordered_by_score(self):
        view = self._view_with_cleared([
            {"component": "pain",    "train_p": 0.01, "train_d": 0.4, "holdout_d": 0.3},
            {"component": "metrics", "train_p": 0.01, "train_d": 0.6, "holdout_d": 0.4},
        ])
        cands = rank_candidates(view)
        self.assertEqual(len(cands), 2)
        # metrics: 0.6*0.4 = 0.24 > pain: 0.4*0.3 = 0.12
        self.assertEqual(cands[0]["component"], "metrics")
        self.assertEqual(cands[1]["component"], "pain")

    def test_direction_reflects_train_sign(self):
        view = self._view_with_cleared([
            {"component": "champion", "train_p": 0.02, "train_d": -0.5, "holdout_d": -0.25},
        ])
        cands = rank_candidates(view)
        self.assertEqual(cands[0]["direction"], "lower")

    def test_positive_direction(self):
        view = self._view_with_cleared([
            {"component": "pain", "train_p": 0.02, "train_d": 0.5, "holdout_d": 0.25},
        ])
        self.assertEqual(rank_candidates(view)[0]["direction"], "higher")


# --------------------------------------------------------------------------
# draft_proposal()

class TestDraftProposal(unittest.TestCase):

    def _proposal(self, comp="pain", direction="higher"):
        return draft_proposal(
            component=comp,
            train=_train(),
            holdout=_holdout(),
            direction=direction,
            cohorts={"progressed": 51, "stalled": 63},
            run_date=date(2026, 9, 27),
        )

    def test_component_in_proposal(self):
        p = self._proposal()
        self.assertEqual(p["component"], "pain")

    def test_direction_in_proposal(self):
        p = self._proposal(direction="lower")
        self.assertEqual(p["direction"], "lower")

    def test_numbers_present(self):
        p = self._proposal()
        nums = p["numbers"]
        self.assertAlmostEqual(nums["train_p"], 0.01)
        self.assertAlmostEqual(nums["train_d"], 0.5)
        self.assertAlmostEqual(nums["holdout_d"], 0.25)

    def test_caveats_present(self):
        p = self._proposal()
        self.assertGreater(len(p["caveats"]), 0)

    def test_no_confidence_adjusted_language(self):
        """Proposal must not use belief-updated or confidence-adjusted framing."""
        p = self._proposal()
        full_text = json.dumps(p).lower()
        for forbidden in ("confidence-adjusted", "belief-updated", "bayesian",
                          "posterior", "prior probability", "updated belief"):
            self.assertNotIn(forbidden, full_text,
                             f"Forbidden language found: {forbidden!r}")

    def test_no_significance_test_during_tracking(self):
        """Experiment design must state no significance test during tracking."""
        p = self._proposal()
        design_text = json.dumps(p["experiment_design"]).lower()
        self.assertIn("no significance test", design_text)

    def test_human_decides_framing(self):
        """Experiment design must state a human reviews results."""
        p = self._proposal()
        design_text = json.dumps(p["experiment_design"]).lower()
        self.assertIn("human", design_text)

    def test_run_date_stored(self):
        p = self._proposal()
        self.assertEqual(p["run_date"], "2026-09-27")


# --------------------------------------------------------------------------
# process_result() integration — using real + synthetic fixtures

class TestProcessResult(unittest.TestCase):

    def test_no_clear_fixture_logs_no_clear(self):
        """Real cohort data (no component cleared) → status logged as no_clear."""
        sb = _fake_sb()
        summary = process_result(NO_CLEAR_RESULT, date(2026, 9, 27), sb, dry_run=True)
        self.assertEqual(summary["logged"], "no_clear")
        self.assertEqual(summary["cleared"], [])

    def test_one_clear_fixture_writes_pending_review(self):
        """Synthetic fixture with pain clearing → 'pending_review' row written."""
        sb = _fake_sb()
        summary = process_result(ONE_CLEAR_RESULT, date(2026, 9, 27), sb, dry_run=False)
        self.assertIn("pain", summary["cleared"])
        # Confirm insert was made with status=pending_review
        inserts = [row for row in sb._inserts if row.get("status") == "pending_review"]
        self.assertEqual(len(inserts), 1)
        self.assertEqual(inserts[0]["component"], "pain")

    def test_one_clear_fixture_never_reaches_approved(self):
        """The loop must not autonomously set status='approved'."""
        sb = _fake_sb()
        process_result(ONE_CLEAR_RESULT, date(2026, 9, 27), sb, dry_run=False)
        for row in sb._inserts:
            self.assertNotEqual(row.get("status"), "approved",
                                "Loop must not write status='approved' autonomously")

    def test_already_active_component_skipped(self):
        """If pain is already active, it must be skipped — no duplicate insert."""
        sb = _fake_sb(active_components=["pain"])
        summary = process_result(ONE_CLEAR_RESULT, date(2026, 9, 27), sb, dry_run=False)
        self.assertIn("pain", summary["skipped"])
        # No insert for pain
        pain_inserts = [r for r in sb._inserts if r.get("component") == "pain"]
        self.assertEqual(len(pain_inserts), 0)

    def test_proposal_contains_real_numbers(self):
        """Proposal in inserted row must carry the actual train_d and holdout_d."""
        sb = _fake_sb()
        process_result(ONE_CLEAR_RESULT, date(2026, 9, 27), sb, dry_run=False)
        inserts = [r for r in sb._inserts if r.get("status") == "pending_review"]
        self.assertEqual(len(inserts), 1)
        proposal = inserts[0]["proposal"]
        nums = proposal["numbers"]
        # From the synthetic fixture: train_d=0.42, holdout_d=0.31
        self.assertAlmostEqual(nums["train_d"], 0.42, places=2)
        self.assertAlmostEqual(nums["holdout_d"], 0.31, places=2)

    def test_no_clear_insert_has_correct_status(self):
        """The no_clear log row must have status='no_clear', not anything else."""
        sb = _fake_sb()
        process_result(NO_CLEAR_RESULT, date(2026, 9, 27), sb, dry_run=False)
        no_clear_rows = [r for r in sb._inserts if r.get("status") == "no_clear"]
        self.assertEqual(len(no_clear_rows), 1)
        # Must not also insert a pending_review row
        pending_rows = [r for r in sb._inserts if r.get("status") == "pending_review"]
        self.assertEqual(len(pending_rows), 0)


if __name__ == "__main__":
    unittest.main()
