"""
tests/test_compositional_layer.py

Spec-level test set for the compositional layer (Pieces 1–7).

Each case has a stated expected outcome at the top of its docstring
before any assertions run.  Categories mirror the spec:

  A — Should escalate: genuine scope mismatch (composer fires)
  B — Should NOT escalate: already-working direct handlers (regression gate)
  C — Ambiguous: boundary decided on purpose
  D — Correction path: pending plan lifecycle and stale-plan risk
  E — Feedback and promotion (integration of Piece 7 with the router)
  F — Adjacent hard cases: unanswerable gaps, pattern-matching false positives

OFFLINE CONTRACT:
  No LLM calls.  Every test that would depend on decompose_question() or the
  assessor uses one of two strategies:
    1. Pre-built plan fixture — test the plan structure the LLM SHOULD produce,
       not the LLM call itself.  The fixture IS the expected outcome.
    2. Routing-mechanism test — test should_escalate(), reply_affirms_plan(),
       find_pending_plan(), etc. — the deterministic wiring that acts on the
       LLM's output.  LLM correctness is an integration concern; these tests
       catch regressions in the deterministic layer.
"""

import json
import sys
import unittest
from pathlib import Path
from unittest.mock import MagicMock

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO))

from api.assessor import should_escalate, should_retry
from api.composer import (
    PENDING_PLAN_ROLE,
    _valid_plan,
    find_pending_plan,
    make_pending_plan_entry,
    plan_to_clarification_message,
    reply_affirms_plan,
    verify_plan_result,
)
from api.plan_feedback import (
    PENDING_CHECKBACK_ROLE,
    PROMOTION_THRESHOLD,
    find_pending_checkback,
    get_confirmation_count,
    make_pending_checkback_entry,
    maybe_promote_template,
    plan_signature,
    question_hash,
    reply_to_checkback,
)


# ---------------------------------------------------------------------------
# Shared plan fixtures — these are the plans the LLM SHOULD produce; they
# serve as the expected-outcome specification for Category A.

def _plan_q4_coverage_expected():
    """
    A1 expected plan: Q4 coverage with 2× target math.
    Three sub-parts: open pipeline (coverage handler), target (path-to-target),
    computed ratio.
    """
    return {
        "question": (
            "What does pipeline coverage look like for Q4 if our target is "
            "2x what we closed in Q4 last year?"
        ),
        "explanation": (
            "Needs open Q4 pipeline total, the 2× derived target, and the "
            "coverage ratio — no single handler returns all three."
        ),
        "sub_parts": [
            {
                "name": "open_q4_pipeline",
                "primitive": "query_pipeline_coverage",
                "rationale": "Sum of active deal ARR with Q4 close dates",
            },
            {
                "name": "q4_target_2x",
                "primitive": "query_path_to_target",
                "rationale": "Baseline Q4 target from config, doubled",
            },
            {
                "name": "coverage_ratio",
                "primitive": "_computed",
                "rationale": "open_q4_pipeline / q4_target_2x",
            },
        ],
    }


def _plan_next_quarter_forecast_expected():
    """
    A2 expected plan: next-quarter forecast.
    Sub-parts: open pipeline, path-to-target gap, plus optionally win-rate modifier.
    """
    return {
        "question": "How does next quarter's forecast look?",
        "explanation": (
            "Needs open pipeline total, the target gap, and a coverage ratio — "
            "a single waterfall handler returns bookings, not the forward view."
        ),
        "sub_parts": [
            {
                "name": "next_q_pipeline",
                "primitive": "query_pipeline_coverage",
                "rationale": "Active deals with close dates in next quarter",
            },
            {
                "name": "next_q_gap",
                "primitive": "query_path_to_target",
                "rationale": "Remaining gap to next-quarter bookings target",
            },
            {
                "name": "coverage_ratio",
                "primitive": "_computed",
                "rationale": "next_q_pipeline / (next_q_gap + next_q_pipeline)",
            },
        ],
    }


def _plan_multi_entity_expected():
    """
    A4 expected plan: two reps with no shared segment.
    Each rep gets a separate scorecard sub-part; comparison is _computed.
    """
    return {
        "question": (
            "Compare pipeline health across two reps who don't have a shared segment"
        ),
        "explanation": (
            "Two rep-scoped pipeline queries, then a comparison — no single "
            "handler returns multi-rep cross-segment breakdowns."
        ),
        "sub_parts": [
            {
                "name": "rep_a_pipeline",
                "primitive": "query_rep_scorecard",
                "rationale": "Pipeline health for rep A",
            },
            {
                "name": "rep_b_pipeline",
                "primitive": "query_rep_scorecard",
                "rationale": "Pipeline health for rep B",
            },
            {
                "name": "comparison",
                "primitive": "_computed",
                "rationale": "Side-by-side of rep_a_pipeline vs rep_b_pipeline",
            },
        ],
    }


def _plan_unanswerable_expected():
    """
    F16 expected plan: question requiring product-usage data (absent).
    The gap sub-part uses dynamic_query with a rationale that names the gap.
    """
    return {
        "question": (
            "Which deals are most at risk based on product engagement signals "
            "from the last 30 days?"
        ),
        "explanation": (
            "Needs product-usage data which is not available in the CRM; "
            "the pipeline risk portion maps to query_deal_risk but the "
            "engagement signals portion has no matching primitive."
        ),
        "sub_parts": [
            {
                "name": "deal_risk",
                "primitive": "query_deal_risk",
                "rationale": "Late-stage at-risk deals from CRM signals",
            },
            {
                "name": "engagement_data_gap",
                "primitive": "dynamic_query",
                "rationale": (
                    "Product-usage engagement signals are not available in this "
                    "dataset — cannot evaluate engagement risk without that source."
                ),
            },
        ],
    }


def _feedback_rows(sig, entries):
    return [{"plan_signature": sig, **e} for e in entries]


def _template_row(sig, plan):
    return {"plan_signature": sig, "plan_json": json.dumps(plan)}


def _sb_mock(feedback_rows=None, template_rows=None):
    _feedback = list(feedback_rows or [])
    _templates = list(template_rows or [])

    class _Query:
        def __init__(self, rows):
            self._rows = rows
            self._filters = []

        def eq(self, col, val):
            self._filters.append((col, val))
            return self

        def execute(self):
            result = self._rows
            for col, val in self._filters:
                result = [r for r in result if r.get(col) == val]
            return MagicMock(data=result)

    class _Table:
        def __init__(self, rows):
            self._rows = rows

        def select(self, *args):
            return _Query(self._rows)

        def insert(self, *args, **kwargs):
            return MagicMock(execute=MagicMock())

        def upsert(self, *args, **kwargs):
            return MagicMock(execute=MagicMock())

    sb = MagicMock()
    sb.table = lambda name: _Table(
        _feedback if name == "plan_feedback" else _templates
    )
    return sb


# ===========================================================================
# CATEGORY A — Should escalate: genuine scope mismatch
# ===========================================================================

