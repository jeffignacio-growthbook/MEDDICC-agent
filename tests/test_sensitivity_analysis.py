"""
Single-factor "what if" sensitivity analysis (Tier C) — tests first.

Built on Tier A (metric_reconciliation) and Tier B stage 1
(rate_mix_decomposition). Standalone, read-only, no handler.

Two kinds of sensitivity:
  - rate: hold every segment's WEIGHT fixed, substitute ONE segment's rate with
    a hypothetical (or the "team_average" shortcut), recompute the weighted-
    average total. Delta = weight · (hypothetical − real).
  - sum: hold the sum-over-deals total, substitute one or more deals' values
    with a hypothetical, recompute. Delta = Σ(hypothetical − real).

The required null-scenario sanity check (Part 3): substituting the real value
back must reproduce the real total EXACTLY. It is a first-class, self-checking
property of both functions (they raise if a null scenario ever moves the
total), not just a test assertion.

Part 4 validates against a real, already-reasoned case: Christian's qualified
loss rate this quarter. Real pinned values (captured read-only 2026-09-26 via
Supabase MCP, project htgvkqycrwesdysustxd; qualified basis = Sales/default
pipeline deals seen at Discovery-or-later in deals_snapshot on/before close,
not closed as Disqualified — the same basis as loss_concentration.py):
FY2027-Q3 window 2026-08-01..2026-10-31.
"""
import sys
from pathlib import Path

REPO = Path(__file__).parent.parent
sys.path.insert(0, str(REPO / "scripts"))
sys.path.insert(0, str(REPO / "scripts" / "analytics"))

from sensitivity_analysis import (
    rate_sensitivity, rate_sensitivity_from_decomposition,
    sum_sensitivity, sum_sensitivity_from_reconciliation,
)
from rate_mix_decomposition import decompose_rate


# ---- Part 1: rate-based sensitivity --------------------------------------

def _simple_table():
    # two segments, overall = 0.5*0.8 + 0.5*0.2 = 0.5
    return {"A": {"weight": 0.5, "rate": 0.8},
            "B": {"weight": 0.5, "rate": 0.2}}


def test_rate_basic_substitution():
    r = rate_sensitivity(_simple_table(), "A", 0.3)
    assert abs(r["real_total"] - 0.5) < 1e-12
    # hold A's weight (0.5), rate 0.8 -> 0.3: delta = 0.5*(0.3-0.8) = -0.25
    assert abs(r["delta"] - (-0.25)) < 1e-12
    assert abs(r["hypothetical_total"] - 0.25) < 1e-12


def test_rate_team_average_shortcut_resolves_to_overall():
    r = rate_sensitivity(_simple_table(), "A", "team_average")
    assert abs(r["hypothetical_rate"] - 0.5) < 1e-12, "shortcut must resolve to overall rate"
    # A 0.8 -> 0.5: delta = 0.5*(0.5-0.8) = -0.15 -> total 0.35
    assert abs(r["hypothetical_total"] - 0.35) < 1e-12
    assert r["hypothetical_rate_input"] == "team_average"


def test_rate_null_scenario_reproduces_total_exactly():
    """Part 3: substituting A's real rate back must reproduce the total EXACTLY."""
    r = rate_sensitivity(_simple_table(), "A", 0.8)
    assert r["is_null"] is True
    assert r["hypothetical_total"] == r["real_total"], "null scenario must be exact"
    assert r["delta"] == 0.0


def test_rate_overall_mismatch_raises():
    # stated overall inconsistent with weight*rate table -> caught, not silently used
    try:
        rate_sensitivity(_simple_table(), "A", 0.3, real_overall_rate=0.99)
    except ValueError:
        pass
    else:
        raise AssertionError("a table inconsistent with the stated overall rate must raise")


def test_rate_unknown_segment_raises():
    try:
        rate_sensitivity(_simple_table(), "Z", 0.3)
    except (KeyError, ValueError):
        pass
    else:
        raise AssertionError("an unknown segment must raise")


def test_rate_from_decomposition_extracts_side():
    base = [{"seg": "A", "st": "lost"}, {"seg": "A", "st": "won"},
            {"seg": "B", "st": "lost"}, {"seg": "B", "st": "won"}]
    comp = [{"seg": "A", "st": "lost"}, {"seg": "A", "st": "lost"},
            {"seg": "B", "st": "won"}, {"seg": "B", "st": "won"}]
    d = decompose_rate(base, comp, segment="seg", outcome=("st", "lost"))
    r = rate_sensitivity_from_decomposition(d, "A", 0.0, side="comparison")
    # comparison: A rate 1.0 weight 0.5, B rate 0.0 weight 0.5, overall 0.5
    assert abs(r["real_total"] - 0.5) < 1e-12
    assert abs(r["hypothetical_total"] - 0.0) < 1e-12  # A 1.0->0.0: 0.5 + 0.5*(0-1)=0


