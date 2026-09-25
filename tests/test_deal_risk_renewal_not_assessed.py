#!/usr/bin/env python3
"""
Renewal-pipeline deals are not risk-assessed by assess_deal_risk.

Its label is cycle length only: days open vs. a segment benchmark taken from
won deals' create-to-close time. Renewals run on a different clock (won
renewals' 75th percentile is 364 days for SMB against the 138-day benchmark
applied), so on 2026-09-25 the label called Bike24, facile.it, Mistral and
Boylesports high risk for being renewals, not for being at risk: 4 of the
forecast's 9 high-risk deals, 3 of the late-stage view's 8. There is no
reliable renewal-risk signal yet, and a renewal benchmark would only add
false precision to a signal that doesn't apply.

So a deal on the Renewal pipeline (866608541) gets no label. It goes to
not_assessed_deals with the reason, is counted in summary.not_assessed, and
is in none of total_assessed / high / moderate / low / insufficient_data
(so high_risk_fraction is over assessed deals only). Never dropped
silently. The same holds on every path: get_at_risk_deals (now selecting
pipeline_id), query_high_priority_deal_risk, assess_forecast_trust, and the
dynamic loop's assess_deal_risk tool (which also dropped `basis` until now).
"""
import asyncio
import sys
from datetime import date, timedelta
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

import deal_risk_assessor as dra  # noqa: E402
from strict_supabase import StrictSupabase  # noqa: E402

RENEWAL = "866608541"


def _deal(i, days_open, pipeline, segment="SMB", stage=None, fc="COMMIT", **kw):
    today = date.today()
    d = {"deal_id": i, "company_name": f"Co {i}", "stage": stage or dra.LATE_STAGE_IDS[0],
         "create_date": (today - timedelta(days=days_open)).isoformat(),
         "close_date": today.isoformat(), "segment": segment, "forecast_category": fc,
         "deal_status": "active", "pipeline_id": pipeline}
    d.update(kw)
    return d


def _check(result, assessed_ids, not_assessed_ids):
    s = result["summary"]
    assert {d["deal_id"] for d in result["assessed_deals"]} == assessed_ids, result["assessed_deals"]
    na = result.get("not_assessed_deals") or []
    assert {d["deal_id"] for d in na} == not_assessed_ids, na
    assert s["not_assessed"] == len(not_assessed_ids), s
    assert s["total_assessed"] == len(assessed_ids), s
    assert sum(s[k] for k in ("high_risk", "moderate_risk", "low_risk", "insufficient_data")) == len(assessed_ids)
    for d in na:
        assert "renewal" in d["reason"].lower() and d["pipeline_id"] == RENEWAL, d
    assert "renewal" in result["not_assessed_note"].lower()
    assert "Renewal-pipeline deals are not assessed" in result["basis"], result["basis"]


def test_assess_deal_risk_reports_renewals_as_not_assessed():
    sb = StrictSupabase({"analyses": []})
    r = dra.assess_deal_risk([_deal("S", 400, "default"), _deal("R", 400, RENEWAL),
                              _deal("S2", 10, "default")], sb)
    _check(r, {"S", "S2"}, {"R"})
    assert r["summary"]["high_risk"] == 1 and r["summary"]["low_risk"] == 1
    empty = dra.assess_deal_risk([], sb)
    assert empty["summary"]["not_assessed"] == 0 and empty["not_assessed_deals"] == []
    print("✓ assess_deal_risk: a 400-day renewal is not assessed (reason stated, counted), "
          "the 400-day sales deal is high risk; counts cover assessed deals only")


def test_get_at_risk_deals_selects_pipeline_and_excludes_renewals():
    import api.handlers as handlers
    deals = [_deal("S", 400, "default"), _deal("R", 400, RENEWAL, stage="1297321622"),
             _deal("L", 20, "default", stage="qualifiedtobuy")]
    sb = StrictSupabase({"deals": deals, "analyses": []})
    r = asyncio.run(handlers.query_high_priority_deal_risk({}, sb))
    _check(r, {"S", "L"}, {"R"})
    assert all("pipeline_id" in cols for cols in sb.selected("deals")), sb.selected("deals")
    print("✓ query_high_priority_deal_risk: selects pipeline_id; the renewal COMMIT deal is "
          "not assessed and outside every count")


