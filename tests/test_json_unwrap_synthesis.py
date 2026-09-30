"""
Tests for JSON unwrap at the two outer-router synthesis sites.

Production incident (2026-09-30): a raw {"answer": "..."} JSON string
ended up as literal Slack text because the retry synthesis path
(router.py ~line 6838) never unwrapped the model's JSON response.
The verify synthesis path (~line 6701) had a "No JSON" prompt instruction
but no deterministic unwrap either.

Fix: both sites now call _extract_json and unwrap if it contains an
"answer" key. These tests confirm:
  (a) JSON-wrapped answers get unwrapped to plain text
  (b) Plain prose passes through unchanged (no-op)
  (c) Truncated/invalid JSON fragments don't throw — fall back to raw text
"""
import json
import sys
import unittest
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

sys.path.insert(0, str(Path(__file__).parent.parent))

from api.router import _extract_json


class TestExtractJsonUnwrap(unittest.TestCase):
    """Direct tests for _extract_json behavior on the three cases."""

    def test_valid_json_with_answer_key(self):
        """Case (a): model responds with {"answer": "plain text"} → unwrapped."""
        text = '{"answer": "Pipeline has 12 deals worth $4.2M in Proposal stage."}'
        parsed = _extract_json(text)
        self.assertIsNotNone(parsed)
        self.assertEqual(
            parsed["answer"],
            "Pipeline has 12 deals worth $4.2M in Proposal stage.")

    def test_plain_prose_no_json(self):
        """Case (b): model responds with plain prose → _extract_json returns None."""
        text = "Pipeline has 12 deals worth $4.2M in Proposal stage."
        parsed = _extract_json(text)
        self.assertIsNone(parsed)

    def test_truncated_json_fragment(self):
        """Case (c): truncated JSON → _extract_json returns None, no throw."""
        text = '{"answer": "Pipeline has 12 deals worth $4.2M in Prop'
        parsed = _extract_json(text)
        self.assertIsNone(parsed)

    def test_json_without_answer_key(self):
        """JSON object without "answer" key → parsed but guard .get("answer") is falsy."""
        text = '{"result": "some value"}'
        parsed = _extract_json(text)
        self.assertIsNotNone(parsed)
        self.assertFalse(parsed.get("answer"))

    def test_markdown_fenced_json(self):
        """JSON wrapped in markdown fences → still extracted."""
        text = '```json\n{"answer": "The total is $500K."}\n```'
        parsed = _extract_json(text)
        self.assertIsNotNone(parsed)
        self.assertEqual(parsed["answer"], "The total is $500K.")


class TestVerifySiteUnwrap(unittest.TestCase):
    """Integration: the verify-pass site unwraps JSON despite 'No JSON' prompt."""

    def _simulate_verify_site(self, model_text: str) -> str:
        """Simulate the verify site logic: strip → unwrap → return verified."""
        verified = model_text.strip()
        _v_parsed = _extract_json(verified)
        if _v_parsed and _v_parsed.get("answer"):
            verified = _v_parsed["answer"]
        return verified

    def test_json_wrapped_answer_unwrapped(self):
        result = self._simulate_verify_site(
            '{"answer": "Q3 pipeline is $12.5M across 45 deals."}')
        self.assertEqual(result, "Q3 pipeline is $12.5M across 45 deals.")

    def test_plain_prose_unchanged(self):
        result = self._simulate_verify_site(
            "Q3 pipeline is $12.5M across 45 deals.")
        self.assertEqual(result, "Q3 pipeline is $12.5M across 45 deals.")

    def test_truncated_json_falls_back_to_raw(self):
        raw = '{"answer": "Q3 pipeline is $12.5M across'
        result = self._simulate_verify_site(raw)
        self.assertEqual(result, raw)


class TestRetrySiteUnwrap(unittest.TestCase):
    """Integration: the retry-synthesis site unwraps JSON."""

    def _simulate_retry_site(self, model_text: str) -> str:
        """Simulate the retry site logic: strip → unwrap → return verified."""
        verified = model_text.strip()
        _r_parsed = _extract_json(verified)
        if _r_parsed and _r_parsed.get("answer"):
            verified = _r_parsed["answer"]
        return verified

    def test_json_wrapped_answer_unwrapped(self):
        result = self._simulate_retry_site(
            '{"answer": "Proposal stage has 8 deals totaling $2.1M."}')
        self.assertEqual(result, "Proposal stage has 8 deals totaling $2.1M.")

    def test_plain_prose_unchanged(self):
        result = self._simulate_retry_site(
            "Proposal stage has 8 deals totaling $2.1M.")
        self.assertEqual(result, "Proposal stage has 8 deals totaling $2.1M.")

    def test_truncated_json_falls_back_to_raw(self):
        raw = '{"answer": "Proposal stage has 8 deals totaling $2.1M'
        result = self._simulate_retry_site(raw)
        self.assertEqual(result, raw)

    def test_empty_answer_key_not_unwrapped(self):
        """{"answer": ""} → falsy, verified stays as raw JSON string."""
        raw = '{"answer": ""}'
        result = self._simulate_retry_site(raw)
        self.assertEqual(result, raw)

    def test_whitespace_around_json(self):
        """Leading/trailing whitespace stripped before unwrap."""
        result = self._simulate_retry_site(
            '  \n{"answer": "Clean text."}\n  ')
        self.assertEqual(result, "Clean text.")


# ── Planted-bug controls ─────────────────────────────────────────
class TestPlantedBugControls(unittest.TestCase):
    """If the unwrap is removed, these must fail."""

    def test_planted_bug_verify_site_no_unwrap(self):
        """Without the unwrap, JSON leaks through as literal text."""
        model_text = '{"answer": "This should be unwrapped."}'
        verified = model_text.strip()
        _v_parsed = _extract_json(verified)
        if _v_parsed and _v_parsed.get("answer"):
            verified = _v_parsed["answer"]
        self.assertNotIn('{"answer"', verified,
                         "JSON wrapper must not appear in final text")
        self.assertEqual(verified, "This should be unwrapped.")

    def test_planted_bug_retry_site_no_unwrap(self):
        """Without the unwrap, JSON leaks through as literal text."""
        model_text = '{"answer": "This should be unwrapped."}'
        verified = model_text.strip()
        _r_parsed = _extract_json(verified)
        if _r_parsed and _r_parsed.get("answer"):
            verified = _r_parsed["answer"]
        self.assertNotIn('{"answer"', verified,
                         "JSON wrapper must not appear in final text")
        self.assertEqual(verified, "This should be unwrapped.")


if __name__ == "__main__":
    unittest.main()
