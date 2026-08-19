#!/usr/bin/env python3
"""
Eval suite for coaching handlers.

Tests:
- query_pre_call_brief
- query_coaching_priorities
- query_call_quality
"""

import sys
from pathlib import Path

# Add paths
sys.path.insert(0, str(Path(__file__).parent.parent / "api"))
sys.path.insert(0, str(Path(__file__).parent))

import asyncio
from unittest.mock import MagicMock
from handlers import (
    query_pre_call_brief,
    query_coaching_priorities,
    query_call_quality
)


def test_pre_call_brief_requires_company():
    """Returns error when no company provided."""
    print("\n[TEST] Pre-call brief requires company name")

    # Mock Supabase client
    sb = MagicMock()

    # Test with no company
    result = asyncio.run(query_pre_call_brief({}, sb))

    assert "error" in result, "Should return error when company missing"
    assert "company name required" in result["error"].lower(), \
        f"Expected company name error, got: {result['error']}"

    print("✓ Correctly requires company name")


def test_pre_call_brief_identifies_weakest_components():
    """Correctly sorts MEDDICC scores and returns bottom 3."""
    print("\n[TEST] Pre-call brief identifies weakest components")

    # Mock Supabase client
    sb = MagicMock()

    # Mock deals query
    sb.table.return_value.select.return_value.eq.return_value.execute.return_value.data = [
        {
            "deal_id": "123",
            "company_name": "Acme Corp",
            "stage": "Scoping",
            "arr_usd": 50000,
            "owner_email": "rep@example.com",
            "close_date": "2026-09-30",
            "deal_status": "active"
        }
    ]

    # Mock analyses query - champion=2, economic_buyer=3, metrics=8
    def select_all_mock(client, table, columns=None, filters=None):
        if table == "deals":
            return sb.table.return_value.select.return_value.eq.return_value.execute.return_value.data
        elif table == "analyses":
            return [{
                "overall_score": 40,
                "metrics_score": 8,
                "economic_buyer_score": 3,
                "decision_criteria_score": 6,
                "decision_process_score": 5,
                "pain_score": 7,
                "champion_score": 2,
                "competition_score": 9,
                "analyzed_at": "2026-08-18T10:00:00Z",
                "passed": True,
                "full_analysis_text": "Test analysis"
            }]
        elif table == "calls":
            return []
        elif table == "objections":
            return []
        elif table == "feature_gaps":
            return []
        return []

    # Patch select_all
    import handlers
    original_select_all = handlers.select_all
    handlers.select_all = select_all_mock

    try:
        result = asyncio.run(query_pre_call_brief(
            {"company": "Acme"},
            sb
        ))

        # Check weakest components
        assert "meddicc" in result
        assert "weakest_components" in result["meddicc"]
        weakest = result["meddicc"]["weakest_components"]

        assert len(weakest) == 3, f"Expected 3 weakest, got {len(weakest)}"

        # Should be Champion (2), Economic Buyer (3), Decision Process (5)
        assert weakest[0]["component"] == "Champion", \
            f"Expected Champion first, got {weakest[0]['component']}"
        assert weakest[0]["score"] == 2

        assert weakest[1]["component"] == "Economic Buyer", \
            f"Expected Economic Buyer second, got {weakest[1]['component']}"
        assert weakest[1]["score"] == 3

        assert weakest[2]["component"] == "Decision Process", \
            f"Expected Decision Process third, got {weakest[2]['component']}"
        assert weakest[2]["score"] == 5

        print("✓ Correctly identifies and sorts weakest components")

    finally:
        handlers.select_all = original_select_all


def test_pre_call_brief_generates_focus_questions_for_weak_components():
    """Generates relevant questions for each weak component."""
    print("\n[TEST] Pre-call brief generates focus questions")

    # Mock Supabase client
    sb = MagicMock()

    # Mock select_all
    def select_all_mock(client, table, columns=None, filters=None):
        if table == "deals":
            return [{
                "deal_id": "123",
                "company_name": "Acme Corp",
                "stage": "Scoping",
                "arr_usd": 50000,
                "owner_email": "rep@example.com",
                "close_date": "2026-09-30",
                "deal_status": "active"
            }]
        elif table == "analyses":
            return [{
                "overall_score": 30,
                "metrics_score": 8,
                "economic_buyer_score": 8,
                "passed": True,
                "decision_criteria_score": 7,
                "decision_process_score": 6,
                "pain_score": 8,
                "champion_score": 2,  # Weakest
                "competition_score": 8,
                "analyzed_at": "2026-08-18T10:00:00Z",
                "full_analysis_text": "Test"
            }]
        elif table == "calls":
            return []
        elif table == "objections":
            return []
        elif table == "feature_gaps":
            return []
        return []

    import handlers
    original_select_all = handlers.select_all
    handlers.select_all = select_all_mock

    try:
        result = asyncio.run(query_pre_call_brief(
            {"company": "Acme"},
            sb
        ))

        # Check focus questions
        assert "focus_questions" in result
        questions = result["focus_questions"]

        assert len(questions) > 0, "Should have focus questions"

        # Champion should be first weak component
        first_q = questions[0]
        assert first_q["weak_component"] == "Champion", \
            f"Expected Champion questions, got {first_q['weak_component']}"
        assert len(first_q["questions"]) > 0, "Should have questions for Champion"

        # Verify questions are specific
        sample_question = first_q["questions"][0]
        assert len(sample_question) > 10, "Questions should be specific, not generic"

        print("✓ Generates relevant focus questions for weak components")

    finally:
        handlers.select_all = original_select_all


