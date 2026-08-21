#!/usr/bin/env python3
"""
Offline tests for the greeting / help / acknowledgment handler.

query_help builds its example set FROM THE HANDLER REGISTRY (never a hardcoded
prose list), is persona- and thread-aware, handles unknown persona explicitly,
and ends open. These tests lock those invariants without a live LLM: they
exercise the assembly + response builder directly and statically check that the
classifier prompt carries the disambiguation rules.
"""
import sys
import types
from pathlib import Path
from unittest.mock import patch

REPO = Path(__file__).resolve().parent.parent
for p in ("", "scripts", "scripts/analytics", "api"):
    sys.path.insert(0, str(REPO / p) if p else str(REPO))

# router imports supabase + LLMClient at module load; stub the heavy deps.
if "supabase" not in sys.modules:
    _fake = types.ModuleType("supabase")
    _fake.create_client = lambda *a, **k: None
    _fake.Client = type("Client", (), {})
    sys.modules["supabase"] = _fake

from api import router  # noqa: E402
from api.router import (build_help_response, _help_persona_tags,  # noqa: E402
                        _select_help_examples, HELP_EXAMPLES,
                        HANDLER_DESCRIPTIONS, build_intent_prompt)

REP = {"role_group": "ic", "name": "Rep One"}
CRO = {"role_group": "executive", "name": "Boss"}
OPS = {"role_group": "operational", "name": "RevOps"}


# ── the two registry invariants the spec names ────────────────────────

def test_help_examples_come_from_handler_registry():
    """query_help builds its examples from the registry, not a hardcoded list.
    Every bullet in a rendered response is a registry example verbatim."""
    print("\n[TEST] help examples come from the handler registry")
    assert HELP_EXAMPLES, "registry is empty"
    registry_examples = {m["example"] for m in HELP_EXAMPLES.values()}
    with patch.object(router, "is_admin", return_value=False):
        for persona in (REP, CRO, None):
            resp = build_help_response("capability", persona, "U1", [])
            bullets = [ln[2:] for ln in resp.splitlines() if ln.startswith("• ")]
            assert bullets, f"no examples rendered for {persona}"
            for b in bullets:
                assert b in registry_examples, \
                    f"rendered example {b!r} is not from the registry (hardcoded?)"
    print("  ✓ every rendered example is a registry entry, none hardcoded")


def test_every_help_example_maps_to_a_live_handler():
    """Each example's key is a handler that exists and is registered — no
    orphan suggestions that silently go stale when handlers change."""
    print("\n[TEST] every help example maps to a live, registered handler")
    for name in HELP_EXAMPLES:
        assert name in HANDLER_DESCRIPTIONS, \
            f"help example keyed to unregistered handler {name!r}"
    print(f"  ✓ all {len(HELP_EXAMPLES)} example handlers are registered")


# ── persona-aware ──────────────────────────────────────────────────────

def test_persona_filters_examples():
    print("\n[TEST] examples are filtered by persona")
    with patch.object(router, "is_admin", return_value=False):
        rep = build_help_response("capability", REP, "U1", [])
        cro = build_help_response("capability", CRO, "U2", [])
    # A rep-only example and a leadership-only example land in the right one.
    assert "How's the [company] deal looking?" in rep
    assert "How's the [company] deal looking?" not in cro
    assert "Where's the pipeline for this quarter?" in cro
    assert "Where's the pipeline for this quarter?" not in rep
    print("  ✓ rep sees deal-level, leadership sees pipeline/forecast")


def test_admin_sees_data_health():
    """Admin gets both persona sets plus the data-health example."""
    print("\n[TEST] admin sees data-health examples")
    with patch.object(router, "is_admin", return_value=True):
        tags = _help_persona_tags(OPS, "Uadmin")
        assert "admin" in tags
        # data-health example is admin-bucketed
        picked = dict(_select_help_examples(tags, limit=99))
        assert "dynamic_query" in picked, \
            "admin should see the data-health (dynamic_query) example"
    print("  ✓ admin bucket includes the data-health example")


