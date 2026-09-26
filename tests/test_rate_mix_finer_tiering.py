#!/usr/bin/env python3
"""
Tier B stage 1 re-validation: finer depth-tiering (2026-09-26).

The original Christian/Enterprise validation
(tests/test_rate_mix_decomposition.py) split depth into TWO tiers —
Discovery-only (deepest_qual_order == 1) vs past-Discovery (order >= 2, orders
2-5 lumped). The concern: Christian's past-Discovery losses cluster in the
EARLY half (orders 2-3) while the team's WINS in that coarse tier sit in the
LATE half (orders 4-5). So some of what the coarse split attributed to "rate
effect" (Christian converting worse within a tier) could be MIX at a finer
grain (his pool concentrated in the weaker sub-tier).

This re-runs the SAME decompose_rate on the SAME real fixture with a 3-tier
split — Discovery-only / early (orders 2-3) / late (orders 4-5+) — and pins the
before/after. No production code change: this is only a different `segment`
callable passed to the existing function (the point of that being a parameter).

FINDING (honest, real test — it CONFIRMS the original, it does not overturn it):
Christian lost 100% of his qualified deals — every tier, every sub-tier. There
is no sub-tier where he converts at the team's rate, so his rate effect is
+0.2222 at ANY resolution (= 1 − team overall). Finer tiering grows the mix
term (his pool IS underweight the late tier where the team wins) but the
interaction grows to cancel it exactly, because his rate gap is a uniform
+100pp in every tier. Rate effect stays dominant. Enterprise is 100%
Discovery-only, so splitting past-Discovery changes nothing for it.

    depth split      Christian: rate / mix / interaction     dominant
    coarse (2-tier)  +0.2222 / +0.0418 / -0.0418             rate_effect
    finer  (3-tier)  +0.2222 / +0.1037 / -0.1037             rate_effect

    Enterprise       rate / mix / interaction                dominant
    coarse           0.0000 / +0.2222 / 0.0000               mix_effect
    finer            0.0000 / +0.2222 / 0.0000               mix_effect  (unchanged)

Stage-2 decision: rate effect still dominates for Christian even at finer
resolution -> the original conclusion holds, more precisely. Stage 2
(dimensional ranking for a rate-effect-dominant slice) is cleared to proceed as
originally scoped, NOT redirected to "why is his pool concentrated."
"""
import json
import sys
from pathlib import Path

REPO = Path(__file__).parent.parent
sys.path.insert(0, str(REPO / "scripts"))
sys.path.insert(0, str(REPO / "scripts" / "analytics"))

import logging  # noqa: E402
logging.disable(logging.CRITICAL)

import rate_mix_decomposition as rmd  # noqa: E402

FX = json.loads((REPO / "tests" / "fixtures"
                 / "qualified_loss_fy2027_q3_2026_09_25.json").read_text())
ROWS = FX["qualified_closed"]


def _lost(r):
    return r["deal_status"] == "lost"


def _coarse(r):
    return "discovery_only" if r["deepest_qual_order"] == 1 else "past_discovery"


def _tier3(r):
    """3-tier depth split. THE NEW BOUNDARY LOGIC under test: early is orders
    2-3, late is orders 4-5+."""
    o = r["deepest_qual_order"]
    if o == 1:
        return "discovery_only"
    return "early_2_3" if o in (2, 3) else "late_4_5plus"


def _team():
    return ROWS


def _rep(email):
    return [r for r in ROWS if r["owner_email"] == email]


def _segment(name):
    return [r for r in ROWS if r["segment"] == name]


def test_fixture_has_stage_order_granularity():
    """Confirm (don't assume) the existing capture carries per-deal stage order
    — the whole re-validation depends on it, no new data pull needed."""
    assert all("deepest_qual_order" in r for r in ROWS)
    orders = {r["deepest_qual_order"] for r in ROWS}
    assert orders >= {1, 2, 3, 4, 5}, f"need orders 1-5 for a 3-tier split, got {sorted(orders)}"