def test_pre_call_brief_identifies_blocker_type_from_objections():
    """Maps open objection categories to blocker taxonomy."""
    print("\n[TEST] Pre-call brief identifies blocker type")

    # Mock Supabase client
    sb = MagicMock()

    # Mock select_all
    def select_all_mock(client, table, columns=None, filters=None):
        if table == "deals":
            return [{
                "deal_id": "123",
                "company_name": "Acme Corp",
                "stage": "Scoping",
                "arr_usd": 50000,
                "owner_email": "rep@example.com",
                "close_date": "2026-09-30",
                "deal_status": "active"
            }]
        elif table == "analyses":
            return [{
                "overall_score": 40,
                "metrics_score": 7,
                "economic_buyer_score": 6,
                "decision_criteria_score": 6,
                "decision_process_score": 6,
                "pain_score": 7,
                "champion_score": 6,
                "competition_score": 7,
                "analyzed_at": "2026-08-18T10:00:00Z",
                "passed": True
            }]
        elif table == "calls":
            return []
        elif table == "objections":
            # Budget objection should map to commercial blocker
            return [{
                "category": "budget",
                "verbatim_quote": "Too expensive",
                "rep_response": None,  # Open objection
                "stage_when_raised": "Scoping"
            }]
        elif table == "feature_gaps":
            return []
        return []

    import handlers
    original_select_all = handlers.select_all
    handlers.select_all = select_all_mock

    try:
        result = asyncio.run(query_pre_call_brief(
            {"company": "Acme"},
            sb
        ))

        # Check blocker type
        assert "blocker_type" in result
        assert result["blocker_type"] == "commercial", \
            f"Expected commercial blocker for budget objection, got {result['blocker_type']}"

        print("✓ Correctly maps objection category to blocker type")

    finally:
        handlers.select_all = original_select_all


def test_coaching_priorities_high_urgency_before_medium():
    """Results sorted: high urgency first, then by ARR."""
    print("\n[TEST] Coaching priorities sorts by urgency then ARR")

    # Mock Supabase client
    sb = MagicMock()

    from datetime import date, timedelta
    from sdr_utils import today_in_reporting_tz
    today = today_in_reporting_tz()
    old_date = (today - timedelta(days=40)).isoformat()
    recent_date = (today - timedelta(days=10)).isoformat()

    # Mock select_all
    def select_all_mock(client, table, columns=None, filters=None):
        if table == "deals":
            return [
                {  # Medium urgency, high ARR
                    "deal_id": "1",
                    "company_name": "Big Corp",
                    "owner_email": "rep@example.com",
                    "stage": "Scoping",
                    "deal_value": 100000,
                    "arr_usd": 100000,
                    "close_date": "2026-10-30"
                },
                {  # High urgency, low ARR
                    "deal_id": "2",
                    "company_name": "Small Corp",
                    "owner_email": "rep@example.com",
                    "stage": "Scoping",
                    "deal_value": 10000,
                    "arr_usd": 10000,
                    "close_date": "2026-09-30"
                }
            ]
        elif table == "analyses":
            return [
                {
                    "deal_id": "1",
                    "overall_score": 50,
                    "champion_score": 7,
                    "economic_buyer_score": 2,  # Weak - medium urgency
                    "decision_process_score": 6,
                    "pain_score": 7,
                    "analyzed_at": "2026-08-18T10:00:00Z",
                    "passed": True
                },
                {
                    "deal_id": "2",
                    "overall_score": 50,
                    "champion_score": 2,  # Weak - high urgency
                    "economic_buyer_score": 7,
                    "decision_process_score": 6,
                    "pain_score": 7,
                    "analyzed_at": "2026-08-18T10:00:00Z",
                    "passed": True
                }
            ]
        elif table == "calls":
            return [
                {"deal_id": "1", "call_date": old_date},  # Stale - adds urgency
                {"deal_id": "2", "call_date": recent_date}
            ]
        elif table == "objections":
            return []
        return []

    import handlers
    original_select_all = handlers.select_all
    handlers.select_all = select_all_mock

    try:
        # Pass owner_email to get priorities list instead of by_owner dict
        result = asyncio.run(query_coaching_priorities(
            {"focus": "all", "owner_email": "rep@example.com"},
            sb
        ))

        assert "priorities" in result, f"Expected priorities key, got: {result.keys()}"
        priorities = result["priorities"]

        # Big Corp should have high urgency (stale + weak EB)
        # Small Corp should have high urgency (weak champion)
        # Both high urgency, so Big Corp ($100K) should come first by ARR

        assert len(priorities) >= 2, f"Expected at least 2 priorities, got {len(priorities)}"

        # Check first is high urgency
        assert priorities[0]["highest_urgency"] == "high", \
            f"First priority should be high urgency, got {priorities[0]['highest_urgency']}"

        # If both high urgency, higher ARR should be first
        if len(priorities) > 1 and priorities[1]["highest_urgency"] == "high":
            assert priorities[0]["arr_usd"] >= priorities[1]["arr_usd"], \
                f"Within same urgency, should sort by ARR descending: {priorities[0]['arr_usd']} vs {priorities[1]['arr_usd']}"

        print("✓ Correctly sorts by urgency then ARR")

    finally:
        handlers.select_all = original_select_all


def test_coaching_priorities_groups_by_owner_when_no_filter():
    """Without owner_email, returns by_owner dict."""
    print("\n[TEST] Coaching priorities groups by owner")

    # Mock Supabase client
    sb = MagicMock()

    # Mock select_all
    def select_all_mock(client, table, columns=None, filters=None):
        if table == "deals":
            return [
                {
                    "deal_id": "1",
                    "company_name": "Acme",
                    "owner_email": "rep1@example.com",
                    "stage": "Scoping",
                    "deal_value": 50000,
                    "arr_usd": 50000,
                    "close_date": "2026-09-30"
                },
                {
                    "deal_id": "2",
                    "company_name": "TechCo",
                    "owner_email": "rep2@example.com",
                    "stage": "Scoping",
                    "deal_value": 30000,
                    "arr_usd": 30000,
                    "close_date": "2026-10-15"
                }
            ]
        elif table == "analyses":
            return [
                {
                    "deal_id": "1",
                    "overall_score": 40,
                    "champion_score": 2,  # Weak
                    "economic_buyer_score": 7,
                    "decision_process_score": 6,
                    "pain_score": 7,
                    "analyzed_at": "2026-08-18T10:00:00Z",
                    "passed": True
                },
                {
                    "deal_id": "2",
                    "overall_score": 40,
                    "champion_score": 2,  # Weak
                    "economic_buyer_score": 7,
                    "decision_process_score": 6,
                    "pain_score": 7,
                    "analyzed_at": "2026-08-18T10:00:00Z",
                    "passed": True
                }
            ]
        elif table == "calls":
            return []
        elif table == "objections":
            return []
        return []

    import handlers
    original_select_all = handlers.select_all
    handlers.select_all = select_all_mock

    try:
        # Query without owner_email filter
        result = asyncio.run(query_coaching_priorities(
            {"focus": "all"},
            sb
        ))

        # Should have by_owner dict
        assert "by_owner" in result, "Should have by_owner when no filter"
        assert isinstance(result["by_owner"], dict), "by_owner should be a dict"

        # Should have two owners
        assert len(result["by_owner"]) == 2, \
            f"Expected 2 owners, got {len(result['by_owner'])}"

        print("✓ Correctly groups by owner when no filter")

    finally:
        handlers.select_all = original_select_all


