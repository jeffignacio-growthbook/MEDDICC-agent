#!/usr/bin/env python3
"""
Quarter health: three lines built in code and required verbatim.

1. QTD closed-won and gap-to-goal. Closed-won incremental ARR for the
   quarter comes from query_loss_concentration's own closed-deal fetch (the
   rows its won_count counts), not a fifth query; the target is
   query_pipeline's quarterly_target (rep_targets, team, incremental_arr);
   the quarter end is query_pipeline's this_quarter. The follow-on is the
   remaining gap as a share of the forecast (COMMIT+MOST_LIKELY closing this
   quarter): two governed numbers, where "low-risk forecast only" would
   lean on the cycle-length risk label and leave the renewals (no risk read)
   out.
2. The loss-rate headline: query_loss_concentration's loss_rate_headline
   (qualified rate first, all-closed rate beside it).
3. The forecast baseline in plain words, replacing "Directional, not final:
   ... hasn't had as much time to resolve as the historical week-8
   baseline had by quarter end".

Real inputs, all captured 2026-09-25: the four primitives from
quarter_health_primitives_2026_09_25_renewals_not_assessed.json, with
query_loss_concentration recomputed by the current code from the live
closed-deal capture loss_concentration_fy2027_q3_2026_09_25.json (the
earlier capture predates the qualified rate).
"""
import copy
import sys
from datetime import date
from pathlib import Path
from unittest.mock import patch

REPO = Path(__file__).parent.parent
sys.path.insert(0, str(REPO / "tests"))
sys.path.insert(0, str(REPO))
sys.path.insert(0, str(REPO / "scripts"))
sys.path.insert(0, str(REPO / "scripts" / "analytics"))
sys.path.insert(0, str(REPO / "api"))

import logging  # noqa: E402
logging.disable(logging.CRITICAL)

import api.quarter_health as qh  # noqa: E402
from api.plausibility import run_all_checks  # noqa: E402
import test_quarter_health_renewals_live as live  # noqa: E402
import test_quarter_health_disclosure_survival as surv  # noqa: E402
import test_loss_rate_qualified as lossfx  # noqa: E402

AS_OF = date(2026, 9, 25)
RAW = copy.deepcopy(live.RAW)
RAW["query_loss_concentration"] = lossfx.real_result()

QTD_LINE = ("$373,400 closed won QTD against the $1,550,000 target ($1,176,600 remaining), with 5 "
            "weeks left in the quarter. Closing that gap takes 60% of the $1,946,176 forecast "
            "(COMMIT+MOST_LIKELY deals closing this quarter).")
BASELINE = ("That 32% comes from deals that had a full quarter to close. We're only 8 weeks into "
            "this one, so some deals that look stuck today may still close before quarter end.")


def _compose(scenario, raw=None):
    return qh.compose_from_results(copy.deepcopy(raw or RAW), scenario,
                                   stage_rates=live.FIXTURE["stage_close_rate"],
                                   deal_rows=live.FIXTURE["high_risk_deal_rows"], as_of=AS_OF)


def test_qtd_figures_on_real_data():
    q = _compose("base")["figures"]["quarter_to_date"]
    assert q["status"] == "ok", q
    assert (q["closed_won_arr"], q["closed_won_count"], q["target"]) == (373400.0, 9, 1550000), q
    assert q["remaining_to_target"] == 1176600.0 and (q["days_left"], q["weeks_left"]) == (36, 5), q
    assert q["forecast_arr"] == 1946175.68
    assert abs(q["remaining_share_of_forecast"] - 1176600.0 / 1946175.68) < 1e-12
    assert q["line"] == QTD_LINE, q["line"]
    assert "query_loss_concentration" in q["basis"] and "rep_targets" in q["basis"]
    print("✓ QTD: $373,400 won (the 9 wins loss_concentration counts) vs $1,550,000 → "
          "$1,176,600 remaining, 5 weeks left, 60% of the $1,946,176 forecast")


