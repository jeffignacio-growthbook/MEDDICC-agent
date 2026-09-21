"""
Tests for deal_risk_assessor.py — structured risk assessment for high-priority deals.

Updated 2026-09-21: MEDDICC signal enabled with 15% weighting, pre-close filtering enforced.
"""
import sys
from pathlib import Path
from datetime import datetime, date, timezone, timedelta
from unittest.mock import MagicMock, patch

sys.path.insert(0, str(Path(__file__).parent.parent / "scripts"))

from deal_risk_assessor import (
    assess_deal_risk,
    _classify_risk,
    _fetch_latest_meddicc_scores,
    SEGMENT_CYCLE_BENCHMARKS,
    LATE_STAGE_IDS
)


def test_assess_deal_risk_with_overdue_cycle():
    """Test deal significantly past segment cycle benchmark is flagged high_risk.

    2026-09-21: Now includes MEDDICC signal (15% weight) but cycle-length dominates
    for deals significantly past benchmark.
    """
    mock_sb = MagicMock()
    mock_sb.table().select().in_().order().execute.return_value = MagicMock(data=[])

    today = date.today()
    create_date = (today - timedelta(days=362)).isoformat()

    deals = [{
        "deal_id": "123",
        "company_name": "Test Corp",
        "stage": LATE_STAGE_IDS[0],
        "create_date": create_date,
        "close_date": today.isoformat(),
        "segment": "SMB",
        "forecast_category": "COMMIT",
        "deal_status": "active"
    }]

    result = assess_deal_risk(deals, mock_sb)

    assert result["summary"]["total_assessed"] == 1
    assert result["summary"]["high_risk"] == 1

    deal = result["assessed_deals"][0]
    assert deal["days_open"] == 362
    assert deal["days_past_benchmark"] == 224  # 362 - 138 (SMB benchmark)
    assert deal["overall_label"] == "high_risk"
    assert any("224 days past" in rf for rf in deal["risk_factors"])


def test_assess_deal_risk_with_meddicc_context_only():
    """Test MEDDICC displayed as context only, NOT weighted into risk classification.

    2026-09-21: MEDDICC NOT statistically significant (p=0.80). Deal with 20 days past
    benchmark is moderate_risk (by cycle-length) regardless of MEDDICC score.
    """
    today = date.today()
    create_date = (today - timedelta(days=158)).isoformat()  # 20 days past SMB 138-day benchmark

    # Mock MEDDICC data with low overall score (should NOT affect classification)
    mock_sb = MagicMock()
    mock_sb.table().select().in_().order().execute.return_value = MagicMock(data=[{
        "deal_id": "123",
        "analyzed_at": (datetime.now(timezone.utc) - timedelta(days=2)).isoformat(),
        "overall_score": 20,  # Low score, but NOT used for classification
        "champion_score": 3,
        "economic_buyer_score": 2,
        "decision_criteria_score": 3,
        "decision_process_score": 2,
        "pain_score": 3,
        "competition_score": 4,
        "metrics_score": 3
    }])

    deals = [{
        "deal_id": "123",
        "company_name": "Test Corp",
        "stage": LATE_STAGE_IDS[0],
        "create_date": create_date,
        "close_date": today.isoformat(),
        "segment": "SMB",
        "forecast_category": "COMMIT",
        "deal_status": "active"
    }]

    result = assess_deal_risk(deals, mock_sb)

    deal = result["assessed_deals"][0]
    # Cycle-length only: 20 days past → moderate_risk (NOT affected by low MEDDICC score)
    assert deal["overall_label"] == "moderate_risk"
    assert deal["meddicc_status"] == "fresh"
    assert deal["meddicc_overall_score"] == 20
    # Verify MEDDICC is displayed with "context only" caveat
    assert any("20/70 overall score" in rf for rf in deal["risk_factors"])
    assert any("context only" in rf for rf in deal["risk_factors"])
    assert any("p=0.80" in rf for rf in deal["risk_factors"])


