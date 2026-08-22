#!/usr/bin/env python3
"""
Eval: evidence contract (Part 4) + score-reframe (Part 6) of
FIX_MEDDICC_SCORING_PIPELINE.

Part 4 — every component in the generator's output must carry the evidence it
was scored from (a dated quote/fact), or an explicit "not discussed in any
call", plus a Gap. A bare number invites an argument nobody can settle; the
evidence line is the debugging surface.

Part 6 — the Slack synthesis reframes a deal's MEDDICC as "what's missing", not
a grade: lead with the weakest components and their gaps, total is secondary,
never /100, and "not discussed" reads as unread, not weak.

Offline: asserts the prompts carry the contract. (Whether the generator obeys
it is checked live by the nightly + the determinism harness.)
"""
import sys
import types
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
for p in ("", "scripts", "api"):
    sys.path.insert(0, str(REPO / p) if p else str(REPO))

if "supabase" not in sys.modules:
    _f = types.ModuleType("supabase")
    _f.create_client = lambda *a, **k: None
    _f.Client = type("Client", (), {})
    sys.modules["supabase"] = _f


def test_generator_prompt_requires_evidence_and_gap():
    """prompts/CLAUDE.md mandates dated evidence, explicit not-discussed, and a
    Gap line for every one of the 7 components (Part 4)."""
    md = (REPO / "prompts" / "CLAUDE.md").read_text()
    lower = md.lower()
    return [
        ("evidence must carry the call date",
         "with the call date" in lower),
        ("explicit no-evidence sentinel present",
         "not discussed in any call" in lower),
        ("distinguishes low-with-evidence from no-evidence",
         "different" in lower and "evidence" in lower),
        ("a Gap line for every component (7)",
         md.count("**Gap**:") >= 7),
        ("gap uses the rubric's band language",
         "band language" in lower),
    ]


def test_synthesis_reframes_score_as_gaps():
    """build_synthesis_prompt leads with weakest components + gaps, keeps the
    total secondary, and treats 'not discussed' as unread (Part 6)."""
    from api.router import build_synthesis_prompt
    p = build_synthesis_prompt({"role_group": "sales_leadership", "name": "Ryan"})
    pl = p.lower()
    return [
        ("leads with the weakest components", "weakest" in pl),
        ("leads with gaps, not a grade", "gap" in pl),
        ("total is secondary, after the gaps", "secondary" in pl),
        ("never a percentage of 100", "never as a percentage of 100" in pl
         or "not 0-100" in pl),
        ("'not discussed' reads as unread, not weak",
         "unread" in pl and "not discussed in any call" in pl),
    ]


def run():
    print("=" * 72)
    print("EVIDENCE CONTRACT (Part 4) + SCORE REFRAME (Part 6)")
    print("=" * 72)
    passed = failed = 0
    for title, fn in (
        ("PART 4 — generator output carries evidence + gap per component",
         test_generator_prompt_requires_evidence_and_gap),
        ("PART 6 — synthesis reframes score as what's-missing",
         test_synthesis_reframes_score_as_gaps),
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