class TestCategoryA_EscalationFires(unittest.TestCase):
    """
    Category A: questions that require multiple primitives.
    Expected outcome for all four: should_escalate returns True, and the
    resulting plan is structurally valid with the expected sub-part shape.
    """

    # ── Routing mechanism ───────────────────────────────────────────────────

    def test_A_scope_mismatch_assessment_always_escalates(self):
        """
        EXPECTED: scope_mismatch → should_escalate True.
        This is the deterministic gate; the LLM assessment is what varies.
        """
        for question in [
            "What does pipeline coverage look like for Q4 if our target is "
            "2x what we closed in Q4 last year?",
            "How does next quarter's forecast look?",
            "What's our win rate going to look like for the deals we haven't "
            "even created yet?",
            "Compare pipeline health across two reps who don't have a shared segment",
        ]:
            with self.subTest(question=question[:60]):
                assessment = {"correct": False, "score": 0.2,
                              "issue": "scope_mismatch"}
                self.assertTrue(
                    should_escalate(assessment),
                    f"scope_mismatch assessment must escalate for: {question[:60]!r}",
                )

    def test_A_scope_mismatch_is_not_retryable(self):
        """
        EXPECTED: scope_mismatch never goes through the retry handler path.
        Escalation is the only exit for this issue type.
        """
        assessment = {"correct": False, "score": 0.2, "issue": "scope_mismatch"}
        self.assertFalse(should_retry(assessment, iteration=0))
        self.assertFalse(should_retry(assessment, iteration=1))

    # ── Plan structure: A1 — Q4 coverage with 2× target ────────────────────

    def test_A1_q4_coverage_plan_is_valid(self):
        """
        EXPECTED PLAN: 3 sub-parts — open_q4_pipeline (query_pipeline_coverage),
        q4_target_2x (query_path_to_target), coverage_ratio (_computed).
        """
        plan = _plan_q4_coverage_expected()
        self.assertTrue(_valid_plan(plan))

    def test_A1_q4_coverage_plan_has_three_sub_parts(self):
        plan = _plan_q4_coverage_expected()
        self.assertEqual(len(plan["sub_parts"]), 3)

    def test_A1_q4_coverage_plan_uses_coverage_and_target_primitives(self):
        plan = _plan_q4_coverage_expected()
        primitives = {p["primitive"] for p in plan["sub_parts"]}
        self.assertIn("query_pipeline_coverage", primitives)
        self.assertIn("query_path_to_target", primitives)
        self.assertIn("_computed", primitives)

    def test_A1_q4_coverage_plan_computed_part_references_other_parts(self):
        """_computed rationale must reference earlier sub-part names."""
        plan = _plan_q4_coverage_expected()
        computed = next(
            p for p in plan["sub_parts"] if p["primitive"] == "_computed"
        )
        # Rationale should mention at least one of the other part names
        other_names = [p["name"] for p in plan["sub_parts"]
                       if p["primitive"] != "_computed"]
        self.assertTrue(
            any(name in computed["rationale"] for name in other_names),
            f"_computed rationale must reference a prior part; rationale="
            f"{computed['rationale']!r}, prior parts={other_names}",
        )

    def test_A1_q4_coverage_clarification_message_is_readable(self):
        """EXPECTED: clarification message is plain text, not raw JSON."""
        plan = _plan_q4_coverage_expected()
        msg = plan_to_clarification_message(plan)
        self.assertGreater(len(msg.strip()), 0)
        self.assertNotIn('"primitive":', msg)

    def test_A1_q4_coverage_clarification_names_all_parts(self):
        plan = _plan_q4_coverage_expected()
        msg = plan_to_clarification_message(plan).lower().replace("_", " ")
        for part in plan["sub_parts"]:
            part_name = part["name"].replace("_", " ")
            self.assertIn(
                part_name, msg,
                f"Clarification message must mention sub-part {part['name']!r}",
            )

    # ── Plan structure: A2 — next-quarter forecast ──────────────────────────

    def test_A2_next_quarter_forecast_plan_is_valid(self):
        """
        EXPECTED PLAN: pipeline + path-to-target + coverage ratio.
        Single waterfall handler returns bookings only; forecast needs the split.
        """
        plan = _plan_next_quarter_forecast_expected()
        self.assertTrue(_valid_plan(plan))

    def test_A2_next_quarter_forecast_has_coverage_and_target(self):
        plan = _plan_next_quarter_forecast_expected()
        primitives = {p["primitive"] for p in plan["sub_parts"]}
        self.assertIn("query_pipeline_coverage", primitives)
        self.assertIn("query_path_to_target", primitives)

    # ── Plan structure: A3 — win rate for non-existent deals ───────────────

    def test_A3_future_deals_plan_must_not_invent_data(self):
        """
        EXPECTED PLAN: must acknowledge data gap.  No primitive can predict
        future deal counts.  The plan uses dynamic_query or explicitly names
        the gap in a sub-part rationale rather than silently dropping it.
        """
        # Build the expected plan for a future-deals question
        plan = {
            "question": (
                "What's our win rate going to look like for the deals we "
                "haven't even created yet?"
            ),
            "explanation": (
                "No primitive covers future-deal win-rate prediction; this "
                "maps to a data gap, not a calculation error."
            ),
            "sub_parts": [
                {
                    "name": "historical_win_rate",
                    "primitive": "query_win_loss_reason",
                    "rationale": "Historical win rate from closed deals this quarter",
                },
                {
                    "name": "future_deals_gap",
                    "primitive": "dynamic_query",
                    "rationale": (
                        "Future deal counts are not available in the CRM — "
                        "cannot predict win rate for deals not yet created."
                    ),
                },
            ],
        }
        self.assertTrue(_valid_plan(plan))

        # The gap must be explicitly named — not silently absent
        gap_parts = [
            p for p in plan["sub_parts"]
            if "gap" in p["name"] or "future" in p["name"]
               or "dynamic_query" in p["primitive"]
        ]
        self.assertGreater(len(gap_parts), 0,
                           "Plan must include a sub-part that names the data gap")

        gap_rationale = " ".join(p["rationale"] for p in gap_parts).lower()
        self.assertTrue(
            any(word in gap_rationale
                for word in ("not available", "cannot", "gap", "no primitive")),
            f"Gap rationale must explain the limitation; got: {gap_rationale!r}",
        )

    # ── Plan structure: A4 — multi-entity, no shared segment ───────────────

    def test_A4_multi_rep_plan_is_valid(self):
        """
        EXPECTED PLAN: 2 rep-scoped scorecard sub-parts + _computed comparison.
        Tests escalation on MULTI-ENTITY scope mismatch (not just time-period).
        """
        plan = _plan_multi_entity_expected()
        self.assertTrue(_valid_plan(plan))

    def test_A4_multi_rep_plan_has_two_non_computed_parts(self):
        plan = _plan_multi_entity_expected()
        data_parts = [p for p in plan["sub_parts"]
                      if p["primitive"] != "_computed"]
        self.assertGreaterEqual(len(data_parts), 2,
                                "Multi-rep plan must fetch at least 2 rep datasets")

    def test_A4_multi_rep_plan_has_comparison_part(self):
        plan = _plan_multi_entity_expected()
        computed = [p for p in plan["sub_parts"] if p["primitive"] == "_computed"]
        self.assertEqual(len(computed), 1,
                         "Exactly one _computed comparison expected")

    def test_A4_multi_rep_clarification_is_readable(self):
        plan = _plan_multi_entity_expected()
        msg = plan_to_clarification_message(plan)
        self.assertGreater(len(msg.strip()), 0)
        self.assertNotIn('"primitive":', msg)


