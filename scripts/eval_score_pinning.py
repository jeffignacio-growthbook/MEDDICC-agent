#!/usr/bin/env python3
"""
Eval: score-of-record pinned to iteration 1. Offline.

Regeneration must never move the numbers. These checks cover the two
mechanisms: (a) the regeneration prompt states the locked values explicitly and
last, and (b) the post-loop rewrite forces the stored draft's Score lines to the
iteration-1 values, so an LLM drift can't ship a two-provenance artifact.
"""
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
for p in ("", "scripts", "api"):
    sys.path.insert(0, str(REPO / p) if p else str(REPO))

_DRAFT = """# MEDDICC Analysis: Acme

### M - Metrics
**Score**: 8/10
Evidence...

### E - Economic Buyer
**Score**: 4/10
Evidence...

### D - Decision Criteria
**Score**: 7/10

### D - Decision Process
**Score**: 7/10

### I - Identified Pain
**Score**: 9/10

### C - Champion
**Score**: 5/10
Tomas organises the eval.

### C - Competition
**Score**: 7/10
"""

# Same deal, regenerated: champion has drifted 5 → 2 and metrics 8 → 6.
_DRIFTED = _DRAFT.replace("### C - Champion\n**Score**: 5/10",
                          "### C - Champion\n**Score**: 2/10").replace(
                          "### M - Metrics\n**Score**: 8/10",
                          "### M - Metrics\n**Score**: 6/10")


def run():
    from meddicc_agent import (_extract_component_scores, _pin_score_lines,
                               build_initial_messages)
    print("=" * 72)
    print("SCORE PINNING — iteration-1 numbers are the score of record")
    print("=" * 72)
    passed = failed = 0

    def check(label, cond):
        nonlocal passed, failed
        if cond:
            passed += 1; print(f"  ✓ {label}")
        else:
            failed += 1; print(f"  ❌ {label}")

    s = _extract_component_scores(_DRAFT)
    print("\n[extraction]")
    check("champion 5, metrics 8, competition 7",
          s["champion"] == 5 and s["metrics"] == 8 and s["competition"] == 7)

    # Pin a drifted (iteration-3) draft back to iteration-1 values.
    pinned = {"champion": 5, "metrics": 8, "economic_buyer": 4,
              "decision_criteria": 7, "decision_process": 7, "pain": 9,
              "competition": 7}
    fixed, mism = _pin_score_lines(_DRIFTED, pinned)
    after = _extract_component_scores(fixed)
    print("\n[pin rewrite: drifted iter-3 draft → iter-1 numbers]")
    check("champion forced 2 → 5", after["champion"] == 5)
    check("metrics forced 6 → 8", after["metrics"] == 8)
    check("no mismatches after pin", mism == [])
    check("prose left intact (Tomas line survives)", "Tomas organises the eval." in fixed)

    # None-valued components are skipped, not crashed.
    partial = dict(pinned); partial["champion"] = None
    fixed2, mism2 = _pin_score_lines(_DRIFTED, partial)
    print("\n[partial pin: champion unknown from iter 1]")
    check("champion left as-is when unpinnable (2)",
          _extract_component_scores(fixed2)["champion"] == 2)
    check("metrics still pinned (8)",
          _extract_component_scores(fixed2)["metrics"] == 8)

    # Format tolerance: the model varies markdown between iterations. Extraction
    # AND rewrite must handle **Score**:, **Score:**, and 'Score: N / 10'. This
    # is the economic_buyer bug the acceptance gate caught: the brittle pattern
    # matched the iteration-1 draft but silently no-op'd the rewrite on an
    # iteration-3 draft that used '**Score:**'.
    variants = (
        "### E - Economic Buyer\n**Score:** 5/10\n"      # colon inside bold
        "### C - Champion\n**Score**: 5/10\n"            # colon outside bold
        "### C - Competition\nScore: 7 / 10\n")          # spaces around slash
    ev = _extract_component_scores(variants)
    print("\n[format tolerance: **Score:** / **Score**: / spaced slash]")
    check("**Score:** parsed (economic_buyer 5)", ev["economic_buyer"] == 5)
    check("'Score: 7 / 10' parsed (competition 7)", ev["competition"] == 7)
    fixed3, mism3 = _pin_score_lines(variants, {"economic_buyer": 3})
    check("rewrite works on **Score:** (econ 5 → 3, no mismatch)",
          _extract_component_scores(fixed3)["economic_buyer"] == 3 and mism3 == [])

    # Regeneration prompt must list the locked values and forbid changing them.
    msgs = build_initial_messages("calls", {"company": "Acme"}, {"company": {"properties": {"name": "Acme"}}},
                                  previous_feedback="Champion should be 2, not 5.",
                                  pinned_scores=pinned)
    body = msgs[0]["content"]
    print("\n[regeneration prompt with pinned scores]")
    check("declares scores FINAL", "SCORES ARE FINAL" in body or "DO NOT CHANGE" in body)
    check("lists the locked champion value (5)", "Champion: 5/10" in body)
    check("tells model to keep number even if feedback disagrees",
          "do NOT change the number" in body or "score never moves" in body)

    # No pinned_scores (iteration 1) → no lock block.
    msgs1 = build_initial_messages("calls", {"company": "Acme"}, {"company": {"properties": {"name": "Acme"}}},
                                   previous_feedback=None, pinned_scores=None)
    check("iteration-1 prompt has no lock block",
          "SCORES ARE FINAL" not in msgs1[0]["content"])

    print("\n" + "=" * 72)
    print(f"RESULTS: {passed} passed, {failed} failed")
    print("=" * 72)
    return 0 if failed == 0 else 1


if __name__ == "__main__":
    sys.exit(run())
