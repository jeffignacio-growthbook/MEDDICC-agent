"""
Tests for deal_risk_assessor.py — structured risk assessment for high-priority deals.
"""
import sys
from pathlib import Path
from datetime import datetime, date, timezone, timedelta
from unittest.mock import MagicMock, patch

sys.path.insert(0, str(Path(__file__).parent.parent / "scripts"))

from deal_risk_assessor import (
    assess_deal_risk,
    _classify_risk,
    _identify_weak_components,
    SEGMENT_CYCLE_BENCHMARKS,
    LATE_STAGE_IDS
)


def test_assess_deal_risk_with_overdue_cycle():
    """Test deal significantly past segment cycle benchmark is flagged high_risk."""
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


def test_assess_deal_risk_with_weak_meddicc():
    """Test deal with multiple weak MEDDICC components is flagged high_risk."""
    today = date.today()
    create_date = (today - timedelta(days=50)).isoformat()

    # Mock MEDDICC data with multiple weak scores
    mock_sb = MagicMock()
    mock_sb.table().select().in_().order().execute.return_value = MagicMock(data=[{
        "deal_id": "123",
        "analyzed_at": datetime.now(timezone.utc).isoformat(),
        "overall_score": 45,
        "champion_score": 3,  # Red
        "economic_buyer_score": 4,  # Red
        "decision_criteria_score": 5,  # Yellow
        "decision_process_score": 3,  # Red
        "pain_score": 4,  # Red
        "competition_score": 6,  # Yellow
        "metrics_score": 5  # Yellow
    }])

    deals = [{
        "deal_id": "123",
        "company_name": "Test Corp",
        "stage": LATE_STAGE_IDS[0],  # Negotiating - should have all Green
        "create_date": create_date,
        "close_date": today.isoformat(),
        "segment": "SMB",
        "forecast_category": "COMMIT",
        "deal_status": "active"
    }]

    result = assess_deal_risk(deals, mock_sb)

    assert result["summary"]["high_risk"] == 1
    deal = result["assessed_deals"][0]
    assert len(deal["weak_components"]) >= 3  # Multiple weak components
    assert deal["overall_label"] == "high_risk"


def test_assess_deal_risk_with_stale_meddicc():
    """Test deal with stale MEDDICC score (>14 days) is flagged moderate_risk."""
    today = date.today()
    create_date = (today - timedelta(days=50)).isoformat()

    # Mock stale MEDDICC data (18 days old)
    stale_date = datetime.now(timezone.utc) - timedelta(days=18)
    mock_sb = MagicMock()
    mock_sb.table().select().in_().order().execute.return_value = MagicMock(data=[{
        "deal_id": "123",
        "analyzed_at": stale_date.isoformat(),
        "overall_score": 85,
        "champion_score": 9,
        "economic_buyer_score": 8,
        "decision_criteria_score": 8,
        "decision_process_score": 9,
        "pain_score": 9,
        "competition_score": 8,
        "metrics_score": 8
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
    assert deal["meddicc_status"] == "stale"
    assert deal["meddicc_age_days"] == 18
    assert deal["overall_label"] == "moderate_risk"
    assert any("stale" in rf.lower() for rf in deal["risk_factors"])


def test_assess_deal_risk_low_risk():
    """Test deal within benchmark with fresh good MEDDICC is low_risk."""
    today = date.today()
    create_date = (today - timedelta(days=50)).isoformat()  # Well within SMB 138-day benchmark

    # Mock fresh MEDDICC data with all Green scores
    mock_sb = MagicMock()
    mock_sb.table().select().in_().order().execute.return_value = MagicMock(data=[{
        "deal_id": "123",
        "analyzed_at": datetime.now(timezone.utc).isoformat(),
        "overall_score": 90,
        "champion_score": 9,
        "economic_buyer_score": 9,
        "decision_criteria_score": 8,
        "decision_process_score": 9,
        "pain_score": 9,
        "competition_score": 8,
        "metrics_score": 9
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
    assert len(deal["weak_components"]) == 0


def test_assess_deal_risk_insufficient_data():
    """Test deal with Unknown segment and no MEDDICC is insufficient_data."""
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
        "segment": "Unknown",  # No benchmark
        "forecast_category": "COMMIT",
        "deal_status": "active"
    }]

    result = assess_deal_risk(deals, mock_sb)

    deal = result["assessed_deals"][0]
    assert deal["overall_label"] == "insufficient_data"
    assert deal["cycle_benchmark_days"] is None


def test_classify_risk_logic():
    """Test risk classification logic directly."""
    # High risk: >30 days past benchmark
    assert _classify_risk(days_past_benchmark=50, meddicc_status="fresh",
                         weak_components=[], segment="SMB") == "high_risk"

    # High risk: 3+ weak components
    assert _classify_risk(days_past_benchmark=-10, meddicc_status="fresh",
                         weak_components=["A", "B", "C"], segment="SMB") == "high_risk"

    # Moderate risk: 0-30 days past benchmark
    assert _classify_risk(days_past_benchmark=15, meddicc_status="fresh",
                         weak_components=[], segment="SMB") == "moderate_risk"

    # Moderate risk: stale MEDDICC
    assert _classify_risk(days_past_benchmark=-10, meddicc_status="stale",
                         weak_components=[], segment="SMB") == "moderate_risk"

    # Moderate risk: 1-2 weak components
    assert _classify_risk(days_past_benchmark=-10, meddicc_status="fresh",
                         weak_components=["A"], segment="SMB") == "moderate_risk"

    # Low risk: within benchmark, fresh MEDDICC, no weak components
    assert _classify_risk(days_past_benchmark=-10, meddicc_status="fresh",
                         weak_components=[], segment="SMB") == "low_risk"

    # Insufficient data: Unknown segment + no/stale MEDDICC
    assert _classify_risk(days_past_benchmark=None, meddicc_status="missing",
                         weak_components=[], segment="Unknown") == "insufficient_data"


def test_identify_weak_components_late_stage():
    """Test weak component identification for late-stage deals (Green threshold)."""
    meddicc_data = {
        "champion_score": 7,  # Yellow - weak for late stage
        "economic_buyer_score": 9,  # Green - OK
        "decision_criteria_score": 5,  # Yellow - weak
        "decision_process_score": 8,  # Green - OK
        "pain_score": 3,  # Red - weak
        "competition_score": 9,  # Green - OK
        "metrics_score": 6  # Yellow - weak
    }

    weak = _identify_weak_components(meddicc_data, LATE_STAGE_IDS[0])

    assert len(weak) == 4
    assert "Champion (7/10)" in weak
    assert "Decision Criteria (5/10)" in weak
    assert "Pain (3/10)" in weak
    assert "Metrics (6/10)" in weak


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

    test_assess_deal_risk_with_weak_meddicc()
    print("✓ test_assess_deal_risk_with_weak_meddicc")

    test_assess_deal_risk_with_stale_meddicc()
    print("✓ test_assess_deal_risk_with_stale_meddicc")

    test_assess_deal_risk_low_risk()
    print("✓ test_assess_deal_risk_low_risk")

    test_assess_deal_risk_insufficient_data()
    print("✓ test_assess_deal_risk_insufficient_data")

    test_classify_risk_logic()
    print("✓ test_classify_risk_logic")

    test_identify_weak_components_late_stage()
    print("✓ test_identify_weak_components_late_stage")

    test_empty_deals_list()
    print("✓ test_empty_deals_list")

    print()
    print("✅ All tests passed!")
