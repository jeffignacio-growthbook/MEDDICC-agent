"""
Result quality evaluator for CRO Slack Agent.
Assesses whether handler results are useful before committing to synthesis.
"""

# Handlers that return finished, structured fields (not raw "rows" to sample).
# Module-level (not function-local) because api.router also reads this list:
# a handler in here has a bounded, purpose-built return shape by construction
# (an explicit key set a human wrote, not an arbitrary row dump), so its JSON
# is safe to pass to synthesis in full — see the truncation-safety check next
# to `json.dumps(result, default=str)[:3000]` in router.py's
# _dynamic_query_loop_core. Adding a new structured handler here also makes
# it truncation-safe; that's intentional, not a side effect to guard against.
STRUCTURED_HANDLERS = {
    "query_deal":      ["deal"],
    "query_rubric":    ["description", "rubric_overview"],  # score-specific or general
    "query_win_loss":  ["wins", "losses"],  # either populated is a real result;
        # checking "losses" alone (as this read prior to the Handler 5 unified-
        # routing audit) misclassified a genuine wins-only quarter (real wins,
        # zero losses) as "empty" — losses.get() returns [] there, which the
        # loop below treats as "try the next key", and there was no next key
    "generate_win_loss": ["narrative"],
    "set_target":      ["set"],
    "query_arr":       ["arr_by_customer"],
    "query_competitive_intel": ["competitor_counts"],
    "query_rubric_scores_bulk": ["scores"],
    "query_deal_stages_bulk":   ["stages"],
    "query_deal_owners_bulk":   ["owners"],
    "query_deal_values_bulk":   ["values"],
    "query_pipeline":  ["total_deals", "total_pipeline"],  # Phase 2 migration
    "query_stale_deals": ["stale_deals", "stale_count"],  # Phase 2 handler 2/6
    "query_waterfall": ["pipeline_summary", "waterfall"],  # Phase 2 handler 3/6
    "query_rep_pipeline": ["deals", "summary"],  # Phase 2 handler 4/6
    "query_deals_at_risk": ["deals_at_risk", "message"],  # Phase 2 handler 6/6 —
        # "message" must be checked too: the genuinely-empty "no deals at
        # risk" case has an empty deals_at_risk list but a complete,
        # human-readable answer in "message". Checking deals_at_risk alone
        # would misclassify that as "empty" and trigger a wasteful dynamic-
        # query fallback instead of just using the handler's own answer —
        # the same wins-only-quarter mistake query_win_loss's audit found,
        # caught here before it shipped instead of after.
    "query_forecast_trust": ["status"],  # always "insufficient_data" or "ok" —
        # the gated too-early response is a complete, honest answer, not an
        # empty result, same principle as query_deals_at_risk's "message" key.
}


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

    # Handlers that return structured fields (not rows) —
    # check the primary key field is populated
    if handler_name in STRUCTURED_HANDLERS:
        primary_keys = STRUCTURED_HANDLERS[handler_name]
        # Check if ANY of the expected keys exist and have data
        for key in primary_keys:
            primary_val = result.get(key)
            if primary_val is not None:
                if isinstance(primary_val, list) and len(primary_val) == 0:
                    continue  # empty list, try next key
                if isinstance(primary_val, dict) and not primary_val:
                    continue  # empty dict, try next key
                return "good"  # found valid data
        return "empty"

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
