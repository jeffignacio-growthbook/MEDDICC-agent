"""
Test structured aggregation verification — prove the trap springs.

Three core test cases (same "planted discrepancy" standard as every
other primitive built tonight):

1. Wrong total_pipeline: Plant a mismatch between stated total and
   actual sum of underlying deals → verify catches it

2. Missing stage in by_stage: Plant a by_stage dict that drops a stage
   present in underlying data → verify catches it

3. Correct aggregations: Verify correct outputs pass without false alarm

Each test RUNS and confirms the trap springs/doesn't-spring as expected,
not just written.
"""
import sys
from pathlib import Path

# Add api to path
sys.path.insert(0, str(Path(__file__).parent.parent / "api"))

from structured_verification import verify_structured_aggregations


def test_catches_wrong_total_pipeline():
    """
    PLANTED DISCREPANCY TEST 1: Wrong total_pipeline.

    Plant a mismatch: total_pipeline states 500000 but underlying deals
    sum to 600000 → verification must catch it.
    """
    deals = [
        {"deal_id": 1, "_incremental_value": 100000, "_stage_label": "Discovery", "_owner": "rep1@example.com"},
        {"deal_id": 2, "_incremental_value": 200000, "_stage_label": "Scoping", "_owner": "rep2@example.com"},
        {"deal_id": 3, "_incremental_value": 300000, "_stage_label": "Proposal", "_owner": "rep1@example.com"},
    ]

    # Plant wrong total (should be 600000)
    result = verify_structured_aggregations(
        underlying_data=deals,
        structured_output={"total_pipeline": 500000},  # WRONG by 100K
        verification_spec={
            "total_pipeline": {
                "type": "sum",
                "field": "_incremental_value",
                "expected": 500000
            }
        },
        tolerance=0.01
    )

    # Verify the trap springs
    assert not result["match"], "Verification should catch wrong total_pipeline"
    assert len(result["discrepancies"]) == 1, "Should report exactly one discrepancy"

    disc = result["discrepancies"][0]
    assert disc["field"] == "total_pipeline"
    assert disc["expected"] == 500000
    assert disc["actual"] == 600000
    assert disc["diff"] == 100000
    assert disc["type"] == "sum"

    print("✓ TEST 1 PASSED: Catches wrong total_pipeline (planted 100K discrepancy)")


def test_catches_missing_stage_in_by_stage():
    """
    PLANTED DISCREPANCY TEST 2: Missing stage in by_stage.

    Plant a by_stage dict that drops "Scoping" even though underlying
    deals include Scoping deals → verification must catch it.
    """
    deals = [
        {"deal_id": 1, "_incremental_value": 100000, "_stage_label": "Discovery", "_owner": "rep1@example.com"},
        {"deal_id": 2, "_incremental_value": 200000, "_stage_label": "Scoping", "_owner": "rep2@example.com"},
        {"deal_id": 3, "_incremental_value": 300000, "_stage_label": "Proposal", "_owner": "rep1@example.com"},
    ]

    # Plant wrong by_stage (drops Scoping)
    result = verify_structured_aggregations(
        underlying_data=deals,
        structured_output={
            "by_stage": {
                "Discovery": {"count": 1, "value": 100000},
                "Proposal": {"count": 1, "value": 300000},
                # Scoping missing!
            }
        },
        verification_spec={
            "by_stage": {
                "type": "group_by",
                "group_field": "_stage_label",
                "aggregations": {"count": "count", "value": "sum:_incremental_value"},
                "expected": {
                    "Discovery": {"count": 1, "value": 100000},
                    "Proposal": {"count": 1, "value": 300000},
                }
            }
        },
        tolerance=0.01
    )

    # Verify the trap springs
    assert not result["match"], "Verification should catch missing stage"
    assert len(result["discrepancies"]) > 0, "Should report discrepancy for missing Scoping"

    # Find the Scoping discrepancy
    scoping_discs = [d for d in result["discrepancies"] if "Scoping" in d["field"]]
    assert len(scoping_discs) > 0, "Should report Scoping as missing from expected output"

    print("✓ TEST 2 PASSED: Catches missing stage in by_stage (Scoping dropped)")


