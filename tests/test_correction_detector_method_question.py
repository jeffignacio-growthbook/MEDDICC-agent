"""
Tests for the 2026-10-06 false "correction" detection incident (thread
1791259518.438989).

Incident: "What weighted rates did you use for each stage? or did you use
forecast category weights?" was misrouted. Logs showed
"[CORRECTION] Detected correction in question", handler=
correction_scope_question, and NO "[INTENT]" line at all — meaning
api/corrections.py's detect_correction() short-circuited the whole request
BEFORE the intent classifier (an LLM call) ever ran. The bot then asked
"general or specific?" for what was actually a question about METHOD, not a
correction.

Root cause: CORRECTION_PATTERNS' `(?:use|uses|should use|value on)\\s+\\w+`
entry matched the substring "use forecast" inside "...or did you use
forecast category weights?" — detect_correction() is a bare regex .search()
over the raw message, so ANY matching substring anywhere trips it, question
or statement alike. api/router.py called detect_correction(question) at
its stage "-2" block, BEFORE the classifier call ever ran, so there was no
classification signal at all to override it.

Fix (api/corrections.py + api/router.py):
  1b. is_method_question(): a correction-shaped STATEMENT guard — a message
      shaped like a question about method/computation (leading what/how/
      why/which on a clause, or "did you" anywhere) is NEVER treated as a
      correction, unconditionally (not contingent on prior-answer
      existence). CORRECTION_PATTERNS itself is untouched — it legitimately
      catches real corrections like "targets use HubSpot's email
      convention"; the fix is a guard layered IN FRONT of detect_correction
      at its router.py call site.
  1c. Pending-state anchoring: the "is the next message 'general' or
      'specific'?" check was a bare substring test (`'general' in
      user_response`), so an unrelated message merely CONTAINING the word
      ("what's our general pipeline coverage looking like?") would be
      wrongly treated as "the user chose general scope" and create a bogus
      correction proposal. Fixed with an anchored
      re.fullmatch(r"general[.!]?"/r"specific[.!]?") check.

Conventions reused:
  - StrictSupabase fixtures, print-based narration (house style).
  - _FakeLLM + patch.object(router.LLMClient, "from_config", ...) +
    patch.object(router, "message_names_known_company", lambda q, sb: False)
    + asyncio.run(router.route_question(...)) — the EXACT convention from
    tests/test_quota_attainment_retry_regression.py (lines ~270-360), reused
    rather than reinvented.
  - Planted-bug controls that literally reproduce the OLD broken behavior
    inline, proving each test would have caught the real incident.
"""
import asyncio
import json
import sys
import types
import unittest
from pathlib import Path
from unittest.mock import patch

REPO = Path(__file__).resolve().parents[1]
for p in ("", "tests", "scripts", "scripts/analytics", "api"):
    sys.path.insert(0, str(REPO / p) if p else str(REPO))

if "supabase" not in sys.modules:
    _fake = types.ModuleType("supabase")
    _fake.create_client = lambda *a, **k: None
    _fake.Client = type("Client", (), {})
    sys.modules["supabase"] = _fake

import logging  # noqa: E402
logging.disable(logging.CRITICAL)

from strict_supabase import StrictSupabase  # noqa: E402
import api.router as router  # noqa: E402
from corrections import detect_correction, is_method_question  # noqa: E402


# The exact real-incident question (thread 1791259518.438989).
REAL_INCIDENT_QUESTION = (
    "What weighted rates did you use for each stage? "
    "or did you use forecast category weights?"
)
TRUE_CORRECTION = "that's wrong, Marcel's quota is 150K"


# ══════════════════════════════════════════════════════════════
# 1. is_method_question() unit tests
# ══════════════════════════════════════════════════════════════

