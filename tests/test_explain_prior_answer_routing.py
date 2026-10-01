"""
Tests for the explain_prior_answer handler — the fix for tonight's
(2026-10-01) misroute of "how did you come up with that number?" to
query_help/prompt_seeking at 0.95 confidence.

Root cause (diagnosed earlier this session): no intent category existed for
"explain how a prior figure was produced." The classifier pattern-matched
the surface phrasing ("how do...") onto prompt_seeking's own trigger
examples ("how do I use this"), because prompt_seeking has no concept of an
antecedent to rule it out. params["prior_answer_context"] WAS already being
captured (scope=prior_set, no entities) but was never read by any handler —
query_help's branch short-circuits to canned onboarding text before params
is ever consulted.

Fix: a new explain_prior_answer handler, a contrastive classifier
description distinguishing it from prompt_seeking (antecedent vs. no
antecedent), and a lightweight response builder that reads
prior_answer_context and re-explains it — never re-derives a fresh number,
and is explicit when a requested detail wasn't printed in the prior answer.

Test groups:
  OFFLINE (deterministic, no live LLM — always runnable in CI):
    1. Static: explain_prior_answer is registered, with the contrast text
       against prompt_seeking present in the classifier prompt.
    2. The response builder actually grounds its LLM call in the prior
       answer's exact text — doesn't invent a parallel data path.

  LIVE (calls the real classifier/generator — matches tests/
  test_scope_decision.py's existing convention of a live-LLM routing test;
  requires ANTHROPIC_API_KEY / network and will fail in a credential-less
  sandbox, same as test_scope_decision.py does today. Validated by the real
  Pre-Merge Gate CI run, not this offline suite.):
    3. Reproduce tonight's exact exchange as a fixture — confirm it now
       routes to explain_prior_answer, not query_help.
    4. Confirm prompt_seeking's genuine triggers still route correctly
       (no regression on real onboarding questions).
    5. Planted-bug control: the ORIGINAL (pre-fix) classifier wording,
       run against the identical fixture, reproduces the bug — proving
       the new wording is what fixes it, not an unrelated change.
"""
import sys
import types
from pathlib import Path
from unittest.mock import MagicMock

REPO = Path(__file__).resolve().parents[1]
for p in ("", "scripts", "scripts/analytics", "api"):
    sys.path.insert(0, str(REPO / p) if p else str(REPO))

# router imports supabase + LLMClient at module load; stub the heavy dep,
# matching scripts/eval_help_handler.py's convention.
if "supabase" not in sys.modules:
    _fake = types.ModuleType("supabase")
    _fake.create_client = lambda *a, **k: None
    _fake.Client = type("Client", (), {})
    sys.modules["supabase"] = _fake

from api import router  # noqa: E402
from api.router import (  # noqa: E402
    HANDLER_DESCRIPTIONS, build_intent_prompt,
    build_explain_prior_answer_response,
)

# ── Tonight's exact exchange, reproduced as a fixture ──────────────────
PRIOR_ANSWER_FIXTURE = (
    "Pipeline coverage for FY2027 Q3 is $779,000 weighted against a "
    "$1,037,000 quota gap, a 0.75x coverage ratio. That's short of the "
    "1.5-2x range leadership typically wants to see with 4 weeks left "
    "in the quarter."
)
FOLLOWUP_QUESTION = "how did you come up with that number?"


# ══════════════════════════════════════════════════════════════
# OFFLINE — deterministic, no live LLM
# ══════════════════════════════════════════════════════════════

def test_explain_prior_answer_is_registered():
    """The new category exists and is distinct from query_help."""
    print("\n[TEST] explain_prior_answer is a registered handler")
    assert "explain_prior_answer" in HANDLER_DESCRIPTIONS
    assert "query_help" in HANDLER_DESCRIPTIONS
    desc = HANDLER_DESCRIPTIONS["explain_prior_answer"]
    assert "antecedent" in desc.lower(), \
        "description should name the antecedent test distinguishing it " \
        "from prompt_seeking"
    print("  ✓ explain_prior_answer registered with antecedent-based description")


def test_intent_prompt_carries_contrast_with_prompt_seeking():
    """
    PLANTED-DISCREPANCY PROOF (static): the production classifier prompt
    must literally contain the contrastive language that separates
    explain_prior_answer from prompt_seeking — this is the exact fix for
    tonight's 0.95-confidence misroute. If this text were stripped, this
    assertion (not just the live routing test below) would catch it
    immediately, without needing network access.
    """
    print("\n[TEST] intent prompt carries explain_prior_answer vs "
          "prompt_seeking contrast")
    prompt = build_intent_prompt(
        today="2026-10-01", current_quarter="FY2027 Q3",
        history="[]", question=FOLLOWUP_QUESTION, roster_text="")

    assert "explain_prior_answer" in prompt
    assert "antecedent" in prompt.lower()
    # The query_help description's own NEVER-prompt_seeking carve-out:
    assert "NEVER classify as prompt_seeking" in prompt
    # Scope decision must tie explain_prior_answer to prior_set:
    assert "explain_prior_answer" in prompt and "prior_set" in prompt
    print("  ✓ classifier prompt literally carries the antecedent "
          "distinction and the prior_set scope tie-in")


