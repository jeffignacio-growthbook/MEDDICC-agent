"""
Result quality evaluator for CRO Slack Agent.
Assesses whether handler results are useful before committing to synthesis.
"""


def evaluate_result(result: dict, handler_name: str) -> str:
    """
    Assess whether a handler's result is actually useful.

    Returns:
      "good"    — result has usable data, proceed to synthesis
      "partial" — result has some data but gaps; synthesize
                  with a note about what's missing
      "empty"   — no data found; try dynamic fallback
      "error"   — result indicates an error; try fallback
    """
    if not result:
        return "error"

    # Error signal from handler
    if result.get("error"):
        return "error"

    # Handlers that return structured fields (not rows)
    # Check the primary key field is populated
    STRUCTURED_HANDLERS = {
        "query_deal":      "deal",
        "query_rubric":    "description",
        "query_win_loss":  "wins",
        "generate_win_loss": "narrative",
        "set_target":      "set",
        "query_arr":       "arr_by_customer",
    }
    if handler_name in STRUCTURED_HANDLERS:
        primary_key = STRUCTURED_HANDLERS[handler_name]
        primary_val = result.get(primary_key)
        if primary_val is None:
            return "empty"
        if isinstance(primary_val, list) and len(primary_val) == 0:
            return "empty"
        if isinstance(primary_val, dict) and not primary_val:
            return "empty"
        return "good"

    # Row-based handlers
    rows = result.get("rows", [])
    if not rows:
        # Check for alternative data keys
        alternative_keys = [k for k in result
                           if k not in ("rows", "period",
                                        "total_found", "note",
                                        "truncated")]
        if any(result.get(k) for k in alternative_keys):
            return "partial"
        return "empty"

    # Check rows aren't all nulls
    non_null = [r for r in rows
                if any(v is not None for v in r.values())]
    if not non_null:
        return "empty"

    return "good"


def extract_missing_hint(result: dict,
                          handler_name: str) -> str:
    """
    When result quality is 'empty' or 'partial',
    return a hint about what was missing to help
    the dynamic fallback or the honest-answer path.
    """
    hints = {
        "query_deal":     "deal not found in database",
        "query_coverage": "no targets set — use 'set [team] target'",
        "query_win_loss": "no win/loss narratives generated yet",
    }
    return hints.get(handler_name,
                     "no matching data found")