class TestIsMethodQuestionUnit(unittest.TestCase):
    def test_real_incident_question_is_method_question(self):
        self.assertTrue(is_method_question(REAL_INCIDENT_QUESTION))
        print("✓ real incident question classified as a method question")

    def test_true_correction_is_not_a_method_question(self):
        self.assertFalse(is_method_question(TRUE_CORRECTION))
        print("✓ a true correction statement is NOT classified as a method question")

    def test_leading_what_on_first_clause(self):
        self.assertTrue(is_method_question(
            "What weighted rates did you use for each stage"))

    def test_leading_or_plus_did_you_on_second_clause(self):
        self.assertTrue(is_method_question(
            "or did you use forecast category weights"))

    def test_bare_did_you_phrase_anywhere(self):
        self.assertTrue(is_method_question("did you use forecast category weights?"))

    def test_leading_how(self):
        self.assertTrue(is_method_question("How do you calculate attainment?"))

    def test_leading_why(self):
        self.assertTrue(is_method_question("Why is Review excluded from pipeline?"))

    def test_leading_which(self):
        self.assertTrue(is_method_question("Which stages feed the weighted total?"))

    def test_leading_and_plus_question_word(self):
        self.assertTrue(is_method_question(
            "Marcel closed two deals. and what rate applied to them?"))

    def test_empty_string_is_false(self):
        self.assertFalse(is_method_question(""))
        self.assertFalse(is_method_question(None))

    def test_ordinary_statement_not_a_method_question(self):
        self.assertFalse(is_method_question("Marcel is at 80% of quota this quarter."))

    def test_detect_correction_guarded_call_no_longer_treats_incident_as_correction(self):
        """The guarded call exactly as used at the router.py call site:
        `if not is_method_question(question) and detect_correction(question)`."""
        guarded_result = (not is_method_question(REAL_INCIDENT_QUESTION)
                          and detect_correction(REAL_INCIDENT_QUESTION))
        self.assertFalse(guarded_result,
            "the guarded call must NOT treat the real incident question as a correction")
        print("✓ guarded detect_correction() call no longer fires on the real incident question")

    def test_planted_bug_unguarded_detect_correction_fires_on_incident(self):
        """Planted-bug control: reproduce the OLD unguarded call
        (`detect_correction(question)` alone, no is_method_question guard)
        and confirm it DOES fire on the real incident question — proving
        the bug this fix closes was real."""
        print("\n[TEST] planted-bug control: unguarded detect_correction() misfires on method question")
        old_unguarded_result = detect_correction(REAL_INCIDENT_QUESTION)
        self.assertTrue(
            old_unguarded_result,
            "planted-bug control failed to reproduce: the OLD unguarded "
            "detect_correction() call should fire (True) on the real "
            "incident question — if it doesn't, the fixture needs updating"
        )
        print("  ✓ confirmed: unguarded detect_correction() misfires here (the bug); "
              "the is_method_question() guard suppresses it (the fix)")


# ══════════════════════════════════════════════════════════════
# 2. True correction still reaches the correction flow
# ══════════════════════════════════════════════════════════════

class TestTrueCorrectionStillDetected(unittest.TestCase):
    def test_true_correction_not_a_method_question_and_still_a_correction(self):
        self.assertFalse(is_method_question(TRUE_CORRECTION))
        self.assertTrue(detect_correction(TRUE_CORRECTION))
        guarded_result = (not is_method_question(TRUE_CORRECTION)
                          and detect_correction(TRUE_CORRECTION))
        self.assertTrue(guarded_result,
            "a true correction must still trip the guarded detect_correction() call")
        print("✓ true correction ('that's wrong, Marcel's quota is 150K') "
              "is NOT a method question and still reaches the correction flow")


# ══════════════════════════════════════════════════════════════
# 3. Integration — the REAL router.route_question() retry/routing path
# ══════════════════════════════════════════════════════════════

CLASSIFY_MARKER = "no backticks"
SYNTH_MARKER = "SYNTH_EXPLAIN_PRIOR_ANSWER_MARKER"


class _FakeLLM:
    """Branches on system-prompt content, the same convention
    tests/test_quota_attainment_retry_regression.py's _FakeLLM uses."""

    def __init__(self, intent, calls_log):
        self.intent = intent
        self.calls = calls_log

    def complete(self, messages=None, system=None, max_tokens=None, **kw):
        prompt = messages[0]["content"] if messages else ""
        self.calls.append({"system": system, "prompt": prompt})
        attrs = {"input_tokens": 0, "output_tokens": 0}
        if system and CLASSIFY_MARKER in system:
            return type("R", (), {**attrs, "text": json.dumps(self.intent)})()
        # explain_prior_answer's generator call (system doesn't match the
        # classify marker) and any other fallback.
        return type("R", (), {**attrs, "text": SYNTH_MARKER})()


def _base_sb():
    return StrictSupabase({
        "user_personas": [],
        "rep_targets": [],
        "deals": [],
        "fallback_log": [],
        "learning_log": [],
        "result_cache": [],
        "proposals": [],
    })


class TestEndToEndMethodQuestionReachesClassifier(unittest.TestCase):
    def test_real_incident_question_reaches_classifier_and_explain_prior_answer(self):
        """With history containing a prior assistant answer, the exact real
        incident question must make it all the way through to
        handler_name == 'explain_prior_answer' — proving detect_correction's
        block never returns early (the classifier mock WAS called)."""
        print("\n[TEST] real incident question reaches the classifier, not correction_scope_question")
        intent = {"handler": "explain_prior_answer", "confidence": 0.95,
                  "scope": "prior_set", "params": {}}
        calls = []
        llm = _FakeLLM(intent, calls)
        sb = _base_sb()

        history = [
            {"role": "user", "content": "What's team weighted pipeline this quarter?"},
            {"role": "assistant", "content": "Team weighted pipeline is $410,000."},
        ]

        with patch.object(router.LLMClient, "from_config", return_value=llm), \
             patch.object(router, "message_names_known_company", lambda q, sb: False):
            r = asyncio.run(router.route_question(
                question=REAL_INCIDENT_QUESTION, user_id="U1", persona=None,
                history=history, sb=sb, thread_ts=""))

        self.assertTrue(
            any(CLASSIFY_MARKER in (c.get("system") or "") for c in calls),
            "the classifier mock must have been called — proving "
            "detect_correction's block never short-circuited this question"
        )
        self.assertEqual(r["handler_name"], "explain_prior_answer")
        self.assertNotEqual(r["handler_name"], "correction_scope_question")
        print(f"  ✓ final handler_name={r['handler_name']!r}, classifier called={len(calls)} time(s)")

    def test_true_correction_short_circuits_before_classifier(self):
        """A genuine correction must still short-circuit BEFORE the
        classifier call — handler_name == correction_scope_question AND the
        classifier mock's calls log is EMPTY, proving genuine corrections
        still skip the (expensive) LLM classify step entirely, same as
        today."""
        print("\n[TEST] true correction short-circuits before the classifier")
        intent = {"handler": "dynamic_query", "confidence": 0.95,
                  "scope": None, "params": {}}
        calls = []
        llm = _FakeLLM(intent, calls)
        sb = _base_sb()

        with patch.object(router.LLMClient, "from_config", return_value=llm), \
             patch.object(router, "message_names_known_company", lambda q, sb: False):
            r = asyncio.run(router.route_question(
                question=TRUE_CORRECTION, user_id="U1", persona=None,
                history=[], sb=sb, thread_ts=""))

        self.assertEqual(r["handler_name"], "correction_scope_question")
        self.assertEqual(len(calls), 0,
            "a genuine correction must short-circuit before the classifier "
            "is ever called — the (expensive) LLM classify step must be skipped")
        print(f"  ✓ handler_name={r['handler_name']!r}, classifier calls={len(calls)}")