def test_catches_wrong_stage_value():
    """
    PLANTED DISCREPANCY TEST 2b: Wrong value for a stage in by_stage.

    Plant a by_stage dict that has wrong value for Discovery → verify catches it.
    """
    deals = [
        {"deal_id": 1, "_incremental_value": 100000, "_stage_label": "Discovery", "_owner": "rep1@example.com"},
        {"deal_id": 2, "_incremental_value": 200000, "_stage_label": "Scoping", "_owner": "rep2@example.com"},
        {"deal_id": 3, "_incremental_value": 300000, "_stage_label": "Proposal", "_owner": "rep1@example.com"},
    ]

    # Plant wrong by_stage (Discovery value wrong)
    result = verify_structured_aggregations(
        underlying_data=deals,
        structured_output={
            "by_stage": {
                "Discovery": {"count": 1, "value": 50000},  # WRONG (should be 100000)
                "Scoping": {"count": 1, "value": 200000},
                "Proposal": {"count": 1, "value": 300000},
            }
        },
        verification_spec={
            "by_stage": {
                "type": "group_by",
                "group_field": "_stage_label",
                "aggregations": {"count": "count", "value": "sum:_incremental_value"},
                "expected": {
                    "Discovery": {"count": 1, "value": 50000},
                    "Scoping": {"count": 1, "value": 200000},
                    "Proposal": {"count": 1, "value": 300000},
                }
            }
        },
        tolerance=0.01
    )

    # Verify the trap springs
    assert not result["match"], "Verification should catch wrong stage value"
    assert len(result["discrepancies"]) > 0, "Should report discrepancy"

    # Find Discovery value discrepancy
    discovery_discs = [d for d in result["discrepancies"]
                      if "Discovery" in d["field"] and "value" in d["field"]]
    assert len(discovery_discs) == 1, "Should report Discovery value mismatch"

    disc = discovery_discs[0]
    assert disc["expected"] == 50000
    assert disc["actual"] == 100000
    assert disc["diff"] == 50000

    print("✓ TEST 2b PASSED: Catches wrong stage value in by_stage")


def test_correct_aggregations_pass():
    """
    NO-FALSE-ALARM TEST 3: Correct aggregations pass.

    Verify that correct aggregations don't trigger false alarms.
    All values match underlying data → should return match=True.
    """
    deals = [
        {"deal_id": 1, "_incremental_value": 100000, "_stage_label": "Discovery", "_owner": "rep1@example.com"},
        {"deal_id": 2, "_incremental_value": 200000, "_stage_label": "Scoping", "_owner": "rep2@example.com"},
        {"deal_id": 3, "_incremental_value": 300000, "_stage_label": "Proposal", "_owner": "rep1@example.com"},
    ]

    # Correct aggregations (all match underlying data)
    result = verify_structured_aggregations(
        underlying_data=deals,
        structured_output={
            "total_pipeline": 600000,
            "total_deals": 3,
            "by_stage": {
                "Discovery": {"count": 1, "value": 100000},
                "Scoping": {"count": 1, "value": 200000},
                "Proposal": {"count": 1, "value": 300000},
            },
            "by_owner": {
                "rep1@example.com": {"count": 2, "value": 400000},
                "rep2@example.com": {"count": 1, "value": 200000},
            }
        },
        verification_spec={
            "total_pipeline": {
                "type": "sum",
                "field": "_incremental_value",
                "expected": 600000
            },
            "total_deals": {
                "type": "count",
                "expected": 3
            },
            "by_stage": {
                "type": "group_by",
                "group_field": "_stage_label",
                "aggregations": {"count": "count", "value": "sum:_incremental_value"},
                "expected": {
                    "Discovery": {"count": 1, "value": 100000},
                    "Scoping": {"count": 1, "value": 200000},
                    "Proposal": {"count": 1, "value": 300000},
                }
            },
            "by_owner": {
                "type": "group_by",
                "group_field": "_owner",
                "aggregations": {"count": "count", "value": "sum:_incremental_value"},
                "expected": {
                    "rep1@example.com": {"count": 2, "value": 400000},
                    "rep2@example.com": {"count": 1, "value": 200000},
                }
            }
        },
        tolerance=0.01
    )

    # Verify no false alarm
    assert result["match"], "Correct aggregations should pass verification"
    assert "discrepancies" not in result or not result["discrepancies"]

    print("✓ TEST 3 PASSED: Correct aggregations pass (no false alarm)")


