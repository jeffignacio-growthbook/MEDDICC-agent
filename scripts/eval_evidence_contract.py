#!/usr/bin/env python3
"""
Eval: evidence surfacing (Part 4) + score reframe (Part 6) of
FIX_MEDDICC_SCORING_PIPELINE.

IMPORTANT design note (why this isn't the literal Part 4 spec):
Part 4 asked for a per-component evidence+Gap contract IN THE GENERATOR OUTPUT.
Adding Gap/dated-evidence directives to the generator prompt was implemented,
and the mandatory determinism re-run (Part 1's gate) caught that it reintroduced
non-determinism in the one genuinely-borderline component, champion (spread 2,
then 3, across two wordings; the other six components stayed spread 0). Naming a
band gap for a borderline component tips its score at temperature 0. Per the
task's own rule — determinism first, and "less variance" ≠ deterministic — the
generator-side change was reverted.

Resolution: the generator keeps its pre-existing, deterministic per-component
"Evidence from calls" field; the evidence/gap presentation moves to the
SYNTHESIS layer (build_synthesis_prompt), where it is actually consumed and
cannot perturb a score. This eval enforces that split, and guards against a
regression that would put a score-perturbing Gap directive back in the
generator prompt.
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


def test_generator_keeps_evidence_but_stays_deterministic():
    """The generator prompt carries per-component evidence (7 components) but
    must NOT carry a score-perturbing Gap directive — that broke champion
    determinism and was reverted."""
    md = (REPO / "prompts" / "CLAUDE.md").read_text()
    return [
        ("per-component 'Evidence from calls' present (>=7)",
         md.count("**Evidence from calls**") >= 7),
        ("no generator-side **Gap** directive (determinism regression guard)",
         "**Gap**:" not in md),
        ("no generator-side dated-evidence directive (regression guard)",
         "WITH the call date" not in md),
    ]


def test_synthesis_surfaces_evidence_and_gaps():
    """The evidence/gap contract lives at the synthesis layer now: lead with
    weakest components + gaps, show evidence, total secondary, and read
    no-evidence as unread not weak (Parts 4 goal + 6)."""
    from api.router import build_synthesis_prompt
    p = build_synthesis_prompt({"role_group": "sales_leadership", "name": "Ryan"})
    pl = p.lower()
    return [
        ("leads with the weakest components", "weakest" in pl),
        ("surfaces the gap, not just a grade", "gap" in pl),
        ("shows component evidence", "evidence" in pl),
        ("total is secondary", "secondary" in pl),
        ("never a percentage of 100",
         "never as a percentage of 100" in pl or "not 0-100" in pl),
        ("no-evidence reads as unread, not weak", "unread" in pl),
    ]


def run():
    print("=" * 72)
    print("EVIDENCE SURFACING (Part 4, synthesis-layer) + REFRAME (Part 6)")
    print("=" * 72)
    passed = failed = 0
    for title, fn in (
        ("generator keeps evidence, stays deterministic (no Gap directive)",
         test_generator_keeps_evidence_but_stays_deterministic),
        ("synthesis surfaces evidence + gaps, total secondary",
         test_synthesis_surfaces_evidence_and_gaps),
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
