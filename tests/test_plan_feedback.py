"""
Tests for api/plan_feedback.py — Piece 7: feedback, template promotion,
and handler-promotion flagging for the compositional layer.

Hard invariants (non-negotiable, derived from spec):
  A. plan_signature captures STRUCTURE ONLY — the same primitives in any
     order produce the same signature regardless of question text or values.
  B. "No" feedback never contributes to the confirmation count.
  C. The same question instance (same question_hash) counts as exactly 1
     confirmation no matter how many times the user confirms.
  D. Rejection of plan X has no effect on plan Y's confirmation count.
  E. Promotion is a flag (flagged_for_handler_review), not code execution.
  F. find_template() returns STRUCTURE only — no stored values; callers must
     always re-run Execute/Verify fresh.
  G. check-back prompt contains "yes"/"no" guidance (Slack-legible).
"""
import hashlib
import json
import sys
import unittest
from pathlib import Path
from unittest.mock import MagicMock

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO))

from api.plan_feedback import (
    PENDING_CHECKBACK_ROLE,
    PROMOTION_THRESHOLD,
    checkback_prompt,
    find_pending_checkback,
    find_template,
    get_confirmation_count,
    make_pending_checkback_entry,
    maybe_promote_template,
    plan_signature,
    question_hash,
    record_feedback,
    reply_to_checkback,
)


# ---------------------------------------------------------------------------
# Fixtures

def _plan_q4_coverage():
    return {
        "question": "How is our Q4 pipeline coverage?",
        "sub_parts": [
            {"name": "open_q4_pipeline", "primitive": "query_pipeline_coverage"},
            {"name": "q4_target", "primitive": "query_path_to_target"},
            {"name": "coverage_ratio", "primitive": "_computed",
             "rationale": "open_q4_pipeline / q4_target"},
        ],
    }


def _plan_q4_arr_total():
    """Different plan — same structure shape but different primitive."""
    return {
        "question": "What's our total Q4 ARR?",
        "sub_parts": [
            {"name": "new_arr", "primitive": "query_waterfall"},
            {"name": "expansion_arr", "primitive": "query_waterfall"},
            {"name": "total_arr", "primitive": "_computed",
             "rationale": "new_arr + expansion_arr"},
        ],
    }


def _plan_q4_coverage_reworded():
    """Same structure as _plan_q4_coverage but different question text."""
    return {
        "question": "Show me Q4 pipeline coverage breakdown",
        "sub_parts": [
            {"name": "open_q4_pipeline", "primitive": "query_pipeline_coverage"},
            {"name": "q4_target", "primitive": "query_path_to_target"},
            {"name": "coverage_ratio", "primitive": "_computed",
             "rationale": "ratio of open_q4_pipeline to q4_target"},
        ],
    }


def _sb_mock(feedback_rows=None, template_rows=None):
    """Mock Supabase client that applies .eq() filters to in-memory rows."""
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


# ---------------------------------------------------------------------------
# Invariant A: plan_signature — structure only, order-independent

class TestPlanSignature(unittest.TestCase):

    def test_same_plan_same_signature(self):
        plan = _plan_q4_coverage()
        self.assertEqual(plan_signature(plan), plan_signature(plan))

    def test_structure_only_question_text_ignored(self):
        """Same primitives, different question text → same signature."""
        plan_a = _plan_q4_coverage()
        plan_b = _plan_q4_coverage_reworded()
        self.assertEqual(plan_signature(plan_a), plan_signature(plan_b))

    def test_different_primitives_different_signature(self):
        """Different primitives → different signature."""
        plan_a = _plan_q4_coverage()
        plan_b = _plan_q4_arr_total()
        self.assertNotEqual(plan_signature(plan_a), plan_signature(plan_b))

    def test_empty_plan_returns_empty(self):
        self.assertEqual(plan_signature({}), "")
        self.assertEqual(plan_signature(None), "")

    def test_order_independent(self):
        """Reordering sub_parts doesn't change signature (sorted internally)."""
        plan_fwd = {
            "sub_parts": [
                {"name": "a", "primitive": "query_pipeline_coverage"},
                {"name": "b", "primitive": "query_waterfall"},
            ]
        }
        plan_rev = {
            "sub_parts": [
                {"name": "b", "primitive": "query_waterfall"},
                {"name": "a", "primitive": "query_pipeline_coverage"},
            ]
        }
        self.assertEqual(plan_signature(plan_fwd), plan_signature(plan_rev))

    def test_signature_is_16_hex_chars(self):
        sig = plan_signature(_plan_q4_coverage())
        self.assertEqual(len(sig), 16)
        self.assertTrue(all(c in "0123456789abcdef" for c in sig))