def test_qtd_edges():
    raw = copy.deepcopy(RAW)
    raw["query_loss_concentration"]["won_incremental_arr"] = 1600000.0
    q = _compose("base", raw)["figures"]["quarter_to_date"]
    assert q["line"] == ("$1,600,000 closed won QTD against the $1,550,000 target ($50,000 over "
                         "target), with 5 weeks left in the quarter."), q["line"]
    raw = copy.deepcopy(RAW)
    raw["query_pipeline"]["quarterly_target"] = None
    q = _compose("base", raw)["figures"]["quarter_to_date"]
    assert q["status"] == "unavailable" and "target" in q["reason"] and "line" not in q
    raw = copy.deepcopy(RAW)
    raw["query_pipeline"]["this_quarter"]["label"] = "FY2027 Q4"
    q = _compose("base", raw)["figures"]["quarter_to_date"]
    assert q["status"] == "unavailable" and "quarter" in q["reason"]
    raw = copy.deepcopy(RAW)
    raw["query_loss_concentration"] = {"status": "error", "error": "boom"}
    c = _compose("base", raw)
    assert c["figures"]["quarter_to_date"]["status"] == "unavailable"
    assert "QTD" in c["_synthesis_note"] and "unavailable" in c["_synthesis_note"]
    print("✓ QTD edges: over target stated as over; no target, quarter mismatch or a failed "
          "loss primitive -> unavailable with the reason, no line")


def test_baseline_sentence_builder_and_forecast_trust_note():
    assert qh.forecast_baseline_sentence(_compose("base")["figures"]["forecast_trust"]) == BASELINE
    from forecast_trust import assess_forecast_trust
    from strict_supabase import StrictSupabase
    by_week = {w: {"classified": 91, "won": 29, "win_rate": 0.3187, "reason": None} for w in range(1, 14)}
    with patch("utils.get_fiscal_quarter") as gfq, \
         patch("snapshot_deals.get_week_of_quarter") as gw, \
         patch("forecast_analyses.query_commit_ml_calibration_by_week") as cal:
        gfq.return_value = (date(2026, 8, 1), date(2026, 10, 31), "FY2027 Q3")
        gw.return_value = 8
        cal.return_value = {"by_week": by_week}
        r = assess_forecast_trust(StrictSupabase({"deals": [], "analyses": []}), as_of=AS_OF)
    assert r["note"] == BASELINE, r["note"]
    assert "irectional" not in r["note"] and "baseline" not in r["note"]
    print("✓ baseline in plain words, word for word, in forecast_trust's own note and from the composer")


def test_note_requires_the_three_lines_verbatim():
    for scenario in qh.SCENARIOS:
        note = _compose(scenario)["_synthesis_note"]
        for line in (QTD_LINE, RAW["query_loss_concentration"]["loss_rate_headline"], BASELINE):
            assert f'"{line}"' in note, (scenario, line)
        assert "verbatim" in note and "Do not combine" in note and "different populations" in note
        assert "quarter_to_date" in note
    print("✓ the synthesis note quotes the QTD line, the loss-rate headline and the baseline "
          "sentence verbatim, in both scenarios")


def test_lines_survive_every_model_input_and_pass_plausibility():
    disclosures = surv.collect_disclosures(RAW)
    assert any(p.endswith("query_loss_concentration.loss_rate_note") for _, p, _ in disclosures)
    assert any(p.endswith("query_loss_concentration.won_arr_note") for _, p, _ in disclosures)
    for scenario in qh.SCENARIOS:
        c = _compose(scenario)
        violations, _ = run_all_checks(c, qh.ENTRY_POINTS[scenario])
        assert not violations, [v.message for v in violations]
        musts = [QTD_LINE, c["figures"]["quarter_to_date"]["basis"], BASELINE,
                 RAW["query_loss_concentration"]["loss_rate_headline"]] + [s for _, _, s in disclosures]
        for name, text in surv._model_inputs(c, scenario).items():
            missing = [m[:60] for m in musts if not surv._present(m, text)]
            assert not missing, (scenario, name, missing[:5])
        f = c["figures"]["loss_concentration"]
        assert (f["qualified_loss_rate"], f["all_closed_loss_rate"]) == (0.7778, 0.9237), f
    print(f"✓ both views: 0 plausibility violations; the QTD line and basis, the loss headline, "
          f"the baseline sentence and all {len(disclosures)} disclosures reach every model input")


if __name__ == "__main__":
    test_qtd_figures_on_real_data()
    test_qtd_edges()
    test_baseline_sentence_builder_and_forecast_trust_note()
    test_note_requires_the_three_lines_verbatim()
    test_lines_survive_every_model_input_and_pass_plausibility()
    print("\n✅ All tests passed")