def test_builder_grounds_prompt_in_prior_answer_text():
    """
    The response builder must pass the EXACT prior answer text and the
    EXACT follow-up question into the generator call — this is what makes
    the explanation grounded rather than a free-floating re-derivation.
    Proven by inspecting the actual prompt sent, not just the response.
    """
    print("\n[TEST] builder grounds its LLM call in the prior answer's "
          "exact text")
    mock_client = MagicMock()
    mock_resp = MagicMock()
    mock_resp.text = ("The $779K figure is the stage-weighted pipeline "
                      "total already shown above; 0.75x is that figure "
                      "divided by the $1,037,000 gap.")
    mock_client.complete.return_value = mock_resp

    result = build_explain_prior_answer_response(
        FOLLOWUP_QUESTION, PRIOR_ANSWER_FIXTURE, mock_client)

    mock_client.complete.assert_called_once()
    sent_messages = mock_client.complete.call_args.kwargs["messages"]
    sent_prompt = sent_messages[0]["content"]

    assert PRIOR_ANSWER_FIXTURE in sent_prompt, \
        "the exact prior answer text must be passed to the generator"
    assert FOLLOWUP_QUESTION in sent_prompt, \
        "the exact follow-up question must be passed to the generator"
    assert "Do NOT invent" in sent_prompt, \
        "the anti-hallucination instruction must be present"
    assert result == mock_resp.text.strip()
    print("  ✓ builder passes prior answer + question verbatim, with the "
          "anti-fabrication instruction, and returns the grounded response")


def test_builder_system_prompt_forbids_fabrication():
    """The system prompt itself (not just the user message) must forbid
    inventing unprinted numbers — defense in depth against the LLM
    rationalizing a plausible-looking but fabricated intermediate value."""
    print("\n[TEST] builder's system prompt forbids fabricating numbers")
    mock_client = MagicMock()
    mock_resp = MagicMock()
    mock_resp.text = "placeholder"
    mock_client.complete.return_value = mock_resp

    build_explain_prior_answer_response(
        FOLLOWUP_QUESTION, PRIOR_ANSWER_FIXTURE, mock_client)

    sent_system = mock_client.complete.call_args.kwargs["system"]
    assert "never invent" in sent_system.lower()
    print("  ✓ system prompt explicitly forbids inventing numbers")


# ══════════════════════════════════════════════════════════════
# LIVE — real classifier/generator calls.
# Matches tests/test_scope_decision.py's existing convention: these
# exercise the ACTUAL classifier, not a mock, because "does the classifier
# now route X correctly" is a behavioral claim about the live model that a
# mock cannot verify. Expected to fail in a credential-less sandbox (no
# ANTHROPIC_API_KEY/.env) — validated by the real Pre-Merge Gate CI run,
# which has the real secret, not by this offline suite.
# ══════════════════════════════════════════════════════════════

def _classify(question: str, history_json: str = "[]") -> dict:
    """Run the REAL production classifier prompt (build_intent_prompt) and
    parse its JSON response, exactly as _route_question does."""
    from llm_client import LLMClient
    from api.router import _extract_json

    client = LLMClient.from_config(role="classifier")
    resp = client.complete(
        messages=[{"role": "user", "content": build_intent_prompt(
            today="2026-10-01", current_quarter="FY2027 Q3",
            history=history_json, question=question, roster_text="")}],
        system="Respond with valid JSON only. No markdown, no backticks, "
               "no explanation.",
        max_tokens=600,
    )
    return _extract_json(resp.text)


def _history_with_prior_answer(prior_answer: str) -> str:
    import json
    return json.dumps([
        {"role": "user", "content": "what's our pipeline coverage this quarter?"},
        {"role": "assistant", "content": prior_answer},
    ])


def test_tonights_exchange_routes_to_explain_prior_answer_not_query_help():
    """
    THE FIX'S PROOF. Reproduce tonight's exact failing exchange: the
    $779K/0.75x coverage answer, followed by "how did you come up with
    that number?". Must now route to explain_prior_answer with
    scope=prior_set, not query_help/prompt_seeking.
    """
    print("\n[TEST] tonight's exchange routes to explain_prior_answer")
    intent = _classify(FOLLOWUP_QUESTION,
                       _history_with_prior_answer(PRIOR_ANSWER_FIXTURE))
    assert intent is not None, "classifier response failed to parse as JSON"
    print(f"  classifier returned: handler={intent.get('handler')} "
          f"scope={intent.get('scope')} confidence={intent.get('confidence')}")
    assert intent.get("handler") == "explain_prior_answer", (
        f"REGRESSION: expected handler=explain_prior_answer, got "
        f"{intent.get('handler')!r} — this is the exact misroute tonight's "
        f"incident reported (query_help/prompt_seeking at 0.95 confidence)")
    assert intent.get("scope") == "prior_set", (
        f"expected scope=prior_set (explain_prior_answer always refers to "
        f"the prior turn), got {intent.get('scope')!r}")
    print("  ✓ routes to explain_prior_answer, scope=prior_set")


