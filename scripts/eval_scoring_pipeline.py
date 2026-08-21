#!/usr/bin/env python3
"""
Eval: MEDDICC scoring-pipeline determinism guards
(FIX_MEDDICC_SCORING_PIPELINE, Parts 1-3, static/offline).

The generator was sampling, not scoring: on frozen evidence Livesport swung
±6 across nights. Root causes, each guarded here:
  P1  scored from ONE recent call + the previous run's output → drift compounds.
      Fix: score from ALL calls; prior state is change-detection context only.
  P2  no temperature set → API default 1.0 → sampling noise.
      Fix: temperature=0 on the generator and evaluator (scoring-path) calls.
  P3  deal stage fed into the scoring prompt → a stale stage corrupts the score
      and breaks score/stage independence.
      Fix: stage removed from the prompt.

These are offline checks (prompt shape + source). The determinism itself is
proven live by verify_scoring_determinism.py (5 runs, CI).
"""
import re
import sys
import types
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
for p in ("", "scripts", "api"):
    sys.path.insert(0, str(REPO / p) if p else str(REPO))

if "anthropic" not in sys.modules:
    _a = types.ModuleType("anthropic")
    _a.Anthropic = type("Anthropic", (), {})
    sys.modules["anthropic"] = _a


def _prompt():
    from meddicc_agent import build_initial_messages
    deal_context = {
        "deal": {"properties": {
            "dealstage": "ZZSTAGE_SENTINEL_SCOPING", "amount": "260000",
            "closedate": "2027-01-01"}},
        "company": {"properties": {"name": "Livesport"}},
        "contacts": [{"properties": {"firstname": "Tomas"}}],
    }
    cumulative = {"company": "Livesport", "meddicc_state": {
        "champion": {"score": 7, "evidence": "prior run said 7"}}}
    msgs = build_initial_messages(
        call_summary="## Call — 2026-08-05\n\n" + ("x" * 200),
        cumulative_state=cumulative, deal_context=deal_context)
    return msgs[0]["content"]


def test_scoring_prompt_excludes_stage():
    """The scoring prompt must not contain deal stage. Stage is stale often
    enough to corrupt the score, and score/stage independence is required for
    the stage-hygiene comparison to mean anything."""
    p = _prompt()
    return [
        ("stage value not in prompt", "ZZSTAGE_SENTINEL_SCOPING" not in p),
        ("no **Stage** label in prompt", "**Stage**" not in p),
        ("deal facts still present (ARR/close/contacts)",
         "ARR" in p and "Close Date" in p and "Contacts" in p),
    ]


def test_prior_state_is_change_detection_only():
    """cumulative_state must be framed as change context, explicitly excluded
    from scoring (Part 1)."""
    p = _prompt().lower()
    return [
        ("prior state marked must-not-influence",
         "must not influence" in p),
        ("instructs to score fresh from the calls",
         "fresh" in p and "from the calls" in p),
        ("all-calls evidence is the scoring source",
         "all calls for this deal" in p and "only from" in p),
    ]


def test_scoring_calls_use_temperature_zero():
    """generate() and evaluate() (scoring path) pin temperature=0; the
    reflection gate (learning path, not scoring) is left as-is (Part 2)."""
    src = (REPO / "scripts" / "meddicc_agent.py").read_text()

    def _call_body(fn_name):
        m = re.search(rf"def {fn_name}\(.*?\n(?=\ndef |\Z)", src, re.DOTALL)
        return m.group(0) if m else ""

    gen = _call_body("generate")
    ev = _call_body("evaluate")
    ref = _call_body("reflect")
    results = [
        ("generate() passes temperature=0", "temperature=0" in gen),
        ("evaluate() passes temperature=0", "temperature=0" in ev),
        ("reflect() left un-pinned (not scoring path)",
         "temperature=0" not in ref),
    ]
    # And the client actually forwards temperature to the API.
    llm = (REPO / "scripts" / "llm_client.py").read_text()
    results.append(("llm_client forwards temperature to Anthropic",
                    'kwargs["temperature"] = temperature' in llm))
    return results


def run():
    print("=" * 72)
    print("MEDDICC SCORING PIPELINE — determinism guards (offline)")
    print("=" * 72)
    passed = failed = 0
    for title, fn in (
        ("PART 3 — stage excluded from scoring prompt",
         test_scoring_prompt_excludes_stage),
        ("PART 1 — prior state is change-detection only",
         test_prior_state_is_change_detection_only),
        ("PART 2 — scoring-path calls pinned to temperature 0",
         test_scoring_calls_use_temperature_zero),
    ):
        print(f"\n[{title}]")
        for label, ok in fn():
            if ok:
                passed += 1; print(f"  ✓ {label}")
            else:
                failed += 1; print(f"  ❌ {label}")
    print("\n" + "=" * 72)
    print(f"RESULTS: {passed} passed, {failed} failed")
    print("=" * 72)
    return 0 if failed == 0 else 1


if __name__ == "__main__":
    sys.exit(run())
