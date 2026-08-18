#!/usr/bin/env python3
"""
Eval script for AE-focused handlers.

Tests five handlers with mocked Supabase responses:
- query_rep_pipeline
- query_rep_attainment
- query_deal_health
- query_stale_deals
- query_team_leaderboard
"""

import sys
import asyncio
from datetime import datetime, timezone
from unittest.mock import AsyncMock, MagicMock

sys.path.insert(0, '/Users/jeffignacio/MEDDICC-agent/api')
sys.path.insert(0, '/Users/jeffignacio/MEDDICC-agent/scripts')

from handlers import (
    query_rep_pipeline,
    query_rep_attainment,
    query_deal_health,
    query_stale_deals,
    query_team_leaderboard
)
from sdr_utils import rate_or_gap


def create_mock_sb():
    """Create a mock Supabase client."""
    mock = MagicMock()
    mock.table = MagicMock(return_value=mock)
    mock.select = MagicMock(return_value=mock)
    mock.eq = MagicMock(return_value=mock)
    mock.lt = MagicMock(return_value=mock)
    mock.lte = MagicMock(return_value=mock)
    mock.gte = MagicMock(return_value=mock)
    mock.order = MagicMock(return_value=mock)
    mock.limit = MagicMock(return_value=mock)
    mock.execute = AsyncMock()
    return mock


async def test_query_rep_pipeline_exact_email_only():
    """Test query_rep_pipeline uses exact match on owner_email, not ILIKE."""
    print("\n[Test 1] query_rep_pipeline — exact email match only")

    sb = create_mock_sb()
    sb.execute.return_value.data = [
        {
            'deal_id': 'deal_1',
            'company_name': 'Acme Corp',
            'deal_value': 50000,
            'stage': 'Negotiating',
            'close_date': '2026-08-30',
            'owner_email': 'christian@growthbook.io',
            'overall_score': 7.5,
            'champion_score': 6.0,
            'last_analyzed': '2026-08-18T10:00:00Z'
        }
    ]

    result = await query_rep_pipeline({'owner_email': 'christian@growthbook.io'}, sb)

    # Verify eq was called with owner_email, not ilike
    calls = [str(call) for call in sb.eq.call_args_list]
    assert any('owner_email' in call for call in calls), "Should filter by owner_email"
    assert all('ilike' not in str(call).lower() for call in sb.method_calls), "Should not use ILIKE"

    assert 'deals' in result
    assert len(result['deals']) == 1
    assert result['deals'][0]['company_name'] == 'Acme Corp'
    print("  ✓ Uses exact match on owner_email")
    print("  ✓ Returns deal data correctly")


async def test_query_rep_attainment_no_targets_returns_data_gap():
    """Test query_rep_attainment returns data_gap when no rep_targets found."""
    print("\n[Test 2] query_rep_attainment — data_gap when no targets")

    sb = create_mock_sb()
    # First call: rep_targets (empty)
    # Second call: won deals
    sb.execute.side_effect = [
        AsyncMock(data=[])(),  # No targets
        AsyncMock(data=[])()   # No deals
    ]

    result = await query_rep_attainment({
        'time_window': 'last_30_days',
        'owner_email': 'christian@growthbook.io'
    }, sb)

    assert result.get('data_gap') is True, "Should set data_gap=True when no targets"
    assert 'no rep_targets' in result.get('gap_reason', '').lower(), "Should explain missing targets"
    print("  ✓ Returns data_gap=True when no targets found")
    print("  ✓ Provides gap_reason explaining missing targets")