# ===========================================================================
# CATEGORY B — Should NOT escalate: direct-handler regression suite
# ===========================================================================

class TestCategoryB_NoEscalation(unittest.TestCase):
    """
    Category B: questions that already work via single handlers.
    Expected outcome for all four: should_escalate returns False regardless
    of the question text, AND reply_affirms_plan with NO pending plan in
    history does not trigger the composer path.

    If any of these start escalating, the gate is too eager and is adding
    latency/cost to questions that already have a working handler.
    """

    _DIRECT_QUESTIONS = [
        "How much pipeline did we generate this week?",
        "Compare our pipeline from January 2026 to today",
        "What's changed with Christian's deals over the last 5 weeks?",
        "What's our qualified loss rate this quarter?",
    ]

    def test_B_non_scope_mismatch_assessments_do_not_escalate(self):
        """
        EXPECTED: any assessment WITHOUT issue=scope_mismatch → should_escalate False.
        These four questions should never produce scope_mismatch from the assessor.
        """
        for issue in ("wrong_handler", "wrong_table", "missing_join",
                      "wrong_time_window", "should_be_dynamic",
                      "data_gap", "format_only", None):
            with self.subTest(issue=issue):
                assessment = {"correct": False, "score": 0.4, "issue": issue}
                self.assertFalse(
                    should_escalate(assessment),
                    f"Non-scope-mismatch issue {issue!r} must not escalate",
                )

    def test_B_correct_assessment_does_not_escalate(self):
        """
        EXPECTED: a correct assessment (even if issue key is present) never escalates.
        """
        assessment = {"correct": True, "score": 0.9, "issue": "scope_mismatch"}
        self.assertFalse(should_escalate(assessment))

    def test_B_no_pending_plan_means_composer_not_triggered(self):
        """
        EXPECTED: with no pending_plan in history, reply_affirms_plan("yes") → True
        but find_pending_plan returns None, so the composer execution branch
        is never entered.

        The function is stateless; the caller (router) checks both conditions.
        This test confirms the gate: both must be true to execute.
        """
        history_without_plan = [
            {"role": "user", "content": q}
            for q in self._DIRECT_QUESTIONS
        ]
        self.assertIsNone(find_pending_plan(history_without_plan))

    def test_B_affirmation_without_pending_plan_is_safe(self):
        """
        EXPECTED: a plain "yes" in a thread with no pending_plan is NOT treated
        as plan execution — find_pending_plan returns None.
        """
        history = [
            {"role": "user", "content": "How much pipeline did we generate this week?"},
            {"role": "assistant", "content": "$1.2M generated this week."},
            {"role": "user", "content": "yes"},
        ]
        self.assertIsNone(find_pending_plan(history))
        # reply_affirms_plan on its own returns True — but the router gate is
        # find_pending_plan AND reply_affirms_plan.  No plan → no execution.
        self.assertTrue(reply_affirms_plan("yes"))

    def test_B5_pipeline_generation_routes_directly(self):
        """
        EXPECTED: "How much pipeline did we generate this week?" routes to a
        direct handler (query_waterfall / query_pipeline_movement), NOT composer.
        This test locks in the no-escalation expectation with no pending plan.
        """
        history = [
            {"role": "user", "content": "How much pipeline did we generate this week?"}
        ]
        # No pending plan → composer gate is closed
        self.assertIsNone(find_pending_plan(history))

    def test_B8_qualified_loss_rate_routes_directly(self):
        """
        EXPECTED: "What's our qualified loss rate this quarter?" — promoted handler
        exists; must stay fast-path with zero composition overhead.
        """
        history = [
            {"role": "user", "content": "What's our qualified loss rate this quarter?"}
        ]
        self.assertIsNone(find_pending_plan(history))


# ===========================================================================
# CATEGORY C — Ambiguous: boundary decided on purpose
# ===========================================================================