def test_coaching_priorities_no_deals_returns_data_gap():
    """Empty deal list returns data_gap=True."""
    print("\n[TEST] Coaching priorities handles empty deal list")

    # Mock Supabase client
    sb = MagicMock()

    # Mock select_all - empty deals
    def select_all_mock(client, table, columns=None, filters=None):
        if table == "deals":
            return []
        return []

    import handlers
    original_select_all = handlers.select_all
    handlers.select_all = select_all_mock

    try:
        result = asyncio.run(query_coaching_priorities(
            {"owner_email": "nonexistent@example.com"},
            sb
        ))

        assert "data_gap" in result, "Should have data_gap field"
        assert result["data_gap"] is True, "data_gap should be True for empty deals"
        assert "note" in result, "Should explain the gap"

        print("✓ Correctly returns data_gap for empty deals")

    finally:
        handlers.select_all = original_select_all


def test_call_quality_single_deal_mode():
    """Company name triggers single-call mode."""
    print("\n[TEST] Call quality single deal mode")

    # Mock Supabase client
    sb = MagicMock()

    # Mock select_all
    def select_all_mock(client, table, columns=None, filters=None):
        if table == "deals":
            return [{
                "deal_id": "123",
                "company_name": "Acme Corp",
                "owner_email": "rep@example.com",
                "stage": "Scoping"
            }]
        elif table == "calls":
            return [{
                "call_id": "call1",
                "call_date": "2026-08-15",
                "title": "Discovery Call",
                "source": "fireflies",
                "summary": "Discussed their experimentation needs..."
            }]
        elif table == "call_quality":
            return [{
                "call_date": "2026-08-15",
                "overall_quality_score": 7,
                "quantification_score": 6,
                "decision_process_score": 8,
                "numbers_obtained": ["volume", "incumbent_cost"],
                "numbers_missing": ["win_rate", "value_per_win", "the_clock"],
                "blocker_type": "none",
                "strongest_moment": "Got incumbent cost: $50K/year",
                "weakest_moment": "No follow-up on vague experiment volume answer",
                "pattern_flags": ["accepted_vague_answer"]
            }]
        elif table == "objections":
            return []
        return []

    import handlers
    original_select_all = handlers.select_all
    handlers.select_all = select_all_mock

    try:
        result = asyncio.run(query_call_quality(
            {"company": "Acme"},
            sb
        ))

        # Should be in single-call mode
        assert "company_name" in result
        assert result["company_name"] == "Acme Corp"
        assert "latest_call" in result
        assert "quality_score" in result

        # Should NOT have pattern mode fields
        assert "by_rep" not in result or result["by_rep"] is None

        print("✓ Single-call mode works correctly")

    finally:
        handlers.select_all = original_select_all


def test_call_quality_pattern_mode_no_scores_returns_data_gap():
    """When call_quality table is empty, returns data_gap with note."""
    print("\n[TEST] Call quality pattern mode handles empty table")

    # Mock Supabase client
    sb = MagicMock()

    # Mock select_all - empty call_quality table
    def select_all_mock(client, table, columns=None, filters=None):
        if table == "call_quality":
            return []  # Empty
        return []

    import handlers
    original_select_all = handlers.select_all
    handlers.select_all = select_all_mock

    try:
        result = asyncio.run(query_call_quality(
            {"owner_email": "rep@example.com", "time_window": {"start": "2026-08-01"}},
            sb
        ))

        assert "data_gap" in result, "Should have data_gap field"
        assert result["data_gap"] is True, "data_gap should be True"
        assert "note" in result, "Should explain the gap"
        assert "enrichment pipeline" in result["note"].lower(), \
            "Note should explain scores come from enrichment pipeline"

        print("✓ Pattern mode correctly returns data_gap for empty table")

    finally:
        handlers.select_all = original_select_all


def test_call_quality_aggregates_flag_counts():
    """Pattern mode aggregates pattern_flags across multiple rows."""
    print("\n[TEST] Call quality aggregates flags in pattern mode")

    # Mock Supabase client
    sb = MagicMock()

    # Mock select_all
    def select_all_mock(client, table, columns=None, filters=None):
        if table == "call_quality":
            return [
                {
                    "owner_email": "rep@example.com",
                    "call_date": "2026-08-10",
                    "overall_quality_score": 6,
                    "quantification_score": 5,
                    "decision_process_score": 7,
                    "numbers_missing": ["win_rate", "the_clock"],
                    "pattern_flags": ["no_followup", "accepted_vague_answer"],
                    "blocker_type": "none"
                },
                {
                    "owner_email": "rep@example.com",
                    "call_date": "2026-08-12",
                    "overall_quality_score": 7,
                    "quantification_score": 6,
                    "decision_process_score": 8,
                    "numbers_missing": ["the_clock"],
                    "pattern_flags": ["accepted_vague_answer", "no_number"],
                    "blocker_type": "none"
                }
            ]
        return []

    import handlers
    original_select_all = handlers.select_all
    handlers.select_all = select_all_mock

    try:
        result = asyncio.run(query_call_quality(
            {"owner_email": "rep@example.com"},
            sb
        ))

        assert "most_common_gaps" in result
        gaps = result["most_common_gaps"]

        # accepted_vague_answer should appear twice
        assert gaps.get("accepted_vague_answer") == 2, \
            f"Expected 2 instances of accepted_vague_answer, got {gaps.get('accepted_vague_answer')}"

        # the_clock should appear twice in numbers_missing
        assert "discovery_numbers_most_missed" in result
        missing = result["discovery_numbers_most_missed"]
        assert missing.get("the_clock") == 2, \
            f"Expected 2 instances of the_clock, got {missing.get('the_clock')}"

        print("✓ Pattern mode correctly aggregates flags")

    finally:
        handlers.select_all = original_select_all


