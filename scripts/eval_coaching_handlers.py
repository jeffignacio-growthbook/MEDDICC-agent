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
                "analyzed_at": "2026-08-18T10:00:00Z"
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
