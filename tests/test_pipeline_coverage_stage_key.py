#!/usr/bin/env python3
"""
query_pipeline_coverage weights each deal by its CURRENT stage.

The governed stage table (forecast_analyses.query_stage_close_rate) is built
from deals_snapshot.stage_order: the config order of the stage a deal was
in. assess_pipeline_coverage looked each deal up by
deals.highest_stage_order_reached instead, a high-water mark that numbers
Review 8/9 and never falls. On live FY2027 Q3 data that keyed 16 of 44
qualified Sales deals ($2,106,050) to a stage they are not in: Negotiating
deals weighted at Awaiting Signature's 65% instead of Negotiating's 29%,
Freie Presse (Awaiting Signature) at Review's 0.2%. Weighted pipeline read
$1,231,113; weighted by current stage it is $701,826.

Now:
  - qualified = a Sales-pipeline deal whose CURRENT stage is Discovery
    through Awaiting Signature (loss_concentration.discovery_or_later_stages,
    the same boundary as the qualified loss rate: not Meeting Set, not
    Review, not a closed stage);
  - its rate is the table's row for that stage's config order;
  - Renewal-pipeline expansion has no governed rate (the table is Sales,
    New+Expansion only): reported as renewal_not_weighted, never given a
    Sales stage's rate;
  - the deals query filters server-side (active, closing this quarter)
    instead of reading the whole table.

Real data: tests/fixtures/coverage_and_pace_2026_09_25.json (every active
deal closing in FY2027 Q3, captured read-only 2026-09-25) and the governed
stage table from the same day's primitive capture.
"""
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

from strict_supabase import StrictSupabase  # noqa: E402

FX = json.loads((REPO / "tests" / "fixtures" / "coverage_and_pace_2026_09_25.json").read_text())
RATES = json.loads((REPO / "tests" / "fixtures" /
                    "quarter_health_primitives_2026_09_25_renewals_not_assessed.json").read_text())["stage_close_rate"]
TARGET_ROW = {"period": "FY2027_Q3", "level": "team", "metric": "incremental_arr", "target_value": 1550000}


def run(deals=None, rates=None):
    from pipeline_coverage import assess_pipeline_coverage
    sb = StrictSupabase({"deals": deals if deals is not None else FX["active_this_quarter"],
                         "rep_targets": [TARGET_ROW]})
    with patch("utils.get_fiscal_quarter") as gfq, \
         patch("snapshot_deals.get_week_of_quarter") as gw, \
         patch("time_resolver.current_quarter_label") as cql, \
         patch("forecast_analyses.query_stage_close_rate") as sr, \
         patch("forecast_analyses.query_coverage_proxy_target_by_week") as curve:
        gfq.return_value = (date(2026, 8, 1), date(2026, 10, 31), "FY2027 Q3")
        gw.return_value = 8
        cql.return_value = "FY2027_Q3"
        sr.return_value = rates or RATES
        curve.return_value = {"by_week": {}}
        return assess_pipeline_coverage(sb, as_of=date(2026, 9, 25)), sb


def test_live_quarter_weighted_by_current_stage():
    r, sb = run()
    q, w = r["qualified_pipeline"], r["stage_weighting"]
    assert (q["deal_count"], round(q["raw_value"], 2)) == (44, 4907065.68), q
    assert round(w["weighted_value"], 2) == 701825.86, w["weighted_value"]
    assert (w["weighted_deal_count"], w["unweighted_deal_count"]) == (44, 0)
    rn = r["renewal_not_weighted"]
    assert (rn["deal_count"], rn["value"]) == (8, 295485.0) and "no governed" in rn["note"]
    assert "current stage" in r["scope"] and "highest_stage_order_reached" not in r["scope"]
    cols = sb.selected("deals")
    assert all("stage" in c for c in cols), cols
    print("✓ live FY2027 Q3: 44 qualified Sales deals, $4,907,066 raw, $701,826 weighted by current "
          "stage (was $1,231,113 by highest_stage_order_reached); 8 renewal deals ($295,485) not weighted")


def test_each_deal_uses_its_current_stage_row():
    by = RATES["by_stage_order"]
    def deal(stage, h, arr=100000, pipeline="default", i="x"):
        return {"deal_id": i, "pipeline_id": pipeline, "stage": stage, "new_arr": arr,
                "expansion_arr": 0, "highest_stage_order_reached": h, "close_date": "2026-10-15",
                "deal_status": "active"}
    r, _ = run([deal("43449439", 8, i="fp"), deal("24682892", 5, i="neg")])
    expect = 100000 * by["5"]["win_rate"] + 100000 * by["4"]["win_rate"]
    assert abs(r["stage_weighting"]["weighted_value"] - expect) < 1e-6, r["stage_weighting"]
    r, _ = run([deal("79653122", 3, i="ms"), deal("decisionmakerboughtin", 8, i="rv"),
                deal("1297321620", 2, pipeline="866608541", i="rn")])
    assert r["qualified_pipeline"]["deal_count"] == 0 and r["renewal_not_weighted"]["deal_count"] == 1
    print("✓ Awaiting Signature (high-water 8) weighs at Awaiting Signature's rate, Negotiating "
          "(high-water 5) at Negotiating's; Meeting Set and Review are not qualified; a renewal is "
          "not weighted with a Sales rate")


def test_stage_below_min_evidence_is_unweighted_not_defaulted():
    rates = json.loads(json.dumps(RATES))
    rates["by_stage_order"]["5"]["win_rate"] = None
    r, _ = run(rates=rates)
    w = r["stage_weighting"]
    assert w["unweighted_deal_count"] == 3 and round(w["unweighted_value"], 2) == 173390.68, w
    print("✓ a stage with no governed rate: its deals are unweighted (3, $173,391), never given 1.0")


if __name__ == "__main__":
    test_live_quarter_weighted_by_current_stage()
    test_each_deal_uses_its_current_stage_row()
    test_stage_below_min_evidence_is_unweighted_not_defaulted()
    print("\n✅ All tests passed")