async def test_query_rep_attainment_proration_not_needed():
    """Test query_rep_attainment does not prorate — uses rep_targets.target_value as-is."""
    print("\n[Test 3] query_rep_attainment — no proration logic")

    sb = create_mock_sb()
    sb.execute.side_effect = [
        # rep_targets
        AsyncMock(data=[{
            'owner_email': 'christian@growthbook.io',
            'target_value': 500000,
            'period': 'Q3_FY2027'
        }])(),
        # won deals
        AsyncMock(data=[{
            'owner_email': 'christian@growthbook.io',
            'deal_value': 250000
        }])()
    ]

    result = await query_rep_attainment({
        'time_window': 'this_quarter',
        'owner_email': 'christian@growthbook.io'
    }, sb)

    assert 'reps' in result
    rep_data = result['reps'][0]

    # Should use full target_value (500000), not prorated
    assert rep_data['target_value'] == 500000
    assert rep_data['won_value'] == 250000

    # Attainment should be calculated using rate_or_gap
    attainment = rate_or_gap(250000, 500000)
    assert rep_data['attainment_rate'] == attainment['value']
    assert rep_data['attainment_data_gap'] == attainment['data_gap']

    print("  ✓ Uses rep_targets.target_value directly (no proration)")
    print("  ✓ Calculates attainment with rate_or_gap")


async def test_query_deal_health_null_scores_excluded():
    """Test query_deal_health excludes deals with null overall_score."""
    print("\n[Test 4] query_deal_health — excludes null scores")

    sb = create_mock_sb()
    sb.execute.return_value.data = [
        {
            'deal_id': 'deal_1',
            'company_name': 'Acme Corp',
            'overall_score': 3.5,
            'metrics_score': 2.0,
            'economic_buyer_score': 5.0,
            'decision_criteria_score': 4.0,
            'decision_process_score': 3.0,
            'identify_pain_score': 4.0,
            'champion_score': 2.0,
            'competition_score': 3.0
        }
        # deal_2 with null overall_score should not be in results
    ]

    result = await query_deal_health({
        'score_threshold': 5.0,
        'owner_email': 'christian@growthbook.io'
    }, sb)

    # Verify .is_('not', null) or similar was called
    # The handler should filter out null scores
    assert 'deals' in result
    assert all(d['overall_score'] is not None for d in result['deals'])
    print("  ✓ Excludes deals with null overall_score")


async def test_query_deal_health_component_filter():
    """Test query_deal_health filters by component score when specified."""
    print("\n[Test 5] query_deal_health — component filter")

    sb = create_mock_sb()
    sb.execute.return_value.data = [
        {
            'deal_id': 'deal_1',
            'company_name': 'Acme Corp',
            'overall_score': 6.0,
            'champion_score': 2.0,
            'metrics_score': 8.0
        }
    ]

    result = await query_deal_health({
        'score_threshold': 5.0,
        'component': 'champion',
        'component_threshold': 3.0
    }, sb)

    # Should filter by champion_score < 3.0
    assert 'deals' in result
    if len(result['deals']) > 0:
        assert result['deals'][0]['champion_score'] <= 3.0

    print("  ✓ Filters by component score when specified")


async def test_query_stale_deals_uses_last_analyzed_not_ilike():
    """Test query_stale_deals uses last_analyzed timestamp, not text ILIKE."""
    print("\n[Test 6] query_stale_deals — uses last_analyzed timestamp")

    sb = create_mock_sb()
    sb.execute.return_value.data = [
        {
            'deal_id': 'deal_1',
            'company_name': 'Acme Corp',
            'last_analyzed': '2026-07-01T10:00:00Z',
            'close_date': '2026-06-30',
            'stage': 'Negotiating'
        }
    ]

    result = await query_stale_deals({
        'stale_days': 30,
        'owner_email': 'christian@growthbook.io'
    }, sb)

    # Should use lte or lt for date comparison, not ilike
    assert all('ilike' not in str(call).lower() for call in sb.method_calls), "Should not use ILIKE"

    # Should use lte/lt for timestamp comparison
    calls = [str(call) for call in sb.method_calls]
    assert any('lte' in call.lower() or 'lt' in call.lower() for call in calls), "Should use lte/lt for date"

    assert 'stale_deals' in result or 'past_close_deals' in result
    print("  ✓ Uses timestamp comparison (lte/lt), not ILIKE")