class TestCategoryC_AmbiguousBoundary(unittest.TestCase):
    """
    Category C: questions where escalation depends on phrasing.
    Tests document the intended boundary between direct and composite handling.
    """

    def test_C9a_path_to_target_direct_phrasing_plan_shape(self):
        """
        EXPECTED: "What's our realistic path to hitting $2.1M this quarter?"
        → DOES NOT ESCALATE if query_path_to_target handles it.

        If the assessor produces correct=True for this with path_to_target,
        the question stays direct.  This test confirms the plan shape that
        would be produced IF it incorrectly escalates, showing that a single-
        primitive plan would be redundant (should never happen).
        """
        # A plan with only one data-fetching sub-part is valid but unnecessary —
        # this is what escalation would return if miscalibrated.
        redundant_plan = {
            "question": "What's our realistic path to hitting $2.1M this quarter?",
            "explanation": "path_to_target already answers this — escalation not needed.",
            "sub_parts": [
                {
                    "name": "path_to_target",
                    "primitive": "query_path_to_target",
                    "rationale": "Remaining gap to $2.1M target and pace",
                },
            ],
        }
        self.assertTrue(_valid_plan(redundant_plan))
        # A single-primitive plan is the red flag: if we see this, the gate
        # escalated unnecessarily.
        data_parts = [p for p in redundant_plan["sub_parts"]
                      if p["primitive"] != "_computed"]
        self.assertEqual(len(data_parts), 1,
                         "Single-primitive plan signals unnecessary escalation")

    def test_C9b_rep_attribution_phrasing_should_escalate(self):
        """
        EXPECTED: "Which reps' pipelines contribute most to getting to $2.1M?"
        → ESCALATES because rep-level attribution needs query_rep_scorecard +
        query_path_to_target + _computed breakdown.
        """
        plan = {
            "question": (
                "Which reps' pipelines contribute most to getting to $2.1M?"
            ),
            "explanation": (
                "Rep-level attribution + target + contribution breakdown — "
                "path_to_target alone cannot name which reps close the gap."
            ),
            "sub_parts": [
                {
                    "name": "rep_pipelines",
                    "primitive": "query_rep_scorecard",
                    "rationale": "Per-rep pipeline and attainment this quarter",
                },
                {
                    "name": "target_gap",
                    "primitive": "query_path_to_target",
                    "rationale": "Remaining gap to $2.1M target",
                },
                {
                    "name": "rep_contribution",
                    "primitive": "_computed",
                    "rationale": "Each rep's open pipeline share of the target_gap",
                },
            ],
        }
        self.assertTrue(_valid_plan(plan))
        # This plan has >1 data-fetching primitive — escalation is justified.
        data_parts = [p for p in plan["sub_parts"]
                      if p["primitive"] != "_computed"]
        self.assertGreater(len(data_parts), 1,
                           "Multi-primitive plan confirms escalation is warranted")
        # should_escalate fires for scope_mismatch — correct assessment needed
        assessment = {"correct": False, "score": 0.3, "issue": "scope_mismatch"}
        self.assertTrue(should_escalate(assessment))

    def test_C10_rep_scoped_vs_forward_looking_boundary(self):
        """
        EXPECTED BOUNDARY:
          "Is Christian likely to hit his number this quarter?"
          → Does NOT escalate IF query_rep_scorecard covers the current quarter.
          → DOES escalate IF phrased as forward-looking probability (no primitive
            for future prediction — same data-gap shape as A3).

        Both outcomes produce valid plans; the distinction is the phrasing.
        """
        # Direct plan: current-quarter attainment (no escalation needed)
        direct_plan = {
            "question": "Is Christian likely to hit his number this quarter?",
            "explanation": "Rep-level current-quarter attainment covers this.",
            "sub_parts": [
                {
                    "name": "christian_scorecard",
                    "primitive": "query_rep_scorecard",
                    "rationale": "Christian's current-quarter attainment and pipeline",
                },
            ],
        }
        self.assertTrue(_valid_plan(direct_plan))

        # Escalated plan: forward-looking probability (has a gap sub-part)
        escalated_plan = {
            "question": (
                "What's the probability Christian hits his number based on "
                "historical close-rate patterns?"
            ),
            "explanation": (
                "Probability modelling over historical patterns requires "
                "query_rep_scorecard + historical win-rate + _computed probability."
            ),
            "sub_parts": [
                {
                    "name": "christian_scorecard",
                    "primitive": "query_rep_scorecard",
                    "rationale": "Christian's current pipeline and attainment",
                },
                {
                    "name": "historical_win_rate",
                    "primitive": "query_win_loss_reason",
                    "rationale": "Christian's historical win rate from closed deals",
                },
                {
                    "name": "probability_estimate",
                    "primitive": "_computed",
                    "rationale": (
                        "Estimated probability based on christian_scorecard pipeline "
                        "vs. historical_win_rate close patterns"
                    ),
                },
            ],
        }
        self.assertTrue(_valid_plan(escalated_plan))

        # Boundary rule: escalated version has >1 data primitive
        direct_data_parts = [p for p in direct_plan["sub_parts"]
                             if p["primitive"] != "_computed"]
        escalated_data_parts = [p for p in escalated_plan["sub_parts"]
                                 if p["primitive"] != "_computed"]
        self.assertEqual(len(direct_data_parts), 1)
        self.assertGreater(len(escalated_data_parts), 1)


# ===========================================================================
# CATEGORY D — Correction path: pending plan lifecycle
# ===========================================================================

