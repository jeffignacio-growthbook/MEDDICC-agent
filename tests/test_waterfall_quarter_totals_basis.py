#!/usr/bin/env python3
"""
query_waterfall: quarter-level totals state their basis, like each week does.

Live on 2026-09-24 ("show me this quarter's pipeline waterfall"), every week
line carried its own basis, but the answer closed with "Quarter-to-date
closed: $80K won | $965K lost". The $965K is $825K from deal-value weeks
(before Sep 11) plus $140K from an Incremental ARR week, stated as one
unlabeled figure.

Now:
  1. the handler returns waterfall_totals: per field, the total, the bases
     of the weeks that actually contribute to it, a basis_label (for a
     mixed total, its split by basis), and the note says to use it;
  2. check_answer_week_basis also flags a line quoting a mixed-basis total
     without saying so. Totals fed by one basis only (the live $80K won) are
     not flagged.

The live answer's own weekly values and closing line are pinned as a
regression.
"""
import copy
import sys
from pathlib import Path

REPO = Path(__file__).parent.parent
sys.path.insert(0, str(REPO / "tests"))
sys.path.insert(0, str(REPO))

import logging  # noqa: E402
logging.disable(logging.CRITICAL)

import api.router as router  # noqa: E402
from api.plausibility import check_answer_week_basis, answer_caveat  # noqa: E402
import test_waterfall_basis_and_disclosure as wf  # noqa: E402
from canary_harness import run_canary_case  # noqa: E402


def test_handler_returns_basis_labeled_quarter_totals():
    r = wf._run_handler()
    t = r.get("waterfall_totals")
    assert t, "no quarter-level totals"
    # fixture: 09-14 deal_value (new 25,000, won 3,000); 09-21 incremental_arr (new 7,000, lost 1,000)
    assert (t["new_pipeline_value"]["total"], t["new_pipeline_value"]["value_basis"]) == (32000, "mixed")
    assert t["new_pipeline_value"]["by_basis"] == {"deal_value": 25000, "incremental_arr": 7000}
    assert t["new_pipeline_value"]["basis_label"] == (
        "mixed basis: $25,000 deal value (pre-2026-09-11 basis) + $7,000 Incremental ARR"), \
        t["new_pipeline_value"]["basis_label"]
    assert (t["won_value"]["total"], t["won_value"]["value_basis"]) == (3000, "deal_value")
    assert (t["lost_value"]["total"], t["lost_value"]["value_basis"]) == (1000, "incremental_arr")
    assert "QUARTER TOTALS" in r["_synthesis_note"] and "waterfall_totals" in r["_synthesis_note"]
    print("✓ real handler: waterfall_totals labels each quarter total by its contributing weeks "
          "(new $32,000 mixed = $25,000 deal value + $7,000 Incremental ARR; won deal value; "
          "lost Incremental ARR); the note says to use it")


def test_totals_and_labels_reach_both_synthesis_paths():
    r = wf._run_handler()
    label = r["waterfall_totals"]["new_pipeline_value"]["basis_label"]
    classifier = router._smart_truncate_for_synthesis(
        router._cap_rows_for_synthesis(copy.deepcopy(r)), router.SYNTH_PAYLOAD_CHARS)
    loop = run_canary_case("show me this quarter's pipeline waterfall", "query_waterfall",
                           {}, r, time_window=wf.TW)["synthesis_text"]
    for name, text in (("classifier", classifier), ("dynamic loop", loop)):
        assert '"waterfall_totals"' in text and label in text, name
    print("✓ waterfall_totals and its mixed-basis label reach the synthesis input on both paths")


def _live_rows():
    """The 2026-09-24 live answer's weeks (won / lost only)."""
    def w(d, basis, won=0, lost=0):
        return {"week_ending": d, "value_basis": basis, "by_slice": [],
                "won_value": won, "lost_value": lost}
    return {"waterfall": [
        w("2026-08-17", "deal_value", lost=75000),
        w("2026-08-28", "deal_value", won=80000, lost=750000),
        w("2026-09-14", "incremental_arr"),
        w("2026-09-21", "incremental_arr", lost=140000),
    ]}


LIVE_ANSWER = (
    "• Aug 17 — New: $0 | Won: $0 | Lost: $75K | Net: -$180K (deal value basis)\n"
    "• Aug 28 — New: $0 | Won: $80K | Lost: $750K | Net: -$830K (deal value basis)\n"
    "• Sep 14 — New: $0 | Won: $0 | Lost: $0 | Net: +$201K (Incremental ARR basis)\n"
    "• Sep 21 — New: $0 | Won: $0 | Lost: $140K | Net: +$17K (Incremental ARR basis)\n"
    "\n"
    "Quarter-to-date closed: $80K won | $965K lost\n")


def test_live_answer_flags_only_the_mixed_total():
    v = check_answer_week_basis(LIVE_ANSWER, _live_rows())
    assert len(v) == 1, v
    (t,) = v[0].context["unlabeled_totals"]
    assert (t["field"], t["total"]) == ("lost_value", 965000), t
    assert "mixes two bases" in answer_caveat(v)
    print("✓ the live answer: $965K lost (deal value + Incremental ARR weeks) flagged; "
          "$80K won (one deal-value week) and every labeled week line pass")


def test_labeled_totals_pass():
    for line in ("Quarter-to-date lost: $965K (mixed basis: $825K deal value + $140K Incremental ARR)",
                 "QTD lost $965K: $825K on deal value, $140K on Incremental ARR",
                 "QTD won $80K (deal value)"):
        answer = LIVE_ANSWER.replace("Quarter-to-date closed: $80K won | $965K lost", line)
        assert not check_answer_week_basis(answer, _live_rows()), line
    print("✓ totals that say 'mixed basis' or name both bases pass")


def test_dynamic_loop_caveats_an_unlabeled_mixed_total():
    r = wf._run_handler()
    saved, seen = router._log_query_cost, {}

    def capture(sb, question, cost_state, result, exc):
        seen["outcome"] = router._compute_query_cost_outcome(result, cost_state, exc)
    router._log_query_cost = capture
    try:
        bad = ("• Sep 14: +$25K new (deal value)\n• Sep 21: +$7K new (Incremental ARR)\n"
               "Quarter to date: $32K new pipeline")
        rep = run_canary_case("show me this quarter's pipeline waterfall", "query_waterfall",
                              {}, r, answer_text=bad, time_window=wf.TW)
    finally:
        router._log_query_cost = saved
    assert rep["answer"].endswith("so it mixes two bases."), rep["answer"]
    assert seen["outcome"] == "answered_with_week_basis_mismatch", seen
    print("✓ dynamic loop: an unlabeled mixed-basis quarter total ships with the caveat and "
          "outcome answered_with_week_basis_mismatch")


if __name__ == "__main__":
    test_handler_returns_basis_labeled_quarter_totals()
    test_totals_and_labels_reach_both_synthesis_paths()
    test_live_answer_flags_only_the_mixed_total()
    test_labeled_totals_pass()
    test_dynamic_loop_caveats_an_unlabeled_mixed_total()
    print("\n✅ All tests passed")