def test_christian_finer_tiering_still_rate_effect_dominant():
    coarse = rmd.decompose_rate(_team(), _rep("christian@growthbook.io"),
                                segment=_coarse, outcome=_lost,
                                baseline_label="team", comparison_label="Christian")
    fine = rmd.decompose_rate(_team(), _rep("christian@growthbook.io"),
                              segment=_tier3, outcome=_lost,
                              baseline_label="team", comparison_label="Christian")

    # before (coarse) — on record
    assert round(coarse["rate_effect"], 4) == 0.2222
    assert round(coarse["mix_effect"], 4) == 0.0418
    assert round(coarse["interaction"], 4) == -0.0418
    assert coarse["dominant"] == "rate_effect"

    # after (finer) — the re-validation
    assert round(fine["total_delta"], 4) == 0.2222
    assert round(fine["rate_effect"], 4) == 0.2222, "rate effect is UNCHANGED at finer grain"
    assert round(fine["mix_effect"], 4) == 0.1037, "mix grows (pool underweight the late tier)"
    assert round(fine["interaction"], 4) == -0.1037, "interaction grows to cancel mix exactly"
    assert fine["dominant"] == "rate_effect", "rate effect STILL dominates at finer resolution"

    # exact reconciliation, no residual (the identity, at the new tier count)
    assert fine["reconciles"] is True and abs(fine["residual"]) < 1e-9
    assert abs((fine["rate_effect"] + fine["mix_effect"] + fine["interaction"])
               - fine["total_delta"]) < 1e-12

    # the finding: rate effect did NOT move toward mix — it is identical, because
    # Christian loses 100% in every sub-tier (no tier where he converts like the team)
    assert round(fine["rate_effect"], 4) == round(coarse["rate_effect"], 4)
    assert round(fine["mix_effect"], 4) > round(coarse["mix_effect"], 4)  # mix grew, but is cancelled
    # per sub-tier: Christian is 100% in early AND late; the team is 81.8% / 25%
    assert fine["segments"]["early_2_3"]["comparison_rate"] == 1.0
    assert fine["segments"]["late_4_5plus"]["comparison_rate"] == 1.0
    assert round(fine["segments"]["early_2_3"]["baseline_rate"], 4) == 0.8182
    assert round(fine["segments"]["late_4_5plus"]["baseline_rate"], 4) == 0.2500
    print("✓ Christian: rate effect UNCHANGED +0.2222 (dominant) coarse->fine; mix +0.0418->+0.1037 "
          "grows but is cancelled by interaction -0.0418->-0.1037. Loses 100% in every sub-tier — "
          "genuine rate effect at any resolution. Original conclusion CONFIRMED.")


def test_enterprise_finer_tiering_unchanged_mix_effect():
    coarse = rmd.decompose_rate(_team(), _segment("Enterprise"), segment=_coarse,
                                outcome=_lost, baseline_label="team", comparison_label="Enterprise")
    fine = rmd.decompose_rate(_team(), _segment("Enterprise"), segment=_tier3,
                              outcome=_lost, baseline_label="team", comparison_label="Enterprise")
    for d in (coarse, fine):
        assert round(d["total_delta"], 4) == 0.2222
        assert round(d["rate_effect"], 4) == 0.0
        assert round(d["mix_effect"], 4) == 0.2222
        assert round(d["interaction"], 4) == 0.0
        assert d["dominant"] == "mix_effect"
        assert d["reconciles"] is True
    # splitting past-Discovery does nothing: Enterprise is 100% Discovery-only,
    # so both new sub-tiers are empty (imputed) for it
    assert fine["segments"]["early_2_3"]["comparison_n"] == 0
    assert fine["segments"]["late_4_5plus"]["comparison_n"] == 0
    assert fine["segments"]["early_2_3"]["comparison_imputed"] is True
    assert fine["segments"]["late_4_5plus"]["comparison_imputed"] is True
    print("✓ Enterprise: unchanged coarse->fine (rate 0.0, mix +0.2222, mix-dominant) — it is 100% "
          "Discovery-only, so splitting past-Discovery leaves both sub-tiers empty for it.")


def test_three_tiers_actually_present_for_the_team():
    """The 3-tier split must produce three real, non-empty team tiers (else the
    'finer' split is finer in name only)."""
    d = rmd.decompose_rate(_team(), _rep("christian@growthbook.io"),
                           segment=_tier3, outcome=_lost)
    for tier in ("discovery_only", "early_2_3", "late_4_5plus"):
        assert tier in d["segments"], tier
        assert d["segments"][tier]["baseline_n"] > 0, f"{tier} empty for the team"
    # team sub-tier rates, real pinned: early (o2-3) 9/11, late (o4-5) 2/8
    assert round(d["segments"]["early_2_3"]["baseline_rate"], 4) == 0.8182
    assert round(d["segments"]["late_4_5plus"]["baseline_rate"], 4) == 0.2500
    print("✓ 3-tier split yields three real team tiers: Discovery-only 100%, early(2-3) 81.8%, "
          "late(4-5+) 25.0%")


if __name__ == "__main__":
    test_fixture_has_stage_order_granularity()
    test_christian_finer_tiering_still_rate_effect_dominant()
    test_enterprise_finer_tiering_unchanged_mix_effect()
    test_three_tiers_actually_present_for_the_team()
    print("\n✅ All tests passed")