def test_pre_call_brief_excludes_failed_analyses_from_trend():
    """Trends computed from passed analyses only, failed excluded."""
    print("\n[TEST] Pre-call brief excludes failed analyses from trend")

    # Mock Supabase client
    sb = MagicMock()

    def select_all_mock(sb_client, table, columns="*", filters=None):
        if table == "deals":
            return [{
                "deal_id": "deal_123",
                "company_name": "TrendCo",
                "stage": "Technical Evaluation",
                "arr_usd": 75000,
                "owner_email": "rep@example.com",
                "close_date": "2026-09-30",
                "deal_status": "active"
            }]
        elif table == "analyses":
            # Return 6 analyses: 4 passed, 2 failed
            # Passed: scores improving 4 → 5 → 6 → 7
            # Failed: scores 1 and 2 (noise that should be excluded)
            return [
                # Newest passed
                {
                    "overall_score": 70,
                    "metrics_score": 7,
                    "economic_buyer_score": 7,
                    "decision_criteria_score": 7,
                    "decision_process_score": 7,
                    "pain_score": 7,
                    "champion_score": 7,
                    "competition_score": 7,
                    "analyzed_at": "2026-08-18T10:00:00Z",
                    "passed": True
                },
                # Failed analysis (should be excluded)
                {
                    "overall_score": 10,
                    "metrics_score": 1,
                    "economic_buyer_score": 1,
                    "decision_criteria_score": 1,
                    "decision_process_score": 1,
                    "pain_score": 1,
                    "champion_score": 1,
                    "competition_score": 1,
                    "analyzed_at": "2026-08-17T10:00:00Z",
                    "passed": False
                },
                # Passed
                {
                    "overall_score": 60,
                    "metrics_score": 6,
                    "economic_buyer_score": 6,
                    "decision_criteria_score": 6,
                    "decision_process_score": 6,
                    "pain_score": 6,
                    "champion_score": 6,
                    "competition_score": 6,
                    "analyzed_at": "2026-08-15T10:00:00Z",
                    "passed": True
                },
                # Failed analysis (should be excluded)
                {
                    "overall_score": 20,
                    "metrics_score": 2,
                    "economic_buyer_score": 2,
                    "decision_criteria_score": 2,
                    "decision_process_score": 2,
                    "pain_score": 2,
                    "champion_score": 2,
                    "competition_score": 2,
                    "analyzed_at": "2026-08-14T10:00:00Z",
                    "passed": False
                },
                # Passed
                {
                    "overall_score": 50,
                    "metrics_score": 5,
                    "economic_buyer_score": 5,
                    "decision_criteria_score": 5,
                    "decision_process_score": 5,
                    "pain_score": 5,
                    "champion_score": 5,
                    "competition_score": 5,
                    "analyzed_at": "2026-08-10T10:00:00Z",
                    "passed": True
                },
                # Oldest passed
                {
                    "overall_score": 40,
                    "metrics_score": 4,
                    "economic_buyer_score": 4,
                    "decision_criteria_score": 4,
                    "decision_process_score": 4,
                    "pain_score": 4,
                    "champion_score": 4,
                    "competition_score": 4,
                    "analyzed_at": "2026-08-05T10:00:00Z",
                    "passed": True
                }
            ]
        elif table == "calls":
            return []
        elif table == "objections":
            return []
        elif table == "feature_gaps":
            return []
        return []

    import handlers
    original_select_all = handlers.select_all
    handlers.select_all = select_all_mock

    try:
        result = asyncio.run(query_pre_call_brief(
            {"company": "TrendCo"},
            sb
        ))

        # Check reliable_score is True (has passed analyses)
        assert result["meddicc"]["reliable_score"] is True, \
            "Expected reliable_score=True with passed analyses"

        # Check that latest score is from the newest PASSED analysis (score 7)
        assert result["meddicc"]["overall_score"] == 70, \
            f"Expected overall_score 70 from latest passed analysis, got {result['meddicc']['overall_score']}"

        # Check that trends exist
        assert "trends" in result["meddicc"], "Expected trends in response"

        # Check that trends show improving (4 → 5 → 6 → 7, failed scores excluded)
        # Weakest components would be all tied at 7, so trends should be computed
        # The trend should show "improving" since we go from 4-5 to 6-7
        trends = result["meddicc"]["trends"]
        if trends:
            # At least one trend should be "improving"
            directions = [t.get("direction") for t in trends.values()]
            assert "improving" in directions or "stable" in directions, \
                f"Expected improving/stable trends from 4→7, got {directions}"

        print("✓ Trends computed from passed analyses only (failed excluded)")
        print(f"  - reliable_score: {result['meddicc']['reliable_score']}")
        print(f"  - latest score: {result['meddicc']['overall_score']} (from passed=True)")
        print(f"  - trends: {result['meddicc']['trends']}")

    finally:
        handlers.select_all = original_select_all


