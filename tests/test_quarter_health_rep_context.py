#!/usr/bin/env python3
"""
Quarter health: each qualified-loss rep row carries what that rep still has
live.

"christian: 14/14 qualified closed lost" on its own reads as the worst rep
on the team. It is this quarter's closed deals, backward-looking. Beside it
the answer now gives what the rep has open: their forecast this quarter
(COMMIT and Most Likely) and their open pipeline. A poor loss record with
nothing live behind it (Dan: 4 of 6 lost, no forecast deals) is a different
story from one with a strong forecast behind it (Christian: $601,800, all
Most Likely).

Sources, reused rather than recomputed:
  open pipeline   query_pipeline.by_owner, as returned (all the rep's active
                  incremental pipeline, any close date, top 10 owners).
  forecast        query_forecast_trust.by_owner: the forecast's own cohort
                  query now selects owner_email and splits the same deals by
                  owner (no new query). query_pipeline.by_owner has no
                  COMMIT/Most Likely split and no quarter scope, so it can't
                  give a per-rep forecast.

Real data: the forecast cohort with owners, captured read-only from live
Supabase on 2026-09-25 (tests/fixtures/forecast_cohort_owners_2026_09_25.json,
md5 a98f1c6c5ed150c489badfa0f032eb15; deals last updated 01:28 UTC, before
both primitive captures), joined with the live primitive captures the other
quarter-health tests use.
"""
import copy
import json
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
import api.router as router  # noqa: E402
from api.plausibility import run_all_checks  # noqa: E402
from forecast_trust import forecast_by_owner  # noqa: E402
from strict_supabase import StrictSupabase  # noqa: E402
import test_quarter_health_qtd_and_wording as base  # noqa: E402
import test_quarter_health_disclosure_survival as surv  # noqa: E402

COHORT = json.loads((REPO / "tests" / "fixtures" / "forecast_cohort_owners_2026_09_25.json").read_text())
RAW = copy.deepcopy(base.RAW)
RAW["query_forecast_trust"]["by_owner"] = forecast_by_owner(COHORT["deals"])

REAL_LINES = [
    "christian@growthbook.io: 14/14 qualified closed lost (100.0% loss rate), 22.2 pts above the "
    "team's 77.8% | still live: $601,800 forecast (COMMIT $0, Most Likely $601,800; 3 deals); "
    "$7,545,708 open pipeline (65 deals)",
    "dan@growthbook.io: 4/6 qualified closed lost (66.7% loss rate), 11.1 pts below the team's 77.8% "
    "| still live: $0 forecast (no COMMIT or Most Likely deals closing this quarter); $1,018,000 open "
    "pipeline (8 deals)",
    "james.shannon@growthbook.io: 3/5 qualified closed lost (60.0% loss rate), 17.8 pts below the "
    "team's 77.8% | still live: $285,220 forecast (COMMIT $172,720, Most Likely $112,500; 4 deals); "
    "$3,377,220 open pipeline (32 deals)",
    "jake@growthbook.io: 4/4 closed lost, fewer than 5: too thin for a rate | still live: $345,000 "
    "forecast (COMMIT $170,000, Most Likely $175,000; 4 deals); $2,485,000 open pipeline (27 deals)",
    "cary@growthbook.io: 0/3 closed lost, fewer than 5: too thin for a rate | still live: $638,671 "
    "forecast (COMMIT $170,671, Most Likely $468,000; 5 deals); $2,739,121 open pipeline (27 deals)",
    "scott.keller@growthbook.io: 2/3 closed lost, fewer than 5: too thin for a rate | still live: $0 "
    "forecast (no COMMIT or Most Likely deals closing this quarter); $3,470,790 open pipeline (43 deals)",
    "marcel@growthbook.io: 1/1 closed lost, fewer than 5: too thin for a rate | still live: $35,000 "
    "forecast (COMMIT $0, Most Likely $35,000; 1 deal); $1,894,125 open pipeline (23 deals)",
]


def _compose(scenario, raw=None):
    return base._compose(scenario, raw or RAW)


def test_forecast_by_owner_on_the_live_cohort():
    by = forecast_by_owner(COHORT["deals"])
    assert abs(sum(o["forecast_arr"] for o in by.values()) - 1946175.68) < 0.01
    assert sum(o["deal_count"] for o in by.values()) == 21
    c = by["christian@growthbook.io"]
    assert (c["commit_arr"], c["most_likely_arr"], c["deal_count"]) == (0.0, 601800.0, 3), c
    top_commit = max(by, key=lambda k: by[k]["commit_arr"])
    assert top_commit == "james.shannon@growthbook.io" and by[top_commit]["commit_arr"] == 172720.0
    assert "dan@growthbook.io" not in by and "scott.keller@growthbook.io" not in by
    print("✓ forecast by owner (live cohort): sums to $1,946,176 over 21 deals; Christian $601,800 "
          "all Most Likely, no COMMIT; most COMMIT is James Shannon ($172,720); Dan and Scott none")


