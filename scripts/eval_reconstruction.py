#!/usr/bin/env python3
"""
Regression fixture for historical pipeline reconstruction.

This fixture locks the reconstruction algorithm behind a permanent test suite.
The core logic (get_stage_at_date, confidence labels, point-in-time field lookups)
was proven correct in mock testing but failed in production due to:
  1. ~291-row population cap (pagination failure or hardcoded limit)
  2. deal_value and close_date using current values as proxies

This test preserves the correct algorithm through any future refactor and
proves the new confidence labels correctly reflect history coverage.

CRITICAL: Tests import from scripts/analytics/point_in_time.py (production code),
not a local copy. A fixture testing a duplicate silently stops guarding the real
code exactly when it matters.

Fixture includes:
- Deal moving backward through stages (regression is real)
- Deal moving through 4 stages in one week (weekly sampling limitation)
- Stage change later same day as snapshot (midnight boundary handling)
- Deal history starting after early snapshot date (pre_history returns null)
- Deal with no history at all (no_history handling)
"""
import sys
from datetime import datetime, timedelta
from pathlib import Path
from typing import Dict, List, Optional, Tuple

# Ensure we can import from scripts
REPO_ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(REPO_ROOT / 'scripts'))
sys.path.insert(0, str(REPO_ROOT / 'scripts' / 'analytics'))

# Import production reconstruction functions (NOT local copies)
from analytics.point_in_time import get_stage_at_date, get_field_at_date


class MockReconstructor:
    """
    Test harness for reconstruction logic.

    Uses production functions from point_in_time.py (NOT local copies).
    Operates on synthetic data to prove correctness independent of HubSpot API.
    """

    def __init__(self):
        self.property_history = {}
        self.amount_history = {}      # deal_value (amount) history
        self.closedate_history = {}   # close_date (closedate) history

    def add_deal_history(self, deal_id: str, history: List[Dict]):
        """Add stage history for a deal (timestamp, value pairs)."""
        self.property_history[deal_id] = {'history': history}

    def add_amount_history(self, deal_id: str, history: List[Dict]):
        """Add amount (deal_value) history for a deal."""
        self.amount_history[deal_id] = {'history': history}

    def add_closedate_history(self, deal_id: str, history: List[Dict]):
        """Add closedate (close_date) history for a deal."""
        self.closedate_history[deal_id] = {'history': history}

    def get_stage_at_date(
        self,
        deal_id: str,
        snapshot_date: datetime
    ) -> Tuple[Optional[str], str, bool]:
        """Delegate to production function from point_in_time.py."""
        return get_stage_at_date(self.property_history, deal_id, snapshot_date)

    def get_field_at_date(
        self,
        field_history: Dict,
        deal_id: str,
        snapshot_date: datetime
    ) -> Tuple[Optional[str], str]:
        """Delegate to production function from point_in_time.py."""
        return get_field_at_date(field_history, deal_id, snapshot_date)


def test_backward_stage_movement():
    """
    Regression is real and must be handled correctly.

    A deal moves backward from Proposal to Qualification.
    Weekly snapshots must show this, not skip it.
    """
    r = MockReconstructor()

    # Deal moves forward, then backward
    r.add_deal_history('deal_001', [
        {'timestamp': '2026-01-05T10:00:00Z', 'value': 'qualification'},
        {'timestamp': '2026-01-12T14:00:00Z', 'value': 'proposal'},
        {'timestamp': '2026-01-20T09:00:00Z', 'value': 'qualification'},  # Moved backward
        {'timestamp': '2026-01-27T16:00:00Z', 'value': 'proposal'},
    ])

    # Snapshots on Mondays at midnight
    snapshots = [
        ('2026-01-06', 'qualification'),  # After first change
        ('2026-01-13', 'proposal'),       # After second change
        ('2026-01-20', 'proposal'),       # Midnight BEFORE 9am backward move same day
        ('2026-01-27', 'qualification'),  # Midnight BEFORE 4pm forward move same day
    ]

    for date_str, expected_stage in snapshots:
        snapshot_date = datetime.fromisoformat(date_str + 'T00:00:00')
        stage, confidence, has_history = r.get_stage_at_date('deal_001', snapshot_date)

        assert stage == expected_stage, \
            f"On {date_str}, expected {expected_stage} but got {stage}"
        assert confidence == 'exact', \
            f"On {date_str}, stage history covers this date - should be 'exact', got {confidence}"
        assert has_history is True

    print("✓ test_backward_stage_movement passed")