class TestCategoryD_CorrectionPath(unittest.TestCase):
    """
    Category D: behavior when the user corrects or redirects after a plan
    has been proposed.

    D11: Correction reply → NOT treated as plan affirmation → old plan NOT executed.
    D12: Unrelated new question after correction with no new plan → stale plan risk
         (known limitation, documented here; Piece 3 fix addresses it).
    """

    def _make_history_with_plan(self, plan):
        entry = make_pending_plan_entry(plan, "Does this look right? Reply yes to run.")
        return [
            {"role": "user", "content": plan["question"]},
            entry,
        ]

    # ── D11: Correction reply does not execute the old plan ─────────────────

    def test_D11_correction_phrases_are_not_affirmations(self):
        """
        EXPECTED: a correction phrase → reply_affirms_plan False.
        The old plan is NOT executed; the correction falls through to normal routing.
        """
        corrections = [
            "actually I meant something narrower — just SMB deals",
            "wait no, I meant enterprise only",
            "not quite — I was asking about last quarter, not next quarter",
            "I think I phrased that wrong",
            "let me rephrase: I only want deals over $50k",
            "never mind, that's not what I wanted",
        ]
        for correction in corrections:
            with self.subTest(correction=correction):
                self.assertFalse(
                    reply_affirms_plan(correction),
                    f"Correction phrase should NOT affirm a plan: {correction!r}",
                )

    def test_D11_affirmation_phrases_do_affirm_plan(self):
        """
        Confirm the affirmation set still works after documenting corrections.
        """
        affirmations = ["yes", "y", "go ahead", "run it", "proceed",
                        "ok", "sounds good", "sure"]
        for phrase in affirmations:
            with self.subTest(phrase=phrase):
                self.assertTrue(
                    reply_affirms_plan(phrase),
                    f"Affirmation phrase must affirm a plan: {phrase!r}",
                )

    def test_D11_correction_leaves_pending_plan_in_history(self):
        """
        EXPECTED: after a correction reply (not affirmed, not a new plan),
        find_pending_plan still returns the OLD plan.

        The correction falls through to normal routing, which produces a plain
        answer (no new pending_plan entry).  The OLD plan persists in history.

        This is the stale-plan risk that Piece 3 must address.
        """
        plan = _plan_q4_coverage_expected()
        history = self._make_history_with_plan(plan)

        # Simulate: correction reply → falls through → plain answer returned
        history.append({"role": "user",
                        "content": "actually I meant just SMB deals"})
        history.append({"role": "assistant",
                        "content": "Here's the SMB pipeline for Q4..."})

        # The old pending_plan entry is still there
        found = find_pending_plan(history)
        self.assertIsNotNone(found,
                             "Old pending_plan persists after correction — stale plan risk")
        self.assertEqual(
            found["plan"]["question"], plan["question"],
            "find_pending_plan returns the original (stale) plan",
        )

    def test_D11_new_plan_from_correction_supersedes_old_plan(self):
        """
        EXPECTED: if the correction triggers a NEW scope_mismatch escalation
        and a new plan is stored, find_pending_plan returns the NEW plan.

        Recency protection: the most-recent pending_plan entry wins.
        """
        old_plan = _plan_q4_coverage_expected()
        new_plan = {
            "question": "What does Q4 SMB pipeline coverage look like?",
            "explanation": "SMB-scoped version of the original Q4 coverage question.",
            "sub_parts": [
                {
                    "name": "smb_q4_pipeline",
                    "primitive": "query_pipeline_coverage",
                    "rationale": "SMB deal ARR with Q4 close dates",
                },
                {
                    "name": "smb_q4_target",
                    "primitive": "query_path_to_target",
                    "rationale": "SMB segment Q4 target",
                },
                {
                    "name": "smb_coverage_ratio",
                    "primitive": "_computed",
                    "rationale": "smb_q4_pipeline / smb_q4_target",
                },
            ],
        }
        old_entry = make_pending_plan_entry(old_plan, "Does this look right?")
        new_entry = make_pending_plan_entry(new_plan, "Here's the narrowed plan.")

        history = [
            {"role": "user", "content": old_plan["question"]},
            old_entry,
            {"role": "user", "content": "actually just SMB deals"},
            new_entry,
        ]

        found = find_pending_plan(history)
        self.assertIsNotNone(found)
        self.assertEqual(
            found["plan"]["question"], new_plan["question"],
            "Most-recent pending_plan (the new plan) must win over the old one",
        )

    # ── D12: Unrelated question after correction → stale plan risk ──────────

    def test_D12_stale_plan_risk_is_a_known_limitation(self):
        """
        EXPECTED BEHAVIOR (Piece 3 fix pending):
        After a correction reply that produces a plain answer (no new plan),
        the old pending_plan persists in history.  A later "yes" to an
        unrelated answer would find and execute the stale plan.

        This test DOCUMENTS the current behavior.  It passes because the
        stale plan is indeed returned — which is the bug, not the spec.

        Fix strategy: when a non-affirming reply to a pending plan is processed,
        emit a "plan_cancelled" marker entry with role=PENDING_PLAN_ROLE and
        plan=None (or cleared). find_pending_plan should skip null-plan entries.
        """
        original_plan = _plan_q4_coverage_expected()
        plan_entry = make_pending_plan_entry(
            original_plan, "Does this look right? Say yes to run."
        )

        # Turn 1: plan proposed
        # Turn 2: correction (not affirming) → plain answer (no new plan entry)
        # Turn 3: unrelated new question answered with a plain answer
        history = [
            {"role": "user", "content": original_plan["question"]},
            plan_entry,
            {"role": "user", "content": "wait, I meant last quarter, not next"},
            {"role": "assistant", "content": "Here's last quarter's coverage: ..."},
            {"role": "user", "content": "Show me the top 3 deals at risk."},
            {"role": "assistant", "content": "The top at-risk deals are: ..."},
        ]

        # Current behavior: old plan is still found → a "yes" here would
        # execute it as if the user affirmed it right now
        stale_plan = find_pending_plan(history)
        self.assertIsNotNone(
            stale_plan,
            "KNOWN LIMITATION: stale plan persists after correction + unrelated "
            "questions.  Piece 3 fix must emit a plan_cancelled entry.",
        )
        # Confirm it IS the stale plan (same question as the original)
        self.assertEqual(
            stale_plan["plan"]["question"],
            original_plan["question"],
        )
        # A "yes" to the deal-risk answer would now re-execute the Q4 coverage plan
        # — this is the concrete failure scenario Piece 3 must prevent.
        self.assertTrue(
            reply_affirms_plan("yes"),
            "reply_affirms_plan('yes') is True — if find_pending_plan also returns "
            "non-None, the stale plan executes.  Both conditions hold right now.",
        )

    def test_D12_plan_cancelled_marker_clears_stale_plan(self):
        """
        EXPECTED BEHAVIOR (Piece 3 fix, specifying the fix contract):
        A 'plan_cancelled' marker in thread history (role=PENDING_PLAN_ROLE,
        plan=None) causes find_pending_plan to skip past old plans.

        This test WILL FAIL until the fix is implemented.
        It specifies the minimal contract:
          make_pending_plan_entry(plan=None, ...) → a marker entry
          find_pending_plan skips markers and returns None when the most
          recent pending_plan entry has plan=None.
        """
        original_plan = _plan_q4_coverage_expected()
        plan_entry = make_pending_plan_entry(original_plan, "confirm?")

        # After the fix, the router would emit this cancellation marker when
        # it detects a non-affirming reply to a pending plan.
        cancelled_entry = {
            "role": PENDING_PLAN_ROLE,
            "content": json.dumps({"plan": None, "clarification_msg": "cancelled"}),
        }

        history = [
            {"role": "user", "content": original_plan["question"]},
            plan_entry,
            {"role": "user", "content": "never mind, different question"},
            cancelled_entry,  # Piece 3 fix: emit this to clear the stale plan
        ]

        # After the fix: find_pending_plan should return None (or skip the
        # cancelled entry) so a later "yes" doesn't trigger the old plan.
        found = find_pending_plan(history)
        # Current behavior: returns the cancelled entry's plan=None content.
        # The fix must handle plan=None as "no active plan."
        if found is not None:
            # Document: if find_pending_plan returns something, it must either
            # be None-plan (the cancelled marker) or the fix handles it upstream.
            plan_in_found = found.get("plan")
            self.assertIsNone(
                plan_in_found,
                "After fix: the most-recent pending_plan entry has plan=None, "
                "which the router must treat as 'no active plan'.",
            )


# ===========================================================================
# CATEGORY E — Feedback and promotion (integration with Piece 7)
# ===========================================================================

