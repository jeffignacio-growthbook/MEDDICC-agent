#!/usr/bin/env python3
"""
Tier B Stage 2: dimensional root-cause ranking.

Validates that rank_rate_dimensions:
  1. Independently surfaces depth=past_discovery as the dominant slice for Christian
     (a real rate-effect case) without being told the answer.
  2. Produces no meaningful rate-effect candidates for Enterprise
     (a real mix-effect case) — correctly excluded, not mistakenly promoted.
  3. Planted-bug controls on the scoring formula: weight-blind scoring and EP-only
     (no surprise) each cause wrong rankings on synthetic data, confirming the combined
     score EP × Surprise is load-bearing.

Fixture: tests/fixtures/qualified_loss_fy2027_q3_2026_09_25.json
(same real data used by Stage 1; row schema: deal_id, company_name, owner_email,
 segment, deal_status, deepest_qual_order, ever_commit_ml)

Real validated numbers (computed offline):
  Christian vs team: total_delta=+22.22%, past_discovery score=1.8947 (EP=100%, Surprise=1.89×)
  Enterprise vs team: all depth/segment rate gaps = 0; top score ≈0.08 (ever_commit_ml only)
"""
import json
import sys
from pathlib import Path

REPO = Path(__file__).parent.parent
sys.path.insert(0, str(REPO))

from scripts.analytics.dimensional_rank import rank_rate_dimensions

FIXTURE = REPO / "tests" / "fixtures" / "qualified_loss_fy2027_q3_2026_09_25.json"


def _load():
    with open(FIXTURE) as f:
        return json.load(f)["qualified_closed"]


ROWS = _load()


def depth(r):
    return "discovery_only" if r["deepest_qual_order"] == 1 else "past_discovery"


def lost(r):
    return r["deal_status"] == "lost"


def _team():
    return ROWS


def _rep(email):
    return [r for r in ROWS if r["owner_email"] == email]


def _seg(name):
    return [r for r in ROWS if r["segment"] == name]


# ---------------------------------------------------------------------------
# 1. Christian — rate-effect case: top slice must be depth=past_discovery
# ---------------------------------------------------------------------------

def test_christian_top_slice_is_past_discovery():
    """Script independently surfaces past_discovery as dominant without being told."""
    result = rank_rate_dimensions(
        _team(), _rep("christian@growthbook.io"),
        dimensions=[depth, "segment", "ever_commit_ml"],
        outcome=lost,
    )
    assert result["total_delta"] > 0, "anomaly must be positive"
    contributing = result["contributing"]
    assert contributing, "must find at least one contributing slice"

    top = contributing[0]
    assert top["dimension"] == "depth", (
        f"Expected depth dimension at #1, got {top['dimension']!r}={top['value']!r}"
    )
    assert top["value"] == "past_discovery", (
        f"Expected past_discovery at #1, got {top['value']!r}"
    )
    # EP near 1.0: this one slice explains essentially all of the total_delta
    assert top["ep"] > 0.95, f"EP={top['ep']:.4f}; expected ~1.0"
    # Surprise > 1: local rate gap exceeds the global gap
    assert top["surprise"] > 1.0, f"Surprise={top['surprise']:.4f}; expected >1"
    # Score matches our pre-validated number
    assert abs(top["score"] - 1.8947) < 0.001, f"Score={top['score']:.4f}; expected 1.8947"
    print(f"✓ Christian #1: {top['dimension']}={top['value']!r} "
          f"EP={top['ep']:.1%} Surprise={top['surprise']:.2f}× Score={top['score']:.4f}")


def test_christian_discovery_only_scores_zero():
    """discovery_only has rate_gap=0 for Christian (both sides 100% loss); must not rank."""
    result = rank_rate_dimensions(
        _team(), _rep("christian@growthbook.io"),
        dimensions=[depth], outcome=lost,
    )
    zero_slices = [c for c in result["contributing"] if c["value"] == "discovery_only"]
    assert not zero_slices, "discovery_only must not appear in contributing (rate gap = 0)"
    print("✓ discovery_only correctly absent from contributing list (rate gap = 0)")


