#!/usr/bin/env python3
"""
Tests for Phase 3 Forecast Analyses

Critical requirements from spec:
1. week-3 conversion excludes incomplete quarters
2. week-3 conversion returns null (not zero) on insufficient history
3. commit calibration classifies slip separately from loss
4. category churn curve covers all weeks with data
5. analyses return null on thin data, never fabricate

These tests verify the analyses are correct before any proposals are built on them.
"""
import sys
from pathlib import Path
from unittest.mock import Mock, MagicMock, patch

sys.path.insert(0, str(Path(__file__).parent))

from analytics.forecast_analyses import (
    _get_complete_quarters,
    _classify_deal_outcome,
    query_week3_conversion,
    query_commit_outcome_by_week,
    query_commit_calibration
)


def test_week3_conversion_excludes_incomplete_quarters():
    """
    Week-3 conversion must only use quarters with all 13 weeks of data.

    If a quarter has only 10 weeks, it cannot be included in the analysis.
    """
    print("\n[TEST] Week-3 conversion excludes incomplete quarters")

    # _get_complete_quarters now paginates via supabase_client.select_all
    # (the old unpaginated .execute() silently capped at 1,000 rows and saw no
    # complete quarter). Mock that seam; the assertion is unchanged.
    rows = [
        {'fiscal_quarter': 'FY2027 Q1', 'week_of_quarter': w}
        for w in range(1, 11)  # Only 10 weeks
    ] + [
        {'fiscal_quarter': 'FY2027 Q2', 'week_of_quarter': w}
        for w in range(1, 14)  # Complete 13 weeks
    ]

    with patch('supabase_client.select_all', return_value=rows):
        complete = _get_complete_quarters(Mock())

        # Should only include Q2, not Q1
        if 'FY2027 Q1' in complete:
            raise AssertionError(
                f"Incomplete quarter included: FY2027 Q1 has only 10 weeks but was included\n"
                f"Week-3 conversion must exclude quarters without full 13-week data"
            )

        if 'FY2027 Q2' not in complete:
            raise AssertionError(
                f"Complete quarter excluded: FY2027 Q2 has 13 weeks but was excluded"
            )

    print("  ✓ Incomplete quarters correctly excluded")
    print("  ✓ Complete quarters correctly included")


def test_week3_conversion_returns_null_not_zero_on_insufficient_history():
    """
    When insufficient quarters are available, return null fields, not zeros.

    Returning 0 would fabricate data. Returning null signals "we don't know."
    """
    print("\n[TEST] Week-3 conversion returns null (not zero) on insufficient history")

    # Patch _get_complete_quarters to return empty list
    with patch('analytics.forecast_analyses._get_complete_quarters') as mock_get_quarters:
        with patch('analytics.forecast_analyses._load_config') as mock_config:
            mock_get_quarters.return_value = []
            mock_config.return_value = {
                'trailing_quarters_window': 9,
                'basis': 'count',
                'min_evidence_count': 30
            }

            sb = Mock()
            result = query_week3_conversion(sb)

            # Should have error field, not fabricated zeros
            if 'error' not in result:
                raise AssertionError(
                    "Missing error field — should return error when no complete quarters available"
                )

            # Should NOT have trailing_average or implied_coverage as 0
            if result.get('trailing_average') == 0:
                raise AssertionError(
                    "Returned trailing_average = 0 (fabricated data)\n"
                    "Should return null/None on insufficient history, never 0"
                )

            if result.get('implied_coverage_target') == 0:
                raise AssertionError(
                    "Returned implied_coverage_target = 0 (fabricated data)\n"
                    "Should return null/None on insufficient history, never 0"
                )

    print("  ✓ Returns error on insufficient data")
    print("  ✓ Does not fabricate zeros")
    print("  ✓ Null fields signal 'we don't know'")


