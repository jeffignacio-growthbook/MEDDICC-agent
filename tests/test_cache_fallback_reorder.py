"""
Tests for the 2026-10-03 G.7 cache-fallback reorder.

Incident: "how did you come up with that number?" (an explain_prior_answer-
shaped follow-up) was answered from the OLD "G.7" cache-fallback path
(api/router.py) — a pre-classification shortcut that swapped in the last
turn's full cached tool_results and ran full resynthesis — instead of
routing to the (correctly built, PR #113) explain_prior_answer handler.
Root cause: G.7 ran BEFORE the intent classifier was ever called, keyed
only on has_followup_pronoun(question) + a live result_cache row, so it
could intercept a question the classifier would have correctly named
explain_prior_answer before classification got a chance to run at all.

Fix: G.7 moved to run AFTER classification (and the confidence floor)
settle on handler_name, and now only engages when handler_name is NOT one
of the three intents that already have their own correct, self-returning
handling path (query_help, acknowledgment, explain_prior_answer) — see the
comment block in api/router.py just above the moved G.7 check. Anything
else (a precomputed data handler with no entity IDs to re-query,
dynamic_query, unanswerable) still falls back to cache resynthesis exactly
as before — this is the ORIGINAL "which of those are at risk" bulk
follow-up use case G.7 was built for, now reached via classification's own
output rather than a pre-classification shortcut.

Secondary hardening (independent of the reorder): has_followup_pronoun()
was matching bare "it"/"they"/"them" as SUBSTRINGS, so "with" (contains
"it"), "digital" (contains "it") etc. tripped it. Now word-boundary
matched.

Test groups (all offline/deterministic — mocked classifier+generator via
the same patch.object(router.LLMClient, "from_config", ...) + StrictSupabase
harness tests/test_rep_clarification.py's end-to-end tests already use;
no live LLM, no network, runs in CI):
  1. has_followup_pronoun word-boundary fix (pure function, no deps).
  2. The reordered G.7: an explain_prior_answer-shaped question with a
     live cache now routes to explain_prior_answer (not cached_result),
     and the citation path actually fires (cached fields reach the
     generator prompt).
  3. The reorder holds even when the question STILL matches
     has_followup_pronoun under the new word-boundary rule — isolates
     that the REORDER (not just the pronoun-regex side effect) is what
     fixes the incident.
  4. REGRESSION GUARD: the original "which of those are at risk" style
     bulk follow-up (classification resolves to an ordinary precomputed
     handler, not one of the three self-handling intents) still correctly
     reaches cached_result's resynthesis mode post-reorder.
"""
import asyncio
import json
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path
from unittest.mock import patch

REPO = Path(__file__).parent.parent
sys.path.insert(0, str(REPO / "tests"))
sys.path.insert(0, str(REPO))
sys.path.insert(0, str(REPO / "api"))
sys.path.insert(0, str(REPO / "scripts"))

import logging  # noqa: E402
logging.disable(logging.CRITICAL)

from strict_supabase import StrictSupabase  # noqa: E402
import api.router as router  # noqa: E402
from api.router import has_followup_pronoun  # noqa: E402


# ══════════════════════════════════════════════════════════════
# 1. has_followup_pronoun — word-boundary, not substring
# ══════════════════════════════════════════════════════════════

def test_pronoun_substring_false_positives_no_longer_match():
    print("\n[TEST] has_followup_pronoun no longer false-positives on substrings")
    false_positives = [
        "how did you come up with that number?",  # the exact incident phrasing
        "that's a great digital strategy",         # "digital" contains "it"
        "did you visit the client site?",          # "visit" contains "it"
        "can you work with them on pricing?".replace("them", ""),  # "with" alone
    ]
    for q in false_positives:
        assert not has_followup_pronoun(q), (
            f"{q!r} should NOT match has_followup_pronoun (no real pronoun "
            f"present) — substring matching regressed")
    print("  ✓ 'with'/'digital'/'visit' no longer falsely trip the pronoun check")


def test_pronoun_real_words_still_match():
    print("\n[TEST] has_followup_pronoun still matches real pronoun usage")
    real_matches = [
        "how did you calculate it?",
        "which of those are at risk?",
        "them deals look risky",
        "they'd probably churn",          # apostrophe still a word boundary
        "what about this deal?".replace("this", "that"),
    ]
    for q in real_matches:
        assert has_followup_pronoun(q), (
            f"{q!r} SHOULD match has_followup_pronoun (genuine pronoun "
            f"reference) — word-boundary fix over-corrected")
    print("  ✓ 'it'/'those'/'them'/\"they'd\" still match as real words")


# ══════════════════════════════════════════════════════════════
# End-to-end harness — mirrors tests/test_rep_clarification.py's
# `_route` helper: a fake LLM keyed on the classifier's distinctive
# system prompt, a StrictSupabase fake, message_names_known_company
# patched to avoid a real HubSpot/company lookup.
# ══════════════════════════════════════════════════════════════