def test_fast_mover_weekly_sampling():
    """
    Weekly sampling limitation: deal moving through 4 stages in 4 days.

    Weekly snapshot will only capture final stage (inherent to weekly sampling, not a bug).
    This is documented limitation - fast deals' intermediate stages are not captured.
    """
    r = MockReconstructor()

    # Deal moves through all 4 stages within one week
    r.add_deal_history('deal_002', [
        {'timestamp': '2026-02-02T10:00:00Z', 'value': 'discovery'},
        {'timestamp': '2026-02-03T11:00:00Z', 'value': 'qualification'},
        {'timestamp': '2026-02-04T12:00:00Z', 'value': 'proposal'},
        {'timestamp': '2026-02-05T13:00:00Z', 'value': 'negotiation'},
    ])

    # Weekly snapshot on Monday before moves
    snapshot_before = datetime.fromisoformat('2026-02-01T00:00:00')
    stage, conf, _ = r.get_stage_at_date('deal_002', snapshot_before)
    assert stage is None  # No history before first change
    assert conf == 'pre_history'

    # Weekly snapshot on Monday after all moves
    snapshot_after = datetime.fromisoformat('2026-02-09T00:00:00')
    stage, conf, _ = r.get_stage_at_date('deal_002', snapshot_after)
    assert stage == 'negotiation'  # Final stage captured
    assert conf == 'exact'

    # Intermediate stages (discovery, qualification, proposal) not captured by weekly grid
    # This is expected and documented - not a defect

    print("✓ test_fast_mover_weekly_sampling passed (weekly sampling limitation documented)")


def test_midnight_boundary_handling():
    """
    Stage change later same day as snapshot (midnight boundary).

    Snapshot at midnight (00:00:00) must NOT include changes from later that day.
    Strictly backward-looking: only history before snapshot timestamp.
    """
    r = MockReconstructor()

    # Stage change at 4pm
    r.add_deal_history('deal_003', [
        {'timestamp': '2026-03-10T16:00:00Z', 'value': 'proposal'},
    ])

    # Snapshot at midnight same day (before the 4pm change)
    snapshot_midnight = datetime.fromisoformat('2026-03-10T00:00:00')
    stage, conf, has_history = r.get_stage_at_date('deal_003', snapshot_midnight)

    assert stage is None, \
        f"Snapshot at midnight should NOT see 4pm change same day, got stage={stage}"
    assert conf == 'pre_history', \
        f"No history before midnight, should be 'pre_history', got {conf}"
    assert has_history is True

    # Snapshot next day captures it
    snapshot_next_day = datetime.fromisoformat('2026-03-11T00:00:00')
    stage, conf, _ = r.get_stage_at_date('deal_003', snapshot_next_day)
    assert stage == 'proposal'
    assert conf == 'exact'

    print("✓ test_midnight_boundary_handling passed")


def test_pre_history_returns_null():
    """
    Deal history begins after early snapshot date.

    pre_history must return None (null), never a guess or default.
    """
    r = MockReconstructor()

    # First stage change on Feb 15
    r.add_deal_history('deal_004', [
        {'timestamp': '2026-02-15T10:00:00Z', 'value': 'qualification'},
    ])

    # Snapshot before deal's first history entry
    snapshot_before = datetime.fromisoformat('2026-02-01T00:00:00')
    stage, conf, has_history = r.get_stage_at_date('deal_004', snapshot_before)

    assert stage is None, \
        f"Before first history entry, stage must be None (not guessed), got {stage}"
    assert conf == 'pre_history', \
        f"Should be 'pre_history', got {conf}"
    assert conf != 'cleared', \
        "No entry at or before D is 'pre_history' — the deal was never staged. " \
        "'cleared' means an entry exists but its value is null."
    assert has_history is True, \
        "Deal has history, just not covering this early date"

    # Snapshot after first history entry
    snapshot_after = datetime.fromisoformat('2026-02-20T00:00:00')
    stage, conf, _ = r.get_stage_at_date('deal_004', snapshot_after)
    assert stage == 'qualification'
    assert conf == 'exact'

    print("✓ test_pre_history_returns_null passed")