# ---- Part 2: sum-metric sensitivity --------------------------------------

def test_sum_basic_substitution():
    adj = [{"deal_id": "1", "real_value": 100.0, "hypothetical_value": 0.0},
           {"deal_id": "2", "real_value": 100.0, "hypothetical_value": 0.0}]
    r = sum_sensitivity(1000.0, adj)
    assert r["delta"] == -200.0
    assert r["hypothetical_total"] == 800.0
    assert len(r["adjustments"]) == 2
    assert r["adjustments"][0]["delta"] == -100.0


def test_sum_null_scenario_reproduces_total_exactly():
    """Part 3 for the sum metric: hypothetical == real reproduces exactly."""
    adj = [{"deal_id": "1", "real_value": 250.0, "hypothetical_value": 250.0}]
    r = sum_sensitivity(1000.0, adj)
    assert r["is_null"] is True
    assert r["hypothetical_total"] == 1000.0
    assert r["delta"] == 0.0


def test_sum_from_reconciliation_uses_current_in_scope():
    recon = {"current_in_scope": {"count": 3, "value": 500000.0}}
    adj = [{"deal_id": "9", "real_value": 75000.0, "hypothetical_value": 0.0}]
    r = sum_sensitivity_from_reconciliation(recon, adj)
    assert r["real_total"] == 500000.0
    assert r["hypothetical_total"] == 425000.0
    assert r["delta"] == -75000.0


# ---- Part 4: real Christian validation -----------------------------------

# (q_closed, q_lost) per rep, qualified basis, FY2027-Q3, real pinned.
REAL_REP_COUNTS = {
    "christian@growthbook.io": (14, 14),
    "dan@growthbook.io": (7, 4),
    "james.shannon@growthbook.io": (5, 3),
    "jake@growthbook.io": (4, 4),
    "cary@growthbook.io": (3, 0),
    "scott.keller@growthbook.io": (3, 2),
    "marcel@growthbook.io": (1, 1),
}
TEAM_CLOSED = 37
TEAM_LOST = 28


def _real_qualified_rows():
    rows = []
    for rep, (closed, lost) in REAL_REP_COUNTS.items():
        rows += [{"owner": rep, "deal_status": "lost"}] * lost
        rows += [{"owner": rep, "deal_status": "won"}] * (closed - lost)
    return rows


def test_christian_matches_team_average_real_case():
    rows = _real_qualified_rows()
    assert len(rows) == TEAM_CLOSED
    assert sum(1 for r in rows if r["deal_status"] == "lost") == TEAM_LOST

    # single-population rep split -> decompose against itself to get the table
    d = decompose_rate(rows, rows, segment="owner", outcome=("deal_status", "lost"))
    team_rate = TEAM_LOST / TEAM_CLOSED
    assert abs(d["comparison"]["rate"] - team_rate) < 1e-9

    r = rate_sensitivity_from_decomposition(
        d, "christian@growthbook.io", "team_average", side="comparison")

    # real total = team qualified loss rate 28/37 = 75.68%
    assert abs(r["real_total"] - 0.7567567567) < 1e-6
    # Christian is 14/14 lost, weight 14/37
    assert abs(r["segment_weight"] - 14 / 37) < 1e-9
    assert abs(r["segment_real_rate"] - 1.0) < 1e-12

    # INDEPENDENT recompute (not the module's formula): if Christian's 14 deals
    # had lost at the team rate, team lost = (28-14) + team_rate*14, over 37.
    expected_hyp = ((TEAM_LOST - 14) + team_rate * 14) / TEAM_CLOSED
    assert abs(r["hypothetical_total"] - expected_hyp) < 1e-9
    assert abs(r["hypothetical_total"] - 0.6647196) < 1e-6
    # direction/magnitude sanity: down ~9.2pp (Christian is the dominant loss cell)
    assert abs(r["delta"] - (expected_hyp - team_rate)) < 1e-12
    assert -0.10 < r["delta"] < -0.08


if __name__ == "__main__":
    import inspect
    fns = [v for k, v in sorted(globals().items())
           if k.startswith("test_") and inspect.isfunction(v)]
    for fn in fns:
        fn()
        print(f"✓ {fn.__name__}")
    print("\n✅ All tests passed")
