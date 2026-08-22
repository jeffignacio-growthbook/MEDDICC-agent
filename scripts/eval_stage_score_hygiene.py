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

    # 3. LiveSport (real deterministic scores) sitting in Scoping.
    #    EB 5 and champion 5 fall below the Scoping→Proposal gate (both need 6),
    #    so it does NOT qualify beyond Scoping — it is ALIGNED, not "ahead".
    #    This is what falls out; it is not tuned to a desired answer.
    reading, q, gap = classify(scoping, LIVESPORT, ladder)
    check("LiveSport @ Scoping with EB5/champ5 → aligned (honest result)",
          reading == "aligned" and gap == 0)
    check("LiveSport qualified stage == its actual stage (Scoping)",
          q == scoping)

    # 4. Sanity: strong scores qualify well past the earliest rung.
    check("strong scores qualify beyond the earliest rung",
          qualified_order(STRONG, ladder) > lo)
    # 5. Sanity: weak scores never clear even the first gate.
    check("weak scores stay on the lowest rung",
          qualified_order(WEAK, ladder) == lo)

    print("\n" + "=" * 72)
    print(f"RESULTS: {passed} passed, {failed} failed")
    print("=" * 72)
    return 0 if failed == 0 else 1


if __name__ == "__main__":
    sys.exit(run())
