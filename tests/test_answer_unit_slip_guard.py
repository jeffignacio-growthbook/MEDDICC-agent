#!/usr/bin/env python3
"""
Unit-slip guard: a stated dollar figure that matches its source only after a
factor of 1,000 (or 1,000,000) is flagged, caveated, and logged.

api/plausibility.check_answer_unit_slips, run by run_answer_checks() on both
synthesis paths (dynamic_query_loop's wrapper, route_question after
synthesis). In the loop it sets answer_unit_slip_suspected, outcome
answered_with_suspected_unit_slip.

False-positive tuning is from a replay of 2,053 figures in 159 production
answers against every money value in deals (see the check's docstring):
26 false flags with a loose rule, 0 with the shipped one. The shapes that
were false flags are pinned below as must-pass cases.
"""
import sys
from pathlib import Path

REPO = Path(__file__).parent.parent
sys.path.insert(0, str(REPO / "tests"))
sys.path.insert(0, str(REPO))

import logging  # noqa: E402
logging.disable(logging.CRITICAL)

import api.router as router  # noqa: E402
import api.plausibility as plausibility  # noqa: E402
from api.plausibility import answer_caveat  # noqa: E402
# pre-fix code has no such check: every test then fails on its assertions, not the import
check_answer_unit_slips = getattr(plausibility, "check_answer_unit_slips", lambda answer, data: [])
import test_pipeline_movement_synthesis_note as pm  # noqa: E402
from canary_harness import run_canary_case  # noqa: E402

DATA = {
    "pipeline_summary": {"total_incremental_arr": 4577066, "total_open_count": 46},
    "summary": {"won_value": 80500},
    "deals": [{"deal_id": "1", "deal_value": 23800}, {"deal_id": "2", "deal_value": 30000},
              {"deal_id": "3", "deal_value": 18700}, {"deal_id": "4", "deal_value": 25000}],
}

SLIPS = {   # answer -> (source_value, factor)
    "Q3 pipeline is $4,577 across 46 deals.": (4577066, 1e3),       # dropped the M
    "Q3 pipeline is $4.58K.": (4577066, 1e3),                         # K for M
    "Q3 pipeline is $4.58 billion.": (4577066, 1e3),                  # billion for million
    "Won $80.5M this quarter.": (80500, 1e3),                         # M for K
    "Q3 pipeline is $4.577.": (4577066, 1e6),                         # dropped the M entirely
}

MUST_PASS = {
    "correct, rounded": "Q3 pipeline is $4.58M across 46 deals; won $80.5K.",
    "correct, exact": "Q3 pipeline is $4,577,066.",
    "derived total matching nothing": "Combined with renewals that's $6.2M.",
    # replay false positives (production answers, 2026-09-24):
    "aggregate /1000 = a deal row ($23.8M vs a $23,800 deal)": "Total pipeline is $23.8M.",
    "aggregate /1000 = a deal row ($18.7M vs $18,700)": "All deals total $18.7M.",
    "round figure x1000 = a round deal ($30 vs $30,000)": "Seats are $30 per user.",
    "round aggregate ($25.0M vs $25,000)": "Pipeline is $25.0M.",
    "no dollar figures": "46 deals are open.",
}


def test_planted_slips_are_flagged_with_their_source():
    for answer, (src, factor) in SLIPS.items():
        v = check_answer_unit_slips(answer, DATA)
        assert len(v) == 1 and v[0].check == "answer_unit_slip", (answer, v)
        (sl,) = v[0].context["slips"]
        assert (sl["source_value"], sl["factor"]) == (src, factor), (answer, sl)
    print(f"✓ {len(SLIPS)} planted slips flagged with the right source value and factor "
          "(dropped M, K for M, billion for million, M for K, x1,000,000)")


def test_correct_figures_and_replay_false_positives_pass():
    for name, answer in MUST_PASS.items():
        assert not check_answer_unit_slips(answer, DATA), name
    print(f"✓ {len(MUST_PASS)} must-pass answers pass, including the production-replay "
          "false-positive shapes ($23.8M / $18.7M vs deal rows, $30, $25.0M)")


def test_caveat_names_both_figures():
    text = answer_caveat(check_answer_unit_slips("Q3 pipeline is $4,577.", DATA))
    assert "$4,577 above may be off by a factor of 1,000" in text and "$4,577,066" in text, text
    print(f"✓ caveat: {text!r}")


def _loop(answer_text):
    r = pm._run_handler()
    assert r["summary"]["added_arr_total"] == 125000
    seen = {}
    saved = router._log_query_cost

    def capture(sb, question, cost_state, result, exc):
        seen["outcome"] = router._compute_query_cost_outcome(result, cost_state, exc)
    router._log_query_cost = capture
    try:
        rep = run_canary_case("how has pipeline moved this quarter?", "query_pipeline_movement",
                              {"view": "movement", "fiscal_quarter": "FY2027 Q3"}, r,
                              answer_text=answer_text)
    finally:
        router._log_query_cost = saved
    return rep, seen["outcome"]


def test_dynamic_loop_caveats_and_logs_a_slip_on_a_real_handler_result():
    for bad in ("Added $125, exited $45,000, net $80,000.",       # 1000x too small
                "Added $125M, exited $45,000, net $80,000."):     # 1000x too large vs summary
        rep, outcome = _loop(bad)
        assert "may be off by a factor of 1,000" in rep["answer"] and "$125,000" in rep["answer"], rep["answer"]
        assert outcome == "answered_with_suspected_unit_slip", (bad, outcome)
        assert rep["result"]["plausibility_violations"][0]["check"] == "answer_unit_slip"
    good = "Added $125,000 across 2 deals, exited $45,000, net $80,000."
    rep, outcome = _loop(good)
    assert rep["answer"] == good and outcome == "answered_cleanly", (rep["answer"], outcome)
    print("✓ dynamic loop, real query_pipeline_movement result: '$125' and '$125M' for "
          "$125,000 ship with the caveat and outcome answered_with_suspected_unit_slip; "
          "the correct answer ships unchanged")


if __name__ == "__main__":
    test_planted_slips_are_flagged_with_their_source()
    test_correct_figures_and_replay_false_positives_pass()
    test_caveat_names_both_figures()
    test_dynamic_loop_caveats_and_logs_a_slip_on_a_real_handler_result()
    print("\n✅ All tests passed")