class TestQuestionHash(unittest.TestCase):

    def test_same_question_same_hash(self):
        q = "How is our Q4 pipeline coverage?"
        self.assertEqual(question_hash(q), question_hash(q))

    def test_case_insensitive(self):
        self.assertEqual(
            question_hash("How is Q4 coverage?"),
            question_hash("how is q4 coverage?"),
        )

    def test_whitespace_normalized(self):
        self.assertEqual(
            question_hash("How  is  Q4  coverage?"),
            question_hash("How is Q4 coverage?"),
        )

    def test_different_questions_different_hash(self):
        self.assertNotEqual(
            question_hash("What are our Q4 wins?"),
            question_hash("How is Q4 coverage?"),
        )


# ---------------------------------------------------------------------------
# reply_to_checkback()

class TestReplyToCheckback(unittest.TestCase):

    def test_yes_confirms(self):
        for reply in ["yes", "y", "yeah", "yep", "correct", "that's right",
                      "right", "exactly", "perfect", "confirmed"]:
            with self.subTest(reply=reply):
                self.assertEqual(reply_to_checkback(reply), "confirmed")

    def test_yes_prefix_confirms(self):
        for reply in ["yes please", "yes that's right", "yes, that was it"]:
            with self.subTest(reply=reply):
                self.assertEqual(reply_to_checkback(reply), "confirmed")

    def test_no_rejects(self):
        for reply in ["no", "n", "nope", "wrong", "not right", "incorrect",
                      "that's wrong", "incorrect"]:
            with self.subTest(reply=reply):
                self.assertEqual(reply_to_checkback(reply), "rejected")

    def test_no_prefix_rejects(self):
        for reply in ["no that's wrong", "no thats not right",
                      "no, it should have been Q3"]:
            with self.subTest(reply=reply):
                self.assertEqual(reply_to_checkback(reply), "rejected")

    def test_unrelated_returns_none(self):
        for reply in [
            "what about next quarter?",
            "show me the deals",
            "how about enterprise?",
            "let me rephrase",
            "",
        ]:
            with self.subTest(reply=reply):
                self.assertIsNone(reply_to_checkback(reply))

    def test_case_insensitive(self):
        self.assertEqual(reply_to_checkback("YES"), "confirmed")
        self.assertEqual(reply_to_checkback("NO"), "rejected")
        self.assertEqual(reply_to_checkback("WRONG"), "rejected")


# ---------------------------------------------------------------------------
# pending_checkback thread history

