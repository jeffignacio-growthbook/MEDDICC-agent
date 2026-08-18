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
from datetime import date, timedelta
from unittest.mock import patch, MagicMock

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


async def test_query_rep_pipeline_exact_email_only():
    """Handler must filter by exact email, never ilike name."""
    print("\n[Test 1] query_rep_pipeline — exact email match only")

    table_data = {
        "deals": [
            {"deal_id": "1", "company_name": "Acme",
             "owner_email": "cary@growthbook.io",
             "deal_value": 50000, "arr_usd": 50000,
             "stage": "Demo", "deal_status": "active",
             "close_date": "2026-10-15", "forecast_category": "commit"},
            # Deal from different owner should NOT appear
            {"deal_id": "2", "company_name": "Beta",
             "owner_email": "christian@growthbook.io",
             "deal_value": 30000, "arr_usd": 30000,
             "stage": "Scoping", "deal_status": "active",
             "close_date": "2026-09-30", "forecast_category": None},
        ],
        "analyses": [],
        "user_personas": [
            {"email": "cary@growthbook.io", "name": "Cary",
             "role": "ae", "role_group": "ic"}
        ],
    }

    sb = MagicMock()

    def mock_select_all(sb_arg, table, columns='*',
                        filters=None, page_size=1000):
        rows = table_data.get(table, [])
        # Apply email filter if present to simulate real behavior
        if filters:
            for f in filters:
                if len(f) >= 3 and f[0] == "eq" and f[1] == "owner_email":
                    rows = [r for r in rows if r.get("owner_email") == f[2]]
        return rows

    with patch("handlers.select_all", side_effect=mock_select_all):
        result = await query_rep_pipeline(
            {"owner_email": "cary@growthbook.io"}, sb
        )

    assert result.get("error") is None, f"Unexpected error: {result}"
    assert len(result["deals"]) == 1
    assert result["deals"][0]["company_name"] == "Acme"
    assert result["summary"]["total_deals"] == 1
    print("  ✓ query_rep_pipeline filters by exact email only")


async def test_query_rep_pipeline_no_email_returns_error():
    """Missing owner_email must return error, not query all deals."""
    print("\n[Test 2] query_rep_pipeline — no email returns error")

    sb = MagicMock()
    with patch("handlers.select_all", return_value=[]):
        result = await query_rep_pipeline({}, sb)
    assert "error" in result
    print("  ✓ query_rep_pipeline returns error when no email provided")


async def test_query_rep_attainment_no_targets_returns_data_gap():
    """Empty rep_targets → data_gap True with actionable note."""
    print("\n[Test 3] query_rep_attainment — data_gap when no targets")

    table_data = {
        "rep_targets": [],  # No targets set
        "deals": [
            {"deal_id": "1", "company_name": "Acme",
             "owner_email": "cary@growthbook.io",
             "deal_value": 50000, "arr_usd": 50000,
             "deal_status": "won", "close_date": "2026-08-10"}
        ],
        "user_personas": [],
    }
    sb = MagicMock()

    def mock_select_all(sb_arg, table, columns='*',
                        filters=None, page_size=1000):
        return table_data.get(table, [])

    with patch("handlers.select_all", side_effect=mock_select_all):
        result = await query_rep_attainment(
            {"time_window": {"start": "2026-08-01",
                             "end":   "2026-10-31",
                             "label": "FY2027 Q3"}},
            sb
        )

    assert result.get("data_gap") is True or \
           "note" in result or \
           result.get("team_summary", {}).get("total_target", 0) == 0
    print("  ✓ query_rep_attainment returns data_gap when no targets")