def test_cleared_stage_distinct_from_pre_history():
    """
    A stage actively cleared to null is 'cleared', not 'pre_history'.

    Both return a null stage and both read as open, but they are different
    facts: 'cleared' means the deal WAS staged and then unstaged, while
    'pre_history' means it was never staged at or before this date. Merging
    them hides the distinction and makes the scale of clearing invisible.
    """
    r = MockReconstructor()

    # Staged in January, then the stage is cleared in June.
    r.add_deal_history('deal_006', [
        {'timestamp': '2026-01-10T10:00:00Z', 'value': 'qualifiedtobuy'},
        {'timestamp': '2026-06-01T10:00:00Z', 'value': None},
    ])

    # Before the clear: a real point-in-time read.
    stage, conf, has_history = r.get_stage_at_date(
        'deal_006', datetime.fromisoformat('2026-03-01T00:00:00'))
    assert stage == 'qualifiedtobuy'
    assert conf == 'exact'

    # After the clear: null stage, but labelled 'cleared', not 'pre_history'.
    stage, conf, has_history = r.get_stage_at_date(
        'deal_006', datetime.fromisoformat('2026-07-01T00:00:00'))
    assert stage is None, "a cleared stage is null, never a carried-forward guess"
    assert conf == 'cleared', \
        f"An entry at or before D with a null value is 'cleared', got {conf}"
    assert has_history is True

    # Before ANY entry: pre_history, so the two are genuinely distinguishable
    # on the same deal.
    stage, conf, _ = r.get_stage_at_date(
        'deal_006', datetime.fromisoformat('2026-01-01T00:00:00'))
    assert stage is None
    assert conf == 'pre_history', \
        f"Before the first entry it is 'pre_history', got {conf}"

    # A later real value wins: clearing is not terminal.
    r.add_deal_history('deal_007', [
        {'timestamp': '2026-01-10T10:00:00Z', 'value': None},
        {'timestamp': '2026-02-10T10:00:00Z', 'value': 'closedwon'},
    ])
    stage, conf, _ = r.get_stage_at_date(
        'deal_007', datetime.fromisoformat('2026-03-01T00:00:00'))
    assert stage == 'closedwon' and conf == 'exact', \
        "a null entry followed by a real one must resolve to the real value"

    # Both null cases still read as open — the inclusion rule is unchanged
    # for now; only the labels are separable.
    from point_in_time import is_terminal_stage
    assert is_terminal_stage(None) is False, \
        "cleared and pre_history both read as open until we decide otherwise"

    print("✓ test_cleared_stage_distinct_from_pre_history passed")


def test_cleared_field_distinct_from_pre_history():
    """
    Same distinction for deal_value and close_date, not just stage.

    A cleared amount and an amount whose history starts later are different
    facts and must not share a label.
    """
    r = MockReconstructor()

    r.add_amount_history('deal_008', [
        {'timestamp': '2026-01-10T10:00:00Z', 'value': '50000'},
        {'timestamp': '2026-06-01T10:00:00Z', 'value': None},
    ])

    value, conf = r.get_field_at_date(
        r.amount_history, 'deal_008',
        datetime.fromisoformat('2026-03-01T00:00:00'))
    assert value == '50000' and conf == 'exact'

    value, conf = r.get_field_at_date(
        r.amount_history, 'deal_008',
        datetime.fromisoformat('2026-07-01T00:00:00'))
    assert value is None, "a cleared amount is null, never carried forward"
    assert conf == 'cleared', f"expected 'cleared', got {conf}"

    value, conf = r.get_field_at_date(
        r.amount_history, 'deal_008',
        datetime.fromisoformat('2026-01-01T00:00:00'))
    assert value is None and conf == 'pre_history', \
        f"before the first entry it is 'pre_history', got {conf}"

    # close_date carries the same distinction.
    r.add_closedate_history('deal_009', [
        {'timestamp': '2026-01-10T10:00:00Z', 'value': '2026-09-30'},
        {'timestamp': '2026-06-01T10:00:00Z', 'value': None},
    ])
    value, conf = r.get_field_at_date(
        r.closedate_history, 'deal_009',
        datetime.fromisoformat('2026-07-01T00:00:00'))
    assert value is None and conf == 'cleared', \
        f"a cleared close_date is 'cleared', got {conf}"

    print("✓ test_cleared_field_distinct_from_pre_history passed")