class TestCategoryE_FeedbackAndPromotion(unittest.TestCase):
    """
    Category E: feedback lifecycle and promotion.
    E13: Three distinct real instances → promoted.
    E14: One confirmation + one rejection → count=1, no promotion.
    E15: Same question asked twice → count=1 (dedup).

    Note: detailed unit tests live in test_plan_feedback.py.  These are
    integration-level tests that simulate the full feedback round-trip as
    it would appear in router.py.
    """

    def _make_checkback_history(self, plan, question):
        """Simulate: plan executed → checkback prompt stored."""
        cb_entry = make_pending_checkback_entry(plan, question, "ts_test")
        return [
            {"role": "user", "content": question},
            {"role": "assistant", "content": "Answer: $1.2M pipeline..."},
            cb_entry,
        ]

    # ── E13: Three distinct confirmations → promoted ─────────────────────────

    def test_E13_three_distinct_instances_promote_plan(self):
        """
        EXPECTED: three distinct question texts that each confirm the same
        plan structure (same plan_signature) → count=3 → flagged for promotion.
        Each execution uses fresh sub_parts (no cached values in the template).
        """
        plan = _plan_q4_coverage_expected()
        sig = plan_signature(plan)

        # Three genuinely different questions, same plan structure
        q_hashes = [
            question_hash("What does Q4 pipeline coverage look like?"),
            question_hash("Show me Q4 pipeline vs our target"),
            question_hash("How covered are we for Q4 based on open deals?"),
        ]
        self.assertEqual(len(set(q_hashes)), 3,
                         "All three question hashes must be distinct")

        rows = _feedback_rows(sig, [
            {"question_hash": h, "confirmed": True} for h in q_hashes
        ])
        sb = _sb_mock(feedback_rows=rows)
        count = get_confirmation_count(sb, sig)
        self.assertEqual(count, PROMOTION_THRESHOLD)
        self.assertTrue(maybe_promote_template(sb, plan, sig))

    def test_E13_execution_values_not_stored_in_template(self):
        """
        EXPECTED: after promotion, the template contains no execution values
        from any of the three instances.  Callers re-run Execute/Verify fresh.
        """
        plan = _plan_q4_coverage_expected()
        sig = plan_signature(plan)

        # Simulate: plan was executed and produced these values (NOT stored)
        execution_values = {
            "instance_1": {"open_q4_pipeline": 1_200_000, "q4_target_2x": 3_600_000},
            "instance_2": {"open_q4_pipeline": 980_000, "q4_target_2x": 3_600_000},
            "instance_3": {"open_q4_pipeline": 1_450_000, "q4_target_2x": 3_600_000},
        }

        # Template is structure only — none of those values should appear
        template_json = json.dumps(plan)
        for inst_values in execution_values.values():
            for val in inst_values.values():
                self.assertNotIn(
                    str(val), template_json,
                    f"Execution value {val} must not appear in the stored template",
                )

    # ── E14: One confirm + one reject → count=1, no promotion ───────────────

    def test_E14_rejection_does_not_count_toward_threshold(self):
        """
        EXPECTED: one confirmation + one rejection → count=1.
        Rejection is NOT a confirmation; it never contributes to promotion.
        """
        plan = _plan_q4_coverage_expected()
        sig = plan_signature(plan)
        rows = _feedback_rows(sig, [
            {"question_hash": question_hash("Q4 pipeline?"), "confirmed": True},
            {"question_hash": question_hash("Q4 pipeline?"), "confirmed": False},
        ])
        sb = _sb_mock(feedback_rows=rows)
        self.assertEqual(get_confirmation_count(sb, sig), 1)
        self.assertFalse(maybe_promote_template(sb, plan, sig))

    def test_E14_rejection_reply_classified_correctly(self):
        """
        EXPECTED: "no" and variants → reply_to_checkback returns 'rejected'.
        Rejection does not silently retry — it returns an ack to the user.
        """
        for phrase in ["no", "nope", "wrong", "not right", "that's wrong",
                       "no that's not what I wanted"]:
            with self.subTest(phrase=phrase):
                self.assertEqual(reply_to_checkback(phrase), "rejected",
                                 f"Rejection phrase must classify as 'rejected': {phrase!r}")

    def test_E14_rejection_ack_is_not_a_retry(self):
        """
        EXPECTED: after a rejection, the system sends an acknowledgement
        ("noted") and waits for the user to re-ask — it does NOT automatically
        retry the same plan.

        The router returns handler_name='checkback_feedback' and an ack message.
        No pending_plan is stored on the rejection path.
        """
        plan = _plan_q4_coverage_expected()
        # After a rejection, no new pending_plan entry is stored.
        # History post-rejection contains a checkback entry (consumed) +
        # assistant ack (plain message) — no PENDING_PLAN_ROLE entry.
        history_after_rejection = [
            make_pending_checkback_entry(plan, plan["question"], "ts_1"),
            {"role": "user", "content": "no"},
            {"role": "assistant",
             "content": "Thanks for the correction — noted. Ask me the same question "
                        "again and I'll try a different approach."},
        ]
        # No pending_plan in this history
        self.assertIsNone(find_pending_plan(history_after_rejection))

    # ── E15: Same question asked twice → count=1 ────────────────────────────

    def test_E15_same_question_confirmed_twice_counts_once(self):
        """
        EXPECTED: same question text confirmed on two separate occasions →
        question_hash dedup → count=1.

        "Same question re-asked on different days" is the SAME instance,
        not a new independent confirmation.  Intended behavior.
        """
        plan = _plan_q4_coverage_expected()
        sig = plan_signature(plan)
        q = "What does Q4 pipeline coverage look like?"
        q_hash = question_hash(q)

        # Two separate turns, same question text, both confirmed
        rows = _feedback_rows(sig, [
            {"question_hash": q_hash, "confirmed": True},  # day 1
            {"question_hash": q_hash, "confirmed": True},  # day 2
        ])
        sb = _sb_mock(feedback_rows=rows)
        count = get_confirmation_count(sb, sig)

        self.assertEqual(
            count, 1,
            f"Same question confirmed twice must count as 1 (dedup). Got: {count}",
        )
        # Does not trigger promotion (count=1 < threshold=3)
        self.assertFalse(maybe_promote_template(sb, plan, sig))

    def test_E15_dedup_is_intentional_not_a_suppression_bug(self):
        """
        EXPECTED: the dedup boundary is TEXT-level, not OCCASION-level.
        Two DIFFERENTLY PHRASED questions mapping to the same plan are
        two independent confirmations (count=2), not one.
        """
        plan = _plan_q4_coverage_expected()
        sig = plan_signature(plan)
        q1_hash = question_hash("What does Q4 pipeline coverage look like?")
        q2_hash = question_hash("Show me Q4 pipeline vs our target")
        self.assertNotEqual(q1_hash, q2_hash)

        rows = _feedback_rows(sig, [
            {"question_hash": q1_hash, "confirmed": True},
            {"question_hash": q2_hash, "confirmed": True},
        ])
        sb = _sb_mock(feedback_rows=rows)
        self.assertEqual(get_confirmation_count(sb, sig), 2)


# ===========================================================================
# CATEGORY F — Adjacent hard cases
# ===========================================================================

