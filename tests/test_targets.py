#!/usr/bin/env python3
"""
Tests for sales targets configuration and semantic assembly.

Ensures targets are correctly structured, loaded, and presented.
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent / 'scripts'))

import yaml
from utils import build_semantic_context


def test_team_total_equals_sum_of_ae_quotas():
    """1,550,000 is the sum of six AE targets. If they diverge, one was edited
    without the other."""
    targets_path = Path(__file__).parent.parent / 'config' / 'targets.yaml'
    with open(targets_path) as f:
        targets_config = yaml.safe_load(f)

    q3_targets = targets_config['targets']['fy2027_q3']
    team_total = q3_targets['team_total']

    # Sum all rep targets
    sum_ae_quotas = sum(
        rep['target'] if isinstance(rep, dict) else rep
        for rep in q3_targets['reps'].values()
    )

    assert sum_ae_quotas == team_total, \
        f"Sum of AE quotas ({sum_ae_quotas:,}) != team_total ({team_total:,})"

    print(f"✓ Team total ${team_total:,} = sum of {len(q3_targets['reps'])} AE quotas")


def test_non_quota_roles_excluded_from_attainment():
    """AMs appear in revenue contribution but never in attainment percentage.
    Showing them at 0% is as wrong as omitting them silently."""
    targets_path = Path(__file__).parent.parent / 'config' / 'targets.yaml'
    with open(targets_path) as f:
        targets_config = yaml.safe_load(f)

    q3_targets = targets_config['targets']['fy2027_q3']

    # Verify non_quota_roles exists
    assert 'non_quota_roles' in q3_targets, "non_quota_roles not configured"

    non_quota = q3_targets['non_quota_roles']
    assert len(non_quota) > 0, "non_quota_roles is empty"

    # Verify AMs are listed
    expected_ams = ['cary.rakin@growthbook.io', 'andy.marshall@growthbook.io']
    for am in expected_ams:
        assert am in non_quota, f"{am} missing from non_quota_roles"

    # Verify AMs are NOT in quota reps
    rep_emails = list(q3_targets['reps'].keys())
    for am in non_quota:
        assert am not in rep_emails, \
            f"{am} appears in both reps and non_quota_roles (inconsistent)"

    print(f"✓ {len(non_quota)} AMs in non_quota_roles, excluded from quota reps")


def test_target_basis_is_incremental_arr():
    """Attainment compares against Incremental ARR. Including renewal base
    would overstate every rep."""
    targets_path = Path(__file__).parent.parent / 'config' / 'targets.yaml'
    with open(targets_path) as f:
        targets_config = yaml.safe_load(f)

    q3_targets = targets_config['targets']['fy2027_q3']

    # Verify basis field
    assert 'basis' in q3_targets, "basis field missing"
    assert q3_targets['basis'] == 'incremental_arr', \
        f"basis should be 'incremental_arr', got '{q3_targets['basis']}'"

    # Verify semantic context explains this
    context = build_semantic_context()
    assert 'basis: incremental_arr' in context, \
        "Semantic context doesn't show target basis"

    print("✓ Target basis is incremental_arr (new_arr + expansion_arr)")


def test_required_pipeline_derived_from_measured_conversion():
    """Required pipeline uses the measured rate, not a fixed coverage multiple.
    The configured 2.5x is miscalibrated against ~9.9% actual."""

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
    targets_path = Path(__file__).parent.parent / 'config' / 'targets.yaml'
    with open(targets_path) as f:
        targets_config = yaml.safe_load(f)

    q3_targets = targets_config['targets']['fy2027_q3']
    james = q3_targets['reps']['james.shannon@growthbook.io']

    # Verify current target is $300K
    assert james['target'] == 300000, \
        f"James Shannon target should be $300K, got ${james['target']:,}"

    # Verify note about correction
    assert 'note' in james, "James Shannon missing correction note"
    assert '250000' in james['note'], "Note should reference original $250K"
    assert 'week 3' in james['note'].lower(), "Note should reference week 3 timing"

    print("✓ James Shannon $250K→$300K correction documented")


def test_ramp_quota_marked():
    """Marcel Geldner is a new AE at $150K ramp target.
    Should be marked so ramp is visible rather than inferred."""
    targets_path = Path(__file__).parent.parent / 'config' / 'targets.yaml'
    with open(targets_path) as f:
        targets_config = yaml.safe_load(f)

    q3_targets = targets_config['targets']['fy2027_q3']
    marcel = q3_targets['reps']['marcel.geldner@growthbook.io']

    # Verify target is $150K
    assert marcel['target'] == 150000, \
        f"Marcel Geldner target should be $150K, got ${marcel['target']:,}"

    # Verify ramp flag
    assert 'ramp' in marcel, "Marcel Geldner missing ramp flag"
    assert marcel['ramp'] is True, "ramp flag should be True"

    print("✓ Marcel Geldner $150K ramp quota marked")


def run_all_tests():
    """Run all target configuration tests."""
    tests = [
        test_team_total_equals_sum_of_ae_quotas,
        test_non_quota_roles_excluded_from_attainment,
        test_target_basis_is_incremental_arr,
        test_required_pipeline_derived_from_measured_conversion,
        test_mid_quarter_correction_noted,
        test_ramp_quota_marked,
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