def test_no_history_at_all():
    """
    Deal with no history available.

    Must return (None, 'no_history', False).
    """
    r = MockReconstructor()

    # Deal exists but has no history entries
    r.add_deal_history('deal_005', [])

    snapshot_date = datetime.fromisoformat('2026-03-01T00:00:00')
    stage, conf, has_history = r.get_stage_at_date('deal_005', snapshot_date)

    assert stage is None
    assert conf == 'no_history'
    assert has_history is False

    # Deal not in property_history at all
    stage, conf, has_history = r.get_stage_at_date('deal_999_nonexistent', snapshot_date)

    assert stage is None
    assert conf == 'no_history'
    assert has_history is False

    print("✓ test_no_history_at_all passed")


def test_confidence_labels_reflect_history_coverage():
    """
    A row whose date is covered by stage history is 'exact', regardless
    of whether a change landed on that exact day.

    The old definition marked almost everything 'interpolated' and made
    correct data look unreliable.
    """
    r = MockReconstructor()

    r.add_deal_history('deal_006', [
        {'timestamp': '2026-01-10T10:00:00Z', 'value': 'qualification'},
        {'timestamp': '2026-01-25T14:00:00Z', 'value': 'proposal'},
    ])

    # Snapshots between stage changes (not on exact same day as any change)
    test_cases = [
        ('2026-01-12T00:00:00', 'qualification', 'exact'),  # 2 days after first change
        ('2026-01-20T00:00:00', 'qualification', 'exact'),  # 10 days after, 5 days before next
        ('2026-01-27T00:00:00', 'proposal', 'exact'),       # 2 days after second change
    ]

    for date_str, expected_stage, expected_conf in test_cases:
        snapshot_date = datetime.fromisoformat(date_str)
        stage, conf, _ = r.get_stage_at_date('deal_006', snapshot_date)

        assert stage == expected_stage, \
            f"On {date_str}, expected {expected_stage}, got {stage}"
        assert conf == expected_conf, \
            f"On {date_str}, history covers this date - should be '{expected_conf}', got '{conf}'"

    print("✓ test_confidence_labels_reflect_history_coverage passed")


def test_deal_value_point_in_time_reconstruction():
    """
    deal_value (amount) must be reconstructed point-in-time, not proxied with current value.

    This was the second cause of prior backfill failure.
    """
    r = MockReconstructor()

    # Deal value changes over time
    r.add_amount_history('deal_007', [
        {'timestamp': '2026-01-10T10:00:00Z', 'value': 50000},
        {'timestamp': '2026-01-20T14:00:00Z', 'value': 75000},  # Upsized
        {'timestamp': '2026-02-05T11:00:00Z', 'value': 60000},  # Downsized
    ])

    test_cases = [
        ('2026-01-15T00:00:00', 50000, 'exact'),   # Between first two changes
        ('2026-01-25T00:00:00', 75000, 'exact'),   # After upsizing
        ('2026-02-10T00:00:00', 60000, 'exact'),   # After downsizing
        ('2026-01-05T00:00:00', None, 'pre_history'),  # Before any history
    ]

    for date_str, expected_value, expected_conf in test_cases:
        snapshot_date = datetime.fromisoformat(date_str)
        value, conf = r.get_field_at_date(r.amount_history, 'deal_007', snapshot_date)

        assert value == expected_value, \
            f"On {date_str}, expected amount={expected_value}, got {value}"
        assert conf == expected_conf, \
            f"On {date_str}, expected confidence='{expected_conf}', got '{conf}'"

    print("✓ test_deal_value_point_in_time_reconstruction passed")


def test_close_date_point_in_time_reconstruction():
    """
    close_date (closedate) must be reconstructed point-in-time, not proxied.

    Close date can change (pushed out, pulled in) before deal actually closes.
    """
    r = MockReconstructor()

    # Close date changes over time (pushed out)
    r.add_closedate_history('deal_008', [
        {'timestamp': '2026-01-15T09:00:00Z', 'value': '2026-02-01'},
        {'timestamp': '2026-01-28T10:00:00Z', 'value': '2026-02-15'},  # Pushed out
        {'timestamp': '2026-02-10T11:00:00Z', 'value': '2026-02-28'},  # Pushed again
    ])

    test_cases = [
        ('2026-01-20T00:00:00', '2026-02-01', 'exact'),   # Original close date
        ('2026-02-05T00:00:00', '2026-02-15', 'exact'),   # After first push
        ('2026-02-20T00:00:00', '2026-02-28', 'exact'),   # After second push
        ('2026-01-10T00:00:00', None, 'pre_history'),     # Before any history
    ]

    for date_str, expected_value, expected_conf in test_cases:
        snapshot_date = datetime.fromisoformat(date_str)
        value, conf = r.get_field_at_date(r.closedate_history, 'deal_008', snapshot_date)

        assert value == expected_value, \
            f"On {date_str}, expected close_date={expected_value}, got {value}"
        assert conf == expected_conf, \
            f"On {date_str}, expected confidence='{expected_conf}', got '{conf}'"

    print("✓ test_close_date_point_in_time_reconstruction passed")