def test_christian_summary_dominance_gap():
    """Summary must show a clear leader; #1 vs #2 gap and scores visible in text."""
    result = rank_rate_dimensions(
        _team(), _rep("christian@growthbook.io"),
        dimensions=[depth, "segment", "ever_commit_ml"],
        outcome=lost,
    )
    summary = result["summary"]
    assert "past_discovery" in summary
    assert "EP" in summary
    assert "Surprise" in summary
    assert "Score" in summary
    assert "Dominance gap" in summary
    print("✓ summary contains required fields and dominance gap indicator")


# ---------------------------------------------------------------------------
# 2. Enterprise — mix-effect case: no meaningful rate-effect slices
# ---------------------------------------------------------------------------

def test_enterprise_no_significant_rate_effect_slices():
    """Enterprise is a mix-effect case; no slice should have high EP or score."""
    result = rank_rate_dimensions(
        _team(), _seg("Enterprise"),
        dimensions=[depth, "segment", "ever_commit_ml"],
        outcome=lost,
    )
    assert result["total_delta"] > 0, "anomaly must exist for Enterprise too"
    contributing = result["contributing"]
    if not contributing:
        print("✓ Enterprise: zero contributing slices (all rate gaps zero)")
        return

    top_score = contributing[0]["score"]
    # Christian's top score is 1.895; Enterprise's must be much lower (no rate-effect explanation)
    assert top_score < 0.2, (
        f"Enterprise top score={top_score:.4f}; expected <0.2 (mix-effect case, no rate anomaly)"
    )
    top_ep = contributing[0]["ep"]
    assert top_ep < 0.5, (
        f"Enterprise top EP={top_ep:.2%}; expected <50% (no slice should explain the anomaly via rate)"
    )
    print(f"✓ Enterprise: top contributing score={top_score:.4f} EP={top_ep:.1%} (correctly low — mix effect)")


def test_enterprise_depth_gaps_are_zero():
    """Within each depth tier, Enterprise loss rate = team loss rate → rate_gap=0."""
    result = rank_rate_dimensions(
        _team(), _seg("Enterprise"),
        dimensions=[depth], outcome=lost,
    )
    for c in result["candidates"]:
        assert abs(c["rate_gap"]) < 1e-9, (
            f"depth={c['value']!r} has rate_gap={c['rate_gap']:.6f}; expected 0 "
            f"(all Enterprise deals are discovery_only, imputed rate matches team)"
        )
    print("✓ Enterprise depth rate gaps all zero (mix-effect confirmed, not rate-effect)")


# ---------------------------------------------------------------------------
# 3. Planted-bug control: weight-blind scoring
#    Correct formula: weight × (rate_gap/Δ)²  → ranks high-weight meaningful slice first
#    Bug formula:     (rate_gap/Δ)²             → ranks tiny extreme-gap slice first
# ---------------------------------------------------------------------------

def _make_weight_blind_population():
    """
    Synthetic populations designed so that:
    - "big" slice: 15/20 baseline, rate gap 46.7% (large contribution)
    - "tiny" slice:  1/20 baseline, rate gap 100%  (extreme but negligible weight)
    - "other" slice: 4/20 baseline, rate gap 0%
    Correct score ranks big > tiny; weight-blind score ranks tiny > big.
    """
    def row(slice_, status):
        return {"slice": slice_, "status": status}

    baseline = (
        [row("big", "won")] * 5 + [row("big", "lost")] * 5      # 10, 50% lost (we'll adjust)
        + [row("tiny", "won")]                                    # 1, 0% lost
        + [row("other", "lost")] * 4                              # 4, 100% lost
    )
    # Rebuild to exact numbers: big=15 deals, tiny=1, other=4
    baseline = (
        [row("big", "lost")] * 5 + [row("big", "won")] * 10     # 15 deals, 33.3% lost
        + [row("tiny", "won")]                                    # 1 deal, 0% lost
        + [row("other", "lost")] * 4                              # 4 deals, 100% lost
    )
    comparison = (
        [row("big", "lost")] * 12 + [row("big", "won")] * 3     # 15 deals, 80% lost
        + [row("tiny", "lost")]                                   # 1 deal, 100% lost
        + [row("other", "lost")] * 4                              # 4 deals, 100% lost
    )
    return baseline, comparison


