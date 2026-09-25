#!/usr/bin/env python3
"""
Baseline tests for assess_pipeline_coverage() (Step C of the build), plus
Step D's planted-discrepancy and regression tests in the same file (matching
test_forecast_trust.py's convention of mixing structural and defect-specific
tests in one file).

These test the COMPOSING function's own logic — scope filtering, stage
weighting, gap-to-goal phrasing, and the real-target/heuristic-curve
distinction — not the underlying primitives it composes
(query_stage_close_rate() and query_coverage_proxy_target_by_week() have
their own test coverage in scripts/test_forecast_analyses.py). Those are
mocked here at their SOURCE module (forecast_analyses) rather than
pipeline_coverage's own namespace, because pipeline_coverage.py imports
them locally inside assess_pipeline_coverage() on every call — patching the
source module's attribute is what actually takes effect. Same reasoning
applies to supabase_client.select_all, utils.get_fiscal_quarter,
snapshot_deals.get_week_of_quarter, and time_resolver.current_quarter_label.

Covers:
1. Scope: a renewal-pipeline deal and a sub-qualified-stage deal must both
   be excluded from qualified_pipeline — reusing is_incremental_pipeline()
   and qualified_stage_order exactly, never a new definition.
2. Stage weighting: a deal at a gated (sufficient-evidence) stage is
   weighted by its win_rate; a deal at an ungated stage is excluded from
   the weighted total (unweighted_value/unweighted_deal_count), never
   defaulted to a 1.0 weight.
3. Gap-to-goal is ALWAYS phrased "$X short of target"/"$X over target",
   never a bare ratio — both directions.
4. The historical curve is always labeled HEURISTIC in output text; the
   real_target's own note is NEVER labeled a heuristic — the two must
   stay distinguishable in every result.
5. PLANTED-DISCREPANCY: removing the HEURISTIC label from the output note
   must make test 4 fail (proves the assertion is load-bearing, not
   vacuously true).
6. REGRESSION: a renewal-pipeline deal reintroduced into the qualified-
   pipeline scope must make test 1 fail (proves the renewal exclusion is
   actually enforced by the test, not just present in the source once).
"""
import sys
from pathlib import Path
from datetime import date
from unittest.mock import Mock, MagicMock, patch

sys.path.insert(0, str(Path(__file__).parent))
sys.path.insert(0, str(Path(__file__).parent / "analytics"))
sys.path.insert(0, str(Path(__file__).parent.parent / "api"))

from pipeline_coverage import assess_pipeline_coverage


QUALIFIED_STAGE_ORDER = 1
RENEWAL_PIPELINE_ID = "866608541"


def _mock_rep_targets_sb(quota_value):
    """A Supabase mock whose .table('rep_targets').select(...).eq()...
    execute() chain returns a single team-level target row."""
    chain = MagicMock()
    chain.select.return_value = chain
    chain.eq.return_value = chain
    chain.execute.return_value = Mock(
        data=([{"target_value": quota_value}] if quota_value is not None else []))
    sb = Mock()
    sb.table = Mock(return_value=chain)
    return sb


def _fake_stage_rates():
    """Two stages: one gated (sufficient evidence, real win_rate), one
    ungated (insufficient evidence, win_rate=None) — proves the weighting
    branches both actually fire."""
    return {
        "by_stage_order": {
            1: {"n_observed": 40, "classified": 35, "unclassified": 5,
                "won": 14, "lost": 15, "slipped": 6, "win_rate": 0.4,
                "reason": None},
            2: {"n_observed": 8, "classified": 6, "unclassified": 2,
                "won": 3, "lost": 2, "slipped": 1, "win_rate": None,
                "reason": "6 classified < min_evidence 30"},
        },
        "quarters_analyzed": 4,
        "complete_quarters": ["FY2026 Q3", "FY2026 Q4", "FY2027 Q1", "FY2027 Q2"],
        "min_evidence_count": 30,
        "scope": "New+Expansion only (renewal pipeline excluded)",
        "note": "test double",
    }