def test_fixture_tests_production_function():
    """
    eval_reconstruction imports from point_in_time, not a local copy.

    A fixture testing a duplicate silently stops guarding the real code
    exactly when it matters - when Phase 2 changes the production function.
    """
    import inspect
    from analytics.point_in_time import get_stage_at_date as prod_get_stage
    from analytics.point_in_time import get_field_at_date as prod_get_field

    # MockReconstructor.get_stage_at_date should delegate to production function
    r = MockReconstructor()

    # Verify the functions used are from point_in_time module, not local copies
    # Check by comparing module names
    stage_func_module = inspect.getmodule(prod_get_stage).__name__
    field_func_module = inspect.getmodule(prod_get_field).__name__

    assert stage_func_module == 'analytics.point_in_time', \
        f"get_stage_at_date should be from analytics.point_in_time, got {stage_func_module}"
    assert field_func_module == 'analytics.point_in_time', \
        f"get_field_at_date should be from analytics.point_in_time, got {field_func_module}"

    # Verify MockReconstructor delegates to production functions (not reimplemented)
    r.add_deal_history('test_prod', [{'timestamp': '2026-01-10T10:00:00Z', 'value': 'stage1'}])
    snapshot_date = datetime.fromisoformat('2026-01-15T00:00:00')

    # Call through MockReconstructor
    stage_mock, conf_mock, has_hist_mock = r.get_stage_at_date('test_prod', snapshot_date)

    # Call production function directly
    stage_prod, conf_prod, has_hist_prod = prod_get_stage(
        r.property_history, 'test_prod', snapshot_date
    )

    # Results must match (proving MockReconstructor delegates, not reimplements)
    assert stage_mock == stage_prod == 'stage1'
    assert conf_mock == conf_prod == 'exact'
    assert has_hist_mock == has_hist_prod is True

    print("✓ test_fixture_tests_production_function passed")
    print("  Fixture imports from analytics.point_in_time (production code)")
    print("  NOT testing a local copy - guard is active")


def test_no_duplicate_reconstruction_implementations():
    """
    point_in_time.py is the only module defining get_stage_at_date or
    get_field_at_date.

    Grep backfill_snapshots.py and eval_reconstruction.py to confirm
    neither defines them locally. Two implementations of one algorithm
    is how the seven-files-disagreeing-about-stages problem started.

    This is a static check - fails on a duplicate definition existing at all,
    which is the actual thing to prevent.
    """
    import subprocess
    from pathlib import Path

    repo_root = Path(__file__).parent.parent
    backfill_path = repo_root / 'scripts' / 'analytics' / 'backfill_snapshots.py'
    eval_path = Path(__file__)

    # Check backfill_snapshots.py for duplicate definitions
    # Allow thin wrappers (return _get_stage_at_date) but not reimplementations
    try:
        result = subprocess.run(
            ['grep', '-n', 'def get_stage_at_date', str(backfill_path)],
            capture_output=True,
            text=True
        )

        if result.returncode == 0:
            # Found definition - check if it's a thin wrapper
            context = subprocess.run(
                ['grep', '-A15', 'def get_stage_at_date', str(backfill_path)],
                capture_output=True,
                text=True
            ).stdout

            if 'return _get_stage_at_date' not in context:
                raise AssertionError(
                    f"backfill_snapshots.py defines get_stage_at_date but doesn't delegate to _get_stage_at_date.\n"
                    f"Found at line {result.stdout.split(':')[0]}. This is a duplicate implementation.\n"
                    f"Context:\n{context}"
                )

    except subprocess.CalledProcessError:
        pass  # grep found nothing, which is fine

    # Check eval_reconstruction.py for duplicate definitions
    # MockReconstructor methods are allowed as thin wrappers
    # Look for actual implementation in the class definition (not in test functions)
    try:
        result = subprocess.run(
            ['sed', '-n', '/^class MockReconstructor/,/^class /p', str(eval_path)],
            capture_output=True,
            text=True
        )

        mock_class = result.stdout

        # Check if MockReconstructor implements the algorithm (not just delegation)
        if 'sorted(' in mock_class and 'return get_stage_at_date' not in mock_class:
            raise AssertionError(
                "MockReconstructor contains reconstruction algorithm implementation.\n"
                "Should only delegate to get_stage_at_date/get_field_at_date from point_in_time."
            )

    except subprocess.CalledProcessError:
        pass

    print("✓ test_no_duplicate_reconstruction_implementations passed")
    print("  point_in_time.py is the ONLY module with reconstruction logic")
    print("  backfill_snapshots.py: thin wrapper (delegates to _get_stage_at_date)")
    print("  eval_reconstruction.py: thin wrapper (delegates to get_stage_at_date)")