def test_forecast_trust_fraction_is_over_assessed_deals_only():
    from forecast_trust import assess_forecast_trust
    deals = [_deal("S", 400, "default", new_arr=50000, expansion_arr=None, close_date="2026-09-30"),
             _deal("R", 400, RENEWAL, new_arr=None, expansion_arr=20000, close_date="2026-09-30",
                   fc="MOST_LIKELY"),
             _deal("S2", 10, "default", new_arr=10000, expansion_arr=None, close_date="2026-09-30"),
             _deal("M", 150, "default", new_arr=5000, expansion_arr=None, close_date="2026-09-30")]  # moderate
    sb = StrictSupabase({"deals": deals, "analyses": []})
    by_week = {w: {"classified": 40, "won": 10, "win_rate": 0.25, "reason": None} for w in range(1, 14)}
    with patch("utils.get_fiscal_quarter") as gfq, \
         patch("snapshot_deals.get_week_of_quarter") as gw, \
         patch("forecast_analyses.query_commit_ml_calibration_by_week") as cal:
        gfq.return_value = (date(2026, 8, 1), date(2026, 10, 31), "FY2027 Q3")
        gw.return_value = 8
        cal.return_value = {"by_week": by_week}
        r = assess_forecast_trust(sb, as_of=date(2026, 9, 25))
    assert r["pipeline"]["deal_count"] == 4, r["pipeline"]          # the forecast itself is unchanged
    assert r["high_risk_count"] == 1 and r["high_risk_fraction"] == 1 / 3, r
    assert r["risk_summary"]["moderate_risk"] == 1
    assert [d["deal_id"] for d in r["risk_not_assessed"]["deals"]] == ["R"], r["risk_not_assessed"]
    assert "renewal" in r["risk_not_assessed"]["note"].lower()
    rd = r["risk_dollars"]
    assert (rd["forecast_arr"], rd["high_risk_arr"], rd["not_assessed_arr"]) == (85000, 50000, 20000), rd
    assert rd["high_risk_share_of_forecast"] == 50000 / 85000 and rd["not_assessed_share_of_forecast"] == 20000 / 85000
    assert "whole forecast" in rd["note"]
    print("✓ forecast trust: the forecast still counts all 4 deals; the high-risk fraction is 1 of "
          "the 3 assessed (the moderate deal's dollars are not high-risk dollars), the renewal is reported as not assessed, and risk_dollars gives high-risk "
          "and not-assessed dollars as shares of the whole forecast")


def test_loop_tool_keeps_basis_and_not_assessed():
    import api.tools as tools
    deals = [_deal("S", 400, "default"), _deal("R", 400, RENEWAL, stage="1297321622")]
    sb = StrictSupabase({"deals": deals, "analyses": []})
    r = asyncio.run(tools.assess_deal_risk(sb))
    assert r["basis"] == dra.risk_basis(), r.keys()
    assert [d["deal_id"] for d in r["not_assessed_deals"]] == ["R"] and "renewal" in r["not_assessed_note"].lower()
    assert r["summary"]["not_assessed"] == 1 and {x["deal_id"] for x in r["rows"]} == {"S"}
    print("✓ the loop's assess_deal_risk tool now carries basis, not_assessed_deals and the note")


if __name__ == "__main__":
    test_assess_deal_risk_reports_renewals_as_not_assessed()
    test_get_at_risk_deals_selects_pipeline_and_excludes_renewals()
    test_forecast_trust_fraction_is_over_assessed_deals_only()
    test_loop_tool_keeps_basis_and_not_assessed()
    print("\n✅ All tests passed")
