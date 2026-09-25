#!/usr/bin/env python3
"""
Quarter health, reframed (2026-09-25): where the quarter stands, then the
one forward-looking figure, then how far to trust it.

  1. Where it stands: the QTD line, and pace (share of the quarter gone vs
     share of target won) with this business's own seasonality beside it.
     Bookings here are back-loaded and uneven, so pace is never called
     ahead or behind.
  2. Coverage: qualified Sales pipeline closing this quarter, each deal
     weighted by its current stage's governed rate (query_pipeline_coverage,
     stage key fixed), against what is still needed. The only coverage
     figure: query_pipeline's unweighted coverage_ratio is dropped, and no
     single historical rate is applied to anything.
  3. Modifiers, not verdict lines: forecast risk, the qualified loss rate
     and each rep's loss row with what they still have live.
Left out entirely: forecast_trust's same-week historical cohort ("91 deals,
prior quarters") with its note and calibration evidence, and the coverage
primitive's HEURISTIC proxy curve and quota+stretch goal.

Real inputs: the full live 2026-09-25 set (tests/quarter_health_inputs.py).
"""
import copy
import sys
from pathlib import Path

REPO = Path(__file__).parent.parent
sys.path.insert(0, str(REPO / "tests"))
sys.path.insert(0, str(REPO))
sys.path.insert(0, str(REPO / "scripts"))
sys.path.insert(0, str(REPO / "scripts" / "analytics"))
sys.path.insert(0, str(REPO / "api"))

import logging  # noqa: E402
logging.disable(logging.CRITICAL)

import api.quarter_health as qh  # noqa: E402
import quarter_health_inputs as qi  # noqa: E402
import test_quarter_health_disclosure_survival as surv  # noqa: E402

PACE = ("56 of 92 days (61%) of the quarter have passed and 24% of the $1,550,000 target ($373,400) "
        "is closed won.")
SEASONALITY = ("Bookings here are back-loaded and uneven: over the last 8 complete quarters, 8% to 71% "
               "(median 40%) of a quarter's closed-won ARR was in by this point, and a median 37% "
               "closed in the final week, so pace alone doesn't show whether this quarter is ahead or "
               "behind.")
COVERAGE = ("Weighted by each deal's current-stage close rate, the $4,907,066 of qualified Sales "
            "pipeline closing this quarter (44 deals) is worth $701,826: 0.60x the $1,176,600 still "
            "needed to reach target. $295,485 of Renewal-pipeline expansion (8 deals) has no stage "
            "rate and is not counted.")
DOWNSIDE = ("If the 5 high-risk forecast deals ($436,300) are lost, weighted coverage falls from "
            "$701,826 to $590,533: 0.50x the $1,176,600 still needed (was 0.60x).")
FORECAST_RISK = ("22% of the forecast ($436,300 of $1,946,176) is high risk; 12% ($225,485 across 6 "
                 "Renewal-pipeline deals) has no risk read yet.")


def test_pace_and_coverage_figures():
    f = qi.compose("base")["figures"]
    p, c = f["pace"], f["coverage"]
    assert (p["line"], p["seasonality_line"]) == (PACE, SEASONALITY), (p["line"], p["seasonality_line"])
    assert (p["days_elapsed"], p["days_in_quarter"]) == (56, 92)
    assert c["line"] == COVERAGE, c["line"]
    assert round(c["weighted_arr"], 2) == 701825.86 and c["remaining_to_target"] == 1176600.0
    assert round(c["coverage_of_remaining"], 4) == 0.5965
    assert "not specific to the weeks left" in c["basis"]
    print("✓ pace: 61% of the quarter gone, 24% of target won, with the seasonality line; coverage: "
          "$701,826 weighted = 0.60x the $1,176,600 still needed")