def test_commit_calibration_classifies_slip_separately_from_loss():
    """
    A deal open past quarter end with a pushed close date is SLIPPED, never LOST.

    Collapsing slip and loss is the exact error Kellogg critiques.
    This test verifies the three-way classification (Won/Slipped/Lost).
    """
    print("\n[TEST] Commit calibration classifies slip separately from loss")

    # Terminal outcome now comes from the deals table (OUTCOME-READ), not the
    # last snapshot row — the backfilled snapshot has no won/lost rows, so a
    # snapshot-based classifier would call every deal SLIPPED. Committed quarter
    # window: FY2027 Q2 = 2026-05-01 .. 2026-07-31.
    q_start, q_end = '2026-05-01', '2026-07-31'
    deals_by_id = {
        # open stage, close pushed to next quarter → SLIPPED (not LOST)
        'test_deal_123': {'stage': 'presentationscheduled',
                          'close_date': '2026-08-15', 'owner_email': 'a@x.com'},
        # terminally lost, closed within quarter → LOST
        'test_deal_456': {'stage': 'closedlost',
                          'close_date': '2026-07-20', 'owner_email': 'a@x.com'},
        # terminally won, closed within quarter → WON
        'test_deal_789': {'stage': 'closedwon',
                          'close_date': '2026-07-25', 'owner_email': 'b@x.com'},
        # terminally won but closed AFTER quarter end → SLIPPED (did not win in-qtr)
        'test_deal_late': {'stage': 'closedwon',
                           'close_date': '2026-08-05', 'owner_email': 'b@x.com'},
    }

    outcome = _classify_deal_outcome('test_deal_123', q_start, q_end, deals_by_id)
    if outcome != 'SLIPPED':
        raise AssertionError(
            f"Expected 'SLIPPED' for deal open past quarter end, got '{outcome}'\n"
            f"A deal still open with pushed close date is SLIPPED, not LOST.\n"
            f"This is the exact error Kellogg critiques — slip and loss must be separate."
        )
    print("  ✓ Deal open past quarter end correctly classified as SLIPPED")

    outcome_lost = _classify_deal_outcome('test_deal_456', q_start, q_end, deals_by_id)
    if outcome_lost != 'LOST':
        raise AssertionError(f"Expected 'LOST' for closed lost deal, got '{outcome_lost}'")
    print("  ✓ Closed lost deal correctly classified as LOST")

    outcome_won = _classify_deal_outcome('test_deal_789', q_start, q_end, deals_by_id)
    if outcome_won != 'WON':
        raise AssertionError(f"Expected 'WON' for closed won deal, got '{outcome_won}'")
    print("  ✓ Closed won deal correctly classified as WON")

    # A win that lands after quarter end did NOT win in the committed quarter.
    outcome_late = _classify_deal_outcome('test_deal_late', q_start, q_end, deals_by_id)
    if outcome_late != 'SLIPPED':
        raise AssertionError(
            f"Expected 'SLIPPED' for a win closing after quarter end, got '{outcome_late}'")
    print("  ✓ Won-but-closed-after-quarter correctly classified as SLIPPED (not WON)")
    print("  ✓ Three-way classification working: Won/Slipped/Lost are distinct")


def test_commit_outcome_by_week_structure():
    """
    query_commit_outcome_by_week returns a per-commit-week outcome table
    (n/won/lost/slipped/win_rate) plus a volume curve — NOT a tag-retention
    curve. It must reach _classify_deal_outcome, never compare forecast_category
    across snapshots.
    """
    print("\n[TEST] commit outcome-by-week structure (not retention)")

    with patch('analytics.forecast_analyses._get_complete_quarters') as mock_get_quarters, \
         patch('analytics.forecast_analyses._load_config') as mock_config, \
         patch('analytics.forecast_analyses._quarter_window_iso') as mock_win, \
         patch('supabase_client.select_all') as mock_select_all:
        mock_get_quarters.return_value = ['FY2027 Q1']
        mock_config.return_value = {'min_evidence_count': 30}
        mock_win.return_value = ('2026-02-01', '2026-04-30')
        mock_select_all.return_value = []  # deals table load

        sb = Mock()
        mock_response = Mock(); mock_response.data = []
        mock_chain = Mock()
        mock_chain.eq = Mock(return_value=mock_chain)
        mock_chain.execute = Mock(return_value=mock_response)
        sb.table = Mock(return_value=Mock(select=Mock(return_value=mock_chain)))

        result = query_commit_outcome_by_week(sb)

    for key in ('by_week', 'volume_by_week', 'per_quarter'):
        if key not in result:
            raise AssertionError(f"Missing {key} in result")
    if 'churn_curve' in result or 'retention_rate' in str(result):
        raise AssertionError("Result still exposes tag-retention shape")
    print("  ✓ outcome-by-week structure present; no retention curve")