def test_planted_bug_weight_blind_scoring():
    """
    Control: removing the weight factor always ranks the smallest extreme-gap slice #1.
    The correct formula (weight × rate_gap²/Δ²) ranks the large contributing slice #1.
    """
    baseline, comparison = _make_weight_blind_population()

    result = rank_rate_dimensions(
        baseline, comparison, dimensions=["slice"],
        outcome=("status", "lost"), min_n=1,
    )
    contributing = result["contributing"]
    assert len(contributing) >= 2

    top = contributing[0]
    # Correct formula: "big" has weight=15/20=0.75; "tiny" has weight=1/20=0.05
    # big score = 0.75 × (0.467/0.40)² ≈ 1.02; tiny score = 0.05 × (1.0/0.40)² ≈ 0.31
    assert top["value"] == "big", (
        f"Correct formula must rank 'big' (high weight) above 'tiny' (extreme gap, tiny weight); "
        f"got {top['value']!r} at #1. Score: {top['score']:.4f}"
    )

    # Verify the planted bug: if we used rate_gap²/Δ² (no weight), tiny would win
    td = result["total_delta"]
    scores_weight_blind = {}
    for c in contributing:
        scores_weight_blind[c["value"]] = (c["rate_gap"] / td) ** 2

    assert scores_weight_blind.get("tiny", 0) > scores_weight_blind.get("big", 0), (
        "Bug formula (rate_gap²/Δ²) must rank tiny > big to confirm the control is valid"
    )
    print(
        f"✓ Weight-blind planted bug: correct ranks big(score={top['score']:.3f}) > "
        f"tiny; bug would rank tiny({scores_weight_blind['tiny']:.3f}) > big({scores_weight_blind['big']:.3f})"
    )


# ---------------------------------------------------------------------------
# 4. Planted-bug control: EP-only (no surprise factor)
#    Correct formula: EP × Surprise → ranks disproportionate small slice first
#    Bug formula:     EP alone       → ranks large-weight proportional slice first
# ---------------------------------------------------------------------------

def _make_ep_only_population():
    """
    Synthetic populations designed so that:
    - "heavy" slice: 14/20 baseline, rate gap 14.3% (large EP due to weight, small Surprise)
    - "light" slice:  2/20 baseline, rate gap 50%   (small EP, large Surprise)
    - "other":        4/20 baseline, rate gap 0%
    EP-only ranks heavy first; EP × Surprise correctly ranks light first (disproportionate).
    """
    def row(s, status):
        return {"slice": s, "status": status}

    baseline = (
        [row("heavy", "lost")] * 7 + [row("heavy", "won")] * 7  # 14 deals, 50% lost
        + [row("light", "lost")] * 1 + [row("light", "won")] * 1  # 2 deals, 50% lost
        + [row("other", "lost")] * 4                               # 4 deals, 100% lost
    )
    comparison = (
        [row("heavy", "lost")] * 9 + [row("heavy", "won")] * 5  # 14 deals, 64.3% lost
        + [row("light", "lost")] * 2                              # 2 deals, 100% lost
        + [row("other", "lost")] * 4                              # 4 deals, 100% lost
    )
    return baseline, comparison


def test_planted_bug_ep_only_no_surprise():
    """
    Control: EP alone always promotes the largest-weight slice regardless of anomaly strength.
    The correct formula (EP × Surprise) promotes the disproportionate slice.
    """
    baseline, comparison = _make_ep_only_population()

    result = rank_rate_dimensions(
        baseline, comparison, dimensions=["slice"],
        outcome=("status", "lost"), min_n=1,
    )
    contributing = result["contributing"]
    assert len(contributing) >= 2

    top = contributing[0]
    # Correct: "light" has EP=33% but Surprise=3.33× → score=1.11
    #          "heavy" has EP=67% but Surprise=0.95× → score=0.64
    assert top["value"] == "light", (
        f"Correct formula must rank 'light' (disproportionate gap) above 'heavy' (large but proportional); "
        f"got {top['value']!r} at #1. Score: {top['score']:.4f}"
    )

    # Verify the planted bug: EP alone would rank heavy first
    ep_only = {c["value"]: c["ep"] for c in contributing}
    assert ep_only.get("heavy", 0) > ep_only.get("light", 0), (
        "EP-only bug must rank heavy > light to confirm the control is valid"
    )
    print(
        f"✓ EP-only planted bug: correct ranks light(score={top['score']:.3f}) > heavy; "
        f"EP-only would rank heavy(EP={ep_only['heavy']:.1%}) > light(EP={ep_only['light']:.1%})"
    )