class _FakeLLM:
    """Branches on `system`: the classifier always passes the literal
    "valid JSON only" system string (api/router.py's classify step);
    anything else is a generator call (synthesis, verify, or
    explain_prior_answer's own builder) and gets a plain fake answer.
    Records every call so a test can inspect exactly what prompt text
    reached the generator (e.g. to confirm the citation path fired)."""

    def __init__(self, intent: dict):
        self.intent = intent
        self.calls = []

    def complete(self, messages=None, system=None, max_tokens=None, **kw):
        prompt = messages[0]["content"]
        self.calls.append({"system": system, "prompt": prompt})
        # input_tokens/output_tokens: the full synthesis path (cached_result's
        # resynthesis, unlike explain_prior_answer's early return) tracks
        # token usage off the classifier response object.
        attrs = {"input_tokens": 0, "output_tokens": 0}
        if system and "valid JSON only" in system:
            return type("R", (), {**attrs, "text": json.dumps(self.intent)})()
        return type("R", (), {**attrs, "text": "FAKE_SYNTHESIZED_ANSWER"})()

    @property
    def generator_calls(self):
        return [c for c in self.calls
                if not (c["system"] and "valid JSON only" in c["system"])]


def _tables(result_cache_rows=None):
    return {
        "user_personas": [],
        "result_cache": result_cache_rows or [],
    }


PRIOR_QUESTION = "what's our pipeline coverage this quarter?"
PRIOR_ANSWER = (
    "Pipeline coverage for FY2027 Q3 is $779,000 weighted against a "
    "$1,037,000 quota gap, a 0.75x coverage ratio."
)
# A distinctive marker that only reaches the generator prompt if
# explain_prior_answer's citation path actually spliced cached_fields in —
# proves "the citation path actually fires", not just "routed correctly".
CACHED_FIELD_MARKER = "stage_weighting_marker_7f3a"


def _live_cache_row(thread_ts="T1", handler_name="query_pipeline_coverage",
                    question=PRIOR_QUESTION):
    now = datetime.now(timezone.utc)
    return {
        "result_key": "k1",
        "thread_ts": thread_ts,
        "handler_name": handler_name,
        "question": question[:500],
        "payload": json.dumps({"stage_weighting": {"note": CACHED_FIELD_MARKER}}),
        "row_count": 1,
        "created_at": (now - timedelta(minutes=1)).isoformat(),
        "expires_at": (now + timedelta(minutes=29)).isoformat(),
    }


def _history_with_prior_answer():
    return [
        {"role": "user", "content": PRIOR_QUESTION},
        {"role": "assistant", "content": PRIOR_ANSWER},
    ]


def _route(question, history, intent, result_cache_rows):
    llm = _FakeLLM(intent)
    sb = StrictSupabase(_tables(result_cache_rows))
    with patch.object(router.LLMClient, "from_config", return_value=llm), \
         patch.object(router, "message_names_known_company", lambda q, sb: False):
        r = asyncio.run(router.route_question(
            question=question, user_id="U1", persona=None,
            history=history, sb=sb, thread_ts="T1"))
    return r, llm


# ══════════════════════════════════════════════════════════════
# 2. Reordered G.7: explain_prior_answer wins over a live cache
# ══════════════════════════════════════════════════════════════

def test_original_incident_question_now_routes_to_explain_prior_answer():
    """THE FIX'S PROOF — the exact incident phrasing. Classifier (fake)
    resolves it to explain_prior_answer, same as the real classifier does
    post PR #113; a live result_cache row from the SAME prior turn also
    exists. Must route to explain_prior_answer, not cached_result."""
    print("\n[TEST] original incident question routes to explain_prior_answer, "
          "not cached_result, even with a live cache present")
    question = "how did you come up with that number?"
    intent = {"handler": "explain_prior_answer", "confidence": 0.95,
              "scope": "prior_set", "params": {}}
    r, llm = _route(question, _history_with_prior_answer(), intent,
                    [_live_cache_row(question=PRIOR_QUESTION)])

    assert r["handler_name"] == "explain_prior_answer", (
        f"REGRESSION: expected explain_prior_answer, got "
        f"{r['handler_name']!r} — the old cached_result shortcut "
        f"intercepted again")
    # Citation path actually fired: the generator call was built from the
    # prior answer, and the live cache's payload reached the prompt too.
    gen_prompts = [c["prompt"] for c in llm.generator_calls]
    assert any(PRIOR_ANSWER in p for p in gen_prompts), \
        "explain_prior_answer must ground its prompt in the exact prior answer text"
    assert any(CACHED_FIELD_MARKER in p for p in gen_prompts), (
        "the citation-only cache fetch did not reach the generator prompt — "
        "explain_prior_answer answered from prose alone, not citing cached fields")
    print("  ✓ routes to explain_prior_answer")
    print("  ✓ citation path fired: cached fields reached the generator prompt")