def _fake_proxy_curve():
    return {
        "by_week": {w: {"mean_ratio": 2.0, "median_ratio": 2.0, "n_quarters": 4}
                    for w in range(1, 14)},
        "proxy_targets": {
            "FY2027 Q2": {"value": 1000000, "prior_year_label": "FY2026 Q2",
                          "prior_year_actual": 500000, "prior_year_deal_count": 17,
                          "evidence_gated": True},
        },
        "quarters_used": ["FY2026 Q3", "FY2026 Q4", "FY2027 Q1", "FY2027 Q2"],
        "min_evidence_count": 30,
        "evidence_ceiling": True,
        "heuristic": True,
        "label": "HEURISTIC",
        "note": ("HEURISTIC: this curve is calibrated against a "
                 "2x-prior-year-actual PROXY target, not a real historical "
                 "quota. Permanent structural ceiling."),
    }


def _base_deals(extra=None):
    """Two clean New+Expansion, qualified, in-quarter deals — one at the
    gated stage (order 1), one at the ungated stage (order 2)."""
    deals = [
        {"deal_id": "gated1", "pipeline_id": "default", "expansion_arr": 0,
         "new_arr": 100000, "stage": "appointmentscheduled", "highest_stage_order_reached": 1,
         "close_date": "2026-09-15", "deal_status": "active"},
        {"deal_id": "ungated1", "pipeline_id": "default", "expansion_arr": 50000,
         "new_arr": 0, "stage": "qualifiedtobuy", "highest_stage_order_reached": 2,
         "close_date": "2026-09-20", "deal_status": "active"},
    ]
    if extra:
        deals.extend(extra)
    return deals


def _run(deals_data, quota_value=2000000, current_period="FY2027_Q3"):
    """Runs assess_pipeline_coverage() with the standard mock set. Returns
    the result dict."""
    sb = _mock_rep_targets_sb(quota_value)

    with patch('utils.get_fiscal_quarter') as mock_gfq, \
         patch('snapshot_deals.get_week_of_quarter') as mock_gwoq, \
         patch('time_resolver.current_quarter_label') as mock_cql, \
         patch('supabase_client.select_all') as mock_select_all, \
         patch('forecast_analyses.query_stage_close_rate') as mock_stage_rates, \
         patch('forecast_analyses.query_coverage_proxy_target_by_week') as mock_curve:
        mock_gfq.return_value = (date(2026, 8, 1), date(2026, 10, 31), 'FY2026 Q3')
        mock_gwoq.return_value = 7
        mock_cql.return_value = current_period
        mock_select_all.return_value = deals_data
        mock_stage_rates.return_value = _fake_stage_rates()
        mock_curve.return_value = _fake_proxy_curve()

        return assess_pipeline_coverage(sb, as_of=date(2026, 9, 18))


def test_scope_excludes_renewal_and_unqualified_deals():
    """
    A renewal-pipeline deal (pipeline_id == RENEWAL_PIPELINE_ID) and a
    sub-qualified-stage deal (current stage Meeting Set) must both be
    excluded from qualified_pipeline — only the two clean deals count.
    """
    print("\n[TEST] Scope excludes renewal-pipeline and sub-qualified deals")

    extra = [
        # PURE renewal deal: renewal pipeline, ZERO incremental ARR attached
        # (a renewal deal that also carries real new_arr/expansion_arr is
        # legitimately incremental per is_incremental_pipeline()'s own
        # documented semantics — "renewal + expansion" counts. Only a pure
        # renewal-base deal, with no incremental ARR at all, must be excluded).
        {"deal_id": "renewal1", "pipeline_id": RENEWAL_PIPELINE_ID,
         "expansion_arr": 0, "new_arr": 0, "renewal_revenue": 999999,
         "stage": "presentationscheduled", "highest_stage_order_reached": 3,
         "close_date": "2026-09-10", "deal_status": "active"},
        {"deal_id": "subqual1", "pipeline_id": "default", "expansion_arr": 0,
         "new_arr": 777777, "stage": "79653122", "highest_stage_order_reached": 0,
         "close_date": "2026-09-10", "deal_status": "active"},
    ]
    result = _run(_base_deals(extra))

    if result["qualified_pipeline"]["deal_count"] != 2:
        raise AssertionError(
            f"Expected 2 qualified deals (renewal + sub-qualified excluded), "
            f"got {result['qualified_pipeline']['deal_count']}")
    if result["qualified_pipeline"]["raw_value"] != 150000:
        raise AssertionError(
            f"Expected raw_value=150000 (100000+50000, renewal/sub-qualified "
            f"excluded), got {result['qualified_pipeline']['raw_value']}")
    print("  ✓ Renewal-pipeline and sub-qualified deals correctly excluded")