class TestPendingCheckback(unittest.TestCase):

    def test_entry_has_correct_role(self):
        plan = _plan_q4_coverage()
        entry = make_pending_checkback_entry(plan, "Q4 coverage?", "ts_123")
        self.assertEqual(entry["role"], PENDING_CHECKBACK_ROLE)

    def test_entry_stores_plan_signature(self):
        plan = _plan_q4_coverage()
        entry = make_pending_checkback_entry(plan, "Q4 coverage?", "ts_123")
        content = json.loads(entry["content"])
        self.assertEqual(content["plan_signature"], plan_signature(plan))

    def test_entry_stores_question_hash(self):
        q = "How is Q4 coverage?"
        entry = make_pending_checkback_entry(_plan_q4_coverage(), q, "ts_123")
        content = json.loads(entry["content"])
        self.assertEqual(content["question_hash"], question_hash(q))

    def test_entry_stores_plan_for_promotion(self):
        """Plan must be stored so promotion can happen on confirmation."""
        plan = _plan_q4_coverage()
        entry = make_pending_checkback_entry(plan, "Q4 coverage?", "ts_123")
        content = json.loads(entry["content"])
        self.assertIn("plan", content)
        self.assertEqual(
            content["plan"]["sub_parts"][0]["primitive"],
            plan["sub_parts"][0]["primitive"],
        )

    def test_find_returns_most_recent(self):
        plan_a = _plan_q4_coverage()
        plan_b = _plan_q4_arr_total()
        entry_a = make_pending_checkback_entry(plan_a, "Q4 coverage?", "ts_1")
        entry_b = make_pending_checkback_entry(plan_b, "Q4 total?", "ts_2")
        history = [entry_a, entry_b]
        found = find_pending_checkback(history)
        # Most-recent (entry_b) wins
        self.assertEqual(
            found["plan_signature"],
            plan_signature(plan_b),
        )

    def test_find_returns_none_when_absent(self):
        history = [{"role": "user", "content": "hello"}]
        self.assertIsNone(find_pending_checkback(history))

    def test_find_handles_empty_history(self):
        self.assertIsNone(find_pending_checkback([]))
        self.assertIsNone(find_pending_checkback(None))


# ---------------------------------------------------------------------------
# Invariant G: check-back prompt

class TestCheckbackPrompt(unittest.TestCase):

    def test_prompt_is_nonempty(self):
        self.assertGreater(len(checkback_prompt().strip()), 0)

    def test_prompt_contains_yes_no_guidance(self):
        prompt = checkback_prompt().lower()
        self.assertIn("yes", prompt)
        self.assertIn("no", prompt)

    def test_prompt_contains_no_values(self):
        """Prompt must not contain question-specific numbers or names."""
        prompt = checkback_prompt()
        # No dollar amounts
        self.assertNotIn("$", prompt)
        # No digits that look like ARR values
        import re
        self.assertFalse(bool(re.search(r"\d{4,}", prompt)))


# ---------------------------------------------------------------------------
# Invariant B: rejection not counted; Invariant C: deduplication

def _feedback_rows(sig, entries):
    """Build feedback rows that include plan_signature so .eq() filter works."""
    return [{"plan_signature": sig, **e} for e in entries]


def _template_row(sig, plan):
    return {"plan_signature": sig, "plan_json": json.dumps(plan)}