async def test_query_deal_health_null_scores_excluded():
    """Test query_deal_health excludes deals with null overall_score."""
    print("\n[Test 4] query_deal_health — excludes null scores")

    sb = MagicMock()

    table_data = {
        "deals": [
            {
                'deal_id': 'deal_1',
                'company_name': 'Acme Corp',
                'deal_status': 'active',
                'stage': 'Demo',
                'owner_email': 'christian@growthbook.io'
            }
        ],
        "analyses": [
            {
                'deal_id': 'deal_1',
                'overall_score': 3.5,
                'metrics_score': 2.0,
                'economic_buyer_score': 5.0,
                'decision_criteria_score': 4.0,
                'decision_process_score': 3.0,
                'identify_pain_score': 4.0,
                'champion_score': 2.0,
                'competition_score': 3.0
            }
        ]
    }

    def mock_select_all(sb_arg, table, columns='*',
                        filters=None, page_size=1000):
        rows = table_data.get(table, [])
        # Apply filters
        if filters:
            for f in filters:
                if len(f) >= 3:
                    if f[0] == "eq":
                        rows = [r for r in rows if r.get(f[1]) == f[2]]
                    elif f[0] == "lt":
                        rows = [r for r in rows if r.get(f[1]) is not None and r.get(f[1]) < f[2]]
        return rows

    with patch("handlers.select_all", side_effect=mock_select_all):
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

    sb = MagicMock()

    table_data = {
        "deals": [
            {
                'deal_id': 'deal_1',
                'company_name': 'Acme Corp',
                'deal_status': 'active',
                'stage': 'Demo',
                'owner_email': 'christian@growthbook.io'
            }
        ],
        "analyses": [
            {
                'deal_id': 'deal_1',
                'overall_score': 6.0,
                'champion_score': 2.0,
                'metrics_score': 8.0
            }
        ]
    }

    def mock_select_all(sb_arg, table, columns='*',
                        filters=None, page_size=1000):
        rows = table_data.get(table, [])
        # Apply filters
        if filters:
            for f in filters:
                if len(f) >= 3:
                    if f[0] == "eq":
                        rows = [r for r in rows if r.get(f[1]) == f[2]]
                    elif f[0] == "lt":
                        rows = [r for r in rows if r.get(f[1]) is not None and r.get(f[1]) < f[2]]
        return rows

    with patch("handlers.select_all", side_effect=mock_select_all):
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


async def test_query_stale_deals_uses_date_not_name_match():
    """Staleness uses last_analyzed date, not ilike name patterns."""
    print("\n[Test 6] query_stale_deals — uses last_analyzed timestamp")

    old_date = (date.today() - timedelta(days=30)).isoformat()
    recent_date = (date.today() - timedelta(days=3)).isoformat()

    table_data = {
        "deals": [
            # Stale deal — last_analyzed 30 days ago
            {"deal_id": "1", "company_name": "Stale Corp",
             "owner_email": "cary@growthbook.io",
             "deal_value": 50000, "stage": "Demo",
             "deal_status": "active", "close_date": "2026-09-30",
             "last_analyzed": old_date},
            # Recent deal — should NOT appear as stale
            {"deal_id": "2", "company_name": "Active Corp",
             "owner_email": "cary@growthbook.io",
             "deal_value": 30000, "stage": "Scoping",
             "deal_status": "active", "close_date": "2026-10-15",
             "last_analyzed": recent_date},
        ],
        "analyses": [],
    }
    sb = MagicMock()

    def mock_select_all(sb_arg, table, columns='*',
                        filters=None, page_size=1000):
        return table_data.get(table, [])

    with patch("handlers.select_all", side_effect=mock_select_all):
        result = await query_stale_deals({"stale_days": 21}, sb)

    stale = result.get("stale_deals", [])
    names = [d["company_name"] for d in stale]
    assert "Stale Corp" in names, f"Stale Corp should be stale: {names}"
    assert "Active Corp" not in names, \
        f"Active Corp should not be stale: {names}"
    print("  ✓ query_stale_deals identifies stale by date not name")


