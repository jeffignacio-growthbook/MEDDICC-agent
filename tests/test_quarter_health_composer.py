#!/usr/bin/env python3
"""
Quarter-health composer (api/quarter_health.py): the contract, apart from
disclosure survival (tests/test_quarter_health_disclosure_survival.py).

  - One composer, fixed order: query_forecast_trust, query_pipeline,
    query_high_priority_deal_risk, query_loss_concentration, the same for
    both scenarios; the scenario changes the framing and adds the downside
    block, nothing else.
  - No new score: no composite/score/grade/index key anywhere the composer
    writes; each figure is its primitive's own number; the synthesis note
    forbids combining them and says the populations differ.
  - A primitive that raises or returns an error is reported as unavailable
    in its own section; the other three are unaffected (fail gracefully).
  - Downside: worst case = forecast (query_forecast_trust's COMMIT +
    MOST_LIKELY incremental ARR) minus each high-risk forecast deal's
    incremental ARR x (1 - its stage's win rate) from the governed table
    query_stage_close_rate() (the one query_pipeline_coverage weights
    with), looked up by the deal's CURRENT stage order, Sales pipeline
    only. The table is built from snapshot stage_order, which is the
    config order of the stage the deal was in; deals.highest_stage_order_
    reached is a different measure (highest stage ever, and Review = 9
    there vs 8 in snapshots), so it is not the key. A deal with no
    governed rate (Renewal pipeline, or a rate below min_evidence) is
    listed and left out of the weighted figure, never given a default
    weight; the floor (every at-risk deal lost) is stated beside it.
Real primitive outputs from tests/fixtures/quarter_health_primitives_2026_09_25.json.
"""
import asyncio
import copy
import json
import re
import sys
from pathlib import Path
from unittest.mock import patch

REPO = Path(__file__).parent.parent
sys.path.insert(0, str(REPO / "tests"))
sys.path.insert(0, str(REPO))
sys.path.insert(0, str(REPO / "scripts"))
sys.path.insert(0, str(REPO / "scripts" / "analytics"))

import logging  # noqa: E402
logging.disable(logging.CRITICAL)

import api.quarter_health as qh  # noqa: E402
import api.handlers as handlers  # noqa: E402

FIXTURE = json.loads((REPO / "tests" / "fixtures" / "quarter_health_primitives_2026_09_25.json").read_text())
ORDER = ("query_forecast_trust", "query_pipeline", "query_high_priority_deal_risk",
         "query_loss_concentration")
RAW = {k: FIXTURE[k] for k in ORDER}
RATES = FIXTURE["stage_close_rate"]
ROWS = FIXTURE["high_risk_deal_rows"]
SCORE_KEY = re.compile(r"(score|grade|rating|composite|index|health_value)", re.I)


def _compose(scenario, raw=None, rows=None):
    return qh.compose_from_results(copy.deepcopy(raw or RAW), scenario,
                                   stage_rates=RATES, deal_rows=ROWS if rows is None else rows)


class _SB:
    """Only the two downside reads go to the database here; the four
    primitives are replaced by recorders."""
    def __init__(self, rows):
        self.rows = rows

    def table(self, name):
        assert name == "deals", name
        rows = self.rows

        class Q:
            def select(self, *a, **k): return self
            def in_(self, col, ids):
                self._ids = set(map(str, ids)); return self
            def execute(self):
                class R: pass
                r = R(); r.data = [x for x in rows if str(x["deal_id"]) in self._ids]; return r
        return Q()


def _run_live(scenario, fail=None):
    calls = []

    def recorder(name):
        async def fn(params, sb):
            calls.append(name)
            if name == fail:
                raise RuntimeError("boom")
            return copy.deepcopy(RAW[name])
        return fn

    with patch.multiple(handlers, **{n: recorder(n) for n in ORDER}), \
         patch("forecast_analyses.query_stage_close_rate", side_effect=lambda sb=None: copy.deepcopy(RATES)) as rates:
        out = asyncio.run(qh.compose_quarter_health(_SB(ROWS), {}, scenario))
    return out, calls, rates