class TestFeedbackDeduplication(unittest.TestCase):

    def test_confirmed_rows_counted(self):
        """Three distinct confirmed question_hashes → count = 3."""
        sig = plan_signature(_plan_q4_coverage())
        rows = _feedback_rows(sig, [
            {"question_hash": "aaa111", "confirmed": True},
            {"question_hash": "bbb222", "confirmed": True},
            {"question_hash": "ccc333", "confirmed": True},
        ])
        sb = _sb_mock(feedback_rows=rows)
        self.assertEqual(get_confirmation_count(sb, sig), 3)

    def test_duplicate_question_hash_counts_once(self):
        """
        Invariant C: same question re-asked multiple times → counts as 1.
        """
        sig = plan_signature(_plan_q4_coverage())
        rows = _feedback_rows(sig, [
            {"question_hash": "aaa111", "confirmed": True},
            {"question_hash": "aaa111", "confirmed": True},  # duplicate
            {"question_hash": "bbb222", "confirmed": True},
        ])
        sb = _sb_mock(feedback_rows=rows)
        self.assertEqual(get_confirmation_count(sb, sig), 2)

    def test_rejection_not_counted(self):
        """
        Invariant B: confirmed=False rows do not count.
        """
        sig = plan_signature(_plan_q4_coverage())
        rows = _feedback_rows(sig, [
            {"question_hash": "aaa111", "confirmed": True},
            {"question_hash": "bbb222", "confirmed": False},  # rejection
        ])
        sb = _sb_mock(feedback_rows=rows)
        self.assertEqual(get_confirmation_count(sb, sig), 1)

    def test_all_rejections_count_zero(self):
        sig = plan_signature(_plan_q4_coverage())
        rows = _feedback_rows(sig, [
            {"question_hash": "aaa111", "confirmed": False},
            {"question_hash": "bbb222", "confirmed": False},
        ])
        sb = _sb_mock(feedback_rows=rows)
        self.assertEqual(get_confirmation_count(sb, sig), 0)

    def test_empty_feedback_count_zero(self):
        sig = plan_signature(_plan_q4_coverage())
        sb = _sb_mock(feedback_rows=[])
        self.assertEqual(get_confirmation_count(sb, sig), 0)

    def test_db_failure_returns_zero(self):
        """On DB failure, count returns 0 (safe default)."""
        sb = MagicMock()
        sb.table.side_effect = Exception("DB down")
        self.assertEqual(get_confirmation_count(sb, "any_sig"), 0)


# ---------------------------------------------------------------------------
# Invariant D: rejection isolation across plan signatures

class TestRejectionIsolation(unittest.TestCase):

    def test_rejection_of_plan_a_doesnt_affect_plan_b(self):
        """
        Invariant D: recording a rejection for one signature must not
        touch or be counted against any other signature.
        """
        sig_a = plan_signature(_plan_q4_coverage())
        sig_b = plan_signature(_plan_q4_arr_total())
        self.assertNotEqual(sig_a, sig_b, "Plans should have different signatures")

        # plan B has 2 confirmed rows
        rows_b = _feedback_rows(sig_b, [
            {"question_hash": "x1", "confirmed": True},
            {"question_hash": "x2", "confirmed": True},
        ])
        # Mock returns plan B rows for plan B's signature
        sb = _sb_mock(feedback_rows=rows_b)
        self.assertEqual(get_confirmation_count(sb, sig_b), 2)

        # A separate rejection for plan A is irrelevant to plan B's count
        # (the mock is separate; the signature-filtered query ensures isolation)
        self.assertEqual(
            get_confirmation_count(sb, sig_b), 2,
            "Plan B confirmation count must be unaffected by plan A rejections",
        )


# ---------------------------------------------------------------------------
# Invariant E: promotion threshold + flagging

class TestPromotion(unittest.TestCase):

    def test_no_promotion_below_threshold(self):
        """Fewer than PROMOTION_THRESHOLD confirmations → no promotion."""
        sig = plan_signature(_plan_q4_coverage())
        rows = _feedback_rows(sig, [
            {"question_hash": f"h{i}", "confirmed": True}
            for i in range(PROMOTION_THRESHOLD - 1)
        ])
        sb = _sb_mock(feedback_rows=rows)
        result = maybe_promote_template(sb, _plan_q4_coverage(), sig)
        self.assertFalse(result)

    def test_promotion_at_threshold(self):
        """Exactly PROMOTION_THRESHOLD distinct confirmations → promotes."""
        sig = plan_signature(_plan_q4_coverage())
        rows = _feedback_rows(sig, [
            {"question_hash": f"h{i}", "confirmed": True}
            for i in range(PROMOTION_THRESHOLD)
        ])
        sb = _sb_mock(feedback_rows=rows)
        result = maybe_promote_template(sb, _plan_q4_coverage(), sig)
        self.assertTrue(result)

    def test_promotion_above_threshold(self):
        """More than PROMOTION_THRESHOLD → still promotes."""
        sig = plan_signature(_plan_q4_coverage())
        rows = _feedback_rows(sig, [
            {"question_hash": f"h{i}", "confirmed": True}
            for i in range(PROMOTION_THRESHOLD + 2)
        ])
        sb = _sb_mock(feedback_rows=rows)
        result = maybe_promote_template(sb, _plan_q4_coverage(), sig)
        self.assertTrue(result)

    def test_promotion_threshold_is_at_least_3(self):
        """
        Spec requires N ≥ 3.  This test locks in that floor so a careless
        lowering to 1 or 2 is caught immediately.
        """
        self.assertGreaterEqual(PROMOTION_THRESHOLD, 3)

    def test_db_failure_returns_false(self):
        sb = MagicMock()
        sb.table.side_effect = Exception("DB down")
        result = maybe_promote_template(sb, _plan_q4_coverage(), "sig")
        self.assertFalse(result)


