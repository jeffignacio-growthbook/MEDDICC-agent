#!/usr/bin/env python3
"""
Tests for sales targets configuration and semantic assembly.

Ensures targets are correctly structured, loaded, and presented.

REWRITTEN 2026-10-04 (am-role attainment PR): config/targets.yaml moved
from a single AE-only quarter with a hand-typed team_total and a
non_quota_roles list, to a multi-role (ae/am), multi-period (Q3+Q4)
schema where the team total is ALWAYS computed from the stored reps
(never a separate hand-typed figure). The old non_quota_roles test here
also had two independent email bugs (cary.rakin@ instead of the real
cary@, andy.marshall@ instead of the real marsh@) that this rewrite
fixes alongside the schema change.
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent / 'scripts'))

import yaml
from utils import build_semantic_context


def _load_targets_config():
    targets_path = Path(__file__).parent.parent / 'config' / 'targets.yaml'
    with open(targets_path) as f:
        return yaml.safe_load(f)


def test_q3_team_total_equals_sum_of_rep_quotas():
    """$2,031,069 is the sum of all nine FY2027 Q3 rep quotas (ae + am).
    If they diverge, one was edited without the other."""
    targets_config = _load_targets_config()
    q3 = targets_config['targets']['fy2027_q3']

    sum_quotas = sum(
        rep['target'] if isinstance(rep, dict) else rep
        for rep in q3['reps'].values()
    )

    assert sum_quotas == 2031069, (
        f"Sum of FY2027 Q3 rep quotas (${sum_quotas:,}) != $2,031,069")

    print(f"✓ FY2027 Q3: ${sum_quotas:,} = sum of {len(q3['reps'])} rep quotas")


def test_q4_team_total_equals_sum_of_rep_quotas():
    """$2,568,478 is the sum of all nine FY2027 Q4 rep quotas (ae + am)."""
    targets_config = _load_targets_config()
    q4 = targets_config['targets']['fy2027_q4']

    sum_quotas = sum(
        rep['target'] if isinstance(rep, dict) else rep
        for rep in q4['reps'].values()
    )

    assert sum_quotas == 2568478, (
        f"Sum of FY2027 Q4 rep quotas (${sum_quotas:,}) != $2,568,478")

    print(f"✓ FY2027 Q4: ${sum_quotas:,} = sum of {len(q4['reps'])} rep quotas")


def test_team_total_is_not_hand_typed():
    """team_total must NOT exist as a separate YAML key — it is always
    computed from the reps dict (by seed_targets.py and
    build_semantic_context) so it can never drift from the stored rows."""
    targets_config = _load_targets_config()
    for quarter_key, quarter_data in targets_config['targets'].items():
        assert 'team_total' not in quarter_data, (
            f"{quarter_key} still has a hand-typed team_total key — "
            "this must be removed; the team figure is computed from reps.")

    print("✓ no quarter has a separate hand-typed team_total key")


def test_am_role_reps_have_real_quota_not_non_quota():
    """Cary and marsh@ (Andy Marshall) now have real am-role quota rows —
    they must NOT appear in a non_quota_roles list, and the emails must
    be the REAL HubSpot owner emails (cary@, marsh@), never the stale/
    wrong forms (cary.rakin@, andy.marshall@)."""
    targets_config = _load_targets_config()

    for quarter_key, quarter_data in targets_config['targets'].items():
        non_quota = quarter_data.get('non_quota_roles') or []
        assert 'cary.rakin@growthbook.io' not in non_quota, (
            f"{quarter_key}: stale/wrong email cary.rakin@growthbook.io "
            "should never appear (real email is cary@growthbook.io)")
        assert 'andy.marshall@growthbook.io' not in non_quota, (
            f"{quarter_key}: stale/wrong email andy.marshall@growthbook.io "
            "should never appear (real email is marsh@growthbook.io)")
        assert 'cary@growthbook.io' not in non_quota, (
            f"{quarter_key}: cary@growthbook.io has a real am quota now, "
            "must not be in non_quota_roles")
        assert 'marsh@growthbook.io' not in non_quota, (
            f"{quarter_key}: marsh@growthbook.io has a real am quota now, "
            "must not be in non_quota_roles")

        reps = quarter_data.get('reps', {})
        assert 'cary@growthbook.io' in reps, f"{quarter_key}: cary@growthbook.io missing from reps"
        assert 'marsh@growthbook.io' in reps, f"{quarter_key}: marsh@growthbook.io missing from reps"
        assert reps['cary@growthbook.io'].get('role') == 'am'
        assert reps['marsh@growthbook.io'].get('role') == 'am'

    print("✓ cary@growthbook.io and marsh@growthbook.io have real am quota "
          "rows under their correct HubSpot emails, in both periods")


def test_target_basis_is_incremental_arr_for_every_role():
    """Attainment compares against Incremental ARR for every role (ae and
    am alike) — they share one metric, never a different one per role."""
    targets_config = _load_targets_config()

    for quarter_key, quarter_data in targets_config['targets'].items():
        assert 'basis' in quarter_data, f"{quarter_key}: basis field missing"
        assert quarter_data['basis'] == 'incremental_arr', (
            f"{quarter_key}: basis should be 'incremental_arr', got "
            f"'{quarter_data['basis']}'")

        roles_seen = {rep.get('role') for rep in quarter_data['reps'].values()
                      if isinstance(rep, dict)}
        assert roles_seen == {'ae', 'am'}, (
            f"{quarter_key}: expected both ae and am roles present, got "
            f"{roles_seen}")

    # Verify semantic context explains this
    context = build_semantic_context()
    assert 'basis: incremental_arr' in context, \
        "Semantic context doesn't show target basis"

    print("✓ Every role's target basis is incremental_arr (new_arr + expansion_arr)")


def test_required_pipeline_derived_from_measured_conversion():
    """Required pipeline uses the measured rate, not a fixed coverage multiple.
    The configured 2.5x is miscalibrated against ~9.9% actual.

    NOTE: this assertion already failed on origin/main before this PR
    (pre-existing gap between this test's expectation and
    build_semantic_context's current wording) — left unchanged here, out
    of scope for the am-role attainment fix."""

    # Verify semantic context has the correct guidance
    context = build_semantic_context()

    assert 'measured_conversion_rate' in context, \
        "Semantic context missing measured conversion guidance"

    assert 'required_pipeline = target ÷ measured_conversion_rate' in context, \
        "Formula for required pipeline missing or incorrect"

    # Verify it warns against fixed multiples
    assert 'miscalibrated' in context.lower(), \
        "Should warn that fixed multiples (2.5x) are miscalibrated"

    print("✓ Required pipeline uses measured conversion, not fixed multiples")


def test_mid_quarter_correction_noted():
    """James Shannon was corrected from $250K to $300K after week 3.
    This must be documented to avoid confusion in week-3 vs current comparisons."""
    targets_config = _load_targets_config()
    q3 = targets_config['targets']['fy2027_q3']
    james = q3['reps']['james.shannon@growthbook.io']

    assert james['target'] == 300000, \
        f"James Shannon target should be $300K, got ${james['target']:,}"

    assert 'note' in james, "James Shannon missing correction note"
    assert '250000' in james['note'], "Note should reference original $250K"
    assert 'week 3' in james['note'].lower(), "Note should reference week 3 timing"

    print("✓ James Shannon $250K→$300K correction documented")


def test_ramp_quotas_marked_and_match_approved_figures():
    """Marcel Geldner, Kris Washburn, and marsh@ (Andy Marshall) are new
    hires on ramp quotas in FY2027 Q3 (and still partially ramped in Q4
    for Marcel/Kris). Each must be marked ramp=True (Q3) and match the
    approved, independently-recomputed ramp-formula figures."""
    targets_config = _load_targets_config()
    q3 = targets_config['targets']['fy2027_q3']
    q4 = targets_config['targets']['fy2027_q4']

    marcel_q3 = q3['reps']['marcel@growthbook.io']
    assert marcel_q3['target'] == 135326, f"Marcel Q3 should be $135,326, got ${marcel_q3['target']:,}"
    assert marcel_q3.get('ramp') is True, "Marcel Q3 missing ramp flag"

    kris_q3 = q3['reps']['kris@growthbook.io']
    assert kris_q3['target'] == 81250, f"Kris Q3 should be $81,250, got ${kris_q3['target']:,}"
    assert kris_q3.get('ramp') is True, "Kris Q3 missing ramp flag"

    marsh_q3 = q3['reps']['marsh@growthbook.io']
    assert marsh_q3['target'] == 89493, f"marsh@ Q3 should be $89,493, got ${marsh_q3['target']:,}"
    assert marsh_q3.get('ramp') is True, "marsh@ Q3 missing ramp flag"

    marcel_q4 = q4['reps']['marcel@growthbook.io']
    assert marcel_q4['target'] == 285326, f"Marcel Q4 should be $285,326, got ${marcel_q4['target']:,}"

    kris_q4 = q4['reps']['kris@growthbook.io']
    assert kris_q4['target'] == 270833, f"Kris Q4 should be $270,833, got ${kris_q4['target']:,}"

    marsh_q4 = q4['reps']['marsh@growthbook.io']
    assert marsh_q4['target'] == 287319, f"marsh@ Q4 should be $287,319, got ${marsh_q4['target']:,}"

    print("✓ Marcel, Kris, and marsh@ ramp quotas marked and match approved figures "
          "in both FY2027 Q3 and Q4")


def test_no_stale_emails_as_rep_keys():
    """marcel.geldner@, cary.rakin@, and andy.marshall@ are NOT real
    HubSpot owner emails for these reps and must never be used as a rep
    key (a `reps` dict entry or a `non_quota_roles` list entry) in any
    quarter. (They may still appear in prose comments warning against
    their use — this checks the parsed data, not the raw file text.)"""
    targets_config = _load_targets_config()
    stale_emails = {'marcel.geldner@growthbook.io',
                     'cary.rakin@growthbook.io',
                     'andy.marshall@growthbook.io'}

    for quarter_key, quarter_data in targets_config['targets'].items():
        rep_keys = set(quarter_data.get('reps', {}).keys())
        non_quota = set(quarter_data.get('non_quota_roles') or [])
        found = stale_emails & (rep_keys | non_quota)
        assert not found, (
            f"{quarter_key}: stale/wrong email(s) {found} used as a rep "
            "or non_quota_roles key")

    print("✓ no stale/wrong emails (marcel.geldner@, cary.rakin@, "
          "andy.marshall@) are used as a rep key in config/targets.yaml")


def run_all_tests():
    """Run all target configuration tests."""
    tests = [
        test_q3_team_total_equals_sum_of_rep_quotas,
        test_q4_team_total_equals_sum_of_rep_quotas,
        test_team_total_is_not_hand_typed,
        test_am_role_reps_have_real_quota_not_non_quota,
        test_target_basis_is_incremental_arr_for_every_role,
        test_required_pipeline_derived_from_measured_conversion,
        test_mid_quarter_correction_noted,
        test_ramp_quotas_marked_and_match_approved_figures,
        test_no_stale_emails_as_rep_keys,
    ]

    print("Running targets configuration tests")
    print("=" * 70)
    print()

    failed = []
    for test in tests:
        try:
            test()
        except AssertionError as e:
            print(f"✗ {test.__name__} FAILED: {e}")
            failed.append((test.__name__, e))
        except Exception as e:
            print(f"✗ {test.__name__} ERROR: {e}")
            failed.append((test.__name__, e))

    print()
    print("=" * 70)

    if failed:
        print(f"FAILED: {len(failed)}/{len(tests)} tests")
        for name, error in failed:
            print(f"  - {name}: {error}")
        sys.exit(1)
    else:
        print(f"SUCCESS: All {len(tests)} tests passed")
        sys.exit(0)


if __name__ == '__main__':
    run_all_tests()
