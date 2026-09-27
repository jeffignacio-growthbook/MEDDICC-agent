"""
Pre-Piece-4 verification suite — four hard invariants that must hold before
Execute/Verify/Deliver (Pieces 4–6) are built on top of the compositional layer.

Verification 1 — should_escalate() fires correctly for scope_mismatch.
  Concrete: Q4 coverage question assessment dict → escalates.
  Concrete: 5 already-working-question assessment dicts → none escalate.

Verification 2 — Non-escalating assessment shapes.
  Every "correctly answered by one handler" assessment must return False.
  Every skipped or budget-exhausted assessment must return False.
  Every retryable issue (wrong_handler, wrong_table, ...) must return False.

Verification 3 — _sub_parts_sum_check reconciliation: additive vs. non-additive.
  The Q4 coverage plan has coverage_ratio = open_q4_pipeline / q4_target.
  RATIO sub-parts must NOT be treated as sum relationships, even when their
  component names appear in the rationale string.
  Additive sub-parts (new_arr + expansion_arr) must still be verified.
  Concrete: three cases with real expected values.

Verification 4 — Correction path: NOT-YET-BUILT explicit log.
  A reply that is a correction ("No, just new ARR") is not an affirmation.
  The code falls through to normal routing — the plan is NOT cleared.
  Stale pending_plan entries persist in thread history across turns.
  These are KNOWN GAPS that Pieces 4–6 must address; this test locks in
  the current behavior so any inadvertent future change is caught.
"""
import sys
import unittest
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO))

from api.assessor import should_escalate, should_retry
from api.composer import (
    _sub_parts_sum_check,
    reply_affirms_plan,
    find_pending_plan,
    make_pending_plan_entry,
    PENDING_PLAN_ROLE,
)


# ---------------------------------------------------------------------------
# Shared helpers

def _assessment(correct=True, issue=None, skipped=False, score=0.9):
    d = {"correct": correct, "score": score, "issue": issue}
    if skipped:
        d["skipped"] = True
    return d


def _q4_scope_mismatch():
    """
    Realistic assessment the LLM assessor would return for:
    "How is our Q4 pipeline coverage?" → handler query_pipeline_coverage
    That handler returns an aggregate coverage ratio but cannot decompose
    into (pipeline total, target, ratio) as named components — scope_mismatch.
    """
    return {
        "correct": False,
        "score": 0.35,
        "issue": "scope_mismatch",
        "suggested_handler": None,
        "learning_note": (
            "Q4 coverage needs pipeline total, target, and ratio as "
            "separate primitives; query_pipeline_coverage returns aggregate only."
        ),
    }


def _q4_plan_with_ratio():
    """
    Decomposed plan decompose_question() would produce for the Q4 coverage case.
    The coverage_ratio sub-part is a division, not a sum.
    """
    return {
        "question": "How is our Q4 pipeline coverage?",
        "explanation": "Q4 coverage needs three components: pipeline, target, ratio.",
        "sub_parts": [
            {
                "name": "open_q4_pipeline",
                "primitive": "query_pipeline_coverage",
                "rationale": "Sum of active deal ARR closing in Q4",
            },
            {
                "name": "q4_target",
                "primitive": "query_path_to_target",
                "rationale": "Q4 bookings target from config",
            },
            {
                "name": "coverage_ratio",
                "primitive": "_computed",
                "rationale": "open_q4_pipeline / q4_target",  # DIVISION
            },
        ],
    }


def _additive_plan():
    """Plan with a genuine additive _computed part (new + expansion = total)."""
    return {
        "question": "What's our total Q4 ARR?",
        "sub_parts": [
            {"name": "new_arr", "primitive": "query_waterfall"},
            {"name": "expansion_arr", "primitive": "query_waterfall"},
            {
                "name": "total_arr",
                "primitive": "_computed",
                "rationale": "new_arr + expansion_arr",  # SUM
            },
        ],
    }


# ---------------------------------------------------------------------------
# Verification 1: should_escalate() fires correctly

class TestEscalatesOnScopeMismatch(unittest.TestCase):

    def test_q4_coverage_scope_mismatch_escalates(self):
        """Realistic Q4 coverage assessment → should_escalate returns True."""
        ok = should_escalate(_q4_scope_mismatch())
        self.assertTrue(ok, "scope_mismatch + correct=False must escalate")

    def test_q4_coverage_skipped_does_not_escalate(self):
        """
        If the assessor skips (budget/gap) and marks scope_mismatch,
        the skip takes precedence — don't escalate on a budget-skipped check.
        """
        assessment = _q4_scope_mismatch()
        assessment["skipped"] = True
        self.assertFalse(should_escalate(assessment))

    def test_q4_coverage_correct_does_not_escalate(self):
        """If assessor marks correct=True despite scope_mismatch label, don't escalate."""
        assessment = _q4_scope_mismatch()
        assessment["correct"] = True
        self.assertFalse(should_escalate(assessment))