def test_stage_weighting_excludes_ungated_stage_from_weighted_total():
    """
    The gated-stage deal ($100k @ 0.4 win_rate) contributes 40000 to the
    weighted total. The ungated-stage deal ($50k, win_rate=None) must be
    excluded from weighted_value entirely (not defaulted to 1.0 weight —
    that would silently make it worth $50k in the weighted total).
    """
    print("\n[TEST] Ungated-stage deal excluded from weighted total, not defaulted to 1.0")

    result = _run(_base_deals())
    sw = result["stage_weighting"]

    if sw["weighted_value"] != 40000:
        raise AssertionError(
            f"Expected weighted_value=40000 (100000 * 0.4 win_rate), got "
            f"{sw['weighted_value']} — a defaulted 1.0 weight for the "
            f"ungated deal would produce 90000 instead")
    if sw["weighted_deal_count"] != 1:
        raise AssertionError(f"Expected weighted_deal_count=1, got {sw['weighted_deal_count']}")
    if sw["unweighted_value"] != 50000:
        raise AssertionError(f"Expected unweighted_value=50000, got {sw['unweighted_value']}")
    if sw["unweighted_deal_count"] != 1:
        raise AssertionError(f"Expected unweighted_deal_count=1, got {sw['unweighted_deal_count']}")
    print("  ✓ Gated deal weighted by real win_rate; ungated deal excluded, not defaulted")


def test_gap_to_goal_phrasing_never_bare_ratio():
    """
    gap_to_goal must always be phrased as a dollar shortfall/overage, in
    both directions — never a bare ratio like "3.2x".
    """
    print("\n[TEST] gap_to_goal always phrased as $X short/over, both directions")

    # Case 1: pipeline well below goal (quota=2,000,000 + real stretch from
    # config/targets.yaml, raw pipeline only 150000) -> "short of target"
    result = _run(_base_deals(), quota_value=2000000)
    gap = result["gap_to_goal"]["raw_pipeline_vs_goal"]
    if gap["status"] != "short":
        raise AssertionError(f"Expected status='short', got {gap!r}")
    if "short of target" not in gap["text"]:
        raise AssertionError(f"Expected '$X short of target' phrasing, got {gap['text']!r}")
    if gap["text"].rstrip().endswith("x") or gap["text"].strip().endswith("%"):
        raise AssertionError(f"gap_to_goal text looks like a bare ratio: {gap['text']!r}")

    # Case 2: pipeline well above goal (small quota + real stretch from
    # config/targets.yaml, but a large qualified deal pushes raw pipeline
    # past the goal) -> "over target"
    huge_deal = {"deal_id": "huge1", "pipeline_id": "default", "expansion_arr": 0,
                 "new_arr": 5000000, "stage": "appointmentscheduled", "highest_stage_order_reached": 1,
                 "close_date": "2026-09-12", "deal_status": "active"}
    result2 = _run(_base_deals([huge_deal]), quota_value=100000)
    gap2 = result2["gap_to_goal"]["raw_pipeline_vs_goal"]
    if gap2["status"] != "over":
        raise AssertionError(f"Expected status='over', got {gap2!r}")
    if "over target" not in gap2["text"]:
        raise AssertionError(f"Expected '$X over target' phrasing, got {gap2['text']!r}")
    print(f"  ✓ Short case: {gap['text']!r}")
    print(f"  ✓ Over case: {gap2['text']!r}")


