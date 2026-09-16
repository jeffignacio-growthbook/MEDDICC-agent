"""
Structured aggregation verification — deterministic validation of
aggregated handler outputs against underlying raw data.

Unlike api/aggregation_verification.py (which extracts totals from
free-text prose in dynamic_query_loop), this verifies STRUCTURED
handler outputs (dicts with explicit totals, group-by results) before
they're returned to the router.

Dedicated handlers like query_pipeline return structured data:
    {"total_pipeline": 20082320.68,
     "by_stage": {"Discovery": {"count": 50, "value": 5000000}},
     "deals": [...]}

This primitive recomputes those aggregations from the underlying deals
list and compares — same "catch it in code" pattern as the prose
verification, but operating on structured data instead of extracted text.

Integration: Handler calls verify_structured_aggregations() before
return statement. If verification fails, handler returns error instead
of corrupted data (honest failure better than silent wrong answer).
"""
from typing import Any, Dict, List, Optional
import logging

logger = logging.getLogger(__name__)


def verify_structured_aggregations(
    underlying_data: List[dict],
    structured_output: dict,
    verification_spec: dict,
    tolerance: float = 0.01
) -> dict:
    """
    Verify structured aggregation outputs against underlying raw data.

    Recomputes aggregations from underlying_data according to
    verification_spec and compares against structured_output.
    Returns match/discrepancy in same format as existing
    verify_aggregation_completeness().

    Args:
        underlying_data: Raw rows/deals used to produce aggregations
            (e.g., incremental_deals list with _incremental_value,
            _stage_label, _owner fields).
        structured_output: Handler's aggregated result dict containing
            the fields to verify (e.g., {"total_pipeline": 20M,
            "by_stage": {...}}).
        verification_spec: Dict mapping each field to verify to its
            specification:
                {
                  "total_pipeline": {
                      "type": "sum",
                      "field": "_incremental_value",
                      "expected": structured_output["total_pipeline"]
                  },
                  "total_deals": {
                      "type": "count",
                      "expected": structured_output["total_deals"]
                  },
                  "by_stage": {
                      "type": "group_by",
                      "group_field": "_stage_label",
                      "aggregations": {
                          "count": "count",
                          "value": "sum:_incremental_value"
                      },
                      "expected": structured_output["by_stage"]
                  }
                }
        tolerance: Absolute difference below which floats are considered
            equal (handles rounding/accumulation differences). Default
            0.01 (1 cent) matches Phase 1a baseline tests.

    Returns:
        {"match": True} when all verifications pass
        {"match": False, "discrepancies": [...]} when mismatches found.
            Each discrepancy: {"field": name, "expected": X, "actual": Y,
                               "diff": abs(X-Y)}
    """
    if not underlying_data:
        # No data to verify against - degrade to "nothing to disprove"
        return {"match": True}

    discrepancies = []

    for field_name, spec in verification_spec.items():
        spec_type = spec.get("type")
        expected = spec.get("expected")

        if expected is None:
            # Field not present in structured output, skip verification
            continue

        if spec_type == "sum":
            # Verify a simple sum (e.g., total_pipeline)
            field_to_sum = spec.get("field")
            if not field_to_sum:
                logger.warning(f"[STRUCTURED_VERIFY] {field_name}: 'sum' "
                              f"type requires 'field' parameter, skipping")
                continue

            actual = sum(
                (row.get(field_to_sum) or 0)
                for row in underlying_data
                if isinstance(row, dict)
            )

            if abs(actual - expected) > tolerance:
                discrepancies.append({
                    "field": field_name,
                    "expected": expected,
                    "actual": actual,
                    "diff": abs(actual - expected),
                    "type": "sum"
                })

        elif spec_type == "count":
            # Verify a simple count (e.g., total_deals)
            actual = len(underlying_data)

            if actual != expected:
                discrepancies.append({
                    "field": field_name,
                    "expected": expected,
                    "actual": actual,
                    "diff": abs(actual - expected),
                    "type": "count"
                })

        elif spec_type == "group_by":
            # Verify a group-by aggregation (e.g., by_stage)
            group_field = spec.get("group_field")
            aggregations = spec.get("aggregations", {})
            limit = spec.get("limit")  # Optional top-N limit

            if not group_field:
                logger.warning(f"[STRUCTURED_VERIFY] {field_name}: "
                              f"'group_by' type requires 'group_field', skipping")
                continue

            # Recompute group-by aggregation from underlying data
            groups = {}
            for row in underlying_data:
                if not isinstance(row, dict):
                    continue
                group_value = row.get(group_field)
                if group_value is None:
                    continue

                if group_value not in groups:
                    groups[group_value] = {"_rows": []}
                groups[group_value]["_rows"].append(row)

            # Compute aggregations for each group
            for group_value, group_data in groups.items():
                rows = group_data["_rows"]
                for agg_name, agg_spec in aggregations.items():
                    if agg_spec == "count":
                        group_data[agg_name] = len(rows)
                    elif agg_spec.startswith("sum:"):
                        field = agg_spec.split(":", 1)[1]
                        group_data[agg_name] = sum(
                            (r.get(field) or 0) for r in rows
                        )

            # Remove internal _rows field before comparison
            for group_data in groups.values():
                group_data.pop("_rows", None)

            # Sort by value descending (if applicable) and apply limit
            # CRITICAL: Apply limit BEFORE comparison to avoid false positives
            # for groups beyond the limit (e.g., rep11-15 when limit=10)
            if "value" in str(aggregations.values()):  # Check if any agg is a value sum
                sorted_groups = sorted(
                    groups.items(),
                    key=lambda x: x[1].get("value", 0),
                    reverse=True
                )
                if limit:
                    sorted_groups = sorted_groups[:limit]
                groups = dict(sorted_groups)

            # Compare against expected
            expected_dict = expected if isinstance(expected, dict) else {}

            # Check for missing groups in expected (computed groups not in expected output)
            for group_value in groups:
                if group_value not in expected_dict:
                    discrepancies.append({
                        "field": f"{field_name}.{group_value}",
                        "expected": "present",
                        "actual": "missing from expected output",
                        "type": "group_by_missing",
                        "group_value": group_value,
                        "computed": groups[group_value]
                    })

            # Check for mismatches in present groups
            for group_value, expected_aggs in expected_dict.items():
                if group_value not in groups:
                    # Expected group not in computed results
                    # (might be filtered out by limit or truly missing)
                    if not limit or len(groups) < limit:
                        # If no limit or computed results < limit, this is a real gap
                        discrepancies.append({
                            "field": f"{field_name}.{group_value}",
                            "expected": expected_aggs,
                            "actual": "missing from underlying data",
                            "type": "group_by_missing"
                        })
                    continue

                actual_aggs = groups[group_value]

                # Compare each aggregation within the group
                for agg_name, expected_val in expected_aggs.items():
                    actual_val = actual_aggs.get(agg_name)

                    if actual_val is None:
                        discrepancies.append({
                            "field": f"{field_name}.{group_value}.{agg_name}",
                            "expected": expected_val,
                            "actual": None,
                            "type": "group_by_agg_missing"
                        })
                        continue

                    # Float comparison with tolerance
                    if isinstance(expected_val, (int, float)) and isinstance(actual_val, (int, float)):
                        if abs(actual_val - expected_val) > tolerance:
                            discrepancies.append({
                                "field": f"{field_name}.{group_value}.{agg_name}",
                                "expected": expected_val,
                                "actual": actual_val,
                                "diff": abs(actual_val - expected_val),
                                "type": "group_by_agg"
                            })
                    elif expected_val != actual_val:
                        discrepancies.append({
                            "field": f"{field_name}.{group_value}.{agg_name}",
                            "expected": expected_val,
                            "actual": actual_val,
                            "type": "group_by_agg"
                        })

        else:
            logger.warning(f"[STRUCTURED_VERIFY] {field_name}: unknown type "
                          f"'{spec_type}', skipping")

    if not discrepancies:
        return {"match": True}

    return {
        "match": False,
        "discrepancies": discrepancies
    }