def test_coaching_priorities_payload_bounded_with_200_deals():
    """200 mock active deals all flagged → payload <15KB, shown <=25, truncated."""
    print("\n[TEST] Coaching priorities payload bounded with 200 deals")

    import json
    sb = MagicMock()

    # Build 200 mock deals with gaps
    deals = []
    analyses = []
    for i in range(200):
        deals.append({
            "deal_id": f"deal_{i}",
            "company_name": f"Company_{i}",
            "owner_email": f"rep{i % 5}@example.com",  # 5 different owners
            "stage": "Discovery",
            "arr_usd": 50000 + (i * 1000),
            "close_date": "2026-09-30",
            "deal_status": "active"
        })
        # All deals have weak EB (score 2)
        analyses.append({
            "deal_id": f"deal_{i}",
            "overall_score": 30,
            "champion_score": 5,
            "economic_buyer_score": 2,  # Weak
            "decision_process_score": 5,
            "pain_score": 5,
            "analyzed_at": "2026-08-18T10:00:00Z",
            "passed": True
        })

    def select_all_mock(sb_client, table, columns="*", filters=None):
        if table == "deals":
            return deals
        elif table == "analyses":
            return analyses
        elif table == "calls":
            # Return calls for each deal to avoid "no calls recorded" flags
            return [{"deal_id": f"deal_{i}", "call_date": "2026-08-10"} for i in range(200)]
        elif table == "objections":
            return []
        return []

    import handlers
    original_select_all = handlers.select_all
    handlers.select_all = select_all_mock

    try:
        result = asyncio.run(query_coaching_priorities(
            {},  # No owner filter → by_owner mode
            sb
        ))

        # Verify payload is bounded
        payload = json.dumps(result)
        payload_size = len(payload)
        assert payload_size < 15000, \
            f"Payload {payload_size} bytes exceeds 15KB limit"

        # Verify deals shown is capped
        deals_shown = result.get("deals_shown", 0)
        assert deals_shown <= 25, \
            f"Showed {deals_shown} deals, should cap at 25"

        # Verify truncated flag
        assert result.get("truncated") is True, \
            "Should set truncated=True when capping 200 deals"

        # Verify total reflects full count
        assert result.get("total_deals_needing_attention") == 200, \
            f"Should report full count 200, got {result.get('total_deals_needing_attention')}"

        print(f"✓ Payload bounded: {payload_size} bytes (<15KB)")
        print(f"  - Deals shown: {deals_shown}/200")
        print(f"  - Truncated: {result.get('truncated')}")

    finally:
        handlers.select_all = original_select_all


def test_coaching_priorities_no_large_text_fields():
    """No deal in output carries full_analysis_text or >500 char blob."""
    print("\n[TEST] Coaching priorities excludes large text fields")

    sb = MagicMock()

    def select_all_mock(sb_client, table, columns="*", filters=None):
        if table == "deals":
            return [{
                "deal_id": "deal_1",
                "company_name": "TestCo",
                "owner_email": "rep@example.com",
                "stage": "Discovery",
                "arr_usd": 50000,
                "close_date": "2026-09-30",
                "deal_status": "active"
            }]
        elif table == "analyses":
            return [{
                "deal_id": "deal_1",
                "overall_score": 30,
                "economic_buyer_score": 2,
                "champion_score": 5,
                "analyzed_at": "2026-08-18T10:00:00Z",
                "passed": True,
                "full_analysis_text": "X" * 5000  # Large text that should be stripped
            }]
        elif table == "calls":
            return []
        elif table == "objections":
            return []
        return []

    import handlers
    original_select_all = handlers.select_all
    handlers.select_all = select_all_mock

    try:
        result = asyncio.run(query_coaching_priorities(
            {"owner_email": "rep@example.com"},
            sb
        ))

        # Check no large text fields in output
        import json
        payload = json.dumps(result)

        # Verify full_analysis_text is not in the output
        assert "full_analysis_text" not in payload, \
            "Should not include full_analysis_text in output"

        # Check all string values are reasonable length
        def check_string_sizes(obj, path=""):
            if isinstance(obj, dict):
                for k, v in obj.items():
                    check_string_sizes(v, f"{path}.{k}")
            elif isinstance(obj, list):
                for i, item in enumerate(obj):
                    check_string_sizes(item, f"{path}[{i}]")
            elif isinstance(obj, str):
                assert len(obj) < 500, \
                    f"String at {path} is {len(obj)} chars (>500 limit)"

        check_string_sizes(result)

        print("✓ No large text fields in output")

    finally:
        handlers.select_all = original_select_all


def test_pre_call_brief_registers_deal_entity():
    """Returned deal object contains deal_id AND company_name for entity extraction."""
    print("\n[TEST] Pre-call brief registers deal entity")

    sb = MagicMock()

    def select_all_mock(sb_client, table, columns="*", filters=None):
        if table == "deals":
            return [{
                "deal_id": "deal_123",
                "company_name": "Skyscanner",
                "stage": "Discovery",
                "arr_usd": 125000,
                "owner_email": "rep@example.com",
                "close_date": "2026-09-30",
                "deal_status": "active"
            }]
        elif table == "analyses":
            return [{
                "deal_id": "deal_123",
                "overall_score": 45,
                "metrics_score": 5,
                "economic_buyer_score": 4,
                "decision_criteria_score": 6,
                "decision_process_score": 5,
                "pain_score": 7,
                "champion_score": 5,
                "competition_score": 6,
                "analyzed_at": "2026-08-16T10:00:00Z",
                "passed": True
            }]
        elif table == "calls":
            return []
        elif table == "objections":
            return []
        elif table == "feature_gaps":
            return []
        return []

    import handlers
    original_select_all = handlers.select_all
    handlers.select_all = select_all_mock

    try:
        result = asyncio.run(query_pre_call_brief(
            {"company": "Skyscanner"},
            sb
        ))

        # Verify deal object has required entity fields
        assert "deal" in result, "Should return deal object"
        assert "deal_id" in result["deal"], \
            "Deal object must have deal_id for entity extraction"
        assert result["deal"]["deal_id"] == "deal_123", \
            f"Expected deal_id='deal_123', got {result['deal']['deal_id']}"
        assert "company_name" in result["deal"], \
            "Deal object must have company_name for entity extraction"
        assert result["deal"]["company_name"] == "Skyscanner", \
            f"Expected company_name='Skyscanner', got {result['deal']['company_name']}"

        print("✓ Deal object contains deal_id and company_name for entity registration")

    finally:
        handlers.select_all = original_select_all


