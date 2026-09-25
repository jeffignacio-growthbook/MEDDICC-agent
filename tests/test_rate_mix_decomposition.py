#!/usr/bin/env python3
"""
Rate-vs-mix decomposition (scripts/analytics/rate_mix_decomposition.py),
Tier B stage 1: rule out Simpson's paradox / mix shift before attributing a
rate change to behavior.

A weighted-average rate (loss rate = losses / qualified-closed) can move
between two populations because each segment's own rate moved (rate effect),
because the population's composition shifted toward segments that were always
different (mix effect), or both at once (interaction). The three terms sum to
the observed change EXACTLY — an arithmetic identity, not an estimate, so
there is no residual bucket.

Real data: tests/fixtures/qualified_loss_fy2027_q3_2026_09_25.json — the 36
FY2027 Q3 qualified-closed deals (28 lost, 8 won = 77.8%), each with owner,
company segment, deepest qualifying stage reached and ever-COMMIT/Most-Likely,
captured read-only. Same qualified definition as scripts/loss_concentration.py.

Two hand-investigated cases are pinned, decomposed by depth tier
(Discovery-only vs past-Discovery):
  - Christian (100% loss) vs the team (77.8%): the decomposition attributes
    it to RATE effect (his past-Discovery deals convert worse), NOT mix.
  - Enterprise (100% loss) vs the team: attributes it entirely to MIX (its
    pool is 100% Discovery-only, the tier that loses 100% for everyone),
    with ZERO rate effect.
Opposite conclusions from the same function — the Simpson's-paradox
discrimination this stage exists to make.
"""
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

import rate_mix_decomposition as rmd  # noqa: E402

FX = json.loads((REPO / "tests" / "fixtures"
                 / "qualified_loss_fy2027_q3_2026_09_25.json").read_text())
ROWS = FX["qualified_closed"]


def _depth(r):
    return "discovery_only" if r["deepest_qual_order"] == 1 else "past_discovery"


def _lost(r):
    return r["deal_status"] == "lost"


def _team():
    return ROWS


def _rep(email):
    return [r for r in ROWS if r["owner_email"] == email]


def _segment(name):
    return [r for r in ROWS if r["segment"] == name]


def test_christian_is_a_rate_effect_not_composition():
    d = rmd.decompose_rate(_team(), _rep("christian@growthbook.io"),
                           segment=_depth, outcome=_lost,
                           baseline_label="team", comparison_label="Christian")
    assert round(d["baseline"]["rate"], 4) == 0.7778 and round(d["comparison"]["rate"], 4) == 1.0
    assert round(d["total_delta"], 4) == 0.2222
    assert round(d["rate_effect"], 4) == 0.2222     # his own conversion, holding mix fixed
    assert round(d["mix_effect"], 4) == 0.0418       # pool only slightly more Discovery-heavy
    assert round(d["interaction"], 4) == -0.0418     # which the interaction cancels
    assert d["reconciles"] is True and abs(d["residual"]) < 1e-9
    assert d["dominant"] == "rate_effect"
    # the sharpening finding: within the deeper tier he loses 100% vs the team's 57.9%
    past = d["segments"]["past_discovery"]
    assert round(past["baseline_rate"], 4) == 0.5789 and past["comparison_rate"] == 1.0
    assert "behavior" in d["headline"].lower() and "not composition" in d["headline"].lower()
    print("✓ Christian: +22.2pp is rate effect (+0.2222), not composition (mix +0.0418 cancelled by "
          "interaction -0.0418); within past-Discovery he loses 100% vs the team's 57.9%")