# ══════════════════════════════════════════════════════════════
# 4. Pending-state anchoring (item 1c)
# ══════════════════════════════════════════════════════════════

PENDING_HISTORY = [
    {"role": "user", "content": "actually the quota field is wrong"},
    {"role": "assistant", "content": "the prior (wrong) answer text"},
    {"role": "assistant", "content": "I see you're correcting something...",
     "handler_name": "correction_scope_question"},
]


class TestPendingStateAnchoredMatch(unittest.TestCase):
    def test_unrelated_message_containing_general_does_not_create_proposal(self):
        """'what's our general pipeline coverage looking like?' contains
        the substring 'general' but is NOT the reply 'general' — must fall
        through to normal routing, no proposal row inserted."""
        print("\n[TEST] unrelated 'general'-containing message does not trigger scope-reply branch")
        intent = {"handler": "acknowledgment", "confidence": 0.95,
                  "scope": None, "params": {}}
        calls = []
        llm = _FakeLLM(intent, calls)
        sb = _base_sb()

        with patch.object(router.LLMClient, "from_config", return_value=llm), \
             patch.object(router, "message_names_known_company", lambda q, sb: False):
            r = asyncio.run(router.route_question(
                question="what's our general pipeline coverage looking like?",
                user_id="U1", persona=None, history=PENDING_HISTORY, sb=sb, thread_ts=""))

        proposal_writes = [w for w in sb.writes if w["table"] == "proposals"]
        self.assertEqual(len(proposal_writes), 0,
            "no proposals row should be inserted for an unrelated message "
            "that merely contains the word 'general'")
        self.assertNotIn(r["handler_name"],
                         ("correction_proposal_created", "correction_proposal_failed"))
        print(f"  ✓ no proposals write, handler_name={r['handler_name']!r} "
              "(routing fell through normally)")

    def test_bare_general_reply_still_creates_proposal(self):
        """Positive control: a bare 'general' reply (modulo whitespace/
        punctuation) still creates the proposal as before."""
        print("\n[TEST] bare 'general' reply still creates a proposal")
        calls = []
        llm = _FakeLLM({"handler": "dynamic_query", "confidence": 0.95,
                        "scope": None, "params": {}}, calls)
        sb = _base_sb()

        with patch.object(router.LLMClient, "from_config", return_value=llm), \
             patch.object(router, "message_names_known_company", lambda q, sb: False):
            r = asyncio.run(router.route_question(
                question="general.", user_id="U1", persona=None,
                history=PENDING_HISTORY, sb=sb, thread_ts=""))

        proposal_writes = [w for w in sb.writes if w["table"] == "proposals"]
        self.assertEqual(len(proposal_writes), 1,
            "a bare 'general' reply (with trailing punctuation) must still "
            "create exactly one proposals row, as before this fix")
        print(f"  ✓ proposals write recorded, handler_name={r['handler_name']!r}")

    def test_planted_bug_old_substring_check_wouldve_misfired(self):
        """Planted-bug control: reproduce the OLD bare substring check
        (`'general' in user_response`) inline against the unrelated message
        and confirm it WOULD have misfired — proving the bug this fix
        closes was real."""
        print("\n[TEST] planted-bug control: old substring check misfires on unrelated 'general' message")
        user_response = "what's our general pipeline coverage looking like?".lower().strip()
        old_check_fires = 'general' in user_response
        self.assertTrue(
            old_check_fires,
            "planted-bug control failed to reproduce: the OLD bare "
            "substring check should fire (True) on this unrelated message"
        )
        print("  ✓ confirmed: old substring check misfires here (the bug); "
              "the anchored re.fullmatch() check correctly does not (the fix)")


if __name__ == "__main__":
    unittest.main(verbosity=2)