def test_forecast_trust_splits_its_own_deals_by_owner():
    from forecast_trust import assess_forecast_trust
    deals = [dict(d, deal_status="active", create_date=None, segment=None) for d in COHORT["deals"]]
    sb = StrictSupabase({"deals": deals, "analyses": []})
    by_week = {w: {"classified": 91, "won": 29, "win_rate": 0.3187, "reason": None} for w in range(1, 14)}
    with patch("utils.get_fiscal_quarter") as gfq, \
         patch("snapshot_deals.get_week_of_quarter") as gw, \
         patch("forecast_analyses.query_commit_ml_calibration_by_week") as cal:
        gfq.return_value = (date(2026, 8, 1), date(2026, 10, 31), "FY2027 Q3")
        gw.return_value = 8
        cal.return_value = {"by_week": by_week}
        r = assess_forecast_trust(sb, as_of=date(2026, 9, 25))
    assert r["by_owner"] == forecast_by_owner(COHORT["deals"])
    assert abs(sum(o["forecast_arr"] for o in r["by_owner"].values()) - r["pipeline"]["incremental_arr"]) < 0.01
    cohort_cols = [c for c in sb.selected("deals") if "forecast_category" in c and "new_arr" in c]
    assert cohort_cols and all("owner_email" in c for c in cohort_cols), sb.selected("deals")
    print("✓ assess_forecast_trust: the cohort query selects owner_email; by_owner splits the same "
          "deals and sums to the forecast total")


def test_every_rep_row_carries_its_live_figures():
    f = _compose("base")["figures"]["loss_concentration"]
    assert f["rep_context"] == REAL_LINES, f["rep_context"]
    by_rep = RAW["query_loss_concentration"]["by_rep"]
    assert len(f["rep_context"]) == len(by_rep) == 7
    for line, row in zip(f["rep_context"], by_rep):
        assert line.startswith(row["text"] + " | still live: "), line
    assert not any("jake.stangl" in line for line in f["rep_context"])
    assert "backward-looking" in f["rep_context_basis"] and "query_pipeline.by_owner" in f["rep_context_basis"]
    print("✓ all 7 rep rows carry forecast and open pipeline beside the loss row (Christian 14/14 with "
          "$601,800 forecast; Dan 4/6 and Scott 2/3 with no forecast deals); the SDR is not a rep row")


def test_note_asks_for_losses_with_live_context():
    for scenario in qh.SCENARIOS:
        note = _compose(scenario)["_synthesis_note"]
        assert "REPS: never give a rep's loss rate on its own" in note, note
        assert "figures.loss_concentration.rep_context" in note
    print("✓ the synthesis note: never a rep's loss rate on its own, always with its live figures")


def test_missing_sources_are_said_not_guessed():
    raw = copy.deepcopy(RAW)
    raw["query_forecast_trust"].pop("by_owner")
    raw["query_pipeline"]["by_owner"].pop("marcel@growthbook.io")
    lines = _compose("base", raw)["figures"]["loss_concentration"]["rep_context"]
    assert all("forecast by rep unavailable" in l for l in lines)
    assert lines[-1].endswith("open pipeline not among query_pipeline's top 10 owners"), lines[-1]
    raw = copy.deepcopy(RAW)
    raw["query_pipeline"] = {"status": "error", "error": "boom"}
    lines = _compose("base", raw)["figures"]["loss_concentration"]["rep_context"]
    assert all(l.endswith("open pipeline unavailable") for l in lines)
    raw = copy.deepcopy(RAW)
    raw["query_loss_concentration"] = {"status": "error", "error": "x"}
    assert "rep_context" not in _compose("base", raw)["figures"]["loss_concentration"]
    print("✓ no forecast split, an owner outside by_owner's top 10, a failed pipeline or loss "
          "primitive: stated in the line (or no lines), never a guessed $0")


def test_joined_lines_survive_every_model_input():
    disclosures = surv.collect_disclosures(RAW)
    for scenario in qh.SCENARIOS:
        c = _compose(scenario)
        violations, _ = run_all_checks(c, qh.ENTRY_POINTS[scenario])
        assert not violations, [v.message for v in violations]
        musts = REAL_LINES + [c["figures"]["loss_concentration"]["rep_context_basis"]] + \
            [s for _, _, s in disclosures]
        inputs = surv._model_inputs(c, scenario)
        for name, text in inputs.items():
            missing = [m[:60] for m in musts if not surv._present(m, text)]
            assert not missing, (scenario, name, missing[:5])
        json.loads(inputs["classifier synthesis"])      # the character cut never fired
        prim = c["primitives"]
        assert "by_rep" not in prim["query_loss_concentration"]       # carried once, in rep_context
        assert "by_owner" not in prim["query_forecast_trust"]
    print(f"✓ both views: 0 plausibility violations; the 7 joined rep lines, their basis and all "
          f"{len(disclosures)} disclosures reach every model input, whole")


def test_composed_budget():
    for scenario in qh.SCENARIOS:
        name = qh.ENTRY_POINTS[scenario]
        c = router._model_view(router._cap_rows_for_synthesis(copy.deepcopy(_compose(scenario))))
        n = len(json.dumps(c, default=str))
        assert n <= router.synth_payload_chars(name), (scenario, n)
    assert router.synth_payload_chars("query_pipeline") == router.SYNTH_PAYLOAD_CHARS
    print("✓ both composed views fit their own budget; every other handler keeps SYNTH_PAYLOAD_CHARS")


if __name__ == "__main__":
    test_forecast_by_owner_on_the_live_cohort()
    test_forecast_trust_splits_its_own_deals_by_owner()
    test_every_rep_row_carries_its_live_figures()
    test_note_asks_for_losses_with_live_context()
    test_missing_sources_are_said_not_guessed()
    test_joined_lines_survive_every_model_input()
    test_composed_budget()
    print("\n✅ All tests passed")
