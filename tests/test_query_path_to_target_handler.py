"""
query_path_to_target handler — Step A/B/D tests (tests-first, offline-capable).

Wraps path_to_target() + time_feasibility() from scripts/analytics/path_to_target.py.
This is a COMPOSER: it calls assess_pipeline_coverage, compute_cycle_time, and derives
days_remaining from the current quarter end to assemble all inputs.

STEP A — handler callable with empty params dict (no required params).
STEP B — appears in HANDLER_DESCRIPTIONS with meaningful description.
STEP D — planted-bug controls: time_feasibility and path_to_target unit tests.
         Existing pipeline covers the gap → net-new should be flagged as "upside".
         Feasible fraction near zero → net-new reframed as next period.
"""
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).parent.parent))
sys.path.insert(0, str(Path(__file__).parent.parent / "scripts" / "analytics"))

import api.router as router
from path_to_target import time_feasibility, path_to_target


# ---------------------------------------------------------------------------
# Step A — registration check (handler itself tested in live integration)
# ---------------------------------------------------------------------------

def test_step_a_handler_exists():
    import api.handlers as handlers_module
    assert hasattr(handlers_module, "query_path_to_target"), (
        "query_path_to_target not found in handlers module — implement it"
    )


# ---------------------------------------------------------------------------
# Step B — registry registration
# ---------------------------------------------------------------------------

def test_step_b_in_handler_descriptions():
    registry = getattr(router, "HANDLER_DESCRIPTIONS", {})
    assert "query_path_to_target" in registry, (
        f"'query_path_to_target' missing from HANDLER_DESCRIPTIONS"
    )


def test_step_b_description_mentions_target():
    registry = getattr(router, "HANDLER_DESCRIPTIONS", {})
    desc = registry.get("query_path_to_target", "").lower()
    assert any(kw in desc for kw in ["target", "gap", "path", "close the gap"]), (
        f"Description not meaningful for path-to-target handler: {desc!r}"
    )


# ---------------------------------------------------------------------------
# Step D — time_feasibility unit tests (planted-bug controls)
# ---------------------------------------------------------------------------

def test_feasibility_fraction_correct():
    """Feasible fraction = deals with cycle <= days_remaining / total."""
    cycles = [10, 20, 30, 40, 50]
    f = time_feasibility(30, cycles)
    assert f["feasible_fraction"] == 0.6  # 10, 20, 30 <= 30 → 3/5
    assert f["n_cycles"] == 5
    assert f["net_new_viable"] is True


def test_feasibility_near_zero_not_viable():
    cycles = [60, 70, 80, 90]  # none close within 20 days
    f = time_feasibility(20, cycles)
    assert f["feasible_fraction"] == 0.0
    assert f["net_new_viable"] is False


def test_feasibility_empty_history_is_none_not_zero():
    """No history → feasible_fraction is None, NOT 0 (unknown ≠ impossible)."""
    f = time_feasibility(30, [])
    assert f["feasible_fraction"] is None
    assert f["net_new_viable"] is False


def test_feasibility_drops_negative_cycles():
    """Negative cycle lengths are bad data and must be dropped before computing fraction."""
    f = time_feasibility(30, [10, -5, 20, None])
    assert f["n_cycles"] == 2  # only 10 and 20 are valid


# ---------------------------------------------------------------------------
# Step D — path_to_target unit tests
# ---------------------------------------------------------------------------

def test_existing_pipeline_covers_bare_gap():
    """When likely >= gap_bare, net_new_needed == 0 and headline says 'not required'."""
    feasibility = time_feasibility(30, [60, 70, 80])  # low fraction, near-zero
    result = path_to_target(
        gap_bare=500_000,
        existing_scenarios={"conservative": 400_000, "likely": 600_000, "stretch": 900_000},
        feasibility=feasibility,
    )
    assert result["bare_plan"]["net_new_needed"] == 0.0
    assert "not required" in result["headline"].lower() or "covers" in result["headline"].lower()
    assert result["bare_plan"]["covered_by_likely"] is True


def test_net_new_not_viable_reframes_to_next_period():
    """When net-new is needed but feasible_fraction is near-zero, headline reframes to NEXT period."""
    feasibility = time_feasibility(30, [60, 70, 80, 90])  # 0% feasible
    result = path_to_target(
        gap_bare=1_000_000,
        existing_scenarios={"conservative": 400_000, "likely": 500_000, "stretch": 800_000},
        feasibility=feasibility,
    )
    assert result["bare_plan"]["net_new_needed"] == 500_000.0
    assert result["net_new_viable"] is False
    assert "next period" in result["headline"].lower()


def test_partial_net_new_viable():
    """When net-new is viable, headline shows feasible fraction and next-period remainder."""
    cycles = [10, 20, 30, 40, 50, 60, 70, 80, 90, 100]  # 30% feasible in 35 days
    feasibility = time_feasibility(35, cycles)
    result = path_to_target(
        gap_bare=1_000_000,
        existing_scenarios={"conservative": 300_000, "likely": 700_000, "stretch": 1_500_000},
        feasibility=feasibility,
    )
    assert result["net_new_viable"] is True
    assert result["bare_plan"]["net_new_needed"] == 300_000.0
    assert result["bare_plan"]["net_new_feasible_this_period"] == pytest.approx(90_000.0)
    assert result["bare_plan"]["net_new_next_period"] == pytest.approx(210_000.0)


def test_padded_plan_uses_pad_multiplier():
    """Padded plan gap = gap_bare * pad_multiplier (default 1.5x)."""
    feasibility = time_feasibility(30, [10, 20, 30])
    result = path_to_target(
        gap_bare=1_000_000,
        existing_scenarios={"conservative": 0, "likely": 0, "stretch": 0},
        feasibility=feasibility,
    )
    assert result["gap_padded"] == pytest.approx(1_500_000.0)
    assert result["pad_multiplier"] == 1.5


def test_accounting_closes():
    """net_new_needed == net_new_feasible_this_period + net_new_next_period."""
    feasibility = time_feasibility(35, [10, 20, 30, 40, 50])
    result = path_to_target(
        gap_bare=800_000,
        existing_scenarios={"conservative": 500_000, "likely": 600_000, "stretch": 1_000_000},
        feasibility=feasibility,
    )
    bp = result["bare_plan"]
    assert bp["net_new_feasible_this_period"] + bp["net_new_next_period"] == pytest.approx(bp["net_new_needed"])