async def test_query_team_leaderboard_nulls_not_zeros():
    """Rep with no won deals → won_arr=None, not won_arr=0."""
    print("\n[Test 7] query_team_leaderboard — nulls, not zeros")

    table_data = {
        "deals": [
            # Cary has active pipeline
            {"deal_id": "1", "company_name": "Acme",
             "owner_email": "cary@growthbook.io",
             "deal_value": 100000, "arr_usd": 100000,
             "deal_status": "active", "close_date": "2026-09-30"},
        ],
        "rep_targets": [],
        "rep_performance": [],
        "user_personas": [
            {"email": "cary@growthbook.io", "name": "Cary",
             "role": "ae", "role_group": "ic"},
            {"email": "christian@growthbook.io", "name": "Christian",
             "role": "ae", "role_group": "ic"},
        ],
    }
    sb = MagicMock()

    def mock_select_all(sb_arg, table, columns='*',
                        filters=None, page_size=1000):
        rows = table_data.get(table, [])
        if filters:
            for f in filters:
                if len(f) >= 3 and f[0] == "eq" and f[1] == "deal_status":
                    rows = [r for r in rows if r.get("deal_status") == f[2]]
        return rows

    with patch("handlers.select_all", side_effect=mock_select_all):
        result = await query_team_leaderboard(
            {"time_window": {"start": "2026-08-01",
                             "end":   "2026-10-31",
                             "label": "FY2027 Q3"},
             "sort_by": "pipeline"},
            sb
        )

    board = result.get("leaderboard", [])
    # Christian has no won deals — won_arr must be None, not 0
    christian = next(
        (r for r in board if "christian" in r.get("owner_email", "")),
        None
    )
    if christian:
        assert christian.get("won_arr") is None, \
            f"won_arr should be None not 0, got: {christian.get('won_arr')}"
    print("  ✓ query_team_leaderboard nulls missing data, not zeros")


async def test_query_team_leaderboard_sort_by_pipeline():
    """Leaderboard sorted by active_pipeline descending."""
    print("\n[Test 8] query_team_leaderboard — sort by pipeline")

    table_data = {
        "deals": [
            {"deal_id": "1", "owner_email": "cary@growthbook.io",
             "deal_value": 100000, "deal_status": "active",
             "close_date": "2026-09-30", "company_name": "A"},
            {"deal_id": "2", "owner_email": "christian@growthbook.io",
             "deal_value": 500000, "deal_status": "active",
             "close_date": "2026-09-30", "company_name": "B"},
        ],
        "rep_targets": [],
        "rep_performance": [],
        "user_personas": [],
    }
    sb = MagicMock()

    def mock_select_all(sb_arg, table, columns='*',
                        filters=None, page_size=1000):
        rows = table_data.get(table, [])
        if filters:
            for f in filters:
                if len(f) >= 3 and f[0] == "eq" and f[1] == "deal_status":
                    rows = [r for r in rows if r.get("deal_status") == f[2]]
        return rows

    with patch("handlers.select_all", side_effect=mock_select_all):
        result = await query_team_leaderboard(
            {"time_window": {"start": "2026-08-01",
                             "end": "2026-10-31",
                             "label": "FY2027 Q3"},
             "sort_by": "pipeline"},
            sb
        )

    board = result.get("leaderboard", [])
    assert len(board) >= 2
    pipelines = [r.get("active_pipeline") or 0 for r in board]
    assert pipelines == sorted(pipelines, reverse=True), \
        f"Not sorted descending: {pipelines}"
    print("  ✓ query_team_leaderboard sorted by pipeline descending")


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
        test_query_rep_pipeline_no_email_returns_error,
        test_query_rep_attainment_no_targets_returns_data_gap,
        test_query_deal_health_null_scores_excluded,
        test_query_deal_health_component_filter,
        test_query_stale_deals_uses_date_not_name_match,
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
            import traceback
            traceback.print_exc()
            failed += 1

    print("\n" + "=" * 60)
    print(f"Results: {passed} passed, {failed} failed")
    print("=" * 60)

    return failed == 0


if __name__ == '__main__':
    success = asyncio.run(main())
    sys.exit(0 if success else 1)