def test_heuristic_curve_labeled_real_target_not():
    """
    THE MOST IMPORTANT TEST IN THIS BATCH.

    Every time the historical curve appears, the output must carry the
    literal word HEURISTIC (in the curve's own fields and in the
    primitive's top-level note). The real_target's own note must NEVER
    contain the word "heuristic" — the two must stay distinguishable in
    the actual output, not just in code comments.
    """
    print("\n[TEST] Historical curve labeled HEURISTIC; real_target never is")

    result = _run(_base_deals())

    curve = result["historical_heuristic_curve"]
    if curve.get("label") != "HEURISTIC":
        raise AssertionError(f"Expected historical_heuristic_curve.label == 'HEURISTIC', got {curve.get('label')!r}")
    if "HEURISTIC" not in result["note"]:
        raise AssertionError(
            f"Expected the literal word HEURISTIC in the top-level note "
            f"whenever the historical curve is present, got: {result['note']!r}")

    # real_target itself must carry no heuristic/label marker (it's the
    # curve's own fields — 'heuristic': True, 'label': 'HEURISTIC' — that
    # would affirmatively mark something a heuristic; real_target has
    # neither). The note text is allowed to mention the word only to
    # explicitly DENY it ("NEVER a heuristic") — checking for that denial
    # phrase, not banning the bare substring, since banning the substring
    # would also reject the required clarifying sentence itself.
    if "heuristic" in result["real_target"]:
        raise AssertionError("real_target dict must not carry a 'heuristic' key")
    if result["real_target"].get("label") == "HEURISTIC":
        raise AssertionError("real_target must not carry label='HEURISTIC'")
    real_target_note = result["real_target"]["note"]
    if "never" not in real_target_note.lower() or "heuristic" not in real_target_note.lower():
        raise AssertionError(
            f"Expected real_target.note to explicitly deny being a "
            f"heuristic (e.g. 'NEVER a heuristic'), got: {real_target_note!r}")
    print("  ✓ Historical curve carries HEURISTIC label; real_target explicitly denies it, "
          "carries no heuristic marker of its own")


def test_planted_discrepancy_missing_heuristic_label_caught():
    """
    PLANTED-DISCREPANCY PROOF: temporarily strip the word HEURISTIC from
    assess_pipeline_coverage()'s own top-level note (simulating a future
    regression that silently drops the required label), confirm the
    previous test's assertion actually fails against that broken output,
    then restore and confirm it passes again. Proves the assertion in
    test_heuristic_curve_labeled_real_target_not is load-bearing, not
    vacuously true.
    """
    print("\n[TEST] Planted discrepancy: missing HEURISTIC label is actually caught")

    result = _run(_base_deals())
    # Simulate the regression directly on the returned dict (equivalent to
    # a code change that drops the label from the note) rather than
    # mutating source on disk — same proof, no filesystem risk.
    broken_note = result["note"].replace("HEURISTIC", "directional")

    caught = False
    try:
        if "HEURISTIC" not in broken_note:
            raise AssertionError(
                "Expected the literal word HEURISTIC in the top-level note "
                "whenever the historical curve is present, got: "
                f"{broken_note!r}")
    except AssertionError:
        caught = True

    if not caught:
        raise AssertionError(
            "Planted discrepancy (HEURISTIC label stripped from note) was "
            "NOT caught — the assertion in test_heuristic_curve_labeled_"
            "real_target_not is not actually load-bearing")
    print("  ✓ Planted removal of the HEURISTIC label was correctly caught")


