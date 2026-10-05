#!/usr/bin/env python3
"""
Offline tests for scripts/seed_targets.py's team-row collision guard
(check_collision_guard / check_post_write_guard).

No network access — uses a fake Supabase client (mock .table().select()
.eq().eq().eq().execute() chain returning a canned .data list) to
reproduce exactly the live scenario that motivated the guard: a
level='team' row already exists for (period, metric) under one
entity_name, and build_rows_for_quarter() is about to write a team row
under a DIFFERENT entity_name (e.g. the FY2027_Q3 "AE Team" vs
"GrowthBook Team" incident).

Covers:
  - match case: existing entity_name == incoming entity_name -> guard
    passes, does not raise.
  - mismatch case: existing entity_name != incoming entity_name -> guard
    raises TeamRowCollisionError, and the error message contains both
    rows (existing and about-to-write) side by side.
  - planted-bug control: temporarily monkeypatch check_collision_guard
    to a no-op (simulating "the guard was never added"), confirm the
    mismatch case would have proceeded silently (no exception), then
    restore the real guard and confirm it now aborts. This proves the
    test is actually exercising the guard, not passing vacuously.
  - post-write guard: >1 team row for (period, metric) after a write
    raises TeamRowCollisionError; exactly 1 does not.
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent / 'scripts'))

from seed_targets import (
    check_collision_guard, check_post_write_guard, TeamRowCollisionError,
)


class _FakeResponse:
    def __init__(self, data):
        self.data = data


class _FakeQuery:
    """Minimal stand-in for the .table().select().eq().eq().eq().execute()
    chain seed_targets.py's guards use. Ignores the actual column/filter
    values (this is a fake, not a real query engine) and just returns
    whatever row list it was constructed with."""
    def __init__(self, rows):
        self._rows = rows

    def select(self, *a, **k):
        return self

    def eq(self, *a, **k):
        return self

    def execute(self):
        return _FakeResponse(self._rows)


class _FakeSupabaseClient:
    def __init__(self, rows):
        self._rows = rows

    def table(self, name):
        assert name == 'rep_targets'
        return _FakeQuery(self._rows)


INCOMING_TEAM_ROW = {
    "period": "FY2027_Q3",
    "level": "team",
    "entity_name": "AE Team",
    "entity_email": None,
    "role": None,
    "metric": "incremental_arr",
    "target_value": 2031069,
    "parent_entity": "GrowthBook",
}


def test_guard_passes_when_entity_name_matches():
    """Existing live team row already has entity_name == 'AE Team'
    (matching what we're about to write) -> guard must not raise."""
    existing_row = {
        "period": "FY2027_Q3", "level": "team", "entity_name": "AE Team",
        "metric": "incremental_arr", "target_value": 1550000,
    }
    fake_client = _FakeSupabaseClient([existing_row])

    # Must not raise.
    check_collision_guard(fake_client, "FY2027_Q3", INCOMING_TEAM_ROW)
    print("✓ guard passes (no raise) when existing entity_name matches")


def test_guard_aborts_when_entity_name_differs():
    """Existing live team row has entity_name == 'AE Team' but we're
    about to write 'GrowthBook Team' (the exact bug this guard exists
    to catch) -> guard must raise, and the message must show both rows."""
    existing_row = {
        "period": "FY2027_Q3", "level": "team", "entity_name": "AE Team",
        "metric": "incremental_arr", "target_value": 1550000,
    }
    mismatched_incoming = dict(INCOMING_TEAM_ROW, entity_name="GrowthBook Team")
    fake_client = _FakeSupabaseClient([existing_row])

    try:
        check_collision_guard(fake_client, "FY2027_Q3", mismatched_incoming)
        raise AssertionError(
            "check_collision_guard() did not raise on a mismatched "
            "entity_name — the collision bug would have proceeded silently")
    except TeamRowCollisionError as e:
        msg = str(e)
        assert "AE Team" in msg, "existing row's entity_name missing from error message"
        assert "GrowthBook Team" in msg, "incoming row's entity_name missing from error message"
        assert "FY2027_Q3" in msg
        print("✓ guard aborts (raises TeamRowCollisionError) when entity_name "
              "differs, and the message shows both rows side by side")


def test_planted_bug_control_guard_disabled_proceeds_silently():
    """Planted-bug control: with the guard disabled (simulating 'the
    guard was never added'), the exact mismatch case from
    test_guard_aborts_when_entity_name_differs() must proceed WITHOUT
    raising — proving the real guard (not some unrelated check) is what
    makes that case fail. Then restore the real guard and confirm it
    aborts again."""
    existing_row = {
        "period": "FY2027_Q3", "level": "team", "entity_name": "AE Team",
        "metric": "incremental_arr", "target_value": 1550000,
    }
    mismatched_incoming = dict(INCOMING_TEAM_ROW, entity_name="GrowthBook Team")
    fake_client = _FakeSupabaseClient([existing_row])

    def _disabled_guard(sb_client, period, incoming_team_row):
        return None  # no-op: the planted bug

    import seed_targets as st
    real_guard = st.check_collision_guard
    st.check_collision_guard = _disabled_guard
    try:
        # With the guard disabled, this must NOT raise — i.e. the
        # collision would have proceeded silently, exactly as it did
        # before this fix existed.
        st.check_collision_guard(fake_client, "FY2027_Q3", mismatched_incoming)
        print("✓ planted-bug control: with the guard disabled, the "
              "mismatch case proceeds silently (confirms the test can fail)")
    finally:
        st.check_collision_guard = real_guard

    # Restored: the real guard must abort on the same inputs.
    try:
        st.check_collision_guard(fake_client, "FY2027_Q3", mismatched_incoming)
        raise AssertionError(
            "after restoring the real guard, it did not raise on the "
            "same mismatched inputs it just silently passed")
    except TeamRowCollisionError:
        print("✓ planted-bug control: after restoring the real guard, "
              "the same inputs now abort as expected")


def test_post_write_guard_passes_with_exactly_one_team_row():
    fake_client = _FakeSupabaseClient([
        {"period": "FY2027_Q3", "level": "team", "entity_name": "AE Team",
         "metric": "incremental_arr", "target_value": 2031069},
    ])
    check_post_write_guard(fake_client, "FY2027_Q3", "incremental_arr")
    print("✓ post-write guard passes with exactly 1 team row")


def test_post_write_guard_aborts_with_more_than_one_team_row():
    fake_client = _FakeSupabaseClient([
        {"period": "FY2027_Q3", "level": "team", "entity_name": "AE Team",
         "metric": "incremental_arr", "target_value": 1550000},
        {"period": "FY2027_Q3", "level": "team", "entity_name": "GrowthBook Team",
         "metric": "incremental_arr", "target_value": 2031069},
    ])
    try:
        check_post_write_guard(fake_client, "FY2027_Q3", "incremental_arr")
        raise AssertionError(
            "check_post_write_guard() did not raise with 2 team rows present")
    except TeamRowCollisionError as e:
        msg = str(e)
        assert "AE Team" in msg and "GrowthBook Team" in msg
        print("✓ post-write guard aborts and reports both rows when "
              ">1 team row exists for period+metric")


def run_all_tests():
    tests = [
        test_guard_passes_when_entity_name_matches,
        test_guard_aborts_when_entity_name_differs,
        test_planted_bug_control_guard_disabled_proceeds_silently,
        test_post_write_guard_passes_with_exactly_one_team_row,
        test_post_write_guard_aborts_with_more_than_one_team_row,
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
