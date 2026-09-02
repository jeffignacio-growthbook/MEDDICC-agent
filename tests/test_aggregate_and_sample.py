"""
Tests for _aggregate_and_sample() — aggregate large results, sample for synthesis.
"""
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent.parent))

from api.router import _aggregate_and_sample


def test_small_result_passes_through():
    """9 rows with sample_size=20 arrive complete, no truncation."""
    result = {
        "rows": [{"deal_id": i, "deal_value": 1000} for i in range(9)],
        "table": "deals"
    }
    agg = _aggregate_and_sample(result, sample_size=20)

    assert len(agg["rows"]) == 9, f"Expected 9 rows, got {len(agg['rows'])}"
    assert agg.get("truncated") == False, "Should not be truncated"
    assert agg["row_count"] == 9, f"Expected row_count=9, got {agg['row_count']}"
    assert "sample" not in agg or len(agg["sample"]) == 9, "No separate sample for small result"
    print("✓ Small result passes through whole")


def test_large_result_aggregated_with_sample():
    """138 rows → aggregates + 20-row sample + truncated flag."""
    rows = [
        {
            "deal_id": i,
            "deal_value": i * 1000,
            "stage": "Discovery" if i < 80 else "Scoping"
        }
        for i in range(138)
    ]
    result = {"rows": rows, "table": "deals"}
    agg = _aggregate_and_sample(result, sample_size=20, order_by="deal_value desc")

    assert agg["row_count"] == 138, f"Expected row_count=138, got {agg['row_count']}"
    assert len(agg["sample"]) == 20, f"Expected 20 sample rows, got {len(agg['sample'])}"
    assert len(agg["rows"]) == 20, f"Expected 20 rows (sample), got {len(agg['rows'])}"
    assert agg["truncated"] == True, "Should be truncated"
    assert "deal_value" in agg["aggregates"], "Should have deal_value aggregates"
    assert agg["aggregates"]["deal_value"]["sum"] == sum(i*1000 for i in range(138)), \
        "Sum should match all 138 rows"
    assert agg["sample_basis"] == "20 largest by deal_value", \
        f"Expected sample_basis with order_by, got {agg['sample_basis']}"
    print("✓ Large result aggregated with sample")


def test_null_counts_surface():
    """15 of 138 deals with null deal_value are counted."""
    rows = [
        {
            "deal_id": i,
            "deal_value": i * 1000 if i < 123 else None,
        }
        for i in range(138)
    ]
    result = {"rows": rows, "table": "deals"}
    agg = _aggregate_and_sample(result, sample_size=20)

    assert "null_counts" in agg["aggregates"], "Should have null_counts"
    assert agg["aggregates"]["null_counts"]["deal_value"] == 15, \
        f"Expected 15 nulls, got {agg['aggregates']['null_counts'].get('deal_value')}"
    print("✓ Null counts surface in aggregates")


def test_stage_counts():
    """Low-cardinality text columns produce counts."""
    rows = [
        {"deal_id": i, "stage": "Discovery" if i < 87 else "Scoping" if i < 111 else "Proposal"}
        for i in range(138)
    ]
    result = {"rows": rows, "table": "deals"}
    agg = _aggregate_and_sample(result, sample_size=20)

    assert "stage_counts" in agg["aggregates"], "Should have stage_counts"
    counts = agg["aggregates"]["stage_counts"]
    assert counts["Discovery"] == 87, f"Expected 87 Discovery, got {counts.get('Discovery')}"
    assert counts["Scoping"] == 24, f"Expected 24 Scoping, got {counts.get('Scoping')}"
    assert counts["Proposal"] == 27, f"Expected 27 Proposal, got {counts.get('Proposal')}"
    print("✓ Stage counts computed correctly")


def test_sample_basis_no_order():
    """When no order_by, sample_basis says 'first N rows'."""
    rows = [{"deal_id": i} for i in range(100)]
    result = {"rows": rows, "table": "deals"}
    agg = _aggregate_and_sample(result, sample_size=20)

    assert "first 20 rows" in agg["sample_basis"], \
        f"Expected 'first 20 rows', got {agg['sample_basis']}"
    print("✓ Sample basis correct when no ordering")


def test_numeric_aggregates():
    """Numeric columns get sum/mean/min/max."""
    rows = [{"deal_id": i, "deal_value": i * 1000} for i in range(1, 101)]
    result = {"rows": rows, "table": "deals"}
    agg = _aggregate_and_sample(result, sample_size=20)

    dv = agg["aggregates"]["deal_value"]
    assert dv["sum"] == sum(i * 1000 for i in range(1, 101)), "Sum incorrect"
    assert dv["mean"] == 50500.0, f"Mean should be 50500, got {dv['mean']}"
    assert dv["min"] == 1000, f"Min should be 1000, got {dv['min']}"
    assert dv["max"] == 100000, f"Max should be 100000, got {dv['max']}"
    print("✓ Numeric aggregates (sum/mean/min/max) correct")


def test_payload_size():
    """500-row result → sample should keep payload small."""
    import json
    rows = [
        {
            "deal_id": i,
            "company_name": f"Company {i}",
            "deal_value": i * 1000,
            "stage": "Discovery"
        }
        for i in range(500)
    ]
    result = {"rows": rows, "table": "deals"}
    agg = _aggregate_and_sample(result, sample_size=20)

    payload = json.dumps(agg)
    payload_size = len(payload)

    assert payload_size < 20000, \
        f"Payload should be < 20KB, got {payload_size} bytes"
    assert len(agg["rows"]) == 20, "Should only have 20 rows in payload"
    assert agg["row_count"] == 500, "Should report full row count"
    print(f"✓ Payload size controlled: {payload_size} bytes (500 rows → 20 sample)")


if __name__ == '__main__':
    test_small_result_passes_through()
    test_large_result_aggregated_with_sample()
    test_null_counts_surface()
    test_stage_counts()
    test_sample_basis_no_order()
    test_numeric_aggregates()
    test_payload_size()
    print("\n✅ All tests passed")