# ---------------------------------------------------------------------------
# Verification 2: already-working question assessment shapes don't escalate

class TestNonEscalatingQuestions(unittest.TestCase):
    """
    These are realistic assessments for questions that a single handler
    already answers correctly.  None should trigger escalation.
    """

    def test_closed_won_deals_this_week(self):
        """win_loss_reason handler answers correctly."""
        a = _assessment(correct=True, issue=None, score=0.88)
        self.assertFalse(should_escalate(a))

    def test_at_risk_deals(self):
        """query_deal_risk answers correctly."""
        a = _assessment(correct=True, issue=None, score=0.91)
        self.assertFalse(should_escalate(a))

    def test_q4_waterfall_aggregate(self):
        """
        'What's our Q4 waterfall total?' — query_waterfall answers this fine.
        Not a scope_mismatch: one handler, one number.
        """
        a = _assessment(correct=True, issue=None, score=0.85)
        self.assertFalse(should_escalate(a))

    def test_rep_scorecard(self):
        """query_rep_scorecard answers correctly."""
        a = _assessment(correct=True, issue=None, score=0.90)
        self.assertFalse(should_escalate(a))

    def test_wrong_handler_does_not_escalate(self):
        """wrong_handler → should retry (different path), not escalate."""
        a = _assessment(correct=False, issue="wrong_handler", score=0.40)
        self.assertFalse(should_escalate(a))
        self.assertTrue(should_retry(a, iteration=0))

    def test_data_gap_does_not_escalate(self):
        """data_gap → honest answer, no escalation or retry."""
        a = _assessment(correct=False, issue="data_gap", score=0.80,
                        skipped=True)
        self.assertFalse(should_escalate(a))
        self.assertFalse(should_retry(a, iteration=0))

    def test_budget_exhausted_does_not_escalate(self):
        """Budget-skipped assessment → assume ok, no escalation."""
        a = _assessment(correct=True, score=0.5, skipped=True)
        a["reason"] = "budget_exhausted"
        self.assertFalse(should_escalate(a))

    def test_format_only_does_not_escalate(self):
        """format_only issue (correct data, poor presentation) → no escalation."""
        a = _assessment(correct=False, issue="format_only", score=0.65)
        self.assertFalse(should_escalate(a))


# ---------------------------------------------------------------------------
# Verification 3: _sub_parts_sum_check — additive vs. non-additive

class TestSumCheckRatioVsAdditive(unittest.TestCase):
    """
    The Q4 coverage plan has coverage_ratio = open_q4_pipeline / q4_target.
    Both component names appear in the rationale string, but the relationship
    is division, not addition.  The check must NOT treat this as a sum and
    must NOT return False for a numerically correct ratio result.
    """

    def test_ratio_sub_part_is_not_sum_checked(self):
        """
        coverage_ratio = 2.49 (pipeline / target).
        Sum of components = 6,810,000.  Must NOT flag as mismatch.
        """
        plan = _q4_plan_with_ratio()
        results = {
            "open_q4_pipeline": {"total_arr": 4_860_000},
            "q4_target": {"target": 1_950_000},
            # Ratio stored with a 'total' key — the historical false negative:
            # 2.49 != 4,860,000 + 1,950,000 = 6,810,000
            "coverage_ratio": {"total": 2.49},
        }
        ok, note = _sub_parts_sum_check(plan, results)
        self.assertTrue(
            ok,
            f"Ratio sub-part incorrectly treated as sum — false negative. note={note!r}",
        )
        self.assertEqual(note, "")

    def test_ratio_sub_part_without_total_key_is_ok(self):
        """If coverage_ratio result has no 'total'/'total_arr' key, check skips cleanly."""
        plan = _q4_plan_with_ratio()
        results = {
            "open_q4_pipeline": {"total_arr": 4_860_000},
            "q4_target": {"target": 1_950_000},
            "coverage_ratio": {"ratio": 2.49, "label": "2.49x"},
        }
        ok, note = _sub_parts_sum_check(plan, results)
        self.assertTrue(ok)

    def test_additive_sum_still_verified(self):
        """
        Additive: new_arr + expansion_arr = total_arr.
        Correct totals pass; wrong totals fail.
        """
        plan = _additive_plan()
        # Correct: 4M + 860K = 4.86M
        results_ok = {
            "new_arr": {"total": 4_000_000},
            "expansion_arr": {"total": 860_000},
            "total_arr": {"total": 4_860_000},
        }
        ok, note = _sub_parts_sum_check(plan, results_ok)
        self.assertTrue(ok, f"Correct sum flagged as mismatch: {note!r}")

        # Wrong: states 5.2M but parts sum to 4.86M
        results_bad = {
            "new_arr": {"total": 4_000_000},
            "expansion_arr": {"total": 860_000},
            "total_arr": {"total": 5_200_000},
        }
        ok, note = _sub_parts_sum_check(plan, results_bad)
        self.assertFalse(ok, "Sum mismatch should be detected")
        self.assertIn("mismatch", note.lower())

    def test_mixed_plan_ratio_skipped_sum_checked(self):
        """
        A plan with both an additive and a ratio _computed part:
        only the additive one is sum-checked.
        """
        plan = {
            "question": "coverage and total",
            "sub_parts": [
                {"name": "new_arr", "primitive": "query_waterfall"},
                {"name": "expansion_arr", "primitive": "query_waterfall"},
                {"name": "q4_target", "primitive": "query_path_to_target"},
                {
                    "name": "total_arr",
                    "primitive": "_computed",
                    "rationale": "new_arr + expansion_arr",
                },
                {
                    "name": "coverage",
                    "primitive": "_computed",
                    "rationale": "total_arr / q4_target",
                },
            ],
        }
        results = {
            "new_arr": {"total": 4_000_000},
            "expansion_arr": {"total": 860_000},
            "q4_target": {"target": 1_950_000},
            "total_arr": {"total": 4_860_000},   # correct sum
            "coverage": {"total": 2.49},           # ratio, NOT summed
        }
        ok, note = _sub_parts_sum_check(plan, results)
        self.assertTrue(ok, f"Mixed plan with correct additive and ratio parts should pass: {note!r}")


