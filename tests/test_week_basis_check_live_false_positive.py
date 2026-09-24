#!/usr/bin/env python3
"""
check_answer_week_basis must not flag a correctly labeled answer.

Its first live run (2026-09-24 15:05 UTC, query_cost_log id 465) flagged a
waterfall answer whose table was right: every row carried its week's basis
and the quarter totals gave their split. It appended "The basis shown for
one or more weeks above doesn't match how that week was computed", which
was false. Two causes:
  1. the table wrote "Incr. ARR", which the basis pattern didn't recognise,
     so the Sep 14 / Sep 21 rows looked unlabeled;
  2. for an unlabeled line, the check fell back to every basis named
     anywhere else in the answer ("deal value", "mixed basis" from the
     notes) and called several bases "wrong", even though the week's own
     basis was among them. A prose line ("especially Sep 21: $1.76M pushed
     out") was flagged the same way.

The exact live answer is pinned as a negative control (not flagged, on the
pure check and through the dynamic loop). Planted errors in that same
answer are still caught.
"""
import sys
from pathlib import Path

REPO = Path(__file__).parent.parent
sys.path.insert(0, str(REPO / "tests"))
sys.path.insert(0, str(REPO))

import logging  # noqa: E402
logging.disable(logging.CRITICAL)

import api.router as router  # noqa: E402
from api.plausibility import check_answer_week_basis  # noqa: E402
from canary_harness import run_canary_case  # noqa: E402

LIVE_ANSWER = (REPO / "tests" / "fixtures" / "live_waterfall_answer_2026_09_24_1505.txt").read_text()


def _w(d, basis, new=0, won=0, lost=0, net=0):
    return {"week_ending": d, "value_basis": basis, "by_slice": [], "new_pipeline_value": new,
            "won_value": won, "lost_value": lost, "net_change": net,
            "pulled_in_value": 0, "pushed_out_value": 0}


# The live run's weeks (from the answer's own table, which matched the rows).
LIVE_ROWS = {"waterfall": [
    _w("2026-08-03", "deal_value", new=235000, net=1277500),
    _w("2026-08-10", "deal_value", new=190000, net=780000),
    _w("2026-08-17", "deal_value", lost=75000, net=-180000),
    _w("2026-08-24", "deal_value", net=-407100),
    _w("2026-08-28", "deal_value", won=80000, lost=750000, net=-830000),
    _w("2026-09-07", "deal_value"),
    _w("2026-09-08", "deal_value"),
    _w("2026-09-14", "incremental_arr", net=200670),
    _w("2026-09-21", "incremental_arr", lost=140000, net=16800),
]}


def test_the_live_answer_is_not_flagged():
    v = check_answer_week_basis(LIVE_ANSWER, LIVE_ROWS)
    assert not v, [x.message for x in v]
    print("✓ the 2026-09-24 15:05 live answer (rows labeled 'Deal value' / 'Incr. ARR', "
          "labeled quarter splits, prose mention of Sep 21) is not flagged")


def test_planted_errors_in_the_same_answer_are_still_caught():
    cases = {
        # a row labeled with the other basis
        "Sep 21 row says deal value":
            (LIVE_ANSWER.replace("+$16,800     Incr. ARR", "+$16,800     Deal value"),
             ["2026-09-21"]),
        # abbreviation on a deal-value week
        "Aug 28 row says Incr. ARR":
            (LIVE_ANSWER.replace("-$830,000    Deal value", "-$830,000    Incr. ARR"),
             ["2026-08-28"]),
    }
    for name, (answer, weeks) in cases.items():
        v = check_answer_week_basis(answer, LIVE_ROWS)
        flagged = sorted({w["week_ending"] for x in v for w in x.context.get("wrong", [])})
        assert flagged == weeks, (name, flagged, [x.message for x in v])
    # the quarter-total rule still bites on this answer
    unlabeled = LIVE_ANSWER.replace("• Lost: $965,000 — $825K deal value + $140K Incremental ARR",
                                    "• Lost: $965,000")
    v = check_answer_week_basis(unlabeled, LIVE_ROWS)
    assert [t["total"] for x in v for t in x.context.get("unlabeled_totals", [])] == [965000], v
    print("✓ planted errors in the same answer are still caught: a wrong row label (both "
          "directions, incl. 'Incr. ARR') names exactly that week; an unlabeled $965,000 "
          "mixed total is flagged")


def test_abbreviations_are_recognised():
    rows = {"waterfall": [_w("2026-09-14", "incremental_arr"), _w("2026-08-24", "deal_value")]}
    for label in ("Incr. ARR", "Incr ARR", "incremental ARR", "INCR. ARR"):
        answer = f"• Sep 14: +$200K ({label})\n• Aug 24: -$407K (deal value)"
        assert not check_answer_week_basis(answer, rows), label
    print("✓ 'Incr. ARR', 'Incr ARR', 'incremental ARR' and 'INCR. ARR' all read as Incremental ARR")


def test_the_live_answer_ships_unchanged_through_the_dynamic_loop():
    saved, seen = router._log_query_cost, {}

    def capture(sb, question, cost_state, result, exc):
        seen["outcome"] = router._compute_query_cost_outcome(result, cost_state, exc)
    router._log_query_cost = capture
    try:
        rep = run_canary_case("Show me this quarter's pipeline waterfall — new, won and lost by week",
                              "query_waterfall", {}, LIVE_ROWS, answer_text=LIVE_ANSWER)
    finally:
        router._log_query_cost = saved
    assert rep["answer"] == LIVE_ANSWER, rep["answer"][-300:]
    assert seen["outcome"] == "answered_cleanly", seen
    print("✓ dynamic loop: the live answer ships with no caveat, outcome answered_cleanly "
          "(was answered_with_week_basis_mismatch, query_cost_log id 465)")


if __name__ == "__main__":
    test_the_live_answer_is_not_flagged()
    test_planted_errors_in_the_same_answer_are_still_caught()
    test_abbreviations_are_recognised()
    test_the_live_answer_ships_unchanged_through_the_dynamic_loop()
    print("\n✅ All tests passed")
