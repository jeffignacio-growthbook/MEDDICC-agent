#!/usr/bin/env python3
"""
Path-to-target: time-feasibility gate + allocated dual-lever gap plan — tests first.

Combines the gap (bare and 1.5x-padded) with a time-feasibility fraction and
splits the gap across two levers:
  - existing pipeline (ALWAYS available): covered by the Conservative/Likely/
    Stretch scenario totals a caller supplies (the deal-level scenario planning).
  - net-new pipeline: sized ONLY to the time-feasible fraction of a newly-created
    deal that could realistically close before period end. When that fraction is
    near zero this late in the quarter, net-new is reframed as next-period.

time_feasibility is data-driven: the fraction of historical won deals whose
cycle (create->close) fits inside the days remaining — same historical source
family as pipeline_coverage's stage win-rate table.

Real validation (FY2027 Q3, captured read-only 2026-09-26 via Supabase MCP):
  gap remaining $1,176,600; ~5 weeks (35 days) left.
  Existing in-quarter pipeline, governed stage-weighted:
    Conservative (proposal+) $1,304,403; Likely $1,527,544; Stretch (gross) $4,897,066.
  Won-deal cycle (n=78, last ~4 quarters): avg 80.7d, median 56.5d,
    39.7% close in <= 35 days -> feasible fraction 0.397 for a 35-day window.
"""
import sys
from pathlib import Path

REPO = Path(__file__).parent.parent
sys.path.insert(0, str(REPO / "scripts"))
sys.path.insert(0, str(REPO / "scripts" / "analytics"))

from path_to_target import time_feasibility, path_to_target


# ---- time_feasibility ----------------------------------------------------

def test_feasibility_is_share_within_window():
    cycles = [10, 20, 30, 40, 50, 60, 70, 80, 90, 100]  # 10 deals
    f = time_feasibility(35, cycles)
    assert f["feasible_fraction"] == 0.3  # 10,20,30 <= 35 -> 3/10
    assert f["n_cycles"] == 10
    assert f["avg_cycle_days"] == 55.0
    assert f["net_new_viable"] is True   # 0.3 >= 0.15


def test_feasibility_near_zero_flags_not_viable():
    cycles = [90, 100, 110, 120]  # none close within 35d
    f = time_feasibility(35, cycles)
    assert f["feasible_fraction"] == 0.0
    assert f["net_new_viable"] is False


def test_feasibility_empty_history_is_none_not_zero():
    f = time_feasibility(35, [])
    assert f["feasible_fraction"] is None
    assert f["net_new_viable"] is False


def test_feasibility_ignores_negative_cycles():
    f = time_feasibility(35, [10, -5, 20])  # -5 dropped as bad data
    assert f["n_cycles"] == 2
    assert f["feasible_fraction"] == 1.0


# ---- path_to_target allocation ------------------------------------------

def _feas(frac, viable=True):
    return {"feasible_fraction": frac, "net_new_viable": viable,
            "days_remaining": 35, "n_cycles": 78, "avg_cycle_days": 80.7,
            "median_cycle_days": 56.5, "near_zero_threshold": 0.15}


def test_existing_covers_gap_no_net_new():
    scen = {"conservative": 1_304_403, "likely": 1_527_544, "stretch": 4_897_066}
    r = path_to_target(1_176_600, scen, _feas(0.397))
    b = r["bare_plan"]
    assert b["net_new_needed"] == 0.0, "Likely already exceeds the bare gap"
    assert b["covered_by_conservative"] is True   # even Conservative covers it
    assert b["covered_by_likely"] is True


def test_padded_gap_sizes_net_new_by_feasibility():
    scen = {"conservative": 1_304_403, "likely": 1_527_544, "stretch": 4_897_066}
    r = path_to_target(1_176_600, scen, _feas(0.397), pad_multiplier=1.5)
    assert r["gap_padded"] == 1_764_900.0
    p = r["padded_plan"]
    # net-new needed beyond Likely = 1,764,900 - 1,527,544 = 237,356
    assert round(p["net_new_needed"], 0) == 237_356
    # feasible this period = needed * 0.397
    assert round(p["net_new_feasible_this_period"], 0) == round(237_356 * 0.397, 0)
    # the rest rolls to next period
    assert round(p["net_new_next_period"], 0) == round(237_356 * (1 - 0.397), 0)
    assert r["net_new_viable"] is True


def test_net_new_needed_never_negative():
    scen = {"conservative": 2_000_000, "likely": 3_000_000, "stretch": 5_000_000}
    r = path_to_target(1_000_000, scen, _feas(0.4))
    assert r["bare_plan"]["net_new_needed"] == 0.0
    assert r["padded_plan"]["net_new_needed"] == 0.0  # 1.5M gap < 3M likely


def test_near_zero_feasibility_reframes_net_new_next_period():
    scen = {"conservative": 100_000, "likely": 200_000, "stretch": 300_000}
    r = path_to_target(1_000_000, scen, _feas(0.05, viable=False))
    p = r["bare_plan"]
    assert p["net_new_needed"] == 800_000.0     # 1,000,000 - 200,000
    assert round(p["net_new_feasible_this_period"], 0) == 40_000  # 800k * 0.05
    assert round(p["net_new_next_period"], 0) == 760_000
    assert r["net_new_viable"] is False
    assert "next" in r["headline"].lower() and "period" in r["headline"].lower()


def test_real_fy2027q3_validation():
    """The known case: existing pipeline covers the bare gap at every scenario;
    net-new is only needed for the padded target and only ~40% can land in the
    35 days left, so most of it targets next quarter."""
    scen = {"conservative": 1_304_403, "likely": 1_527_544, "stretch": 4_897_066}
    r = path_to_target(1_176_600, scen, _feas(0.397))
    # existing lever alone closes the bare gap (all three scenarios clear it)
    assert r["bare_plan"]["covered_by_conservative"]
    assert r["bare_plan"]["net_new_needed"] == 0.0
    # net-new is a viable-but-partial lever (39.7% >= 15%), not near-zero
    assert r["net_new_viable"] is True
    # padded target does need some net-new, most of which rolls to next quarter
    assert r["padded_plan"]["net_new_needed"] > 0
    assert r["padded_plan"]["net_new_next_period"] > r["padded_plan"]["net_new_feasible_this_period"]


if __name__ == "__main__":
    import inspect
    for name, fn in sorted(globals().items()):
        if name.startswith("test_") and inspect.isfunction(fn):
            fn(); print(f"✓ {name}")
    print("\n✅ All tests passed")