def test_analyses_return_null_on_thin_data_never_fabricate():
    """
    All analyses must return null/error on thin data, never fabricate numbers.

    This is the master test: insufficient data = null, not made-up stats.
    """
    print("\n[TEST] Analyses return null on thin data, never fabricate")

    # Test week-3 conversion with empty quarters
    with patch('analytics.forecast_analyses._get_complete_quarters') as mock_quarters:
        with patch('analytics.forecast_analyses._load_config') as mock_config:
            mock_quarters.return_value = []
            mock_config.return_value = {'trailing_quarters_window': 9, 'basis': 'count', 'min_evidence_count': 30}

            sb = Mock()
            w3_result = query_week3_conversion(sb)

            if 'error' not in w3_result:
                if w3_result.get('trailing_average') is not None and w3_result.get('trailing_average') != 0:
                    raise AssertionError(
                        f"Week-3 conversion fabricated data: trailing_average = {w3_result.get('trailing_average')}\n"
                        f"Should return null/error on thin data"
                    )

    print("  ✓ Week-3 conversion returns null on thin data")

    # Test commit outcome-by-week with empty data
    with patch('analytics.forecast_analyses._get_complete_quarters') as mock_quarters:
        mock_quarters.return_value = []

        sb = Mock()
        outcome_result = query_commit_outcome_by_week(sb)

        if 'error' not in outcome_result:
            if outcome_result.get('by_week'):
                raise AssertionError(
                    "Commit outcome-by-week fabricated a table with no quarters"
                )

    print("  ✓ Commit outcome-by-week returns null on thin data")

    # Test commit calibration with no quarters
    with patch('analytics.forecast_analyses._get_complete_quarters') as mock_quarters:
        with patch('analytics.forecast_analyses._load_config') as mock_config:
            mock_quarters.return_value = []
            mock_config.return_value = {'anchor_week': 3, 'claimed_commit_accuracy': 0.90, 'min_evidence_count': 30}

            sb = Mock()
            calib_result = query_commit_calibration(sb)

            if 'error' not in calib_result:
                if calib_result.get('actual_hit_rate') is not None and calib_result.get('breakdown', {}).get('total', 0) == 0:
                    raise AssertionError(
                        "Commit calibration fabricated hit rate with no deals"
                    )

    print("  ✓ Commit calibration returns null on thin data")
    print("  ✓ No analyses fabricate numbers on insufficient data")


def main():
    """Run all forecast analysis tests."""
    print("=" * 70)
    print("FORECAST ANALYSIS TESTS (Phase 3)")
    print("=" * 70)

    tests = [
        test_week3_conversion_excludes_incomplete_quarters,
        test_week3_conversion_returns_null_not_zero_on_insufficient_history,
        test_commit_calibration_classifies_slip_separately_from_loss,
        test_commit_outcome_by_week_structure,
        test_analyses_return_null_on_thin_data_never_fabricate,
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

    print("\n✅ All forecast analysis tests passed")
    print("   Analyses are correct and safe to build proposals on (Phase 4)")
    return 0


if __name__ == '__main__':
    sys.exit(main())