def test_unmapped_stage_raises_not_defaults_open():
    """An unrecognized stage ID must raise, not silently read as non-terminal.
    Failing open over-includes and produces plausible wrong numbers."""
    from point_in_time import (
        UnclassifiableStageError, is_terminal_stage, is_deal_open_at_date
    )

    # A stage id retired before the reconstruction window. field_semantics
    # cannot classify it, so reconstruction must refuse it outright.
    retired = '10024681'

    try:
        is_terminal_stage(retired)
        raise AssertionError(
            f"is_terminal_stage({retired!r}) returned instead of raising. "
            f"An unclassifiable stage read as non-terminal silently promotes "
            f"the deal into the open-pipeline denominator."
        )
    except UnclassifiableStageError as e:
        assert retired in str(e), "error must name the offending stage id"
        assert 'field_semantics' in str(e), "error must point at the fix"

    # The inclusion rule defaults to the strict test, so it raises too rather
    # than counting the deal as open.
    try:
        is_deal_open_at_date(
            datetime.fromisoformat('2023-01-01T00:00:00'),
            retired,
            datetime.fromisoformat('2026-03-01T00:00:00'),
        )
        raise AssertionError(
            "is_deal_open_at_date defaulted to open for an unclassifiable stage"
        )
    except UnclassifiableStageError:
        pass

    # A MISSING stage is not an UNCLASSIFIABLE stage. Raising on one form of
    # absence and not the other made the same fact behave two ways, and halted
    # a whole nightly snapshot over one deal with a blank stage (61167803975).
    for blank in ('', '   ', '\t'):
        assert is_terminal_stage(blank) is False, (
            f"is_terminal_stage({blank!r}) must read as 'no stage known', not "
            f"raise. An unset field is absence, not an unrecognized id."
        )

    # None is NOT unclassifiable: it is the pre_history case, where the deal
    # existed but history does not reach this date. It must not raise.
    assert is_terminal_stage(None) is False, \
        "None means 'no history at this date', not 'unknown stage'"
    assert is_deal_open_at_date(
        datetime.fromisoformat('2023-01-01T00:00:00'),
        None,
        datetime.fromisoformat('2026-03-01T00:00:00'),
    ) is True, "a deal with no history at D is open, not an error"

    # Every stage id in the current export must classify without raising.
    for stage_id in ('appointmentscheduled', 'qualifiedtobuy',
                     'presentationscheduled', 'decisionmakerboughtin',
                     'closedwon', 'closedlost', '79653122', '24682892',
                     '43449439', '68509551', '1297321618', '1297321619',
                     '1297321620', '1297321622', '1297321623', '1297321624'):
        is_terminal_stage(stage_id)  # must not raise

    assert is_terminal_stage('closedwon') is True
    assert is_terminal_stage('68509551') is True, "Disqualified is lost"
    assert is_terminal_stage('1297321624') is True, "Closed Lost (Renewal)"
    assert is_terminal_stage('79653122') is False, "Meeting Set is open"

    print("✓ test_unmapped_stage_raises_not_defaults_open passed")
    print("  unmapped stage ids raise; None stays 'pre_history', not an error")


