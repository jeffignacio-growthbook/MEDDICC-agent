"""
Pre-synthesis completeness verification for dynamic_query_loop.

Detects when filter_table queries use a subset of IDs from a previous step
WITHOUT explicit filtering criteria (indicating accidental truncation rather
than intentional narrowing).

Example bug pattern (Q14):
  Step 0: filter_table(deals) → 107 closed deals
  Step 1: filter_table(calls, filters=[["in_", "deal_id", [16 IDs]]]) → 7 calls

  Problem: Only checked 16 of 107 deals for calls, with no stated reason.
  Solution: Force retry with all 107 deal IDs.

Example legitimate narrowing (NOT a bug):
  Step 0: filter_table(deals) → 200 deals
  Step 1: filter_table(deals, filters=[["eq", "stage", "Discovery"], ["in_", "deal_id", [50 IDs]]])

  Reason: The smaller ID set has an EXPLICIT filter (stage="Discovery").
  This is intentional narrowing, not truncation.
"""
import logging
from typing import Dict, List, Optional, Any

logger = logging.getLogger(__name__)


def _extract_in_filter_ids(filters: List) -> Optional[List]:
    """Extract deal/company/call IDs from an 'in_' filter."""
    if not filters:
        return None

    for f in filters:
        if not isinstance(f, (list, tuple)) or len(f) < 3:
            continue
        op, col, val = f[0], f[1], f[2] if len(f) > 2 else None
        if op in ("in_", "in") and col in ("deal_id", "company_id", "call_id"):
            if isinstance(val, list):
                return val
            # Handle string values (comma-separated)
            if isinstance(val, str):
                return [v.strip() for v in val.split(",")]

    return None


def _has_explicit_filters_beyond_in(filters: List) -> bool:
    """Check if filters contain explicit criteria beyond just the 'in_' ID list."""
    if not filters:
        return False

    # Look for any filter that's NOT just an 'in_' on IDs
    for f in filters:
        if not isinstance(f, (list, tuple)) or len(f) < 2:
            continue
        op, col = f[0], f[1]

        # Skip the 'in_' ID filter itself
        if op in ("in_", "in") and col in ("deal_id", "company_id", "call_id"):
            continue

        # Any other filter indicates intentional narrowing
        return True

    return False


def _get_previous_step_ids(accumulated_data: Dict, iteration: int, id_column: str) -> Optional[List]:
    """
    Extract IDs from ANY previous step that contains the target id_column.

    Scans backward from iteration-1 to step_0, looking for the most recent step
    that has rows with the target id_column. This catches cross-step patterns like:
    - Step 0: 107 deals (deal_id)
    - Step 1-2: Other queries (different tables/columns)
    - Step 3: Query subset of deal_ids → should compare against step_0, not step_2

    Returns None if:
    - No previous step exists
    - No previous step has rows with the ID column
    """
    if iteration == 0:
        return None

    # Scan backward from the most recent step to step_0
    all_ids = set()
    found_any = False

    for i in range(iteration - 1, -1, -1):
        step_key = f"step_{i}_raw"
        if step_key not in accumulated_data:
            continue

        step_result = accumulated_data[step_key]
        if not isinstance(step_result, dict):
            continue

        rows = step_result.get("rows", [])
        if not rows:
            continue

        # Check if this step has the target ID column
        step_ids = []
        for row in rows:
            if isinstance(row, dict) and id_column in row:
                row_id = row[id_column]
                if row_id is not None:
                    step_ids.append(str(row_id))

        if step_ids:
            all_ids.update(step_ids)
            found_any = True

    return list(all_ids) if found_any else None


def detect_incomplete_cross_reference(
    accumulated_data: Dict,
    iteration: int,
    parsed_response: Dict,
    tool_result: Dict
) -> Optional[Dict]:
    """
    Detect if a filter_table call used fewer IDs than the previous step had,
    WITHOUT explicit filtering criteria (indicating accidental truncation).

    Returns None if:
    - Not a filter_table call
    - No 'in_' filter on IDs
    - Has explicit filters beyond the ID list (intentional narrowing)
    - Previous step didn't have more IDs
    - This is already a retry attempt

    Returns incompleteness info dict if detection triggers:
    {
        "detected": True,
        "previous_count": 107,
        "requested_count": 16,
        "missing_ids": [...],
        "id_column": "deal_id",
        "reason": "Cross-step ID mismatch without explicit filters"
    }
    """
    tool_name = parsed_response.get("tool")
    if tool_name != "filter_table":
        return None

    params = parsed_response.get("params", {})
    filters = params.get("filters", [])

    # Extract IDs from the 'in_' filter
    requested_ids = _extract_in_filter_ids(filters)
    if not requested_ids:
        return None

    # Determine which ID column is being used
    id_column = None
    for f in filters:
        if not isinstance(f, (list, tuple)):
            continue
        op, col = f[0], f[1]
        if op in ("in_", "in") and col in ("deal_id", "company_id", "call_id"):
            id_column = col
            break

    if not id_column:
        return None

    # Check for explicit filters beyond the ID list
    # If present, this is intentional narrowing, not truncation
    if _has_explicit_filters_beyond_in(filters):
        logger.info(f"[COMPLETENESS] filter_table has explicit filters beyond ID list - "
                   f"intentional narrowing, not truncation")
        return None

    # Get IDs from previous step
    prev_ids = _get_previous_step_ids(accumulated_data, iteration, id_column)
    if not prev_ids:
        # No previous IDs to compare against
        return None

    # Normalize for comparison
    requested_ids_set = set(str(id) for id in requested_ids)
    prev_ids_set = set(str(id) for id in prev_ids)

    # Check if this is a SUBSET (not just different)
    if not requested_ids_set.issubset(prev_ids_set):
        # Not a subset - this is querying different entities
        return None

    # Check if significantly fewer IDs requested
    requested_count = len(requested_ids_set)
    prev_count = len(prev_ids_set)

    if requested_count >= prev_count:
        # Using all or more IDs - not incomplete
        return None

    # Calculate what's missing
    missing_ids = prev_ids_set - requested_ids_set
    missing_count = len(missing_ids)

    # Only flag if a significant portion is missing (> 10% or > 10 IDs)
    threshold_count = max(10, int(prev_count * 0.1))
    if missing_count < threshold_count:
        logger.info(f"[COMPLETENESS] Small difference ({missing_count}/{prev_count} IDs) - "
                   f"likely intentional sampling")
        return None

    logger.warning(
        f"[COMPLETENESS] Detected incomplete cross-reference: "
        f"previous step had {prev_count} {id_column}s, "
        f"but this filter_table only queried {requested_count} ({missing_count} missing)"
    )

    return {
        "detected": True,
        "previous_count": prev_count,
        "requested_count": requested_count,
        "requested_ids": list(requested_ids_set),
        "missing_count": missing_count,
        "missing_ids": list(missing_ids),
        "id_column": id_column,
        "reason": "Cross-step ID mismatch without explicit filters",
        "prev_step": iteration - 1,
        "current_step": iteration
    }
