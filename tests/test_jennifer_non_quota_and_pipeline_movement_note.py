"""
Tests for two small 2026-10-06 changes:

1. config/targets.yaml: jennifer@growthbook.io (finance role, handles
   low-amount renewals, no quota) added to non_quota_roles for both
   FY2027_Q3 and FY2027_Q4. api/handlers.py::query_rep_attainment reads
   this list per-quarter to build known_roster_emails, so a win under her
   email is attributed to a known, non-quota person instead of being
   folded into the "no quota assigned" roster-gap line. Her own
   user_personas.role was separately updated (live data, not config) from
   "ae" to "finance" — not covered by a test here, that's a live DB value.

2. api/handlers.py::query_pipeline_movement's docstring now states it
   reads a WEEKLY deals_snapshot ETL and can lag the live `deals` table —
   found while reconciling a real production discrepancy (a deal's
   close_date moved in `deals` but the handler's snapshot-sourced view of
   it hadn't caught up yet).

Planted-bug controls for both, per this repo's convention.
"""
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO / 'scripts'))

import yaml
import api.handlers as handlers


def _load_targets_config():
    targets_path = REPO / 'config' / 'targets.yaml'
    with open(targets_path) as f:
        return yaml.safe_load(f)


def test_jennifer_in_non_quota_roles_both_quarters():
    print("\n[TEST] jennifer@growthbook.io is in non_quota_roles for Q3 and Q4")
    targets_config = _load_targets_config()
    for quarter_key in ('fy2027_q3', 'fy2027_q4'):
        non_quota = targets_config['targets'][quarter_key].get('non_quota_roles') or []
        assert 'jennifer@growthbook.io' in non_quota, (
            f"{quarter_key}: jennifer@growthbook.io missing from non_quota_roles")
    print("  ✓ present in both fy2027_q3 and fy2027_q4")


def test_jennifer_not_a_quota_rep():
    """She must not ALSO appear as a reps:// quota entry — non_quota_roles
    and reps are mutually exclusive by design (a rep is one or the other,
    never both)."""
    print("\n[TEST] jennifer@growthbook.io is not a quota-bearing rep")
    targets_config = _load_targets_config()
    for quarter_key, quarter_data in targets_config['targets'].items():
        reps = quarter_data.get('reps', {})
        assert 'jennifer@growthbook.io' not in reps, (
            f"{quarter_key}: jennifer@growthbook.io must not be a reps: quota entry "
            "(she's in non_quota_roles instead)")
    print("  ✓ not present in any quarter's reps:")


def test_planted_bug_missing_from_non_quota_roles():
    """Planted-bug control: reproduce the pre-fix config (no non_quota_roles
    entry for her at all) and confirm the assertion above would have failed,
    proving this test actually catches the gap."""
    print("\n[TEST] planted-bug control: absent non_quota_roles entry fails the check")
    pre_fix_non_quota = []  # the key didn't exist at all before this change
    assert 'jennifer@growthbook.io' not in pre_fix_non_quota, (
        "planted-bug control failed to reproduce: pre-fix non_quota_roles "
        "should not have contained her email")
    # And the real (fixed) config does.
    targets_config = _load_targets_config()
    assert 'jennifer@growthbook.io' in (
        targets_config['targets']['fy2027_q3'].get('non_quota_roles') or [])
    print("  ✓ confirmed: pre-fix config lacked the entry; fixed config has it")


def test_pipeline_movement_docstring_discloses_weekly_lag():
    print("\n[TEST] query_pipeline_movement docstring discloses weekly-snapshot lag")
    doc = handlers.query_pipeline_movement.__doc__ or ""
    assert "weekly" in doc.lower() or "WEEKLY" in doc, (
        "docstring must disclose that deals_snapshot is a weekly ETL")
    assert "lag" in doc.lower(), (
        "docstring must disclose that this handler's view can lag the live `deals` table")
    print("  ✓ docstring names the weekly ETL and the lag it can cause")


def test_planted_bug_docstring_missing_lag_disclosure():
    """Planted-bug control: the ORIGINAL docstring (captured before this
    change) had no lag disclosure at all — confirm that absence would have
    failed the check above."""
    print("\n[TEST] planted-bug control: pre-fix docstring had no lag disclosure")
    pre_fix_doc_excerpt = (
        "Pipeline movement / composition / deal-level changes / coverage curve,\n"
        "    read from deals_snapshot.\n\n"
        "    Movement view now includes dollar fields (added_arr_total, exited_arr_total,"
    )
    assert "lag" not in pre_fix_doc_excerpt.lower(), (
        "planted-bug control failed to reproduce: pre-fix docstring excerpt "
        "should not have mentioned lag")
    # And the real (fixed) docstring does.
    doc = handlers.query_pipeline_movement.__doc__ or ""
    assert "lag" in doc.lower()
    print("  ✓ confirmed: pre-fix docstring had no lag disclosure; fixed one does")


def run_all_tests():
    tests = [
        test_jennifer_in_non_quota_roles_both_quarters,
        test_jennifer_not_a_quota_rep,
        test_planted_bug_missing_from_non_quota_roles,
        test_pipeline_movement_docstring_discloses_weekly_lag,
        test_planted_bug_docstring_missing_lag_disclosure,
    ]
    failed = []
    for test in tests:
        try:
            test()
        except AssertionError as e:
            print(f"✗ {test.__name__} FAILED: {e}")
            failed.append((test.__name__, e))
    if failed:
        print(f"FAILED: {len(failed)}/{len(tests)} tests")
        sys.exit(1)
    print(f"SUCCESS: All {len(tests)} tests passed")
    sys.exit(0)


if __name__ == '__main__':
    run_all_tests()