def test_one_composer_fixed_order_for_both_scenarios():
    for scenario in qh.SCENARIOS:
        out, calls, rates = _run_live(scenario)
        assert tuple(calls) == ORDER, (scenario, calls)
        assert rates.called == (scenario == "downside"), scenario
    assert qh.SCENARIOS == ("base", "downside")
    print("✓ both scenarios call the same four primitives in the fixed order; only the downside "
          "reads the governed stage table")


def test_scenarios_differ_only_in_framing_and_the_downside_block():
    base, down = _compose("base"), _compose("downside")
    assert "downside" not in base and "downside" in down
    strip = lambda c: {k: v for k, v in c.items()
                       if k not in ("scenario", "question_frame", "_synthesis_note", "downside")}
    assert strip(base) == strip(down)
    assert base["_synthesis_note"] != down["_synthesis_note"]
    print("✓ base and downside compositions are identical apart from framing and the downside block")


def _composer_keys(c):
    keys = []

    def walk(o, path):
        if isinstance(o, dict):
            for k, v in o.items():
                if path.startswith("primitives.") and path.count(".") >= 1:
                    continue                      # primitives' own fields, relayed verbatim
                keys.append(f"{path}.{k}".lstrip("."))
                walk(v, f"{path}.{k}".lstrip("."))
    walk(c, "")
    return keys


def test_no_new_score_and_the_note_forbids_blending():
    for scenario in qh.SCENARIOS:
        c = _compose(scenario)
        bad = [k for k in _composer_keys(c) if SCORE_KEY.search(k.split(".")[-1])]
        assert not bad, bad
        note = c["_synthesis_note"]
        for phrase in ("Do not combine", "different populations", "verdict"):
            assert phrase in note, (scenario, phrase)
        f = c["figures"]
        assert f["forecast_trust"]["forecast_arr"] == RAW["query_forecast_trust"]["pipeline"]["incremental_arr"]
        assert f["pipeline"]["total_pipeline"] == RAW["query_pipeline"]["total_pipeline"]
        assert f["deal_risk"]["summary"] == RAW["query_high_priority_deal_risk"]["summary"]
        assert f["loss_concentration"]["team_loss_rate"] == RAW["query_loss_concentration"]["team_loss_rate"]
    print("✓ no score/grade/composite key; each figure is its primitive's own number; the note "
          "forbids combining them")


def test_a_failing_primitive_is_reported_and_the_rest_survive():
    out, calls, _ = _run_live("base", fail="query_pipeline")
    assert tuple(calls) == ORDER
    assert out["figures"]["pipeline"]["status"] == "unavailable", out["figures"]["pipeline"]
    assert "boom" in out["figures"]["pipeline"]["error"]
    assert out["figures"]["forecast_trust"]["forecast_arr"] == RAW["query_forecast_trust"]["pipeline"]["incremental_arr"]
    assert "query_pipeline" in out["_synthesis_note"] and "unavailable" in out["_synthesis_note"]
    err = copy.deepcopy(RAW)
    err["query_loss_concentration"] = {"error": "Failed to assess loss concentration: x", "status": "error"}
    c = _compose("base", err)
    assert c["figures"]["loss_concentration"]["status"] == "unavailable"
    print("✓ a primitive that raises or errors is marked unavailable in its own section and named "
          "in the note; the other three are intact")


# ------------------------------------------------------------ downside maths

def _expected_downside():
    """Independent of the composer: straight from the fixture."""
    import yaml
    cfg = yaml.safe_load((REPO / "config" / "client.yaml").read_text())
    order = {s["id"]: s["order"] for p in cfg["pipeline"]["pipelines"] if p["id"] == "default"
             for s in p["stages"]}
    rates = RATES["by_stage_order"]
    ft = RAW["query_forecast_trust"]
    hi = {d["deal_id"] for d in ft["assessed_deals"] if d["overall_label"] == "high_risk"}
    weighted = unrated = total = 0.0
    for r in ROWS:
        assert r["deal_id"] in hi
        arr = (r.get("new_arr") or 0) + (r.get("expansion_arr") or 0)
        total += arr
        so = order.get(r["stage"]) if r["pipeline_id"] == "default" else None
        row = rates.get(str(so)) if so is not None else None
        wr = row.get("win_rate") if row else None
        if wr is None:
            unrated += arr
        else:
            weighted += arr * (1 - wr)
    f = ft["pipeline"]["incremental_arr"]
    return {"forecast": f, "at_risk": total, "weighted": weighted, "unrated": unrated,
            "worst": f - weighted, "floor": f - total}