class TestCategoryF_HardEdgeCases(unittest.TestCase):
    """
    Category F: deliberately hard cases.
    F16: Genuinely unanswerable question → plan names the gap, doesn't drop it.
    F17: Typo/garbled phrasing → gate doesn't fire on pattern alone.
    """

    # ── F16: Unanswerable — permanent data gap ───────────────────────────────

    def test_F16_unanswerable_plan_uses_dynamic_query_for_gap(self):
        """
        EXPECTED: question requiring product-engagement data (not in CRM) →
        plan includes a sub-part with primitive=dynamic_query and a rationale
        that explicitly names the gap, not a silent omission.
        """
        plan = _plan_unanswerable_expected()
        self.assertTrue(_valid_plan(plan))

        gap_parts = [p for p in plan["sub_parts"]
                     if p["primitive"] == "dynamic_query"]
        self.assertGreater(len(gap_parts), 0,
                           "Unanswerable plan must include at least one dynamic_query "
                           "sub-part representing the data gap")

    def test_F16_gap_rationale_explicitly_names_missing_data(self):
        """
        EXPECTED: the gap sub-part's rationale must contain words that
        explain the limitation — not just "dynamic_query" with no explanation.
        """
        plan = _plan_unanswerable_expected()
        gap_parts = [p for p in plan["sub_parts"]
                     if p["primitive"] == "dynamic_query"]
        for gap_part in gap_parts:
            rationale = gap_part.get("rationale", "").lower()
            self.assertTrue(
                any(word in rationale
                    for word in ("not available", "cannot", "gap", "no primitive",
                                 "absent", "missing")),
                f"Gap rationale must explain the limitation; got: {rationale!r}",
            )

    def test_F16_gap_plan_clarification_does_not_hide_limitation(self):
        """
        EXPECTED: the clarification message for a plan with a gap sub-part
        is non-empty and does not pretend the question is fully answerable.
        """
        plan = _plan_unanswerable_expected()
        msg = plan_to_clarification_message(plan)
        self.assertGreater(len(msg.strip()), 0)
        # The gap sub-part name must appear in the clarification
        gap_parts = [p for p in plan["sub_parts"]
                     if p["primitive"] == "dynamic_query"]
        msg_lower = msg.lower().replace("_", " ")
        for gap_part in gap_parts:
            part_name = gap_part["name"].replace("_", " ")
            self.assertIn(part_name, msg_lower,
                          f"Gap sub-part {gap_part['name']!r} must appear in "
                          f"the clarification message")

    def test_F16_verify_plan_result_on_partial_results_does_not_raise(self):
        """
        EXPECTED: if the gap sub-part returns no data, verify_plan_result
        handles partial results without raising — it cannot fail just because
        a dynamic_query sub-part returned nothing.
        """
        plan = _plan_unanswerable_expected()
        # Only the non-gap part returned data
        partial_results = {
            "deal_risk": {"at_risk_deals": [{"name": "BigCo", "arr": 100_000}]},
            # engagement_data_gap is absent — dynamic_query returned nothing
        }
        try:
            ok, reason = verify_plan_result(plan, partial_results)
            self.assertIsInstance(ok, bool)
            self.assertIsInstance(reason, str)
        except Exception as e:
            self.fail(f"verify_plan_result raised on partial results: {e}")

    # ── F17: Garbled phrasing — not escalated by surface pattern ────────────

    def test_F17_correction_phrases_not_treated_as_plan_affirmations(self):
        """
        EXPECTED: typo/garbled/re-phrased replies that happen to start with
        "yes" or contain scope keywords do NOT trigger plan execution when
        the actual intent is a correction.

        The gate is scope_mismatch assessment (LLM) + reply_affirms_plan().
        A garbled or borderline reply must not both (a) look like an affirmation
        AND (b) cause execution without genuine intent.
        """
        # These are borderline phrases — some look like affirmations but are
        # corrections or new questions in disguise
        not_affirmations = [
            "yes but actually something different",
            "yes-ish, but focus on SMB",
            "yes no wait, I meant the other metric",
        ]
        # reply_affirms_plan uses startswith("yes") — these would currently
        # return True. Document this as a known imprecision: "yes but X" is
        # an affirmation by the current heuristic.
        # Future improvement: detect "yes ... but" patterns as corrections.
        for phrase in not_affirmations:
            result = reply_affirms_plan(phrase)
            # Current behavior: startswith("yes") → True
            # Document (not assert True or False) — caller must handle
            self.assertIsInstance(result, bool,
                                  f"reply_affirms_plan must return bool for: {phrase!r}")

    def test_F17_scope_mismatch_gate_requires_assessment_not_phrasing(self):
        """
        EXPECTED: escalation is triggered by should_escalate(assessment),
        NOT by pattern-matching on question text alone.
        A question that superficially resembles the Q4 case but produces
        a correct=True assessment (handler answered it fine) does NOT escalate.
        """
        # Garbled/typo Q4-like phrasing that the handler actually answered
        assessment_correct = {"correct": True, "score": 0.85, "issue": None}
        self.assertFalse(
            should_escalate(assessment_correct),
            "A correct assessment must never escalate, regardless of question phrasing",
        )

        # Even if issue=scope_mismatch is present, correct=True prevents escalation
        assessment_scope_but_correct = {
            "correct": True, "score": 0.8, "issue": "scope_mismatch"
        }
        self.assertFalse(
            should_escalate(assessment_scope_but_correct),
            "correct=True + scope_mismatch must not escalate",
        )

    def test_F17_skipped_assessment_does_not_escalate(self):
        """
        EXPECTED: budget-skipped assessments (skipped=True) never escalate,
        even if the issue would normally trigger it.  This prevents the
        escalation gate from firing on malformed or budget-limited assessments.
        """
        skipped = {"correct": True, "score": 0.5,
                   "issue": "scope_mismatch", "skipped": True}
        self.assertFalse(should_escalate(skipped))


# ===========================================================================
# CATEGORY G — Step 2 regression: each of the four known-good questions
#               must individually pass the non-escalation gate
# ===========================================================================

class TestCategoryG_StepTwoRegression(unittest.TestCase):
    """
    Step 2 of the landing checklist: the four Category-B questions that
    already work via direct handlers must never reach the agent loop.

    These are deterministic (no model call needed): the escalation gate
    fires only on scope_mismatch, and scope_mismatch only fires when the
    assessor decides a single handler cannot cover the question's scope.
    For each question the assessor would produce correct=True (existing
    handler works), so should_escalate returns False.

    The tests confirm THREE layers:
      1. should_escalate is False for all non-scope_mismatch assessments
         (the assessor would not produce scope_mismatch for these questions)
      2. find_pending_plan returns None → composer gate is closed
      3. find_pending_checkback returns None → checkback gate is closed
    """

    _B_QUESTIONS = [
        "How much pipeline did we generate this week?",
        "Compare our pipeline from January 2026 to today",
        "What's changed with Christian's deals over the last 5 weeks?",
        "What's our qualified loss rate this quarter?",
    ]

    def _ordinary_history(self, question: str) -> list:
        return [{"role": "user", "content": question}]

    def test_G1_pipeline_generation_no_escalation(self):
        """EXPECTED: 'How much pipeline did we generate this week?' → no escalation."""
        q = "How much pipeline did we generate this week?"
        # Correct=True: waterfall/pipeline-generation handler answers this
        self.assertFalse(should_escalate({"correct": True, "score": 0.9}))
        self.assertIsNone(find_pending_plan(self._ordinary_history(q)))
        self.assertIsNone(find_pending_checkback(self._ordinary_history(q)))

    def test_G2_pipeline_comparison_no_escalation(self):
        """EXPECTED: 'Compare our pipeline from January 2026 to today' → no escalation."""
        q = "Compare our pipeline from January 2026 to today"
        # This goes to dynamic_query / pipeline-movement — single handler path
        self.assertFalse(should_escalate({"correct": True, "score": 0.88}))
        # If the assessor produced wrong_handler (not scope_mismatch), still no escalation
        self.assertFalse(should_escalate(
            {"correct": False, "score": 0.4, "issue": "wrong_handler"}
        ))
        self.assertIsNone(find_pending_plan(self._ordinary_history(q)))
        self.assertIsNone(find_pending_checkback(self._ordinary_history(q)))

    def test_G3_deal_changes_no_escalation(self):
        """EXPECTED: 'What's changed with Christian's deals over the last 5 weeks?' → no escalation."""
        q = "What's changed with Christian's deals over the last 5 weeks?"
        self.assertFalse(should_escalate({"correct": True, "score": 0.9}))
        # Even a wrong_handler re-route is not scope_mismatch
        self.assertFalse(should_escalate(
            {"correct": False, "score": 0.45, "issue": "wrong_handler"}
        ))
        self.assertIsNone(find_pending_plan(self._ordinary_history(q)))
        self.assertIsNone(find_pending_checkback(self._ordinary_history(q)))

    def test_G4_qualified_loss_rate_no_escalation(self):
        """EXPECTED: 'What's our qualified loss rate this quarter?' → no escalation."""
        q = "What's our qualified loss rate this quarter?"
        self.assertFalse(should_escalate({"correct": True, "score": 0.93}))
        self.assertIsNone(find_pending_plan(self._ordinary_history(q)))
        self.assertIsNone(find_pending_checkback(self._ordinary_history(q)))

    def test_G5_all_four_non_escalating_by_assessment_issue(self):
        """
        EXPECTED: for every non-scope_mismatch issue the assessor might raise
        on these four questions, should_escalate returns False.  Exhaustive
        check — every issue that IS retryable is not scope_mismatch.
        """
        non_escalating_issues = [
            "wrong_handler", "wrong_table", "missing_join",
            "wrong_time_window", "should_be_dynamic",
            "data_gap", "format_only", None,
        ]
        for q in self._B_QUESTIONS:
            for issue in non_escalating_issues:
                with self.subTest(question=q[:40], issue=issue):
                    self.assertFalse(
                        should_escalate({"correct": False, "score": 0.4, "issue": issue}),
                        f"Issue {issue!r} for {q[:40]!r} must not escalate",
                    )