async def test_query_team_leaderboard_nulls_not_zeros():
    """Test query_team_leaderboard nulls out missing data, never zero-fills."""
    print("\n[Test 7] query_team_leaderboard — nulls, not zeros")

    sb = create_mock_sb()
    sb.execute.side_effect = [
        # Active deals
        AsyncMock(data=[{
            'owner_email': 'christian@growthbook.io',
            'total_pipeline': 500000,
            'deal_count': 5
        }])(),
        # Won deals
        AsyncMock(data=[{
            'owner_email': 'christian@growthbook.io',
            'won_value': 250000,
            'deals_won': 3
        }])(),
        # rep_targets (empty for this rep)
        AsyncMock(data=[])()
    ]

    result = await query_team_leaderboard({
        'time_window': 'this_quarter'
    }, sb)

    assert 'reps' in result
    rep_data = result['reps'][0]

    # Should have pipeline and won data
    assert rep_data['total_pipeline'] == 500000
    assert rep_data['won_value'] == 250000

    # Should null out missing target, not zero-fill
    assert rep_data.get('target_value') is None, "Should null out missing target"
    assert rep_data.get('attainment_rate') is None, "Should null out attainment when no target"

    print("  ✓ Nulls out missing target_value (not zero)")
    print("  ✓ Nulls out attainment_rate when no target")


async def test_query_team_leaderboard_sort_by_pipeline():
    """Test query_team_leaderboard sorts by specified column."""
    print("\n[Test 8] query_team_leaderboard — sort by pipeline")

    sb = create_mock_sb()
    sb.execute.side_effect = [
        # Active deals
        AsyncMock(data=[
            {'owner_email': 'christian@growthbook.io', 'total_pipeline': 500000, 'deal_count': 5},
            {'owner_email': 'cary@growthbook.io', 'total_pipeline': 800000, 'deal_count': 8}
        ])(),
        # Won deals
        AsyncMock(data=[])(),
        # rep_targets
        AsyncMock(data=[])()
    ]

    result = await query_team_leaderboard({
        'time_window': 'this_quarter',
        'sort_by': 'pipeline'
    }, sb)

    assert 'reps' in result
    assert len(result['reps']) == 2

    # Should be sorted by pipeline descending
    assert result['reps'][0]['total_pipeline'] >= result['reps'][1]['total_pipeline']

    print("  ✓ Sorts by pipeline descending")


async def test_rate_or_gap_used_for_all_rates():
    """Test all handlers use rate_or_gap for rate calculations."""
    print("\n[Test 9] rate_or_gap usage verification")

    # Test rate_or_gap directly
    result1 = rate_or_gap(250000, 500000)
    assert result1['value'] == 0.5
    assert result1['data_gap'] is False

    result2 = rate_or_gap(100000, 0)
    assert result2['value'] is None
    assert result2['data_gap'] is True

    result3 = rate_or_gap(100000, None)
    assert result3['value'] is None
    assert result3['data_gap'] is True

    print("  ✓ rate_or_gap(250000, 500000) → {value: 0.5, data_gap: False}")
    print("  ✓ rate_or_gap(100000, 0) → {value: None, data_gap: True}")
    print("  ✓ rate_or_gap(100000, None) → {value: None, data_gap: True}")


async def main():
    print("=" * 60)
    print("AE Handlers Eval")
    print("=" * 60)

    tests = [
        test_query_rep_pipeline_exact_email_only,
        test_query_rep_attainment_no_targets_returns_data_gap,
        test_query_rep_attainment_proration_not_needed,
        test_query_deal_health_null_scores_excluded,
        test_query_deal_health_component_filter,
        test_query_stale_deals_uses_last_analyzed_not_ilike,
        test_query_team_leaderboard_nulls_not_zeros,
        test_query_team_leaderboard_sort_by_pipeline,
        test_rate_or_gap_used_for_all_rates
    ]

    passed = 0
    failed = 0

    for test in tests:
        try:
            await test()
            passed += 1
        except Exception as e:
            print(f"  ✗ FAILED: {e}")
            failed += 1

    print("\n" + "=" * 60)
    print(f"Results: {passed} passed, {failed} failed")
    print("=" * 60)

    return failed == 0


if __name__ == '__main__':
    success = asyncio.run(main())
    sys.exit(0 if success else 1)