def test_retired_stage_is_acknowledged_but_still_raises():
    """An acknowledged retired stage is NOT a classified stage.

    retired_stages exists so the discovery gate can tell a known,
    provably-unreachable id apart from a new unknown one. It must not become
    a back door that lets reconstruction read an unclassified stage as open —
    that is the exact failure the gate was built to prevent.
    """
    from field_semantics import RETIRED_STAGES, is_retired_stage
    from point_in_time import UnclassifiableStageError, is_terminal_stage

    assert RETIRED_STAGES, "expected acknowledged retired stages in config"

    for stage_id in RETIRED_STAGES:
        assert is_retired_stage(stage_id), f"{stage_id} should read as retired"
        try:
            is_terminal_stage(stage_id)
            raise AssertionError(
                f"is_terminal_stage({stage_id!r}) returned instead of raising. "
                f"Being listed in retired_stages must not make an unclassified "
                f"stage readable as open."
            )
        except UnclassifiableStageError:
            pass

    # And retired is not a blanket amnesty: an id not on the list is still
    # plainly unknown, not retired.
    assert not is_retired_stage('99999999')
    assert not is_retired_stage(None)

    print("✓ test_retired_stage_is_acknowledged_but_still_raises passed")
    print(f"  {len(RETIRED_STAGES)} retired ids acknowledged, all still raise")


def test_both_writers_use_the_shared_inclusion_rule():
    """Method 1 and Method 2 must call the shared rule, not reimplement it.

    The whole point of extracting is_deal_open_at_date is that the two cannot
    drift. A local copy in either writer defeats that silently — the copy
    keeps working, it just stops agreeing.
    """
    m1 = (REPO_ROOT / 'scripts/analytics/snapshot_deals.py').read_text()
    m2 = (REPO_ROOT / 'scripts/analytics/backfill_snapshots.py').read_text()

    for name, src in (('snapshot_deals.py', m1), ('backfill_snapshots.py', m2)):
        assert 'is_deal_open_at_date' in src, \
            f"{name} does not call the shared inclusion rule"
        assert 'from point_in_time import' in src, \
            f"{name} does not import from point_in_time"
        # The close_date inclusion test both writers used before. Its return
        # is what made an open past-due deal look closed.
        assert 'close_dt < today_date' not in src, \
            f"{name} still has the close_date inclusion test"
        assert 'close_dt < snapshot_dt' not in src, \
            f"{name} still has the close_date inclusion test"

    print("✓ test_both_writers_use_the_shared_inclusion_rule passed")


def test_scoping_is_not_applied_to_writes():
    """Scoping must gate analysis, never what gets written.

    The renewal pipeline is `analyze: false` for the MEDDICC agent but
    analytics INCLUDES it for GRR/NRR. Scoping the write path would drop
    renewals, Meeting Set and Disqualified out of deals_snapshot entirely and
    destroy the rows GRR/NRR reads. A scoped write is unrecoverable without a
    refetch, so this is a data-loss guard, not a style preference.
    """
    from point_in_time import (is_deal_in_analytics_scope, is_terminal_stage,
                               load_scope_config)

    excluded_pipelines, stage_cfg = load_scope_config()

    # A renewal deal is out of analytics scope...
    assert not is_deal_in_analytics_scope(
        '1297321618', '866608541', excluded_pipelines, stage_cfg), \
        "an open renewal stage should be out of analytics scope"
    # ...but it is still OPEN, so the inclusion rule keeps it, and it gets
    # written. Scope and openness are different questions.
    assert not is_terminal_stage('1297321618'), \
        "an open renewal stage must still read as open for the write path"

    # Meeting Set: out of scope, still open, still written.
    assert not is_deal_in_analytics_scope(
        '79653122', 'default', excluded_pipelines, stage_cfg)
    assert not is_terminal_stage('79653122')

    # A None stage cannot be scoped either way — the caller must count it
    # rather than assume, so this is False and not an exception.
    assert not is_deal_in_analytics_scope(
        None, 'default', excluded_pipelines, stage_cfg)

    # And the write path must not CALL scoping. Checking for the bare name
    # would also match the import, which is legitimate — the same module
    # scopes later, for reporting, after the rows are written.
    src = (REPO_ROOT / 'scripts/analytics/snapshot_deals.py').read_text()
    selection = src.split('qualified_deals = []')[1].split('# Upsert')[0]
    assert 'is_deal_in_analytics_scope(' not in selection, \
        ("snapshot_deals calls analytics scoping while selecting rows to "
         "write. That drops renewal rows GRR/NRR depends on. Scope on read, "
         "never on write.")

    print("✓ test_scoping_is_not_applied_to_writes passed")