def test_assess_deal_risk_low_risk_with_good_meddicc():
    """Test deal within benchmark with good MEDDICC score is low_risk.

    2026-09-21: MEDDICC signal enabled. Deal well within benchmark + good MEDDICC
    should be confidently low_risk.
    """
    today = date.today()
    create_date = (today - timedelta(days=50)).isoformat()  # Well within SMB 138-day benchmark

    # Mock fresh MEDDICC data with high overall score
    mock_sb = MagicMock()
    mock_sb.table().select().in_().order().execute.return_value = MagicMock(data=[{
        "deal_id": "123",
        "analyzed_at": datetime.now(timezone.utc).isoformat(),
        "overall_score": 55,  # Above median
        "champion_score": 6,
        "economic_buyer_score": 7,
        "decision_criteria_score": 8,
        "decision_process_score": 6,
        "pain_score": 9,
        "competition_score": 7,
        "metrics_score": 7
    }])

    deals = [{
        "deal_id": "123",
        "company_name": "Test Corp",
        "stage": LATE_STAGE_IDS[0],
        "create_date": create_date,
        "close_date": today.isoformat(),
        "segment": "SMB",
        "forecast_category": "COMMIT",
        "deal_status": "active"
    }]

    result = assess_deal_risk(deals, mock_sb)

    deal = result["assessed_deals"][0]
    assert deal["overall_label"] == "low_risk"
    assert deal["days_past_benchmark"] < 0  # Within benchmark
    assert deal["meddicc_status"] == "fresh"
    assert deal["meddicc_overall_score"] == 55
    assert any("55/70 overall score" in rf for rf in deal["risk_factors"])


def test_assess_deal_risk_missing_meddicc():
    """Test deal without MEDDICC analysis uses neutral (50) risk score.

    2026-09-21: Missing MEDDICC defaults to neutral (50) to not bias risk.
    """
    today = date.today()
    create_date = (today - timedelta(days=155)).isoformat()  # 17 days past SMB benchmark

    mock_sb = MagicMock()
    mock_sb.table().select().in_().order().execute.return_value = MagicMock(data=[])

    deals = [{
        "deal_id": "123",
        "company_name": "Test Corp",
        "stage": LATE_STAGE_IDS[0],
        "create_date": create_date,
        "close_date": today.isoformat(),
        "segment": "SMB",
        "forecast_category": "COMMIT",
        "deal_status": "active"
    }]

    result = assess_deal_risk(deals, mock_sb)

    deal = result["assessed_deals"][0]
    # Cycle risk: 17/60 * 100 * 0.85 = 24.1
    # MEDDICC risk: 50 * 0.15 = 7.5 (neutral)
    # Weighted: 24.1 + 7.5 = 31.6 → moderate_risk (threshold 30)
    assert deal["overall_label"] == "moderate_risk"
    assert deal["meddicc_status"] == "missing"
    assert deal["meddicc_overall_score"] is None
    assert any("no pre-close analysis available" in rf for rf in deal["risk_factors"])