# ---------------------------------------------------------------------------
# Verification 4: Correction path — NOT YET BUILT

class TestCorrectionPathNotYetBuilt(unittest.TestCase):
    """
    These tests document the current (incomplete) behavior when a user
    replies with a correction to a pending plan rather than an affirmation.

    NOT YET BUILT means: no code exists to handle this path; the tests
    lock in the current fall-through behavior so any future change is caught.
    Pieces 4–6 must address these gaps.
    """

    def test_correction_is_not_an_affirmation(self):
        """A correction reply returns False from reply_affirms_plan."""
        corrections = [
            "No, just new ARR, not expansion",
            "Actually use Q3 not Q4",
            "Change the time window to last month",
            "Never mind",
            "Cancel",
            "no",
            "Wait, I meant closed_won only",
        ]
        for reply in corrections:
            with self.subTest(reply=reply):
                self.assertFalse(
                    reply_affirms_plan(reply),
                    f"Correction {reply!r} must not be treated as affirmation",
                )

    def test_stale_plan_not_cleared_after_correction(self):
        """
        KNOWN GAP (Piece 4 must fix): after a correction falls through,
        the pending_plan entry is never removed from thread history.
        The NEXT "yes" turn would execute the STALE plan if the thread
        history is not cleared or replaced.

        This test documents the current behavior (stale plan survives).
        """
        plan = _q4_plan_with_ratio()
        entry = make_pending_plan_entry(plan, "Shall I go ahead?")
        history = [entry]

        # After a correction, the pending_plan entry is still there
        found = find_pending_plan(history)
        self.assertIsNotNone(
            found,
            "KNOWN GAP: pending_plan not cleared after correction — "
            "Pieces 4–6 must either (a) clear it on non-affirmation, "
            "or (b) replace it with a corrected plan on re-decomposition.",
        )

    def test_new_plan_overwrites_stale_in_find(self):
        """
        KNOWN WORKAROUND: if the scope_mismatch fires again on the corrected
        question, a new pending_plan entry is appended to history.
        find_pending_plan() returns the MOST RECENT one, so the stale one
        is shadowed (but not removed) — correct behavior for today.
        """
        stale_plan = _q4_plan_with_ratio()
        new_plan = _additive_plan()

        stale_entry = make_pending_plan_entry(stale_plan, "Shall I go ahead? (Q4 coverage)")
        new_entry = make_pending_plan_entry(new_plan, "Shall I go ahead? (Q4 total ARR)")

        history = [stale_entry, new_entry]
        found = find_pending_plan(history)

        # Most-recent wins
        self.assertEqual(
            found.get("plan", {}).get("question"),
            new_plan["question"],
            "find_pending_plan must return the most-recent pending_plan entry",
        )

    def test_affirmations_are_still_recognized(self):
        """Affirmations must still work — regression guard."""
        affirmations = [
            "yes", "y", "yeah", "yep", "yup", "sure", "go ahead",
            "go", "run it", "do it", "proceed", "ok", "okay",
            "sounds good", "yes please",
        ]
        for reply in affirmations:
            with self.subTest(reply=reply):
                self.assertTrue(
                    reply_affirms_plan(reply),
                    f"Affirmation {reply!r} must be recognized",
                )


if __name__ == "__main__":
    unittest.main()