def test_worst_case_on_the_real_capture():
    d = _compose("downside")["downside"]
    e = _expected_downside()
    near = lambda a, b: abs(a - b) < 0.01
    assert near(d["forecast_arr"], e["forecast"]), (d["forecast_arr"], e)
    assert near(d["at_risk_arr"], e["at_risk"]) and near(e["at_risk"], 567285.0), (d["at_risk_arr"], e)
    assert near(d["weighted_expected_loss"], e["weighted"]), (d["weighted_expected_loss"], e)
    assert near(d["unrated_at_risk_arr"], e["unrated"]) and near(e["unrated"], 130985.0), e
    assert near(d["worst_case_arr"], e["worst"]) and near(d["floor_if_all_at_risk_lost"], e["floor"])
    assert d["at_risk_count"] == 9 and d["unrated_count"] == 4, d
    by = {x["company_name"]: x for x in d["at_risk_deals"]}
    assert by["Freie Presse"]["stage_order"] == 5 and abs(by["Freie Presse"]["stage_win_rate"] - 0.6505) < 1e-3
    assert by["Skyscanner"]["stage_order"] == 3
    assert by["Mistral"]["stage_win_rate"] is None and "Renewal" in by["Mistral"]["unrated_reason"]
    assert "query_stage_close_rate" in d["basis"] and "current stage" in d["basis"]
    print(f"✓ downside on the real capture: forecast ${e['forecast']:,.0f} - weighted expected loss "
          f"${e['weighted']:,.0f} = worst case ${e['worst']:,.0f}; ${e['unrated']:,.0f} of renewal "
          f"at-risk ARR unrated (no governed rate); floor ${e['floor']:,.0f}")


def test_rate_is_keyed_by_current_stage_not_highest_stage_reached():
    rows = copy.deepcopy(ROWS)
    fp = next(r for r in rows if r["company_name"] == "Freie Presse")
    assert fp["highest_stage_order_reached"] == 8 and fp["stage"] == "43449439"
    d = _compose("downside", rows=rows)["downside"]
    x = next(x for x in d["at_risk_deals"] if x["company_name"] == "Freie Presse")
    assert x["stage_order"] == 5, x                  # Awaiting Signature, not Review's 8
    print("✓ Freie Presse (Awaiting Signature, highest_stage_order_reached 8) gets the Awaiting "
          "Signature rate, not Review's")


def test_renewal_deals_and_gated_rates_are_never_given_a_default_weight():
    rows = copy.deepcopy(ROWS)
    rates = copy.deepcopy(RATES)
    rates["by_stage_order"]["3"]["win_rate"] = None          # Skyscanner's stage below min_evidence
    d = qh.compose_from_results(copy.deepcopy(RAW), "downside", stage_rates=rates, deal_rows=rows)["downside"]
    sky = next(x for x in d["at_risk_deals"] if x["company_name"] == "Skyscanner")
    assert sky["stage_win_rate"] is None and sky["expected_loss"] is None and sky["unrated_reason"], sky
    renewal = [x for x in d["at_risk_deals"] if x["pipeline_id"] == "866608541"]
    assert len(renewal) == 4 and all(x["expected_loss"] is None for x in renewal), renewal
    assert d["unrated_count"] == 5
    print("✓ renewal-pipeline deals and a gated (null) stage rate stay unrated, never weighted "
          "at 0 or 1")


