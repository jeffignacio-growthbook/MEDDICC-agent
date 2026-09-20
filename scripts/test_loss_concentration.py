#!/usr/bin/env python3
"""
Baseline tests for assess_loss_concentration() (Step C), plus Step D's
planted-discrepancy tests in the same file (matching test_pipeline_
coverage.py's convention of mixing structural and defect-specific tests
in one file).

Covers:
1. Below MIN_N total closed deals -> insufficient_data, never a
   misleading breakdown off too few rows.
2. Rep/segment breakdown: loss RATE (not raw count), always reported
   vs. the team average; a slice below MIN_N is flagged
   insufficient_volume instead of a bare 100%/0% rate.
3. Stage-of-loss uses the CANONICAL BUCKET mapping (field_semantics.
   stage_bucket()), not raw highest_stage_order_reached — proven by
   using the real config/client.yaml pipeline (not mocked, since it's
   deterministic project config, same precedent as the region-resolver
   tests reading regions.yaml directly). Order 1 (Discovery) and order
   3 (Technical Evaluation) both bucket to real, non-administrative
   buckets; order 9 (Disqualified) is the ADMINISTRATIVE stage and
   must be counted in administrative_stage_share SEPARATELY from
   by_bucket, never folded into "how deep did we get."
4. Ghost-deal ($0 deal_value) share is computed but NOT excluded from
   the full-population breakdowns above it.
5. PLANTED-DISCREPANCY (bucket-mapping): breaking the order->stage_id
   resolution must make test 3 fail (proves the mapping is load-
   bearing, not vacuously true).
6. PLANTED-DISCREPANCY (rate-normalization): breaking the loss-rate
   formula must make test 2 fail (proves the MIN_N-gated rate math is
   actually enforced by the test, not just present in the source once).

select_all is mocked at its SOURCE module (patched via
supabase_client.select_all), because loss_concentration.py imports it
locally inside assess_loss_concentration() on every call — patching the
source module's attribute is what actually takes effect, same reasoning
test_pipeline_coverage.py documents for its own mocks. get_pipeline_
config() is NOT mocked — it reads the real config/client.yaml,
deterministic project config, not live data.
"""
import sys
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).parent))
sys.path.insert(0, str(Path(__file__).parent.parent / "api"))

from loss_concentration import assess_loss_concentration, MIN_N

FAKE_TW = {"start": "2026-07-01", "end": "2026-09-30", "label": "Q3 FY2027"}


def _deal(deal_id, status, owner_email="rep_a@growthbook.io", segment="SMB",
          stage_order=1, deal_value=50000):
    return {
        "deal_id": deal_id, "deal_status": status, "deal_value": deal_value,
        "close_date": "2026-08-15", "owner_email": owner_email,
        "segment": segment, "highest_stage_order_reached": stage_order,
    }


def _basic_population():
    """10 closed deals: rep_a (6 closed: 3 won/3 lost, n>=MIN_N),
    rep_b (4 closed: 1 won/3 lost, BELOW MIN_N — insufficient_volume).
    Team: 4 won / 6 lost = 60% loss rate."""
    deals = []
    for i in range(3):
        deals.append(_deal(f"a-won-{i}", "won", "rep_a@growthbook.io"))
    for i in range(3):
        deals.append(_deal(f"a-lost-{i}", "lost", "rep_a@growthbook.io"))
    deals.append(_deal("b-won-0", "won", "rep_b@growthbook.io"))
    for i in range(3):
        deals.append(_deal(f"b-lost-{i}", "lost", "rep_b@growthbook.io"))
    return deals


def test_below_min_n_returns_insufficient_data():
    thin = _basic_population()[:MIN_N - 1]
    with patch("supabase_client.select_all", return_value=thin):
        result = assess_loss_concentration(sb=None, time_window=FAKE_TW)
    assert result["status"] == "insufficient_data"
    assert result["reason"] == "too_few_closed_deals"
    assert result["closed_deal_count"] == MIN_N - 1
    assert result["min_required"] == MIN_N
    print("✓ fewer than MIN_N closed deals -> insufficient_data, not a "
          "misleading breakdown")


def test_rep_breakdown_is_rate_normalized_vs_team_average():
    deals = _basic_population()
    with patch("supabase_client.select_all", return_value=deals):
        result = assess_loss_concentration(sb=None, time_window=FAKE_TW)

    assert result["status"] == "ok"
    assert result["closed_deal_count"] == 10
    assert result["won_count"] == 4
    assert result["lost_count"] == 6
    assert result["team_loss_rate"] == 0.6

    by_rep = {r["owner_email"]: r for r in result["by_rep"]}
    rep_a = by_rep["rep_a@growthbook.io"]
    assert rep_a["closed"] == 6 and rep_a["lost"] == 3
    assert rep_a["loss_rate"] == 0.5
    # 0.5 - 0.6 team average = -0.1 (10 pts BELOW team average)
    assert abs(rep_a["vs_team_avg_pts"] - (-0.1)) < 1e-9
    assert "insufficient_volume" not in rep_a

    rep_b = by_rep["rep_b@growthbook.io"]
    assert rep_b["closed"] == 4  # below MIN_N
    assert rep_b.get("insufficient_volume") is True
    assert rep_b["loss_rate"] is None, (
        "a rep with fewer than MIN_N closed deals must never get a "
        "computed rate, however extreme — 3/4 looks like a bad 75% "
        "loss rate but isn't statistically meaningful at this volume")
    print("✓ by_rep is rate-normalized vs. team average, with a real "
          "MIN_N floor that suppresses a misleading rate off too few deals")