def test_enterprise_is_a_mix_effect_not_conversion():
    d = rmd.decompose_rate(_team(), _segment("Enterprise"),
                           segment=_depth, outcome=_lost,
                           baseline_label="team", comparison_label="Enterprise")
    assert round(d["total_delta"], 4) == 0.2222
    assert round(d["rate_effect"], 4) == 0.0         # same conversion as the team, tier for tier
    assert round(d["mix_effect"], 4) == 0.2222       # its pool is entirely the 100%-loss tier
    assert round(d["interaction"], 4) == 0.0
    assert d["reconciles"] is True and abs(d["residual"]) < 1e-9
    assert d["dominant"] == "mix_effect"
    # the empty cell: Enterprise has zero past-Discovery deals; its rate there is imputed
    past = d["segments"]["past_discovery"]
    assert past["comparison_n"] == 0 and past["comparison_imputed"] is True
    assert round(past["comparison_weight"], 4) == 0.0
    assert "composition" in d["headline"].lower() or "mix" in d["headline"].lower()
    print("✓ Enterprise: +22.2pp is entirely mix (+0.2222), rate effect 0.0 — its qualified pool is "
          "100% Discovery-only (the 100%-loss tier); it converts like the team tier for tier")


def test_the_three_terms_sum_to_the_total_exactly():
    """The identity, on several real cuts and dimensions — never approximate."""
    cases = [
        (_team(), _rep("christian@growthbook.io"), _depth),
        (_team(), _segment("Enterprise"), _depth),
        (_team(), _rep("christian@growthbook.io"), lambda r: r["segment"]),   # by company segment
        (_team(), _rep("dan@growthbook.io"), lambda r: r["ever_commit_ml"]),  # by forecast tier
        (_segment("SMB"), _segment("Mid-Market"), _depth),
    ]
    for i, (a, b, seg) in enumerate(cases):
        d = rmd.decompose_rate(a, b, segment=seg, outcome=_lost)
        recon = d["rate_effect"] + d["mix_effect"] + d["interaction"]
        assert abs(recon - d["total_delta"]) < 1e-12, (i, recon, d["total_delta"])
        assert d["reconciles"] is True
        # segment-level terms also sum to the segment totals
        assert abs(sum(s["rate_effect"] for s in d["segments"].values()) - d["rate_effect"]) < 1e-12
    print(f"✓ rate + mix + interaction == total_delta to 1e-12 on {len(cases)} real cuts "
          f"(by depth, by company segment, by forecast tier); segment terms sum to the totals")


def test_dimension_is_a_parameter_not_hardcoded():
    """The same function decomposes by any field or callable already on the
    qualifying rows — depth, company segment, forecast tier."""
    for seg in (_depth, "segment", "ever_commit_ml", "deepest_qual_order"):
        d = rmd.decompose_rate(_team(), _rep("christian@growthbook.io"),
                               segment=seg, outcome=_lost)
        assert d["reconciles"] is True
        assert round(d["total_delta"], 4) == 0.2222   # the overall gap is the same cut any way
    print("✓ segment dimension is a parameter: a callable or a field name (depth, company segment, "
          "forecast tier, raw stage order) all decompose the same +22.2pp gap")


def test_all_three_terms_are_always_reported():
    """Never just the dominant term — every result carries rate, mix and
    interaction, even when one is zero."""
    d = rmd.decompose_rate(_team(), _segment("Enterprise"), segment=_depth, outcome=_lost)
    for k in ("rate_effect", "mix_effect", "interaction", "total_delta", "residual"):
        assert k in d and isinstance(d[k], float)
    assert d["rate_effect"] == 0.0   # reported explicitly as zero, not omitted
    print("✓ rate, mix and interaction are all present every time, including the ones that are zero")


def test_empty_segment_on_both_sides_is_ignored():
    """A tier absent from both populations contributes nothing and doesn't
    break the identity."""
    d = rmd.decompose_rate(_segment("Enterprise"), _segment("Enterprise"),
                           segment=_depth, outcome=_lost)
    assert round(d["total_delta"], 6) == 0.0
    assert round(d["rate_effect"], 6) == 0.0 and round(d["mix_effect"], 6) == 0.0
    assert d["reconciles"] is True
    print("✓ comparing a population to itself gives a zero decomposition that still reconciles")


if __name__ == "__main__":
    test_christian_is_a_rate_effect_not_composition()
    test_enterprise_is_a_mix_effect_not_conversion()
    test_the_three_terms_sum_to_the_total_exactly()
    test_dimension_is_a_parameter_not_hardcoded()
    test_all_three_terms_are_always_reported()
    test_empty_segment_on_both_sides_is_ignored()
    print("\n✅ All tests passed")