def test_unknown_persona_is_explicit_not_silent():
    """A greeting from an unmapped user says so rather than degrading silently."""
    print("\n[TEST] unknown persona handled explicitly")
    with patch.object(router, "is_admin", return_value=False):
        resp = build_help_response("greeting", None, "U0AAMMUPSA2", [])
    assert "mapped to a role" in resp and "Ask Jeff" in resp, resp
    print("  ✓ unmapped user is told, not silently degraded")


# ── thread-aware ────────────────────────────────────────────────────────

def test_reconnection_is_shorter_than_first_contact():
    print("\n[TEST] returning thread gets a shorter greeting")
    with patch.object(router, "is_admin", return_value=False):
        first = build_help_response("greeting", REP, "U1", [])
        again = build_help_response("greeting", REP, "U1",
                                    [{"role": "user", "content": "hi"},
                                     {"role": "assistant", "content": "..."}])
    assert "Welcome back" in again
    assert len(again) < len(first), "reconnection should be shorter"
    print("  ✓ first contact is the full orientation; reconnection is short")


# ── framing per category + ends open ────────────────────────────────────

def test_category_framing_and_open_ending():
    print("\n[TEST] category framing differs; every response ends open")
    with patch.object(router, "is_admin", return_value=False):
        cap = build_help_response("capability", REP, "U1", [])
        seek = build_help_response("prompt_seeking", REP, "U1", [])
        rec = build_help_response("recovery", REP, "U1", [])
        greet = build_help_response("greeting", REP, "U1", [])
    assert not cap.startswith("Hi"), "capability should skip the welcome"
    assert seek.lstrip().startswith("Here's where people usually start"), \
        "prompt_seeking should lead with examples"
    assert ("reset" in rec.lower() or "sorry" in rec.lower()), \
        "recovery should acknowledge the miss first"
    for resp in (cap, seek, rec, greet):
        assert "describe what you're looking at" in resp, \
            "every orientation must end open, inviting the next message"
    print("  ✓ capability/prompt_seeking/recovery/greeting framed distinctly, all open")


# ── classifier prompt carries the routing rules (static) ─────────────────

def test_intent_prompt_carries_disambiguation_rules():
    print("\n[TEST] intent prompt carries greeting/help disambiguation rules")
    assert "query_help" in HANDLER_DESCRIPTIONS
    assert "acknowledgment" in HANDLER_DESCRIPTIONS
    prompt = build_intent_prompt(today="2026-08-21", current_quarter="FY2027 Q3",
                                 history="[]", question="hi", roster_text="")
    # greeting-plus-question routes on the question; "help me [task]" is a task;
    # help_category is offered to the classifier.
    assert "routes on the QUESTION" in prompt
    assert "help me [do a real thing]" in prompt
    assert "help_category" in prompt
    assert "acknowledgment" in prompt
    print("  ✓ whole-message weighing, task carve-out, and help_category present")


def main():
    print("=" * 70)
    print("GREETING / HELP HANDLER TESTS")
    print("=" * 70)
    tests = [
        test_help_examples_come_from_handler_registry,
        test_every_help_example_maps_to_a_live_handler,
        test_persona_filters_examples,
        test_admin_sees_data_health,
        test_unknown_persona_is_explicit_not_silent,
        test_reconnection_is_shorter_than_first_contact,
        test_category_framing_and_open_ending,
        test_intent_prompt_carries_disambiguation_rules,
    ]
    passed = failed = 0
    for t in tests:
        try:
            t(); passed += 1
        except Exception as e:
            failed += 1
            print(f"\n❌ {t.__name__}: {e}")
            import traceback; traceback.print_exc()
    print("\n" + "=" * 70)
    print(f"RESULTS: {passed} passed, {failed} failed")
    print("=" * 70)
    return 0 if failed == 0 else 1


if __name__ == "__main__":
    sys.exit(main())
