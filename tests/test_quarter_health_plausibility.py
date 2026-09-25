#!/usr/bin/env python3
"""
The composed quarter-health view must pass the router's own plausibility
checks: trimming a row must never drop a field a check pairs with one it
keeps.

Live, 2026-09-25 20:04, "Are we in good shape this quarter?"
(query_quarter_health) shipped with a data-quality banner and 8 logged
ERRORs, one per late-stage high-risk deal: "days_past_benchmark (242)
without a valid cycle_benchmark_days (None)" for Bike24, Freie Presse,
facile.it, knowunity.ai, Mistral, Taxfix, Derive and Trade Me.

The benchmarks were never missing. query_high_priority_deal_risk returned
cycle_benchmark_days for all 8 (SMB 138, Mid-Market 168), and days_open -
benchmark = days_past_benchmark for every one. The composer's compact
high_risk_deals rows kept days_past_benchmark and dropped
cycle_benchmark_days and days_open, so check_benchmark_offsets read the
missing benchmark as None. The 8 of 17 and 9 of 21 high-risk figures were
right; the banner was false.

Regression fixture: those exact 8 deals, in the real capture
(tests/fixtures/quarter_health_primitives_2026_09_25.json).
"""
import copy
import json
import sys
from pathlib import Path

REPO = Path(__file__).parent.parent
sys.path.insert(0, str(REPO))
sys.path.insert(0, str(REPO / "scripts"))
sys.path.insert(0, str(REPO / "scripts" / "analytics"))

import logging  # noqa: E402
logging.disable(logging.CRITICAL)

import api.quarter_health as qh  # noqa: E402
from api.plausibility import run_all_checks  # noqa: E402

FIXTURE = json.loads((REPO / "tests" / "fixtures" / "quarter_health_primitives_2026_09_25.json").read_text())
RAW = {k: FIXTURE[k] for k in qh.PRIMITIVE_ORDER}
LIVE_EIGHT = {"Bike24", "Freie Presse", "facile.it", "knowunity.ai", "Mistral", "Taxfix",
              "Derive", "Trade Me"}


def _compose(scenario):
    return qh.compose_from_results(copy.deepcopy(RAW), scenario,
                                   stage_rates=FIXTURE["stage_close_rate"],
                                   deal_rows=FIXTURE["high_risk_deal_rows"])


def test_the_fixture_holds_the_eight_live_deals_with_real_benchmarks():
    hi = [d for d in RAW["query_high_priority_deal_risk"]["assessed_deals"]
          if d["overall_label"] == "high_risk"]
    assert {d["company_name"] for d in hi} == LIVE_EIGHT
    for d in hi:
        assert d["cycle_benchmark_days"] in (138, 168), d
        assert d["days_open"] - d["cycle_benchmark_days"] == d["days_past_benchmark"] > 30, d
    print("✓ the 8 live deals: every benchmark present (SMB 138 / Mid-Market 168), "
          "days_open - benchmark = days_past_benchmark > 30")


def test_composed_view_raises_no_plausibility_violation():
    for scenario in qh.SCENARIOS:
        c = _compose(scenario)
        violations, block = run_all_checks(c, qh.ENTRY_POINTS[scenario])
        assert not violations, [v.message for v in violations]
    print("✓ run_all_checks on both composed views: 0 violations (was 8 benchmark_offset ERRORs live)")


def test_compact_rows_keep_the_benchmark_beside_the_offset():
    c = _compose("base")
    rows = {r["company_name"]: r for r in c["primitives"]["query_high_priority_deal_risk"]["high_risk_deals"]}
    assert set(rows) == LIVE_EIGHT
    src = {d["company_name"]: d for d in RAW["query_high_priority_deal_risk"]["assessed_deals"]}
    for name, r in rows.items():
        for k in ("days_open", "cycle_benchmark_days", "days_past_benchmark"):
            assert r[k] == src[name][k], (name, k)
    print("✓ each compact high-risk row carries days_open, cycle_benchmark_days and "
          "days_past_benchmark exactly as the primitive returned them")


if __name__ == "__main__":
    test_the_fixture_holds_the_eight_live_deals_with_real_benchmarks()
    test_composed_view_raises_no_plausibility_violation()
    test_compact_rows_keep_the_benchmark_beside_the_offset()
    print("\n✅ All tests passed")