def test_prompt_seeking_genuine_examples_still_route_correctly():
    """
    REGRESSION GUARD: genuine orientation questions with NO prior answer
    must still route to query_help — the new category must not swallow
    real onboarding questions.
    """
    print("\n[TEST] genuine prompt_seeking examples still route to query_help")
    genuine_prompt_seeking = [
        "what should I ask you?",
        "where do I start?",
        "I don't know what to ask, give me some examples",
        "how do I use this?",
    ]
    for q in genuine_prompt_seeking:
        intent = _classify(q, history_json="[]")  # no prior answer at all
        assert intent is not None, f"classifier response failed to parse for {q!r}"
        assert intent.get("handler") == "query_help", (
            f"REGRESSION: {q!r} (genuine orientation, no prior answer) "
            f"should route to query_help, got {intent.get('handler')!r} — "
            f"explain_prior_answer must not swallow questions with no "
            f"antecedent")
        print(f"  ✓ {q!r} → query_help")


def test_planted_bug_old_prompt_without_fix_misclassifies():
    """
    PLANTED-DISCREPANCY PROOF (live): run tonight's exact exchange through
    the ORIGINAL (pre-fix) classifier wording — no explain_prior_answer
    category, no antecedent contrast. Confirm it reproduces the bug
    (misroutes to query_help), proving the fix above is actually what
    resolves it, not an unrelated change.
    """
    print("\n[TEST] planted bug: pre-fix prompt wording reproduces tonight's misroute")
    from llm_client import LLMClient
    from api.router import _extract_json

    # Literal pre-fix query_help description (captured before this session's
    # edit) — no explain_prior_answer category exists in this handler list.
    old_handlers_text = (
        "  query_help                - The person is orienting, not asking "
        "a data question — a greeting, asking what the assistant can do, "
        "asking what they should ask, or recovering from a bad answer. Set "
        "params.help_category to one of: 'greeting' (hi, hey, hello), "
        "'capability' (what can you do, how does this work), "
        "'prompt_seeking' (what should I ask you, give me examples, where "
        "do I start, I don't know what to ask, how do I use this), "
        "'recovery' (ONLY for explicit error statements).\n"
        "  dynamic_query             - question requires combining data "
        "from multiple tables or filters not covered by the precomputed "
        "handlers above.\n"
    )
    old_prompt = f"""Classify this Slack question into one of
these handler types. Reply with JSON only.

Handlers:
{old_handlers_text}

Required JSON:
{{
  "handler": "<handler_name>",
  "scope": "<prior_set|new_population|full_scope>",
  "confidence": 0.0-1.0
}}

Today is 2026-10-01. Current quarter: FY2027 Q3.

Conversation history (for follow-up context):
{_history_with_prior_answer(PRIOR_ANSWER_FIXTURE)}

Question: {FOLLOWUP_QUESTION}"""

    client = LLMClient.from_config(role="classifier")
    resp = client.complete(
        messages=[{"role": "user", "content": old_prompt}],
        system="Respond with valid JSON only. No markdown, no backticks, "
               "no explanation.",
        max_tokens=300,
    )
    intent = _extract_json(resp.text)
    assert intent is not None, "old-prompt classifier response failed to parse"
    print(f"  old-prompt classifier returned: handler={intent.get('handler')}")

    if intent.get("handler") != "query_help":
        raise AssertionError(
            "Test setup error: the planted pre-fix prompt did NOT reproduce "
            "tonight's bug (expected it to misroute to query_help) — this "
            "control is not actually demonstrating the failure mode, so it "
            "cannot prove the fix is load-bearing")
    print("  ✓ pre-fix wording reproduces the bug (confirms the fix above "
          "is what actually resolves it, not a coincidental change)")


def main():
    offline_tests = [
        test_explain_prior_answer_is_registered,
        test_intent_prompt_carries_contrast_with_prompt_seeking,
        test_builder_grounds_prompt_in_prior_answer_text,
        test_builder_system_prompt_forbids_fabrication,
    ]
    live_tests = [
        test_tonights_exchange_routes_to_explain_prior_answer_not_query_help,
        test_prompt_seeking_genuine_examples_still_route_correctly,
        test_planted_bug_old_prompt_without_fix_misclassifies,
    ]

    failed = []
    for t in offline_tests + live_tests:
        try:
            t()
        except Exception as e:
            failed.append((t.__name__, str(e)))
            print(f"\n  ❌ FAILED: {e}")

    print("\n" + "=" * 70)
    print("TEST SUMMARY")
    print("=" * 70)
    total = len(offline_tests) + len(live_tests)
    passed = total - len(failed)
    print(f"\nTotal tests: {total} ({len(offline_tests)} offline, "
          f"{len(live_tests)} live)")
    print(f"  ✓ Passed: {passed}")
    if failed:
        print(f"  ✗ Failed: {len(failed)}")
        for name, error in failed:
            print(f"  - {name}")
            print(f"    {error[:200]}")
        return 1
    print("\n✅ All explain_prior_answer tests passed")
    return 0


if __name__ == "__main__":
    sys.exit(main())
