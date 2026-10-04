#!/usr/bin/env python3
"""
Offline tests for scripts/seed_targets.py's row-building logic.

Runs build_rows_for_quarter() against the REAL config/targets.yaml, with
no network access (no SupabaseWriter is constructed) — this is purely
about whether the script's own row-building logic is correct and
idempotent, not about seeding the live rep_targets table.

Asserts the hard invariant: the team row always equals the sum of the
rep rows built in the same call, roles are preserved per rep, and
re-running (idempotency) produces byte-identical rows.
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent / 'scripts'))

import yaml
from seed_targets import build_rows_for_quarter


def _load_targets_config():
    targets_path = Path(__file__).parent.parent / 'config' / 'targets.yaml'
    with open(targets_path) as f:
        return yaml.safe_load(f)['targets']


def test_team_row_equals_sum_of_rep_rows_for_each_period():
    targets = _load_targets_config()
    for quarter_key, quarter_data in targets.items():
        rows = build_rows_for_quarter(quarter_key, quarter_data)
        rep_rows = [r for r in rows if r["level"] == "rep"]
        team_rows = [r for r in rows if r["level"] == "team"]

        assert len(team_rows) == 1, (
            f"{quarter_key}: expected exactly one team row, got "
            f"{len(team_rows)}")

        rep_sum = sum(r["target_value"] for r in rep_rows)
        team_value = team_rows[0]["target_value"]
        assert rep_sum == team_value, (
            f"{quarter_key}: team row ({team_value:,}) != sum of rep rows "
            f"({rep_sum:,})")

    print("✓ team row == sum of rep rows for every configured period")


def test_roles_are_preserved_per_rep():
    targets = _load_targets_config()
    quarter_data = targets['fy2027_q3']
    rows = build_rows_for_quarter('fy2027_q3', quarter_data)
    rep_rows = {r["entity_email"]: r for r in rows if r["level"] == "rep"}

    # Spot-check known role assignments from the approved target table.
    assert rep_rows["cary@growthbook.io"]["role"] == "am"
    assert rep_rows["marsh@growthbook.io"]["role"] == "am"
    assert rep_rows["jake@growthbook.io"]["role"] == "ae"
    assert rep_rows["kris@growthbook.io"]["role"] == "ae"

    am_rows = [r for r in rows if r["level"] == "rep" and r["role"] == "am"]
    assert len(am_rows) == 2, (
        f"expected 2 am-role reps (cary, marsh), got {len(am_rows)}")

    print("✓ per-rep role (ae/am) is read from config, not hardcoded")


def test_rerun_is_idempotent():
    """Running build_rows_for_quarter twice on the same config produces
    identical rows — no hidden mutable state, no drift on re-seed."""
    targets = _load_targets_config()
    quarter_data = targets['fy2027_q3']

    rows_1 = build_rows_for_quarter('fy2027_q3', quarter_data)
    rows_2 = build_rows_for_quarter('fy2027_q3', quarter_data)

    assert rows_1 == rows_2, "re-running build_rows_for_quarter() changed output"
    print("✓ build_rows_for_quarter() is idempotent across repeated calls")


def test_approved_figures_q3_and_q4():
    """Pins the approved, independently-recomputed FY2027 Q3/Q4 figures
    (including ramp math for Marcel, Kris, and marsh) so a future config
    edit that silently changes them is caught here."""
    targets = _load_targets_config()

    q3_rows = build_rows_for_quarter('fy2027_q3', targets['fy2027_q3'])
    q3_team = [r for r in q3_rows if r["level"] == "team"][0]["target_value"]
    assert q3_team == 2031069, f"FY2027 Q3 team total should be 2,031,069, got {q3_team:,}"

    q4_rows = build_rows_for_quarter('fy2027_q4', targets['fy2027_q4'])
    q4_team = [r for r in q4_rows if r["level"] == "team"][0]["target_value"]
    assert q4_team == 2568478, f"FY2027 Q4 team total should be 2,568,478, got {q4_team:,}"

    print("✓ FY2027 Q3 team total $2,031,069 and Q4 team total $2,568,478 "
          "match the approved, independently-recomputed figures")


def run_all_tests():
    tests = [
        test_team_row_equals_sum_of_rep_rows_for_each_period,
        test_roles_are_preserved_per_rep,
        test_rerun_is_idempotent,
        test_approved_figures_q3_and_q4,
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
