#!/usr/bin/env python3
"""
Eval: stage-vs-score hygiene classification (FIX_MEDDICC_SCORING_PIPELINE Part 5).

Pure, offline — drives classify() with synthetic component scores against the
real config ladder + stage_progression gates. No tuning: the bar is the gates
already in config.
"""
import sys
import types
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
for p in ("", "scripts", "api", "scripts/analytics"):
    sys.path.insert(0, str(REPO / p) if p else str(REPO))

# stage_requirements / analytics import field_semantics + yaml only; no network.
from analytics.stage_score_hygiene import classify, qualified_order, _ladder
from rubric import band_meets, band_label


def run():
    print("=" * 72)
    print("STAGE-vs-SCORE HYGIENE — classification (offline, real config gates)")
    print("=" * 72)
    ladder = _ladder()
    orders = [o for o, _i, _n in ladder]
    print(f"ladder orders: {orders}")
    lo = orders[0]                     # lowest rung (Discovery = 1)
    scoping = orders[1]                # Scoping = 2
    late = orders[-1]                  # last rung (e.g. Awaiting Signature)
    passed = failed = 0

    def check(name, cond):
        nonlocal passed, failed
        if cond:
            passed += 1; print(f"  ✓ {name}")
        else:
            failed += 1; print(f"  ❌ {name}")

    STRONG = {c: 9 for c in ("metrics", "economic_buyer", "decision_criteria",
                             "decision_process", "pain", "champion", "competition")}
    WEAK = {c: 2 for c in STRONG}
    # LiveSport's deterministic scores (48/70)
    LIVESPORT = {"metrics": 8, "economic_buyer": 5, "decision_criteria": 7,
                 "decision_process": 7, "pain": 9, "champion": 5, "competition": 7}

    # 1. Strong scores on the lowest rung → score ahead of stage (CRM stale).
    reading, q, gap = classify(lo, STRONG, ladder)
    check("strong scores at earliest stage → score_ahead_of_stage",
          reading == "score_ahead_of_stage" and gap >= 1)

    # 2. Weak scores on the latest rung → stage ahead of score.
    reading, q, gap = classify(late, WEAK, ladder)
    check("weak scores at latest stage → stage_ahead_of_score",
          reading == "stage_ahead_of_score" and gap <= -1)

    # 3. Gates are compared at BAND precision, not integer. This is the anti-
    #    flip property that motivated the change: a component oscillating 5↔6
    #    (both YELLOW) must give the SAME meets-result against a gate of 6, so a
    #    deal does not flip in and out of "qualified" on ±1 sampling noise.
    check("5 and 6 both clear a gate of 6 (both yellow — no ±1 flip)",
          band_meets("economic_buyer", 5, 6) and band_meets("economic_buyer", 6, 6))
    check("a gate of 7 needs green: 6 fails, 7 clears (real boundary kept)",
          (not band_meets("decision_process", 6, 7))
          and band_meets("decision_process", 7, 7))
    check("all-red scores never clear a yellow-floor gate",
          not band_meets("champion", 2, 4))

    # 4. LiveSport (real deterministic scores) sitting in Scoping. HONEST
    #    FALLOUT of band gates: EB 5 and champion 5 are both YELLOW, and the
    #    Scoping→Proposal gate (metrics6/eb6/champ6/dc5) is a yellow-floor gate
    #    once banded — so LiveSport now CLEARS it and qualifies beyond Scoping.
    #    Under the old integer gates a 5 failed a "need 6"; banding says a 5 and
    #    a 6 are the same measurement, so the deal reads as score-ahead-of-stage
    #    (CRM behind), not aligned. Not tuned — this is what the band mapping
    #    produces, and it is a directional change worth reporting.
    reading, q, gap = classify(scoping, LIVESPORT, ladder)
    check("LiveSport @ Scoping now qualifies past Scoping under band gates",
          q > scoping)
    check("LiveSport reads as score_ahead_of_stage (was aligned under ints)",
          reading == "score_ahead_of_stage" and gap >= 1)

    # 5. Sanity: strong scores qualify well past the earliest rung.
    check("strong scores qualify beyond the earliest rung",
          qualified_order(STRONG, ladder) > lo)
    # 6. Sanity: all-red scores never clear even the first gate.
    check("all-red scores stay on the lowest rung",
          qualified_order(WEAK, ladder) == lo)

    print("\n" + "=" * 72)
    print(f"RESULTS: {passed} passed, {failed} failed")
    print("=" * 72)
    return 0 if failed == 0 else 1


if __name__ == "__main__":
    sys.exit(run())