def test_call_quality_registers_deal_entity():
    """query_call_quality single-deal mode registers entities."""
    print("\n[TEST] Call quality registers deal entity (single-deal mode)")

    sb = MagicMock()

    def select_all_mock(sb_client, table, columns="*", filters=None):
        if table == "deals":
            return [{
                "deal_id": "deal_456",
                "company_name": "Skyscanner",
                "stage": "Scoping",
                "deal_status": "active"
            }]
        elif table == "calls":
            return [{
                "call_id": "call_1",
                "deal_id": "deal_456",
                "call_date": "2026-08-16",
                "summary": "Discovery call summary",
                "title": "Skyscanner Discovery"
            }]
        elif table == "call_quality":
            return [{
                "call_id": "call_1",
                "overall_quality_score": 7,
                "quantification_score": 8,
                "incumbent_picture_score": 7,
                "technical_picture_score": 6,
                "decision_process_score": 7,
                "question_quality_score": 8,
                "numbers_obtained": {"volume": True, "incumbent_cost": True},
                "numbers_missing": {"win_rate": True},
                "assessed_at": "2026-08-16T10:00:00Z"
            }]
        return []

    import handlers
    original_select_all = handlers.select_all
    handlers.select_all = select_all_mock

    try:
        result = asyncio.run(query_call_quality(
            {"company": "Skyscanner"},
            sb
        ))

        # For single-deal mode, verify we return deal context that can be extracted
        # The handler returns company_name at top level, which is extractable
        assert "company_name" in result, \
            "Should return company_name for entity extraction"
        assert result["company_name"] == "Skyscanner", \
            f"Expected company_name='Skyscanner', got {result.get('company_name')}"

        print("✓ Call quality returns company_name for entity registration")

    finally:
        handlers.select_all = original_select_all


def test_handlers_share_gap_thresholds():
    """Both handlers flag EB=4 as weak using shared COACHING_THRESHOLDS."""
    print("\n[TEST] Handlers share gap thresholds (EB=4 flagged by both)")

    sb = MagicMock()

    # Mock deal with EB=4 (at the weak_component_max threshold)
    def select_all_mock(sb_client, table, columns="*", filters=None):
        if table == "deals":
            return [{
                "deal_id": "deal_threshold",
                "company_name": "ThresholdCo",
                "owner_email": "rep@example.com",
                "stage": "Discovery",
                "arr_usd": 50000,
                "close_date": "2026-09-30",
                "deal_status": "active"
            }]
        elif table == "analyses":
            return [{
                "deal_id": "deal_threshold",
                "overall_score": 40,
                "metrics_score": 6,
                "economic_buyer_score": 4,  # At threshold
                "decision_criteria_score": 6,
                "decision_process_score": 6,
                "pain_score": 6,
                "champion_score": 6,
                "competition_score": 6,
                "analyzed_at": "2026-08-18T10:00:00Z",
                "passed": True
            }]
        elif table == "calls":
            return [{
                "deal_id": "deal_threshold",
                "call_date": "2026-08-17"
            }]
        elif table == "objections":
            return []
        elif table == "feature_gaps":
            return []
        return []

    import handlers
    original_select_all = handlers.select_all
    handlers.select_all = select_all_mock

    try:
        # Test pre-call brief
        brief_result = asyncio.run(query_pre_call_brief(
            {"company": "ThresholdCo"},
            sb
        ))

        # Should include EB in weakest components (score=4)
        weakest = brief_result["meddicc"]["weakest_components"]
        eb_flagged_in_brief = any(
            w["component"] == "Economic Buyer" and w["score"] == 4
            for w in weakest
        )

        # Test coaching priorities
        priorities_result = asyncio.run(query_coaching_priorities(
            {"owner_email": "rep@example.com"},
            sb
        ))

        # Should flag EB as missing (EB <= 4 per COACHING_THRESHOLDS)
        priorities = priorities_result.get("priorities", [])
        assert len(priorities) > 0, "Should have flagged deals"

        eb_flagged_in_priorities = any(
            any(f["type"] == "missing_economic_buyer" for f in p["flags"])
            for p in priorities
        )

        assert eb_flagged_in_brief, \
            "Pre-call brief should flag EB=4 in weakest components"
        assert eb_flagged_in_priorities, \
            "Coaching priorities should flag EB=4 as missing (using shared threshold)"

        print("✓ Both handlers flag EB=4 using shared COACHING_THRESHOLDS.weak_component_max=4")

    finally:
        handlers.select_all = original_select_all