def test_note_is_three_steps_with_modifiers_last():
    for scenario in qh.SCENARIOS:
        note = qi.compose(scenario)["_synthesis_note"]
        i1, i2, i3 = (note.index(s) for s in ("1. WHERE THE QUARTER STANDS", "2. COVERAGE",
                                              "3. HOW FAR TO TRUST THAT COVERAGE"))
        assert i1 < i2 < i3
        for line in (PACE, SEASONALITY):
            assert i1 < note.index(f'"{line}"') < i2, line
        assert i2 < note.index(f'"{COVERAGE}"') < i3
        loss = qi.RAW["query_loss_concentration"]["loss_rate_headline"]
        for modifier in (FORECAST_RISK, loss):
            assert note.index(f'"{modifier}"') > i3, modifier
        assert "modifiers on the coverage read, not separate verdicts" in note
        assert "Do not call the quarter ahead or behind from pace" in note
        assert "do not apply any single historical win rate" in note
        assert "do not quote query_pipeline's unweighted coverage ratio" in note
        if scenario == "downside":
            assert i2 < note.index(f'"{DOWNSIDE}"') < i3
        else:
            assert DOWNSIDE not in note
    print("✓ the note: stands (QTD, pace, seasonality) → coverage (and the downside) → modifiers "
          "(forecast risk, loss rate, reps), each line verbatim in its step")


def test_competing_and_unverified_figures_are_left_out():
    excluded = surv.collect_disclosures(qi.RAW, excluded=True)
    paths = {p for _, p, _ in excluded}
    assert {"query_forecast_trust.note", "query_forecast_trust.calibration_evidence.note",
            "query_pipeline_coverage.note", "query_pipeline_coverage.real_target.note"} <= paths, paths
    for scenario in qh.SCENARIOS:
        c = qi.compose(scenario)
        prim = c["primitives"]
        for gone in ("historical_heuristic_curve", "gap_to_goal", "real_target"):
            assert gone not in prim["query_pipeline_coverage"], gone
        assert "coverage_ratio" not in prim["query_pipeline"] and "coverage_ratio" not in c["figures"]["pipeline"]
        assert "historical_win_rate_same_week" not in c["figures"]["forecast_trust"]
        for name, text in surv._model_inputs(c, scenario).items():
            leaked = [p for _, p, s in excluded if surv._present(s, text)]
            assert not leaked, (scenario, name, leaked)
        assert "worst_case_arr" not in str(c.get("downside", {}))
    print("✓ left out: the historical cohort, its note and calibration evidence; the coverage "
          "primitive's proxy curve, goal and gap; query_pipeline's unweighted coverage ratio; no "
          "worst-case figure")


def test_unavailable_inputs_are_stated():
    c = qi.compose("base", seasonality={"status": "insufficient_data", "reason": "only 2 quarters"})
    assert c["figures"]["pace"]["seasonality_line"].startswith("No seasonality read (only 2 quarters)")
    raw = copy.deepcopy(qi.RAW)
    raw["query_pipeline_coverage"] = {"status": "error", "error": "boom"}
    c = qi.compose("downside", raw)
    assert c["figures"]["coverage"]["status"] == "unavailable" and c["downside"]["status"] == "unavailable"
    assert "coverage (weighted pipeline vs what is still needed)" in c["_synthesis_note"]
    assert "2. COVERAGE: unavailable" in c["_synthesis_note"]
    raw = copy.deepcopy(qi.RAW)
    raw["query_loss_concentration"]["won_incremental_arr"] = 1600000.0
    c = qi.compose("base", raw)["figures"]["coverage"]
    assert c["coverage_of_remaining"] is None and c["line"].startswith("The target is already met")
    print("✓ no seasonality history, a failed coverage primitive, a target already met: each stated, "
          "nothing estimated")


if __name__ == "__main__":
    test_pace_and_coverage_figures()
    test_note_is_three_steps_with_modifiers_last()
    test_competing_and_unverified_figures_are_left_out()
    test_unavailable_inputs_are_stated()
    print("\n✅ All tests passed")
