#!/usr/bin/env python3
"""
assess_deal_risk() states its own basis in its output.

Its method was documented only in docstrings and comments: the risk label is
cycle-length only (days open vs. the segment's 75th-percentile sales cycle
from closed-won deals; >30 days past = high_risk, 0-30 = moderate, within =
low, no benchmark = insufficient_data), MEDDICC is shown for context and not
weighted (p=0.80), and the label is not a probability. Nothing in the
returned dict said so, so a composed answer (the quarter-health composer)
could only relay counts with no basis, or have the composer invent one.

The primitive now returns `basis`, built from its own constants
(SEGMENT_CYCLE_BENCHMARKS, the 30-day threshold, MEDDICC_STALENESS_DAYS),
on every path including the empty one. query_high_priority_deal_risk
passes it through unchanged; assess_forecast_trust, which labels its
cohort with assess_deal_risk, relays it as `risk_basis`.
"""
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


def _deal(i, days_open, segment="SMB", stage=None, fc="COMMIT", close=None, **kw):
    today = date.today()
    d = {"deal_id": i, "company_name": f"Co {i}", "stage": stage or dra.LATE_STAGE_IDS[0],
         "create_date": (today - timedelta(days=days_open)).isoformat(),
         "close_date": close or today.isoformat(), "segment": segment,
         "forecast_category": fc, "deal_status": "active"}
    d.update(kw)
    return d


def _check_basis(basis):
    assert isinstance(basis, str) and basis, basis
    for seg, days in dra.SEGMENT_CYCLE_BENCHMARKS.items():
        assert f"{seg} {days}" in basis, (seg, days, basis)
    for phrase in ("cycle-length only", "75th percentile", "more than 30 days",
                   "not weighted", "not a probability"):
        assert phrase in basis, (phrase, basis)


def test_basis_on_the_empty_and_the_assessed_paths():
    sb = StrictSupabase({"analyses": []})
    empty = dra.assess_deal_risk([], sb)
    full = dra.assess_deal_risk([_deal("A", 400), _deal("B", 10)], sb)
    _check_basis(empty.get("basis"))
    assert full.get("basis") == empty.get("basis")
    assert full["summary"]["high_risk"] == 1
    print("✓ assess_deal_risk returns its basis on the empty and the assessed paths")


def test_basis_is_built_from_the_constants_it_classifies_with():
    sb = StrictSupabase({"analyses": []})
    with patch.dict(dra.SEGMENT_CYCLE_BENCHMARKS, {"SMB": 999}):
        b = dra.assess_deal_risk([], sb)["basis"]
    assert "SMB 999" in b and "SMB 138" not in b, b
    print("✓ the basis follows SEGMENT_CYCLE_BENCHMARKS (never a stale hand-written copy)")


def test_high_priority_handler_passes_the_basis_through():
    import asyncio
    import api.handlers as handlers
    sb = StrictSupabase({"deals": [_deal("A", 400), _deal("C", 20, stage="qualifiedtobuy")],
                         "analyses": []})
    r = asyncio.run(handlers.query_high_priority_deal_risk({}, sb))
    assert r["summary"]["total_assessed"] == 2, r["summary"]
    _check_basis(r.get("basis"))
    print("✓ query_high_priority_deal_risk passes the basis through")


def test_forecast_trust_relays_the_risk_basis():
    from forecast_trust import assess_forecast_trust
    deals = [_deal("F1", 400, pipeline_id="default", new_arr=50000, expansion_arr=None,
                   close="2026-09-30")]
    sb = StrictSupabase({"deals": deals, "analyses": []})
    by_week = {w: {"classified": 40, "won": 10, "win_rate": 0.25, "reason": None} for w in range(1, 14)}
    with patch("utils.get_fiscal_quarter") as gfq, \
         patch("snapshot_deals.get_week_of_quarter") as gw, \
         patch("forecast_analyses.query_commit_ml_calibration_by_week") as cal:
        gfq.return_value = (date(2026, 8, 1), date(2026, 10, 31), "FY2027 Q3")
        gw.return_value = 8
        cal.return_value = {"by_week": by_week}
        r = assess_forecast_trust(sb, as_of=date(2026, 9, 25))
    assert r["status"] == "ok" and r["high_risk_count"] == 1, r
    _check_basis(r.get("risk_basis"))
    print("✓ assess_forecast_trust relays the basis behind its high_risk_count as risk_basis")


if __name__ == "__main__":
    test_basis_on_the_empty_and_the_assessed_paths()
    test_basis_is_built_from_the_constants_it_classifies_with()
    test_high_priority_handler_passes_the_basis_through()
    test_forecast_trust_relays_the_risk_basis()
    print("\n✅ All tests passed")