def test_forecast_risk_headline_is_dollar_shares_of_the_whole_forecast():
    """The line a reader gets first, built in code and required verbatim:
    high-risk and not-assessed ARR as shares of the WHOLE forecast, not a
    deal-count fraction over assessed deals only."""
    ft = {"forecast_arr": 1946175.68, "high_risk_arr": 436300.0, "not_assessed_arr": 225485.0,
          "not_assessed_deal_count": 6}
    line = qh.forecast_risk_headline(ft)
    assert line == ("22% of the forecast ($436,300 of $1,946,176) is high risk; 12% ($225,485 "
                    "across 6 Renewal-pipeline deals) has no risk read yet."), line
    assert qh.forecast_risk_headline({"forecast_arr": 100.0}) is None     # no risk dollars: no line
    raw = copy.deepcopy(RAW)
    raw["query_forecast_trust"]["risk_dollars"] = {"forecast_arr": 1946175.68, "high_risk_arr": 436300.0,
                                                   "not_assessed_arr": 225485.0}
    raw["query_forecast_trust"]["risk_summary"]["not_assessed"] = 6
    for scenario in qh.SCENARIOS:
        note = qh.compose_from_results(raw, scenario, stage_rates=RATES, deal_rows=ROWS)["_synthesis_note"]
        assert "verbatim: \"" + line + "\"" in note and "share of risk-assessed deals" in note, note
    assert qh.forecast_risk_headline(_compose("base")["figures"]["forecast_trust"]) is None
    print("✓ forecast risk headline: '22% of the forecast ($436,300 of $1,946,176) is high risk; 12% "
          "... has no risk read yet', required verbatim in both notes; absent without risk dollars")


def test_only_high_risk_forecast_deals_are_at_risk():
    """At-risk = the forecast cohort's high_risk label, nothing wider: a
    moderate_risk deal, and a high-risk deal outside the forecast cohort
    (query_high_priority_deal_risk's late-stage-only deals), are not
    subtracted from a forecast they are not in."""
    raw = copy.deepcopy(RAW)
    low = next(d for d in raw["query_forecast_trust"]["assessed_deals"] if d["overall_label"] == "low_risk")
    low["overall_label"] = "moderate_risk"
    d = qh.compose_from_results(raw, "downside", stage_rates=RATES, deal_rows=ROWS)["downside"]
    ids = {x["deal_id"] for x in d["at_risk_deals"]}
    assert low["deal_id"] not in ids and d["at_risk_count"] == 9, d["at_risk_count"]
    ft_hi = {x["deal_id"] for x in RAW["query_forecast_trust"]["assessed_deals"] if x["overall_label"] == "high_risk"}
    hp_hi = {x["deal_id"] for x in RAW["query_high_priority_deal_risk"]["assessed_deals"] if x["overall_label"] == "high_risk"}
    assert ids == ft_hi and hp_hi - ft_hi, "the two cohorts differ, and only the forecast one is used"
    assert d["moderate_risk_excluded_count"] == 2, d.get("moderate_risk_excluded_count")
    assert "2 moderate_risk deals" in d["basis"] and "not subtracted" in d["basis"], d["basis"]
    real = _compose("downside")["downside"]          # the capture has one: Cochlear Ltd, 25 days past
    assert real["moderate_risk_excluded_count"] == 1 and "1 moderate_risk deal in" in real["basis"], real["basis"]
    assert "Cochlear" not in {x["company_name"] for x in real["at_risk_deals"]}
    print(f"✓ at-risk = the forecast cohort's high_risk deals only ({len(hp_hi - ft_hi)} late-stage "
          "high-risk deals outside the forecast are not subtracted; moderate_risk is not at-risk, and "
          "the basis says how many were left out)")


def test_a_high_risk_deal_with_no_deals_row_is_unrated_not_dropped():
    d = _compose("downside", rows=[r for r in ROWS if r["company_name"] != "Taxfix"])["downside"]
    tx = next(x for x in d["at_risk_deals"] if x["company_name"] == "Taxfix")
    assert tx["incremental_arr"] is None and "no deals row" in tx["unrated_reason"], tx
    assert d["at_risk_count"] == 9
    print("✓ a high-risk deal whose deals row is missing is listed as unrated, not dropped")


if __name__ == "__main__":
    for name, fn in list(globals().items()):
        if name.startswith("test_") and callable(fn):
            fn()
    print("\n✅ All tests passed")