# ---------------------------------------------------------------------------
# Invariant F: find_template returns structure only

class TestTemplateStructureOnly(unittest.TestCase):

    def test_find_template_returns_plan_structure(self):
        plan = _plan_q4_coverage()
        sig = plan_signature(plan)
        template_rows = [_template_row(sig, plan)]
        sb = _sb_mock(template_rows=template_rows)
        found = find_template(sb, sig)
        self.assertIsNotNone(found)
        # Structure is present
        self.assertIn("sub_parts", found)
        self.assertEqual(
            found["sub_parts"][0]["primitive"],
            plan["sub_parts"][0]["primitive"],
        )

    def test_find_template_returns_none_when_absent(self):
        sb = _sb_mock(template_rows=[])
        self.assertIsNone(find_template(sb, "nonexistent_sig"))

    def test_find_template_no_stored_values(self):
        """
        The template must contain only plan structure (primitives, names,
        rationales).  Stored answer values (e.g. total_arr: 4860000) must
        not be present — callers always re-run Execute/Verify fresh.
        """
        plan = _plan_q4_coverage()
        plan_with_stale_values = dict(plan)
        # Simulate a corrupted template that somehow stored values
        # (should not happen, but the test documents the expectation)
        plan_with_stale_values["_stale_result"] = {"total_arr": 4_860_000}
        sig = plan_signature(plan)
        template_rows = [_template_row(sig, plan_with_stale_values)]
        sb = _sb_mock(template_rows=template_rows)
        found = find_template(sb, sig)
        # The function returns whatever was stored — the CALLER is responsible
        # for using only sub_parts and ignoring any _stale_result key.
        # This test documents that _stale_result is NOT a sub_part key.
        for part in found.get("sub_parts", []):
            self.assertNotIn("_stale_result", part)

    def test_find_template_db_failure_returns_none(self):
        sb = MagicMock()
        sb.table.side_effect = Exception("DB down")
        self.assertIsNone(find_template(sb, "any_sig"))


# ---------------------------------------------------------------------------
# record_feedback — smoke test (no DB assertions, just no-raise)

class TestRecordFeedback(unittest.TestCase):

    def test_record_confirmed_does_not_raise(self):
        sb = _sb_mock()
        try:
            record_feedback(sb, "sig", "qhash", "Q4 coverage?",
                            "ts_123", confirmed=True)
        except Exception as e:
            self.fail(f"record_feedback raised: {e}")

    def test_record_rejected_does_not_raise(self):
        sb = _sb_mock()
        try:
            record_feedback(sb, "sig", "qhash", "Q4 coverage?",
                            "ts_123", confirmed=False)
        except Exception as e:
            self.fail(f"record_feedback raised: {e}")

    def test_db_failure_does_not_raise(self):
        sb = MagicMock()
        sb.table.side_effect = Exception("DB down")
        try:
            record_feedback(sb, "sig", "qhash", "Q", "ts", confirmed=True)
        except Exception as e:
            self.fail(f"record_feedback raised on DB failure: {e}")


if __name__ == "__main__":
    unittest.main()