def test_float_tolerance():
    """
    TOLERANCE TEST 4: Float precision tolerance.

    Verify that float rounding differences within tolerance (0.01) don't
    trigger false alarms, but differences above tolerance are caught.
    """
    deals = [
        {"deal_id": 1, "_incremental_value": 100000.005, "_stage_label": "Discovery", "_owner": "rep1@example.com"},
        {"deal_id": 2, "_incremental_value": 200000.003, "_stage_label": "Scoping", "_owner": "rep2@example.com"},
    ]

    # Within tolerance (0.008 < 0.01)
    result_within = verify_structured_aggregations(
        underlying_data=deals,
        structured_output={"total_pipeline": 300000.00},  # Actual: 300000.008
        verification_spec={
            "total_pipeline": {
                "type": "sum",
                "field": "_incremental_value",
                "expected": 300000.00
            }
        },
        tolerance=0.01
    )

    assert result_within["match"], "Difference within tolerance should pass"

    # Above tolerance (0.02 > 0.01)
    result_above = verify_structured_aggregations(
        underlying_data=deals,
        structured_output={"total_pipeline": 299999.99},  # Actual: 300000.008, diff=0.018
        verification_spec={
            "total_pipeline": {
                "type": "sum",
                "field": "_incremental_value",
                "expected": 299999.99
            }
        },
        tolerance=0.01
    )

    assert not result_above["match"], "Difference above tolerance should fail"

    print("✓ TEST 4 PASSED: Float tolerance works (0.008 passes, 0.018 fails)")


def test_by_owner_top_10_limit():
    """
    LIMIT TEST 5: by_owner top 10 limit respected.

    Verify that by_owner verification respects the limit=10 parameter
    and only compares top 10 owners (sorted by value descending).
    """
    # Create 15 owners, but only top 10 in structured output
    deals = []
    for i in range(15):
        deals.append({
            "deal_id": i + 1,
            "_incremental_value": (15 - i) * 10000,  # Descending values
            "_stage_label": "Discovery",
            "_owner": f"rep{i+1}@example.com"
        })

    # Structured output has only top 10 (rep1 through rep10)
    by_owner_top10 = {
        f"rep{i+1}@example.com": {"count": 1, "value": (15 - i) * 10000}
        for i in range(10)
    }

    result = verify_structured_aggregations(
        underlying_data=deals,
        structured_output={"by_owner": by_owner_top10},
        verification_spec={
            "by_owner": {
                "type": "group_by",
                "group_field": "_owner",
                "aggregations": {"count": "count", "value": "sum:_incremental_value"},
                "expected": by_owner_top10,
                "limit": 10  # Only verify top 10
            }
        },
        tolerance=0.01
    )

    assert result["match"], "Top 10 limit should pass when all top 10 match"

    print("✓ TEST 5 PASSED: by_owner top 10 limit respected")


if __name__ == "__main__":
    print("=" * 80)
    print("STRUCTURED AGGREGATION VERIFICATION — PROVE THE TRAP SPRINGS")
    print("=" * 80)
    print()

    test_catches_wrong_total_pipeline()
    test_catches_missing_stage_in_by_stage()
    test_catches_wrong_stage_value()
    test_correct_aggregations_pass()
    test_float_tolerance()
    test_by_owner_top_10_limit()

    print()
    print("=" * 80)
    print("✅ ALL TESTS PASSED — Trap springs as expected")
    print("=" * 80)