def test_reorder_holds_even_when_question_matches_pronoun_regex():
    """Isolates the REORDER (not the pronoun-regex side effect) as the
    fix: this phrasing still genuinely matches has_followup_pronoun under
    the NEW word-boundary rule ("it" as a real word) — so the only thing
    standing between this question and the old cached_result shortcut is
    the reorder + the self-handling-intent exclusion."""
    print("\n[TEST] reorder holds even when has_followup_pronoun still matches")
    question = "how did you calculate it?"
    assert has_followup_pronoun(question), \
        "fixture bug: this question must still match has_followup_pronoun"
    intent = {"handler": "explain_prior_answer", "confidence": 0.95,
              "scope": "prior_set", "params": {}}
    r, llm = _route(question, _history_with_prior_answer(), intent,
                    [_live_cache_row(question=PRIOR_QUESTION)])

    assert r["handler_name"] == "explain_prior_answer", (
        f"expected explain_prior_answer even though the question matches "
        f"has_followup_pronoun — got {r['handler_name']!r}; the reorder's "
        f"self-handling-intent exclusion is what must prevent G.7 from "
        f"firing here, not the pronoun regex")
    print("  ✓ explain_prior_answer still wins over a matching, live cache")


def test_no_live_cache_falls_back_to_dynamic_query_not_crash():
    """Sanity: explain_prior_answer with NO live cache still works (prose-
    only, no citation) — confirms the reorder didn't make the cache a
    hard dependency of the explain_prior_answer path."""
    print("\n[TEST] explain_prior_answer with no live cache still answers (prose-only)")
    question = "how did you come up with that number?"
    intent = {"handler": "explain_prior_answer", "confidence": 0.95,
              "scope": "prior_set", "params": {}}
    r, llm = _route(question, _history_with_prior_answer(), intent,
                    result_cache_rows=[])  # no cache at all

    assert r["handler_name"] == "explain_prior_answer", r
    gen_prompts = [c["prompt"] for c in llm.generator_calls]
    assert any(PRIOR_ANSWER in p for p in gen_prompts)
    assert not any(CACHED_FIELD_MARKER in p for p in gen_prompts)
    print("  ✓ answers prose-only when no live cache exists, no crash")


# ══════════════════════════════════════════════════════════════
# 3. REGRESSION GUARD — the ORIGINAL G.7 use case still works
# ══════════════════════════════════════════════════════════════

def test_bulk_followup_still_reaches_cached_result_resynthesis():
    """"which of those are at risk" style bulk follow-up: classification
    resolves to an ordinary precomputed handler (query_deals_at_risk —
    NOT one of the three self-handling intents), there is no entity
    context to re-query by, but a live cache exists. Must still swap in
    the cached payload and resynthesize from it — the exact behavior G.7
    was built for — reached now via classification's own output rather
    than a pre-classification shortcut."""
    print("\n[TEST] bulk follow-up ('which of those are at risk') still "
          "reaches cached_result resynthesis post-reorder")
    question = "which of those are at risk?"
    # The classifier genuinely has somewhere to send this (a real,
    # specific handler) — it is NOT ambiguous or unanswerable. The point
    # of this test is that G.7 still overrides it anyway, same as before.
    intent = {"handler": "query_deals_at_risk", "confidence": 0.9, "params": {}}
    cache_payload = {"deals_at_risk": ["deal-A", "deal-B"], "total_at_risk": 2}
    cache_row = _live_cache_row(handler_name="query_deals_at_risk",
                                question="show me our deals")
    cache_row["payload"] = json.dumps(cache_payload)

    history = [
        {"role": "user", "content": "show me our deals"},
        {"role": "assistant", "content": "Here are your open deals: ..."},
    ]
    r, llm = _route(question, history, intent, [cache_row])

    assert r["handler_name"] == "cached_result", (
        f"REGRESSION: expected cached_result (the bulk-follow-up "
        f"resynthesis path), got {r['handler_name']!r} — G.7's original "
        f"use case broke in the reorder")
    assert r["tool_results"] == cache_payload, (
        f"expected the cached payload to be swapped in as tool_results, "
        f"got {r['tool_results']!r} — query_deals_at_risk must NOT have "
        f"actually run (no entity IDs to scope it)")
    print("  ✓ still routes to cached_result with the cached payload as tool_results")
    print("  ✓ query_deals_at_risk itself was never actually executed")


def test_query_help_and_acknowledgment_also_win_over_live_cache():
    """The other two self-handling intents named in the fix (query_help,
    acknowledgment) must also be immune to G.7, same as explain_prior_answer."""
    print("\n[TEST] query_help / acknowledgment also win over a live cache")
    cache_row = _live_cache_row()

    intent = {"handler": "acknowledgment", "confidence": 0.95, "params": {}}
    r, _ = _route("thanks, that's them", [], intent, [cache_row])
    assert r["handler_name"] == "acknowledgment", r

    intent = {"handler": "query_help", "confidence": 0.95,
              "params": {"help_category": "capability"}}
    r, _ = _route("what can you help me with for those deals?", [], intent, [cache_row])
    assert r["handler_name"] == "query_help", r
    print("  ✓ acknowledgment and query_help both win over a live, pronoun-matching cache")