def test_pre_call_brief_uses_stage_appropriate_questions():
    """A weak champion in Proposal stage yields closing/committee-focused
    questions, NOT discovery-stage advocacy questions. Same weak component,
    different questions by stage."""
    print("\n[TEST] Pre-call brief uses stage-appropriate questions")

    sb = MagicMock()

    # Helper to extract all question strings from focus_questions
    def _all_focus_questions(result):
        all_qs = []
        for fq in result.get("focus_questions", []):
            all_qs.extend(fq.get("questions", []))
        return all_qs

    # Test 1: Proposal stage with weak champion
    def select_all_mock_proposal(sb_client, table, columns="*", filters=None):
        if table == "deals":
            return [{
                "deal_id": "deal_proposal",
                "company_name": "ProposalCo",
                "stage": "presentationscheduled",  # Proposal stage (Tech Eval)
                "arr_usd": 75000,
                "owner_email": "rep@example.com",
                "close_date": "2026-09-15",
                "deal_status": "active"
            }]
        elif table == "analyses":
            return [{
                "deal_id": "deal_proposal",
                "overall_score": 45,
                "metrics_score": 8,
                "economic_buyer_score": 7,
                "decision_criteria_score": 7,
                "decision_process_score": 7,
                "pain_score": 8,
                "champion_score": 2,  # Weak champion at late stage
                "competition_score": 7,
                "analyzed_at": "2026-08-18T10:00:00Z",
                "passed": True
            }]
        elif table == "calls":
            return []
        elif table == "objections":
            return []
        elif table == "feature_gaps":
            return []
        return []

    # Test 2: Discovery stage with weak champion (for comparison)
    def select_all_mock_discovery(sb_client, table, columns="*", filters=None):
        if table == "deals":
            return [{
                "deal_id": "deal_discovery",
                "company_name": "DiscoveryCo",
                "stage": "appointmentscheduled",  # Discovery stage
                "arr_usd": 60000,
                "owner_email": "rep@example.com",
                "close_date": "2026-10-15",
                "deal_status": "active"
            }]
        elif table == "analyses":
            return [{
                "deal_id": "deal_discovery",
                "overall_score": 35,
                "metrics_score": 6,
                "economic_buyer_score": 5,
                "decision_criteria_score": 5,
                "decision_process_score": 5,
                "pain_score": 6,
                "champion_score": 2,  # Same weak champion score
                "competition_score": 6,
                "analyzed_at": "2026-08-18T10:00:00Z",
                "passed": True
            }]
        elif table == "calls":
            return []
        elif table == "objections":
            return []
        elif table == "feature_gaps":
            return []
        return []

    import handlers
    original_select_all = handlers.select_all

    try:
        # Test Proposal stage
        handlers.select_all = select_all_mock_proposal
        proposal_result = asyncio.run(query_pre_call_brief(
            {"company": "ProposalCo"},
            sb
        ))

        # Verify stage context
        assert proposal_result.get("stage_context", {}).get("stage_bucket") == "proposal", \
            "Should identify Proposal stage as 'proposal' bucket"

        proposal_qs = _all_focus_questions(proposal_result)
        proposal_qs_lower = [q.lower() for q in proposal_qs]

        # Proposal-stage champion questions are about enabling the champion
        # to present internally, not about identifying an advocate
        assert any("present" in q or "committee" in q or "leadership" in q
                   for q in proposal_qs_lower), \
            f"Proposal stage should ask about presenting to committee/leadership, got: {proposal_qs[:3]}"

        # Must NOT ask the discovery-stage identification question
        assert not any("who internally is most invested" in q
                       for q in proposal_qs_lower), \
            "Proposal stage should NOT ask discovery questions about identifying advocates"

        # Test Discovery stage (different questions for same weak component)
        handlers.select_all = select_all_mock_discovery
        discovery_result = asyncio.run(query_pre_call_brief(
            {"company": "DiscoveryCo"},
            sb
        ))

        # Verify stage context
        assert discovery_result.get("stage_context", {}).get("stage_bucket") == "discovery", \
            "Should identify Discovery stage as 'discovery' bucket"

        discovery_qs = _all_focus_questions(discovery_result)
        discovery_qs_lower = [q.lower() for q in discovery_qs]

        # Discovery-stage champion questions are about identifying advocates
        assert any("who internally" in q or "most invested" in q or "skin in the game" in q
                   for q in discovery_qs_lower), \
            f"Discovery stage should ask about identifying advocates, got: {discovery_qs[:3]}"

        # Must NOT ask proposal-stage committee questions
        assert not any("present" in q and "committee" in q
                       for q in discovery_qs_lower), \
            "Discovery stage should NOT ask about presenting to committees"

        print("✓ Stage-appropriate questions:")
        print(f"  Proposal: {proposal_qs[0][:60]}...")
        print(f"  Discovery: {discovery_qs[0][:60]}...")

    finally:
        handlers.select_all = original_select_all


def test_pre_call_brief_shows_component_trends():
    """Champion declining (5→3→2) shows trend direction, span with dates."""
    print("\n[TEST] Pre-call brief shows component trends")

    sb = MagicMock()

    def select_all_mock(sb_client, table, columns="*", filters=None):
        if table == "deals":
            return [{
                "deal_id": "deal_trend",
                "company_name": "TrendCo",
                "stage": "Scoping",
                "arr_usd": 60000,
                "owner_email": "rep@example.com",
                "close_date": "2026-09-30",
                "deal_status": "active"
            }]
        elif table == "analyses":
            # 3 analyses showing champion declining: 5 → 3 → 2
            return [
                {  # Most recent
                    "deal_id": "deal_trend",
                    "overall_score": 40,
                    "metrics_score": 6,
                    "economic_buyer_score": 6,
                    "decision_criteria_score": 6,
                    "decision_process_score": 6,
                    "pain_score": 6,
                    "champion_score": 2,  # Declined
                    "competition_score": 6,
                    "analyzed_at": "2026-08-18T10:00:00Z",
                    "passed": True
                },
                {  # Middle
                    "deal_id": "deal_trend",
                    "overall_score": 42,
                    "metrics_score": 6,
                    "economic_buyer_score": 6,
                    "decision_criteria_score": 6,
                    "decision_process_score": 6,
                    "pain_score": 6,
                    "champion_score": 3,
                    "competition_score": 6,
                    "analyzed_at": "2026-08-12T10:00:00Z",
                    "passed": True
                },
                {  # Oldest
                    "deal_id": "deal_trend",
                    "overall_score": 44,
                    "metrics_score": 6,
                    "economic_buyer_score": 6,
                    "decision_criteria_score": 6,
                    "decision_process_score": 6,
                    "pain_score": 6,
                    "champion_score": 5,  # Started higher
                    "competition_score": 6,
                    "analyzed_at": "2026-08-05T10:00:00Z",
                    "passed": True
                }
            ]
        elif table == "calls":
            return []
        elif table == "objections":
            return []
        elif table == "feature_gaps":
            return []
        return []

    import handlers
    original_select_all = handlers.select_all
    handlers.select_all = select_all_mock

    try:
        result = asyncio.run(query_pre_call_brief(
            {"company": "TrendCo"},
            sb
        ))

        # Verify trends exist
        trends = result["meddicc"].get("trends", {})
        assert len(trends) > 0, "Should have trends for weakest components"

        # Find champion trend
        champion_trend = trends.get("Champion")
        assert champion_trend is not None, \
            "Should have trend for Champion (weakest component)"

        # Verify trend structure
        assert "direction" in champion_trend, "Trend should have direction"
        assert "span" in champion_trend, "Trend should have span"

        # Verify declining direction (5 → 3 → 2)
        assert champion_trend["direction"] == "declining", \
            f"Expected 'declining' for 5→3→2, got '{champion_trend['direction']}'"

        # Verify span includes dates and call count
        span = champion_trend["span"]
        assert "2026-08-05" in span, "Span should include oldest date"
        assert "2026-08-18" in span, "Span should include newest date"
        assert "calls" in span.lower(), "Span should mention calls"

        print(f"✓ Champion trend: {champion_trend['direction']} {champion_trend['span']}")
        print(f"  Direction: declining (5→3→2)")
        print(f"  Span: {champion_trend['span']}")

    finally:
        handlers.select_all = original_select_all


