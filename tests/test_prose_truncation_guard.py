"""
Tests for the prose-answer truncation guard in the dynamic query loop.

Production incident (2026-09-30): iter=3 of a pipeline query returned
truncated prose ("I need to identify the deals in the Proposal stage...")
that passed the scratchpad-keyword check and shipped to Slack as a raw
working note.  The keyword heuristic caught iter=2 ("let me work through
this") but missed iter=3 because "I need to identify" isn't a scratchpad
narration pattern.

Fix: the prose-answer gate now also calls _looks_truncated(), which
rejects any response that doesn't end on terminal punctuation.  These
tests confirm:
  (3) prose ending mid-word → rejected
  (4) prose ending with terminal punctuation → accepted
  (5) scratchpad keyword + truncated → rejected (either check catches it)
  (6) iter=3's actual raw text → rejected by truncation check
"""
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from api.router import _looks_truncated, _looks_like_unfinished_scratchpad


# ── Actual iter=3 text from the 2026-09-30 production trace ──────
ITER3_RAW = (
    "I need to identify the deals in the Proposal stage and calculate "
    "the total pipeline value. Let me query the deals data with the "
    "appropriate stage filter to get accurate numbers for the current"
)
# Note: ends on "current" — no terminal punctuation, mid-sentence.


class TestLooksTruncated(unittest.TestCase):
    """Direct unit tests for _looks_truncated."""

    def test_mid_word_truncation(self):
        """Prose ending mid-word → truncated."""
        self.assertTrue(_looks_truncated("Pipeline has 12 deals worth $4.2M in Prop"))

    def test_mid_sentence_truncation(self):
        """Prose ending mid-sentence (comma, then word) → truncated."""
        self.assertTrue(_looks_truncated(
            "There are 12 deals in Proposal, totaling"))

    def test_ends_with_period(self):
        """Ends with period → not truncated."""
        self.assertFalse(_looks_truncated(
            "Pipeline has 12 deals worth $4.2M in Proposal stage."))

    def test_ends_with_exclamation(self):
        """Ends with exclamation → not truncated."""
        self.assertFalse(_looks_truncated("Great quarter!"))

    def test_ends_with_question_mark(self):
        """Ends with question mark → not truncated."""
        self.assertFalse(_looks_truncated("Would you like more detail?"))

    def test_ends_with_closing_paren(self):
        """Ends with closing paren → not truncated."""
        self.assertFalse(_looks_truncated("Total is $4.2M (across 12 deals)"))

    def test_ends_with_closing_quote(self):
        """Ends with closing quote → not truncated."""
        self.assertFalse(_looks_truncated('She said "ship it"'))

    def test_ends_with_ellipsis(self):
        """Ends with ellipsis char → not truncated."""
        self.assertFalse(_looks_truncated("More details coming…"))

    def test_ends_with_colon(self):
        """Colon at end → truncated (unfinished list header)."""
        self.assertTrue(_looks_truncated("Here are the top deals:"))

    def test_ends_with_dash(self):
        """Dash at end → truncated (cut off mid-thought)."""
        self.assertTrue(_looks_truncated("The total is approximately —"))

    def test_empty_string(self):
        """Empty string → not truncated (different failure mode)."""
        self.assertFalse(_looks_truncated(""))

    def test_whitespace_only(self):
        """Whitespace → not truncated."""
        self.assertFalse(_looks_truncated("   \n  "))

    def test_markdown_bold_ending(self):
        """Bold-wrapped sentence ending with period → not truncated."""
        self.assertFalse(_looks_truncated("**Total: $4.2M.**"))

    def test_trailing_whitespace_with_period(self):
        """Trailing whitespace after period → not truncated."""
        self.assertFalse(_looks_truncated("Total is $4.2M.   \n"))


class TestProseAnswerGateLogic(unittest.TestCase):
    """Simulates the gate logic at router.py:4690-4692."""

    def _gate_rejects(self, text: str) -> bool:
        """Return True if the gate would reject (force resynthesis)."""
        stripped = text.strip()
        is_scratchpad = _looks_like_unfinished_scratchpad(stripped)
        is_truncated = _looks_truncated(stripped)
        return is_scratchpad or is_truncated

    # Test 3: prose ending mid-word → rejected
    def test_mid_word_rejected(self):
        self.assertTrue(self._gate_rejects(
            "Pipeline has 12 deals worth $4.2M in Prop"))

    # Test 4: prose ending with terminal punctuation → accepted
    def test_terminal_punctuation_accepted(self):
        self.assertFalse(self._gate_rejects(
            "Pipeline has 12 deals worth $4.2M in Proposal stage."))

    # Test 5: scratchpad keyword + truncated → rejected (either catches it)
    def test_scratchpad_and_truncated(self):
        text = "Let me work through the deals to calculate the total"
        self.assertTrue(_looks_like_unfinished_scratchpad(text))
        self.assertTrue(_looks_truncated(text))
        self.assertTrue(self._gate_rejects(text))

    # Test 6: iter=3's actual raw text → rejected
    def test_iter3_actual_trace(self):
        self.assertFalse(_looks_like_unfinished_scratchpad(ITER3_RAW),
                         "keyword check alone should NOT catch iter=3")
        self.assertTrue(_looks_truncated(ITER3_RAW),
                        "truncation check MUST catch iter=3")
        self.assertTrue(self._gate_rejects(ITER3_RAW))

    def test_clean_prose_accepted(self):
        """Well-formed prose answer passes both checks."""
        text = "Q3 pipeline has 45 deals totaling $12.5M across all stages."
        self.assertFalse(self._gate_rejects(text))

    def test_scratchpad_keyword_only(self):
        """Scratchpad keyword with terminal punct → still rejected by keyword."""
        text = "Let me now calculate the pipeline total for you."
        self.assertTrue(_looks_like_unfinished_scratchpad(text))
        self.assertTrue(self._gate_rejects(text))


class TestPlantedBugControls(unittest.TestCase):
    """If the truncation guard is removed, these must fail."""

    def test_planted_bug_iter3_without_truncation_check(self):
        """Without _looks_truncated, iter=3's text would pass the gate."""
        self.assertFalse(
            _looks_like_unfinished_scratchpad(ITER3_RAW),
            "Keyword check alone does NOT catch iter=3 — this is the "
            "planted bug: removing _looks_truncated lets it through.")
        self.assertTrue(
            _looks_truncated(ITER3_RAW),
            "Truncation check catches what keywords miss.")

    def test_planted_bug_mid_word_without_truncation_check(self):
        """Mid-word text has no scratchpad keywords either."""
        text = "The total pipeline value for Proposal stage is approximately"
        self.assertFalse(_looks_like_unfinished_scratchpad(text))
        self.assertTrue(_looks_truncated(text))


if __name__ == "__main__":
    unittest.main()