def test_pre_close_filter_excludes_post_close_analyses():
    """PLANTED DISCREPANCY: Verify pre-close filter actually excludes post-close analyses.

    2026-09-21: Critical test to prove pre-close filtering works as documented.
    Creates a deal with TWO analyses:
    1. Post-close analysis (should be EXCLUDED)
    2. Pre-close analysis (should be INCLUDED)

    If filter is NOT working, the post-close analysis (higher score) would be used.
    If filter IS working, the pre-close analysis (lower score) is used.

    Expected: pre-close analysis (30/70) is used, not post-close analysis (60/70).
    """
    mock_sb = MagicMock()

    today = date.today()
    close_date = today - timedelta(days=10)  # Deal closed 10 days ago
    create_date = close_date - timedelta(days=150)  # Deal was open 150 days

    # Two analyses: one post-close (should be excluded), one pre-close (should be included)
    mock_analyses = [
        {
            "deal_id": "999",
            "analyzed_at": (close_date + timedelta(days=5)).isoformat(),  # 5 days AFTER close (POST-CLOSE)
            "overall_score": 60,  # Higher score (should be IGNORED)
            "champion_score": 7,
            "economic_buyer_score": 8,
            "decision_criteria_score": 7,
            "decision_process_score": 8,
            "pain_score": 9,
            "competition_score": 9,
            "metrics_score": 7
        },
        {
            "deal_id": "999",
            "analyzed_at": (close_date - timedelta(days=2)).isoformat(),  # 2 days BEFORE close (PRE-CLOSE)
            "overall_score": 30,  # Lower score (should be USED)
            "champion_score": 3,
            "economic_buyer_score": 4,
            "decision_criteria_score": 4,
            "decision_process_score": 5,
            "pain_score": 5,
            "competition_score": 4,
            "metrics_score": 5
        }
    ]

    mock_sb.table().select().in_().order().execute.return_value = MagicMock(data=mock_analyses)

    deals = [{
        "deal_id": "999",
        "company_name": "Pre-Close Filter Test Corp",
        "stage": LATE_STAGE_IDS[0],
        "create_date": create_date.isoformat(),
        "close_date": close_date.isoformat(),
        "segment": "SMB",
        "forecast_category": "COMMIT",
        "deal_status": "closed_won"  # Closed deal
    }]

    result = assess_deal_risk(deals, mock_sb)

    deal = result["assessed_deals"][0]

    # CRITICAL ASSERTION: If pre-close filter is working, score should be 30 (pre-close), NOT 60 (post-close)
    assert deal["meddicc_overall_score"] == 30, \
        f"Pre-close filter FAILED: expected score 30 (pre-close), got {deal['meddicc_overall_score']} (likely post-close 60)"

    # Additional verification: analyzed_at should be the pre-close date
    assert deal["meddicc_age_days"] >= 12, \
        f"Pre-close filter FAILED: analysis age {deal['meddicc_age_days']} days suggests post-close analysis was used"

    print(f"✅ PLANTED DISCREPANCY PASSED: Pre-close filter correctly used score {deal['meddicc_overall_score']}/70 from pre-close analysis")


def test_assess_deal_risk_insufficient_data():
    """Test deal with Unknown segment (no cycle benchmark) is insufficient_data.

    2026-09-21: MEDDICC alone insufficient to classify (only +0.5 discrimination).
    insufficient_data triggered by lack of cycle benchmark.
    """
    today = date.today()
    create_date = (today - timedelta(days=50)).isoformat()

    mock_sb = MagicMock()
    mock_sb.table().select().in_().order().execute.return_value = MagicMock(data=[])

    deals = [{
        "deal_id": "123",
        "company_name": "Test Corp",
        "stage": LATE_STAGE_IDS[0],
        "create_date": create_date,
        "close_date": today.isoformat(),
        "segment": "Unknown",  # No cycle benchmark
        "forecast_category": "COMMIT",
        "deal_status": "active"
    }]

    result = assess_deal_risk(deals, mock_sb)

    deal = result["assessed_deals"][0]
    assert deal["overall_label"] == "insufficient_data"
    assert deal["cycle_benchmark_days"] is None
    assert deal["meddicc_status"] == "missing"