# ---------------------------------------------------------------------------
# 5. Pair dimensions: depth × segment surfaces a meaningful pair for Christian
# ---------------------------------------------------------------------------

def test_pair_dimensions_appear_for_christian():
    """Depth × segment pairs should include past_discovery × SMB and past_discovery × Mid-Market."""
    result = rank_rate_dimensions(
        _team(), _rep("christian@growthbook.io"),
        dimensions=[depth, "segment"],
        outcome=lost, max_depth=2, min_n=2,
    )
    pair_labels = {c["dimension"] for c in result["candidates"]}
    assert "depth × segment" in pair_labels, (
        f"Expected 'depth × segment' pairs; found dimensions: {pair_labels}"
    )
    # Single-dimension top still beats pairs (pairs have smaller n, lower weight)
    top = result["contributing"][0]
    assert top["dimension"] == "depth", (
        f"Single depth dimension must still lead over pairs; got {top['dimension']!r}"
    )
    print(f"✓ Pair dimensions present; single depth still leads: {top['dimension']}={top['value']!r}")


# ---------------------------------------------------------------------------
# 6. Structural invariants
# ---------------------------------------------------------------------------

def test_empty_population_raises():
    import pytest
    with pytest.raises(ValueError):
        rank_rate_dimensions([], _team(), dimensions=[depth], outcome=lost)
    with pytest.raises(ValueError):
        rank_rate_dimensions(_team(), [], dimensions=[depth], outcome=lost)


def test_identical_populations_all_zero():
    """Comparing a population to itself: total_delta=0, all scores=0."""
    result = rank_rate_dimensions(
        _team(), _team(), dimensions=[depth, "segment"],
        outcome=lost,
    )
    assert abs(result["total_delta"]) < 1e-9
    assert not result["contributing"]
    assert not result["offsetting"]
    print("✓ Identical populations: total_delta=0, no contributing or offsetting slices")


def test_min_n_filter_removes_tiny_slices():
    """Slices with n_baseline < min_n must be absent from candidates."""
    result = rank_rate_dimensions(
        _team(), _rep("marcel@growthbook.io"),  # 1 deal
        dimensions=["segment"], outcome=lost, min_n=3,
    )
    for c in result["candidates"]:
        assert c["n_baseline"] >= 3, (
            f"Slice {c['dimension']}={c['value']!r} has n_baseline={c['n_baseline']} < min_n=3"
        )
    print("✓ min_n filter removes slices with insufficient baseline count")


def test_outcome_as_callable():
    """outcome can be a callable; must produce same result as (field, value) tuple."""
    r1 = rank_rate_dimensions(
        _team(), _rep("christian@growthbook.io"),
        dimensions=[depth], outcome=lost,
    )
    r2 = rank_rate_dimensions(
        _team(), _rep("christian@growthbook.io"),
        dimensions=[depth], outcome=("deal_status", "lost"),
    )
    assert abs(r1["total_delta"] - r2["total_delta"]) < 1e-9
    assert len(r1["contributing"]) == len(r2["contributing"])
    if r1["contributing"] and r2["contributing"]:
        assert abs(r1["contributing"][0]["score"] - r2["contributing"][0]["score"]) < 1e-9
    print("✓ callable and (field,value) outcome forms produce identical results")


if __name__ == "__main__":
    test_christian_top_slice_is_past_discovery()
    test_christian_discovery_only_scores_zero()
    test_christian_summary_dominance_gap()
    test_enterprise_no_significant_rate_effect_slices()
    test_enterprise_depth_gaps_are_zero()
    test_planted_bug_weight_blind_scoring()
    test_planted_bug_ep_only_no_surprise()
    test_pair_dimensions_appear_for_christian()
    test_empty_population_raises()
    test_identical_populations_all_zero()
    test_min_n_filter_removes_tiny_slices()
    test_outcome_as_callable()
    print("\n✅ All Stage 2 tests passed")
