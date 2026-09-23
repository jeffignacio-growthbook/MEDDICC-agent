"""
Canonical incremental ARR calculation with NULL handling.

CRITICAL NULL HANDLING:
- new_arr=50000, expansion_arr=NULL → result is 50000 (not NULL or 0)
- new_arr=NULL, expansion_arr=30000 → result is 30000 (not NULL or 0)
- new_arr=NULL, expansion_arr=NULL → result is 0 (not NULL)

The `or 0` coalescing is MANDATORY - without it, a NULL in either field would
propagate and cause the row's contribution to be lost entirely.
"""


def incremental_arr(deal: dict) -> float:
    """
    Calculate incremental ARR from a deal dict.

    Incremental ARR = new_arr + expansion_arr (excludes renewals)

    NULL HANDLING (CRITICAL):
    - Treats NULL/None as 0 for summation
    - A deal with new_arr=50000 and expansion_arr=NULL correctly contributes $50,000
    - A deal with both NULL correctly contributes $0 (not skipped)

    Args:
        deal: dict with "new_arr" and "expansion_arr" keys (may be NULL/None/missing)

    Returns:
        float: incremental ARR value (never NULL, minimum 0)

    Examples:
        >>> incremental_arr({"new_arr": 50000, "expansion_arr": 30000})
        80000
        >>> incremental_arr({"new_arr": 50000, "expansion_arr": None})
        50000
        >>> incremental_arr({"new_arr": None, "expansion_arr": 30000})
        30000
        >>> incremental_arr({"new_arr": None, "expansion_arr": None})
        0
        >>> incremental_arr({})  # Missing keys
        0
    """
    new_arr = deal.get("new_arr") or 0
    expansion_arr = deal.get("expansion_arr") or 0
    return float(new_arr) + float(expansion_arr)


def incremental_arr_with_exclusions(deal: dict, renewal_pipeline_id: str = None) -> float:
    """
    Calculate incremental ARR with optional renewal pipeline exclusion.

    Same as incremental_arr() but returns 0 if deal is in renewal pipeline.

    Args:
        deal: dict with "new_arr", "expansion_arr", "pipeline_id" keys
        renewal_pipeline_id: if provided, returns 0 for deals in this pipeline

    Returns:
        float: incremental ARR or 0 if excluded
    """
    # Exclude renewal pipeline if specified
    if renewal_pipeline_id and str(deal.get("pipeline_id") or "") == str(renewal_pipeline_id):
        return 0.0

    return incremental_arr(deal)