def test_classify_risk_logic_cycle_length_only():
    """Test risk classification logic (cycle-length only, MEDDICC NOT weighted).

    2026-09-21: MEDDICC NOT statistically significant (p=0.80), so classification
    uses cycle-length only.
    """
    # High risk: significantly overdue
    assert _classify_risk(
        days_past_benchmark=50,
        segment="SMB"
    ) == "high_risk"

    # Moderate risk: moderately overdue
    assert _classify_risk(
        days_past_benchmark=20,
        segment="SMB"
    ) == "moderate_risk"

    # Low risk: within benchmark
    assert _classify_risk(
        days_past_benchmark=-10,
        segment="SMB"
    ) == "low_risk"

    # Boundary case: exactly at threshold (30 days past → moderate)
    assert _classify_risk(
        days_past_benchmark=31,
        segment="SMB"
    ) == "high_risk"

    assert _classify_risk(
        days_past_benchmark=30,
        segment="SMB"
    ) == "moderate_risk"

    # Insufficient data: no cycle benchmark
    assert _classify_risk(
        days_past_benchmark=None,
        segment="Unknown"
    ) == "insufficient_data"


def test_fetch_latest_meddicc_scores_pre_close_filter():
    """Test _fetch_latest_meddicc_scores filters to pre-close analyses.

    2026-09-21: Function should exclude post-close analyses.
    """
    mock_sb = MagicMock()

    today = date.today()
    close_date = today - timedelta(days=5)

    # Mock two analyses: pre-close (should be kept) and post-close (should be excluded)
    mock_analyses = [
        {
            "deal_id": "123",
            "analyzed_at": (close_date + timedelta(days=1)).isoformat(),  # POST-close
            "overall_score": 70,
            "champion_score": 9,
            "economic_buyer_score": 9,
            "decision_criteria_score": 9,
            "decision_process_score": 9,
            "pain_score": 9,
            "competition_score": 9,
            "metrics_score": 9
        },
        {
            "deal_id": "123",
            "analyzed_at": (close_date - timedelta(days=3)).isoformat(),  # PRE-close
            "overall_score": 40,
            "champion_score": 5,
            "economic_buyer_score": 5,
            "decision_criteria_score": 5,
            "decision_process_score": 5,
            "pain_score": 5,
            "competition_score": 5,
            "metrics_score": 5
        }
    ]

    mock_sb.table().select().in_().order().execute.return_value = MagicMock(data=mock_analyses)

    deals_dict = {
        "123": {
            "deal_id": "123",
            "close_date": close_date.isoformat(),
            "deal_status": "closed_won"
        }
    }

    result = _fetch_latest_meddicc_scores(mock_sb, ["123"], deals_dict)

    # Should only get the pre-close analysis (score 40, not 70)
    assert "123" in result
    assert result["123"]["overall_score"] == 40


def test_empty_deals_list():
    """Test handling of empty deals list."""
    mock_sb = MagicMock()
    result = assess_deal_risk([], mock_sb)

    assert result["summary"]["total_assessed"] == 0
    assert result["summary"]["high_risk"] == 0
    assert len(result["assessed_deals"]) == 0


if __name__ == "__main__":
    test_assess_deal_risk_with_overdue_cycle()
    print("✓ test_assess_deal_risk_with_overdue_cycle")

    test_assess_deal_risk_with_meddicc_context_only()
    print("✓ test_assess_deal_risk_with_meddicc_context_only")

    test_assess_deal_risk_low_risk_with_good_meddicc()
    print("✓ test_assess_deal_risk_low_risk_with_good_meddicc")

    test_assess_deal_risk_missing_meddicc()
    print("✓ test_assess_deal_risk_missing_meddicc")

    test_pre_close_filter_excludes_post_close_analyses()
    print("✓ test_pre_close_filter_excludes_post_close_analyses [PLANTED DISCREPANCY]")

    test_assess_deal_risk_insufficient_data()
    print("✓ test_assess_deal_risk_insufficient_data")

    test_classify_risk_logic_cycle_length_only()
    print("✓ test_classify_risk_logic_cycle_length_only")

    test_fetch_latest_meddicc_scores_pre_close_filter()
    print("✓ test_fetch_latest_meddicc_scores_pre_close_filter")

    test_empty_deals_list()
    print("✓ test_empty_deals_list")

    print()
    print("✅ All tests passed!")