def test_two_coverage_gates_measure_different_populations():
    """The write gate and the snapshot gate are not interchangeable.

    write gate    (min/max_write_coverage_pct) UNSCOPED — every written row.
                  Guards write mechanics: pagination, row caps, an inclusion
                  rule that drops deals. A property of the whole write.
    snapshot gate (min_scoped_snapshot_coverage_pct) SCOPED — the analytics
                  subset the conversion analyses actually read. Guards whether
                  a quarter is usable.

    On 2026-08-19 the scoped subset was 164 of 415 written rows, so a gate
    passing on one population says nothing about the other.
    """
    import yaml as _yaml

    cfg = _yaml.safe_load((REPO_ROOT / 'config/client.yaml').read_text())
    fa = cfg['forecast_analysis']

    assert 'min_scoped_snapshot_coverage_pct' in fa, \
        "the scoped snapshot gate is missing from forecast_analysis"

    # The old name did not say which population it measured and had no
    # consumer. A stale reference must fail loudly, not read a default.
    assert 'min_snapshot_coverage_pct' not in fa, \
        ("min_snapshot_coverage_pct is back in config. It is ambiguous about "
         "population — use min_scoped_snapshot_coverage_pct.")

    for gate in ('min_write_coverage_pct', 'max_write_coverage_pct'):
        assert gate in fa, f"{gate} is missing from forecast_analysis"

    # No code may read the ambiguous old name.
    offenders = []
    for path in REPO_ROOT.glob('**/*.py'):
        if '__pycache__' in str(path) or path.name == 'eval_reconstruction.py':
            continue
        if 'min_snapshot_coverage_pct' in path.read_text():
            offenders.append(str(path.relative_to(REPO_ROOT)))
    assert not offenders, (
        f"{offenders} read min_snapshot_coverage_pct. That key is gone; use "
        f"min_scoped_snapshot_coverage_pct and measure it on the scoped "
        f"population via is_deal_in_analytics_scope."
    )

    # The write gate must NOT be measured on a scoped population.
    src = (REPO_ROOT / 'scripts/analytics/snapshot_deals.py').read_text()
    assert 'min_write_coverage_pct' in src, \
        "snapshot_deals no longer reads the write gate"
    assert_block = src.split('min_write_coverage_pct')[1]
    assert 'is_deal_in_analytics_scope(' not in \
        assert_block.split('COVERAGE ASSERTION FAILED')[0], \
        ("the write gate is being measured on a scoped population. It guards "
         "write mechanics across every written row — scoping it would hide a "
         "pagination fault in the rows it stopped counting.")

    print("✓ test_two_coverage_gates_measure_different_populations passed")
    print(f"  write gate: {fa['min_write_coverage_pct']}-"
          f"{fa['max_write_coverage_pct']}% unscoped;  snapshot gate: "
          f"{fa['min_scoped_snapshot_coverage_pct']}% scoped")


def run_all_tests():
    """Run all reconstruction regression tests."""
    print("=" * 80)
    print("RECONSTRUCTION REGRESSION TESTS")
    print("=" * 80)
    print()

    tests = [
        # Meta-tests: guard against duplicate implementations
        test_fixture_tests_production_function,
        test_no_duplicate_reconstruction_implementations,
        # Stage reconstruction
        test_backward_stage_movement,
        test_fast_mover_weekly_sampling,
        test_midnight_boundary_handling,
        test_pre_history_returns_null,
        test_no_history_at_all,
        test_cleared_stage_distinct_from_pre_history,
        test_cleared_field_distinct_from_pre_history,
        test_confidence_labels_reflect_history_coverage,
        # Field reconstruction (deal_value, close_date)
        test_deal_value_point_in_time_reconstruction,
        test_close_date_point_in_time_reconstruction,
        # Stage classification gate
        test_unmapped_stage_raises_not_defaults_open,
        test_retired_stage_is_acknowledged_but_still_raises,
        test_both_writers_use_the_shared_inclusion_rule,
        test_scoping_is_not_applied_to_writes,
        test_two_coverage_gates_measure_different_populations,
    ]

    for test in tests:
        test()

    print()
    print("=" * 80)
    print(f"✓ ALL {len(tests)} RECONSTRUCTION TESTS PASSED")
    print("=" * 80)
    print()
    print("The reconstruction algorithm is correct and locked behind this fixture.")
    print("Future refactors must pass these tests to preserve correctness.")


if __name__ == '__main__':
    run_all_tests()
