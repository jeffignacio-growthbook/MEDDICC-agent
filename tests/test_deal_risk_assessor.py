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
    """Test MEDDICC signal is deferred - risk based on cycle-length only.

    2026-09-16: MEDDICC signal deferred due to insufficient historical data.
    Deal with 50 days open and SMB benchmark of 138 days should be low_risk
    (within benchmark), regardless of MEDDICC scores. MEDDICC insufficient_data
    note should appear in risk_factors.
    """
    today = date.today()
    create_date = (today - timedelta(days=50)).isoformat()

    # Mock MEDDICC data with multiple weak scores (IGNORED for risk classification)
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
        "stage": LATE_STAGE_IDS[0],  # Negotiating
        "create_date": create_date,
        "close_date": today.isoformat(),
        "segment": "SMB",
        "forecast_category": "COMMIT",
        "deal_status": "active"
    }]

    result = assess_deal_risk(deals, mock_sb)

    # Should be low_risk (50 days < 138-day SMB benchmark), not high_risk
    assert result["summary"]["low_risk"] == 1
    deal = result["assessed_deals"][0]
    # MEDDICC status marked as insufficient_data, not used for classification
    assert deal["meddicc_status"] == "insufficient_data"
    assert deal["overall_label"] == "low_risk"
    # Verify MEDDICC insufficient_data note is present
    assert any("insufficient_data" in rf for rf in deal["risk_factors"])


def test_assess_deal_risk_with_stale_meddicc():
    """Test MEDDICC staleness is tracked but not used for risk classification.

    2026-09-16: MEDDICC signal deferred. Deal with 50 days open (within SMB
    138-day benchmark) should be low_risk regardless of MEDDICC staleness.
    MEDDICC age is still tracked for transparency.
    """
    today = date.today()
    create_date = (today - timedelta(days=50)).isoformat()

    # Mock stale MEDDICC data (18 days old) - IGNORED for risk classification
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
    # MEDDICC status always marked as insufficient_data (deferred)
    assert deal["meddicc_status"] == "insufficient_data"
    assert deal["meddicc_age_days"] == 18  # Age still tracked for transparency
    assert deal["overall_label"] == "low_risk"  # Based on cycle-length only
    # Verify MEDDICC insufficient_data note is present
    assert any("insufficient_data" in rf for rf in deal["risk_factors"])


def test_assess_deal_risk_low_risk():
    """Test deal within benchmark is low_risk, MEDDICC marked insufficient_data.

    2026-09-16: MEDDICC signal deferred. Risk classification based solely on
    cycle-length. MEDDICC insufficient_data note should appear in risk_factors.
    """
    today = date.today()
    create_date = (today - timedelta(days=50)).isoformat()  # Well within SMB 138-day benchmark

    # Mock fresh MEDDICC data with all Green scores (IGNORED for risk classification)
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
    assert deal["meddicc_status"] == "insufficient_data"  # Deferred, not "fresh"
    # Verify MEDDICC insufficient_data note is present in risk_factors
    assert any("insufficient_data" in rf for rf in deal["risk_factors"])


def test_assess_deal_risk_insufficient_data():
    """Test deal with Unknown segment (no cycle benchmark) is insufficient_data.

    2026-09-16: MEDDICC signal deferred. insufficient_data triggered by lack of
    cycle benchmark only (segment-specific historical data missing).
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
    assert deal["meddicc_status"] == "insufficient_data"  # Always deferred
    # Verify MEDDICC insufficient_data note is present
    assert any("insufficient_data" in rf for rf in deal["risk_factors"])


def test_classify_risk_logic():
    """Test risk classification logic (cycle-length only, MEDDICC deferred).

    2026-09-16: MEDDICC signal deferred. Classification uses only cycle-length
    signal. meddicc_status and weak_components parameters are ignored.
    """
    # High risk: >30 days past benchmark
    assert _classify_risk(days_past_benchmark=50, meddicc_status="ignored",
                         weak_components=[], segment="SMB") == "high_risk"

    # Moderate risk: 0-30 days past benchmark
    assert _classify_risk(days_past_benchmark=15, meddicc_status="ignored",
                         weak_components=[], segment="SMB") == "moderate_risk"

    # Low risk: within benchmark (negative days_past_benchmark)
    assert _classify_risk(days_past_benchmark=-10, meddicc_status="ignored",
                         weak_components=[], segment="SMB") == "low_risk"

    # Low risk at boundary: exactly at benchmark (0 days past)
    assert _classify_risk(days_past_benchmark=0, meddicc_status="ignored",
                         weak_components=[], segment="SMB") == "low_risk"

    # Insufficient data: no cycle benchmark available
    assert _classify_risk(days_past_benchmark=None, meddicc_status="ignored",
                         weak_components=[], segment="Unknown") == "insufficient_data"

    # MEDDICC params are IGNORED - verify weak components don't affect classification
    assert _classify_risk(days_past_benchmark=-10, meddicc_status="stale",
                         weak_components=["A", "B", "C"], segment="SMB") == "low_risk"


def test_identify_weak_components_late_stage():
    """Test weak component identification for late-stage deals (Green threshold).

    2026-09-16: This tests currently-unused logic (MEDDICC signal deferred).
    Kept to verify the function remains intact for future use once sufficient
    historical data exists to validate the MEDDICC framework.
    """
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
