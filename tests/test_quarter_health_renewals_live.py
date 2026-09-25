#!/usr/bin/env python3
"""
Quarter health on the live capture taken after Renewal-pipeline deals
stopped being risk-assessed (2026-09-25 03:28 UTC, workflow run
36090506178, md5 53bb8c672da5fe3aa8feeb787ca3083b):
tests/fixtures/quarter_health_primitives_2026_09_25_renewals_not_assessed.json

What the capture holds, checked here so the reported figures are the
code's, not a hand count:
  forecast (COMMIT+MOST_LIKELY, FY2027 Q3): 21 deals, $1,946,175.68;
    15 assessed, 5 high risk (Skyscanner, Freie Presse, Derive, Taxfix,
    Trade Me), 0 moderate; 6 not assessed (Bike24, Boylesports, Mistral,
    facile.it, Cochlear Ltd, Little Caesars: all Renewal pipeline)
  late-stage/COMMIT view: 14 assessed, 5 high risk (Freie Presse, Taxfix,
    knowunity.ai, Trade Me, Derive); 3 not assessed (Bike24, Mistral,
    facile.it)

And the composed result: no plausibility violation, every disclosure
(including the not-assessed note) reaches every model input, and the
downside subtracts only the 5 Sales-pipeline high-risk deals, with the 6
renewals named as not assessed rather than left unrated.
"""
import copy
import json
import sys
from pathlib import Path

REPO = Path(__file__).parent.parent
sys.path.insert(0, str(REPO / "tests"))
sys.path.insert(0, str(REPO))
sys.path.insert(0, str(REPO / "scripts"))
sys.path.insert(0, str(REPO / "scripts" / "analytics"))

import logging  # noqa: E402
logging.disable(logging.CRITICAL)

import api.quarter_health as qh  # noqa: E402
from api.plausibility import run_all_checks  # noqa: E402
import test_quarter_health_disclosure_survival as surv  # noqa: E402

FIXTURE = json.loads((REPO / "tests" / "fixtures" /
                      "quarter_health_primitives_2026_09_25_renewals_not_assessed.json").read_text())
RAW = {k: FIXTURE[k] for k in qh.PRIMITIVE_ORDER}
FT, HP = RAW["query_forecast_trust"], RAW["query_high_priority_deal_risk"]
RENEWALS_FT = {"Bike24", "Boylesports", "Mistral", "facile.it", "Cochlear Ltd", "Little Caesars"}


def _compose(scenario):
    return qh.compose_from_results(copy.deepcopy(RAW), scenario,
                                   stage_rates=FIXTURE["stage_close_rate"],
                                   deal_rows=FIXTURE["high_risk_deal_rows"])


def _names(res, label):
    return {d["company_name"] for d in res["assessed_deals"] if d["overall_label"] == label}


def test_the_capture_excludes_renewals_from_risk():
    assert FT["pipeline"]["deal_count"] == 21 and FT["pipeline"]["incremental_arr"] == 1946175.68
    assert FT["risk_summary"]["total_assessed"] == 15 and FT["risk_summary"]["not_assessed"] == 6
    assert _names(FT, "high_risk") == {"Skyscanner", "Freie Presse", "Derive", "Taxfix", "Trade Me"}
    assert _names(FT, "moderate_risk") == set()
    assert {d["company_name"] for d in FT["risk_not_assessed"]["deals"]} == RENEWALS_FT
    assert abs(FT["high_risk_fraction"] - 5 / 15) < 1e-9
    assert HP["summary"]["total_assessed"] == 14 and HP["summary"]["not_assessed"] == 3
    assert _names(HP, "high_risk") == {"Freie Presse", "Taxfix", "knowunity.ai", "Trade Me", "Derive"}
    assert {d["company_name"] for d in HP["not_assessed_deals"]} == {"Bike24", "Mistral", "facile.it"}
    assert all(r["pipeline_id"] == "default" for r in FIXTURE["high_risk_deal_rows"])
    print("✓ live capture: forecast 5 high of 15 assessed (6 renewals not assessed); late-stage "
          "5 high of 14 assessed (3 renewals not assessed)")


def test_composed_views_pass_plausibility_and_keep_every_disclosure():
    disclosures = surv.collect_disclosures(RAW)
    assert any(p.endswith("risk_not_assessed.note") for _, p, _ in disclosures)
    assert any(p.endswith(".not_assessed_note") for _, p, _ in disclosures)
    for scenario in qh.SCENARIOS:
        c = _compose(scenario)
        violations, _ = run_all_checks(c, qh.ENTRY_POINTS[scenario])
        assert not violations, [v.message for v in violations]
        for name, text in surv._model_inputs(c, scenario).items():
            missing = [p for _, p, s in disclosures if not surv._present(s, text)]
            assert not missing, (scenario, name, missing[:5])
        prim = c["primitives"]
        assert set(prim["query_forecast_trust"]["risk_not_assessed"]["not_assessed_companies"]) == RENEWALS_FT
        assert prim["query_high_priority_deal_risk"]["not_assessed_count"] == 3
    print(f"✓ both composed views: 0 plausibility violations; all {len(disclosures)} disclosures, "
          "the not-assessed note included, reach every model input; renewals named")


def test_downside_subtracts_only_sales_high_risk_deals():
    d = _compose("downside")["downside"]
    assert d["at_risk_count"] == 5 and d["unrated_count"] == 0, d
    assert all(x["pipeline_id"] == "default" for x in d["at_risk_deals"])
    assert d["renewal_not_assessed_count"] == 6 and d["moderate_risk_excluded_count"] == 0
    assert "6 Renewal-pipeline deals in the forecast are not risk-assessed" in d["basis"], d["basis"]
    assert abs(d["at_risk_arr"] - 436300.0) < 0.01
    assert abs(d["floor_if_all_at_risk_lost"] - (1946175.68 - 436300.0)) < 0.01
    assert d["worst_case_arr"] > d["floor_if_all_at_risk_lost"]
    print(f"✓ downside: 5 Sales high-risk deals (${d['at_risk_arr']:,.0f}), expected loss "
          f"${d['weighted_expected_loss']:,.0f}, worst case ${d['worst_case_arr']:,.0f}, floor "
          f"${d['floor_if_all_at_risk_lost']:,.0f}; 6 renewals not assessed, 0 unrated")


if __name__ == "__main__":
    test_the_capture_excludes_renewals_from_risk()
    test_composed_views_pass_plausibility_and_keep_every_disclosure()
    test_downside_subtracts_only_sales_high_risk_deals()
    print("\n✅ All tests passed")