def test_segment_breakdown_same_shape():
    deals = [
        _deal("s1", "won", segment="Enterprise"),
        _deal("s2", "won", segment="Enterprise"),
        _deal("s3", "lost", segment="Enterprise"),
        _deal("s4", "lost", segment="Enterprise"),
        _deal("s5", "lost", segment="Enterprise"),
        _deal("s6", "won", segment="SMB"),
        _deal("s7", "won", segment="SMB"),
        _deal("s8", "won", segment="SMB"),
        _deal("s9", "won", segment="SMB"),
        _deal("s10", "lost", segment="SMB"),
    ]
    with patch("supabase_client.select_all", return_value=deals):
        result = assess_loss_concentration(sb=None, time_window=FAKE_TW)

    by_seg = {r["segment"]: r for r in result["by_segment"]}
    assert by_seg["Enterprise"]["loss_rate"] == 0.6
    assert by_seg["SMB"]["loss_rate"] == 0.2
    # Worst-first ordering: Enterprise (60%) must sort before SMB (20%).
    assert [r["segment"] for r in result["by_segment"]][0] == "Enterprise"
    print("✓ by_segment uses the same rate-normalized shape, sorted worst-first")


def test_stage_of_loss_uses_canonical_bucket_not_raw_order():
    """Order 1 (Discovery, bucket=discovery), order 3 (Technical
    Evaluation, bucket=proposal), and order 9 (Disqualified, bucket=
    closed_lost, ADMINISTRATIVE) — real config/client.yaml stages, not
    mocked. administrative_stage_share must count ONLY the order-9
    deals, separately from (not instead of) their own by_bucket line."""
    deals = [_deal("w1", "won")]  # pad wins so team_loss_rate isn't 100%
    deals += [_deal(f"d-{i}", "lost", stage_order=1) for i in range(3)]
    deals += [_deal(f"t-{i}", "lost", stage_order=3) for i in range(2)]
    deals += [_deal(f"x-{i}", "lost", stage_order=9) for i in range(5)]

    with patch("supabase_client.select_all", return_value=deals):
        result = assess_loss_concentration(sb=None, time_window=FAKE_TW)

    by_bucket = result["stage_of_loss"]["by_bucket"]
    assert by_bucket["discovery"]["count"] == 3
    assert by_bucket["proposal"]["count"] == 2
    assert by_bucket["closed_lost"]["count"] == 5, (
        "order 9 (Disqualified) canonically buckets to closed_lost via "
        "field_semantics' alias resolution")

    admin = result["stage_of_loss"]["administrative_stage_share"]
    assert admin["count"] == 5, (
        "administrative_stage_share must count exactly the order-9 "
        "deals — not the order-1/order-3 deals, which are real, "
        "non-administrative stages that happen to also be real losses")
    assert admin["pct"] == 0.5  # 5 of 10 total losses
    print("✓ stage-of-loss uses the canonical bucket mapping, and the "
          "administrative-stage share is counted separately, never "
          "folded into by_bucket")


def test_ghost_deal_share_computed_but_not_excluded():
    deals = [_deal("w1", "won")]
    deals += [_deal(f"real-{i}", "lost", deal_value=50000) for i in range(3)]
    deals += [_deal(f"ghost-{i}", "lost", deal_value=0) for i in range(2)]

    with patch("supabase_client.select_all", return_value=deals):
        result = assess_loss_concentration(sb=None, time_window=FAKE_TW)

    assert result["lost_count"] == 5, (
        "ghost ($0-value) losses must still be counted in the full "
        "population, not silently excluded")
    ghost = result["ghost_deal_share"]
    assert ghost["count"] == 2
    assert ghost["pct"] == 0.4
    print("✓ ghost-deal ($0 value) share is reported separately, "
          "without being excluded from the full-population totals")