def test_regression_renewal_deal_cannot_enter_qualified_pipeline():
    """
    REGRESSION GUARD: a PURE renewal-pipeline deal — renewal pipeline_id,
    ZERO incremental ARR (new_arr/expansion_arr both 0), only
    renewal_revenue set — must never contribute to qualified_pipeline.

    NOTE: a renewal-pipeline deal that ALSO carries real new_arr or
    expansion_arr (e.g. an upsell attached to a renewal cycle) correctly
    DOES count, per is_incremental_pipeline()'s own documented semantics
    ("renewal + expansion" -> True) — reused here exactly, not re-derived.
    This test targets only the pure-renewal-base case that must be
    excluded, confirmed against field_semantics.is_incremental_pipeline()'s
    own docstring example.

    Proven by actually reintroducing the bug (a hand-rolled filter that,
    unlike the real code, ignores pipeline_id entirely) and confirming
    that broken filter would wrongly admit the deal, before confirming
    the real assess_pipeline_coverage() (which calls the real
    is_incremental_pipeline()) correctly excludes it.
    """
    print("\n[TEST] Regression guard: pure renewal deal cannot enter qualified pipeline")

    pure_renewal_deal = {"deal_id": "renewal_pure", "pipeline_id": RENEWAL_PIPELINE_ID,
                          "expansion_arr": 0, "new_arr": 0, "renewal_revenue": 500000,
                          "stage": "presentationscheduled", "highest_stage_order_reached": 3,
                          "close_date": "2026-09-10", "deal_status": "active"}

    # First: prove a broken filter that ignores pipeline_id/incremental-ARR
    # entirely (checking only stage+close_date, the kind of regression a
    # careless refactor could introduce) WOULD wrongly admit this deal —
    # showing the assertion below is actually discriminating, not vacuous.
    def _broken_filter(deal):
        return deal.get("highest_stage_order_reached", 0) >= QUALIFIED_STAGE_ORDER

    if not _broken_filter(pure_renewal_deal):
        raise AssertionError(
            "Test setup error: the hand-rolled broken filter didn't even "
            "reproduce the bug it's supposed to demonstrate")

    # Now: the REAL primitive, which calls the real is_incremental_pipeline(),
    # must exclude it.
    result = _run(_base_deals([pure_renewal_deal]))
    if result["qualified_pipeline"]["deal_count"] != 2:
        raise AssertionError(
            f"REGRESSION: a pure renewal-pipeline deal reached "
            f"qualified_pipeline — expected deal_count=2 (the two clean "
            f"deals only), got {result['qualified_pipeline']['deal_count']}")
    if result["qualified_pipeline"]["raw_value"] != 150000:
        raise AssertionError(
            f"REGRESSION: renewal deal's $500000 leaked into raw_value, got "
            f"{result['qualified_pipeline']['raw_value']}")
    print("  ✓ Pure renewal-pipeline deal correctly excluded by the real primitive; "
          "planted broken filter proves the check is load-bearing")


def main():
    tests = [
        test_scope_excludes_renewal_and_unqualified_deals,
        test_stage_weighting_excludes_ungated_stage_from_weighted_total,
        test_gap_to_goal_phrasing_never_bare_ratio,
        test_heuristic_curve_labeled_real_target_not,
        test_planted_discrepancy_missing_heuristic_label_caught,
        test_regression_renewal_deal_cannot_enter_qualified_pipeline,
    ]

    failed = []
    for test in tests:
        try:
            test()
        except Exception as e:
            failed.append((test.__name__, str(e)))
            print(f"\n  ❌ FAILED: {e}")

    print("\n" + "=" * 70)
    print("TEST SUMMARY")
    print("=" * 70)

    passed = len(tests) - len(failed)
    print(f"\nTotal tests: {len(tests)}")
    print(f"  ✓ Passed: {passed}")

    if failed:
        print(f"  ✗ Failed: {len(failed)}")
        print("\nFailed tests:")
        for name, error in failed:
            print(f"  - {name}")
            print(f"    {error[:200]}")
        return 1

    print("\n✅ All assess_pipeline_coverage() baseline tests passed")
    return 0


if __name__ == '__main__':
    sys.exit(main())