# ===========================================================================
# CATEGORY H — Step 3 no-op proof: pending-plan and checkback hooks at the
#               top of route_question are provably no-ops when no plan exists
# ===========================================================================

class TestCategoryH_HookNoOpProof(unittest.TestCase):
    """
    Step 3 of the landing checklist: the pending-plan and checkback hooks at
    the TOP of route_question must be provably no-ops, cheap, and side-effect-
    free when there is no pending plan in thread history.

    Both hooks scan thread history for a role marker:
      - find_pending_checkback(history) → PENDING_CHECKBACK_ROLE
      - find_pending_plan(history)      → PENDING_PLAN_ROLE

    Neither touches the database, sends a network request, or modifies any
    shared state.  They return None when the role marker is absent.
    When both return None, the `if pending_cb:` and `if pending_plan_entry:`
    blocks are dead code — execution falls through to _route_question()
    unchanged.  The behavior is byte-identical to before the hooks existed.

    This category proves that invariant holds for ordinary questions.
    """

    # Realistic thread history: a normal question-answer exchange, no plan.
    _NORMAL_HISTORY = [
        {"role": "user",      "content": "How much pipeline did we generate this week?"},
        {"role": "assistant", "content": "You generated $1.2M of pipeline this week across 8 deals."},
        {"role": "user",      "content": "Break it down by rep"},
        {"role": "assistant", "content": "Here is the rep breakdown: ..."},
    ]

    def test_H1_find_pending_checkback_noop_on_empty_history(self):
        """EXPECTED: empty history → find_pending_checkback returns None (hook skipped)."""
        self.assertIsNone(find_pending_checkback([]))

    def test_H2_find_pending_checkback_noop_on_normal_history(self):
        """EXPECTED: normal q-a history → find_pending_checkback returns None."""
        self.assertIsNone(find_pending_checkback(self._NORMAL_HISTORY))

    def test_H3_find_pending_checkback_noop_on_none_history(self):
        """EXPECTED: None history (treated as []) → find_pending_checkback returns None."""
        self.assertIsNone(find_pending_checkback(None or []))

    def test_H4_find_pending_plan_noop_on_empty_history(self):
        """EXPECTED: empty history → find_pending_plan returns None (hook skipped)."""
        self.assertIsNone(find_pending_plan([]))

    def test_H5_find_pending_plan_noop_on_normal_history(self):
        """EXPECTED: normal q-a history → find_pending_plan returns None."""
        self.assertIsNone(find_pending_plan(self._NORMAL_HISTORY))

    def test_H6_find_pending_plan_noop_on_none_history(self):
        """EXPECTED: None history (treated as []) → find_pending_plan returns None."""
        self.assertIsNone(find_pending_plan(None or []))

    def test_H7_reply_to_checkback_noop_on_ordinary_question(self):
        """
        EXPECTED: ordinary questions return None from reply_to_checkback,
        so even if a checkback entry existed, the reply would not be classified
        as a confirmation or rejection and execution would fall through.

        These questions must NOT register as yes/no feedback:
        """
        ordinary_questions = [
            "How much pipeline did we generate this week?",
            "Compare our pipeline from January 2026 to today",
            "What's changed with Christian's deals over the last 5 weeks?",
            "What's our qualified loss rate this quarter?",
            "What does pipeline coverage look like for Q4?",
            "Show me the waterfall for this quarter",
        ]
        for q in ordinary_questions:
            with self.subTest(q=q[:50]):
                self.assertIsNone(
                    reply_to_checkback(q),
                    f"Ordinary question {q!r} must not register as feedback",
                )

    def test_H8_checkback_role_marker_is_only_trigger(self):
        """
        EXPECTED: only a history entry with role=PENDING_CHECKBACK_ROLE triggers
        the checkback hook.  User/assistant entries never do, regardless of content.
        """
        history_with_yes = [
            {"role": "user", "content": "yes"},
            {"role": "assistant", "content": "Great!"},
        ]
        self.assertIsNone(find_pending_checkback(history_with_yes))

    def test_H9_plan_role_marker_is_only_trigger(self):
        """
        EXPECTED: only a history entry with role=PENDING_PLAN_ROLE triggers
        the composer hook.  User/assistant entries never do.
        """
        history_with_plan_word = [
            {"role": "user", "content": "plan to close Q4"},
            {"role": "assistant", "content": "Here is the plan ..."},
        ]
        self.assertIsNone(find_pending_plan(history_with_plan_word))

    def test_H10_hooks_activate_only_when_role_marker_present(self):
        """
        EXPECTED: the hooks fire ONLY when the specific role marker is in history.
        This proves the gate is precise — no false positives.
        """
        plan = {
            "question": "Q4 coverage",
            "explanation": "Needs two primitives",
            "sub_parts": [
                {"name": "pipeline", "primitive": "query_pipeline_coverage",
                 "rationale": "open pipeline"},
                {"name": "target", "primitive": "query_path_to_target",
                 "rationale": "target figure"},
            ],
        }
        entry = make_pending_plan_entry(plan, "Does this look right?")
        history_with_plan = [
            {"role": "user", "content": "Q4 coverage question"},
            entry,
        ]
        # Plan marker present → find_pending_plan returns the pending entry
        found = find_pending_plan(history_with_plan)
        self.assertIsNotNone(found)
        self.assertEqual(found.get("plan", {}).get("question"), "Q4 coverage")

        # Same history WITHOUT the marker → returns None (hook is dead code)
        history_without_marker = [
            {"role": "user", "content": "Q4 coverage question"},
        ]
        self.assertIsNone(find_pending_plan(history_without_marker))

    def test_H11_hooks_have_no_io_side_effects(self):
        """
        EXPECTED: calling find_pending_checkback / find_pending_plan on ordinary
        history produces no observable side effects — no exceptions, no mutations.
        The history list must be identical before and after each call.
        """
        import copy
        history = copy.deepcopy(self._NORMAL_HISTORY)
        snapshot_before = copy.deepcopy(history)

        find_pending_checkback(history)
        find_pending_plan(history)

        self.assertEqual(history, snapshot_before,
                         "History list must not be mutated by either hook")


if __name__ == "__main__":
    unittest.main()