def test_planted_discrepancy_bucket_mapping_is_load_bearing():
    """Break _order_to_stage_id() so it never resolves order 9 at all
    (returns None for every order) -> administrative_stage_share must
    collapse to 0 and by_bucket must lose the closed_lost line entirely
    for those deals (falls to 'unknown' instead) -> the bucket test
    above must fail. Confirms the mapping is actually load-bearing, not
    just present in the source."""
    import importlib
    path = Path(__file__).parent / "loss_concentration.py"
    original = path.read_text()
    try:
        broken = original.replace(
            "def _order_to_stage_id(pipeline_config: dict) -> Dict[int, str]:\n"
            "    \"\"\"highest_stage_order_reached (int) -> HubSpot stage id, from\n"
            "    config/client.yaml's pipeline stages list. No existing reverse\n"
            "    lookup for this direction (get_stage_order() only goes id->order),\n"
            "    so this is a small, single-purpose helper built fresh — everything\n"
            "    it feeds into (stage_bucket()/stage_label()) is the existing\n"
            "    canonical source, not reinvented.\"\"\"\n"
            "    mapping = {}",
            "def _order_to_stage_id(pipeline_config: dict) -> Dict[int, str]:\n"
            "    mapping = {}\n"
            "    return mapping  # PLANTED BUG: never populated\n"
            "    _unreachable = {}",
        )
        assert broken != original, "plant string not found — test setup is stale"
        path.write_text(broken)

        import loss_concentration
        importlib.reload(loss_concentration)

        deals = [loss_concentration.assess_loss_concentration]  # unused, keep import alive
        test_deals = [_deal("w1", "won")]
        test_deals += [_deal(f"x-{i}", "lost", stage_order=9) for i in range(5)]
        with patch("supabase_client.select_all", return_value=test_deals):
            result = loss_concentration.assess_loss_concentration(
                sb=None, time_window=FAKE_TW)

        admin = result["stage_of_loss"]["administrative_stage_share"]
        caught = admin["count"] == 0 and result["stage_of_loss"]["by_bucket"].get(
            "unknown", {}).get("count") == 5
        assert caught, (
            "❌ PLANTED BUG NOT CAUGHT: breaking the order->stage_id "
            "mapping should have zeroed administrative_stage_share and "
            "pushed the deals into an 'unknown' bucket, but didn't")
        print("✓ planted removal of the order->stage_id mapping WAS caught "
              "(administrative_stage_share collapsed to 0 as expected)")
    finally:
        path.write_text(original)
        import loss_concentration
        importlib.reload(loss_concentration)
        # Confirm clean restore: the real test must pass again post-restore.
        test_deals = [_deal("w1", "won")]
        test_deals += [_deal(f"x-{i}", "lost", stage_order=9) for i in range(5)]
        with patch("supabase_client.select_all", return_value=test_deals):
            restored = loss_concentration.assess_loss_concentration(
                sb=None, time_window=FAKE_TW)
        assert restored["stage_of_loss"]["administrative_stage_share"]["count"] == 5
        print("✓ restore confirmed clean — real mapping re-verified working")


def test_planted_discrepancy_rate_normalization_is_load_bearing():
    """Break the loss-rate formula (lost/closed) to instead divide by
    won count (lost/won) -> rep_a's 3/6 (50%) would instead read as
    3/3 (100%) -> the rate-normalization test above must fail. Confirms
    the MIN_N-gated rate math is actually enforced, not just present."""
    import importlib
    path = Path(__file__).parent / "loss_concentration.py"
    original = path.read_text()
    try:
        broken = original.replace(
            "    loss_rate = lost / closed\n",
            "    loss_rate = lost / won if won else 1.0  # PLANTED BUG\n",
        )
        assert broken != original, "plant string not found — test setup is stale"
        path.write_text(broken)

        import loss_concentration
        importlib.reload(loss_concentration)

        deals = _basic_population()
        with patch("supabase_client.select_all", return_value=deals):
            result = loss_concentration.assess_loss_concentration(
                sb=None, time_window=FAKE_TW)

        by_rep = {r["owner_email"]: r for r in result["by_rep"]}
        rep_a = by_rep["rep_a@growthbook.io"]
        caught = rep_a["loss_rate"] != 0.5
        assert caught, (
            "❌ PLANTED BUG NOT CAUGHT: breaking the loss-rate denominator "
            "should have changed rep_a's rate away from the correct 0.5, "
            "but the test still saw 0.5")
        print(f"✓ planted rate-formula bug WAS caught (rep_a's rate became "
              f"{rep_a['loss_rate']!r} instead of the correct 0.5)")
    finally:
        path.write_text(original)
        import loss_concentration
        importlib.reload(loss_concentration)
        deals = _basic_population()
        with patch("supabase_client.select_all", return_value=deals):
            restored = loss_concentration.assess_loss_concentration(
                sb=None, time_window=FAKE_TW)
        by_rep = {r["owner_email"]: r for r in restored["by_rep"]}
        assert by_rep["rep_a@growthbook.io"]["loss_rate"] == 0.5
        print("✓ restore confirmed clean — real rate formula re-verified working")


if __name__ == "__main__":
    tests = [
        test_below_min_n_returns_insufficient_data,
        test_rep_breakdown_is_rate_normalized_vs_team_average,
        test_segment_breakdown_same_shape,
        test_stage_of_loss_uses_canonical_bucket_not_raw_order,
        test_ghost_deal_share_computed_but_not_excluded,
        test_planted_discrepancy_bucket_mapping_is_load_bearing,
        test_planted_discrepancy_rate_normalization_is_load_bearing,
    ]
    passed = 0
    for t in tests:
        t()
        passed += 1
    print(f"\nTotal tests: {len(tests)}\n  ✓ Passed: {passed}")
    print("\n✅ All assess_loss_concentration() tests passed")