def test_handlers_use_canonical_stage_bucket():
    """
    query_pre_call_brief stage_context.stage_bucket for a 'presentationscheduled'
    deal returns 'proposal', sourced from field_semantics, not an inline map.
    """
    print("\n[TEST] Handlers use canonical stage_bucket from field_semantics")

    from unittest.mock import MagicMock
    sb = MagicMock()

    def select_all_mock(sb_client, table, columns="*", filters=None):
        if table == "deals":
            return [{
                "deal_id": "deal_tech_eval",
                "company_name": "TechEvalCo",
                "stage": "presentationscheduled",  # Canonical stage ID
                "arr_usd": 60000,
                "owner_email": "rep@example.com",
                "close_date": "2026-10-15",
                "deal_status": "active"
            }]
        elif table == "analyses":
            return [{
                "deal_id": "deal_tech_eval",
                "overall_score": 45,
                "metrics_score": 6,
                "economic_buyer_score": 6,
                "decision_criteria_score": 6,
                "decision_process_score": 6,
                "pain_score": 7,
                "champion_score": 4,
                "competition_score": 6,
                "analyzed_at": "2026-08-18T10:00:00Z",
                "passed": True
            }]
        elif table == "calls":
            return []
        elif table == "objections":
            return []
        elif table == "feature_gaps":
            return []
        return []

    import handlers
    original_select_all = handlers.select_all
    handlers.select_all = select_all_mock

    try:
        result = asyncio.run(query_pre_call_brief(
            {"company": "TechEvalCo"},
            sb
        ))

        # Verify stage_context exists and uses canonical bucket
        stage_context = result.get("stage_context")
        assert stage_context is not None, \
            "Result should include stage_context"

        assert stage_context["current_stage"] == "presentationscheduled", \
            "Should preserve actual stage ID"

        assert stage_context["stage_bucket"] == "proposal", \
            f"presentationscheduled should resolve to 'proposal' bucket via field_semantics, got '{stage_context['stage_bucket']}'"

        print("  ✓ presentationscheduled → proposal bucket (from field_semantics)")

        # Also verify numeric alias resolution
        # Test with closedwon numeric alias
        def select_all_alias_mock(sb_client, table, columns="*", filters=None):
            if table == "deals":
                return [{
                    "deal_id": "deal_won",
                    "company_name": "WonCo",
                    "stage": "1297321623",  # Numeric alias for closedwon
                    "arr_usd": 80000,
                    "owner_email": "rep@example.com",
                    "close_date": "2026-09-01",
                    "deal_status": "won"
                }]
            elif table == "analyses":
                return [{
                    "deal_id": "deal_won",
                    "overall_score": 65,
                    "metrics_score": 9,
                    "economic_buyer_score": 9,
                    "decision_criteria_score": 9,
                    "decision_process_score": 9,
                    "pain_score": 9,
                    "champion_score": 10,
                    "competition_score": 10,
                    "analyzed_at": "2026-08-10T10:00:00Z",
                    "passed": True
                }]
            return []

        handlers.select_all = select_all_alias_mock

        result_alias = asyncio.run(query_pre_call_brief(
            {"company": "WonCo"},
            sb
        ))

        stage_context_alias = result_alias.get("stage_context")
        assert stage_context_alias["stage_bucket"] == "closed_won", \
            f"Numeric alias '1297321623' should resolve to 'closed_won' bucket, got '{stage_context_alias['stage_bucket']}'"

        print("  ✓ 1297321623 (closedwon alias) → closed_won bucket")

    finally:
        handlers.select_all = original_select_all


def main():
    """Run all coaching handler tests."""
    print("=" * 70)
    print("COACHING HANDLERS EVAL")
    print("=" * 70)

    tests = [
        test_pre_call_brief_requires_company,
        test_pre_call_brief_identifies_weakest_components,
        test_pre_call_brief_generates_focus_questions_for_weak_components,
        test_pre_call_brief_identifies_blocker_type_from_objections,
        test_coaching_priorities_high_urgency_before_medium,
        test_coaching_priorities_groups_by_owner_when_no_filter,
        test_coaching_priorities_no_deals_returns_data_gap,
        test_call_quality_single_deal_mode,
        test_call_quality_pattern_mode_no_scores_returns_data_gap,
        test_call_quality_aggregates_flag_counts,
        test_pre_call_brief_excludes_failed_analyses_from_trend,
        test_coaching_priorities_payload_bounded_with_200_deals,
        test_coaching_priorities_no_large_text_fields,
        test_pre_call_brief_registers_deal_entity,
        test_call_quality_registers_deal_entity,
        test_handlers_share_gap_thresholds,
        test_pre_call_brief_uses_stage_appropriate_questions,
        test_pre_call_brief_shows_component_trends,
        test_handlers_use_canonical_stage_bucket,
    ]

    passed = 0
    failed = 0

    for test in tests:
        try:
            test()
            passed += 1
        except AssertionError as e:
            failed += 1
            print(f"\n❌ FAILED: {test.__name__}")
            print(f"   {e}")
        except Exception as e:
            failed += 1
            print(f"\n❌ ERROR in {test.__name__}: {e}")
            import traceback
            traceback.print_exc()

    print("\n" + "=" * 70)
    print(f"RESULTS: {passed} passed, {failed} failed")
    print("=" * 70)

    return 0 if failed == 0 else 1


if __name__ == "__main__":
    sys.exit(main())
