"""
The full set of real quarter-health inputs for 2026-09-25, assembled from
live read-only captures (all taken after the deals table's last update at
01:28 UTC, so they describe the same data):

  query_forecast_trust, query_pipeline, query_high_priority_deal_risk,
  stage close rates, high-risk deal rows
      quarter_health_primitives_2026_09_25_renewals_not_assessed.json
      (forecast_trust.by_owner added from forecast_cohort_owners_2026_09_25.json)
  query_loss_concentration
      the current code over loss_concentration_fy2027_q3_2026_09_25.json
  query_pipeline_coverage, bookings seasonality
      the current code over coverage_and_pace_2026_09_25.json

compose(scenario) composes them as production would on that day.
"""
import copy
import json
from datetime import date
from pathlib import Path

REPO = Path(__file__).parent.parent
AS_OF = date(2026, 9, 25)
_FX = REPO / "tests" / "fixtures"
PRIMS = json.loads((_FX / "quarter_health_primitives_2026_09_25_renewals_not_assessed.json").read_text())
# query_stage_close_rate keys by_stage_order by int stage order in production;
# JSON turned them into strings, which hid a live crash (2026-09-25 06:22 UTC,
# tests/test_int_keys_reach_plausibility.py). Restore the production shape.
PRIMS["stage_close_rate"]["by_stage_order"] = {
    int(k): v for k, v in PRIMS["stage_close_rate"]["by_stage_order"].items()}


def build():
    from forecast_trust import forecast_by_owner
    import test_loss_rate_qualified as lossfx
    import test_pipeline_coverage_stage_key as covfx
    import test_bookings_seasonality as szfx
    cohort = json.loads((_FX / "forecast_cohort_owners_2026_09_25.json").read_text())
    raw = {k: copy.deepcopy(PRIMS[k]) for k in
           ("query_forecast_trust", "query_pipeline", "query_high_priority_deal_risk")}
    ft = raw["query_forecast_trust"]
    ft["by_owner"] = forecast_by_owner(cohort["deals"])
    # risk_dollars (added to forecast_trust after this capture): the capture's
    # own labels over the cohort's per-deal incremental ARR, as forecast_trust
    # computes it (tests/test_deal_risk_renewal_not_assessed.py covers that code).
    arr = {d["deal_id"]: (d["new_arr"] or 0) + (d["expansion_arr"] or 0) for d in cohort["deals"]}
    total = ft["pipeline"]["incremental_arr"]
    hi = sum(arr[d["deal_id"]] for d in ft["assessed_deals"] if d["overall_label"] == "high_risk")
    na = sum(arr[d["deal_id"]] for d in ft["risk_not_assessed"]["deals"])
    ft["risk_dollars"] = {"forecast_arr": total, "high_risk_arr": hi,
                          "high_risk_share_of_forecast": hi / total, "not_assessed_arr": na,
                          "not_assessed_share_of_forecast": na / total,
                          "note": ("Shares are of the whole forecast's incremental ARR: high-risk "
                                   "deals' ARR, and the ARR of deals with no risk read (Renewal "
                                   "pipeline, not assessed).")}
    raw["query_loss_concentration"] = lossfx.real_result()
    raw["query_pipeline_coverage"] = covfx.run(rates=PRIMS["stage_close_rate"])[0]
    return raw, szfx.run()[0]


RAW, SEASONALITY = build()


def compose(scenario, raw=None, seasonality=None):
    import api.quarter_health as qh
    return qh.compose_from_results(copy.deepcopy(raw or RAW), scenario,
                                   stage_rates=PRIMS["stage_close_rate"],
                                   deal_rows=PRIMS["high_risk_deal_rows"], as_of=AS_OF,
                                   seasonality=seasonality if seasonality is not None else SEASONALITY)
