#!/usr/bin/env python3
"""
Eval: Handler descriptions completeness.

Tests that HANDLER_DESCRIPTIONS contains an entry for every
handler function in api.handlers, preventing KeyError crashes
in classify_entity_scope_handler.
"""

import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent.parent))

def test_handler_descriptions_complete():
    """Test that all handlers have descriptions."""
    from api.router import HANDLER_DESCRIPTIONS, logger
    import api.handlers as handlers
    import logging
    logger.setLevel(logging.CRITICAL)  # Suppress logs during test

    print("="*80)
    print("HANDLER DESCRIPTIONS COMPLETENESS EVAL")
    print("="*80)
    print()

    # Get all handler functions from api.handlers
    # Filter out imports and utility functions
    KNOWN_NON_HANDLERS = {
        "Counter", "Path", "datetime", "timezone", "select_all",
        "timedelta", "date", "defaultdict", "get_supabase",
        "rate_or_gap", "today_in_reporting_tz",
        # field_semantics helper functions (not handlers)
        "stage_bucket", "stage_label", "is_won", "is_lost", "is_open",
        # 2026-09-11 (PENDING_WORK.md Low Priority #8): five more names
        # visible in api.handlers's namespace that aren't dispatchable
        # handlers either — confirmed by reading each one, not assumed
        # from the name. HANDLER_DESCRIPTIONS is the routing classifier's
        # own menu (build_intent_prompt() lists every key as a pickable
        # "handler", then dispatches with getattr(handlers, name)(params,
        # sb)) — adding a real entry for any of these would let the
        # classifier route a live question to it and crash, since none
        # of them accept (params, sb):
        "canonical_stage",          # field_semantics helper (stage_id: str) -> str,
                                     # imported like stage_bucket/stage_label above.
        "load_scope_config",        # scripts/analytics/point_in_time.py: shared
                                     # config/client.yaml scoping loader, (config=None).
        "is_deal_in_analytics_scope",  # same module: (stage_at_date, pipeline_id, ...)
                                     # -> bool, a scoping predicate, not a handler.
        "compute_cycle_time",       # api/handlers.py's own canonical cycle-time
                                     # calculation, (sb, since_date=None, until_date=None)
                                     # — called BY query_cycle_time (already a
                                     # documented handler), not a handler itself.
        "compute_at_risk_deals",    # api/handlers.py's own canonical at-risk logic,
                                     # (sb, deal_ids=None, use_stage_aware=True,
                                     # time_window=None) — called BY several already-
                                     # documented handlers, not a handler itself.
    }

    all_names = [name for name in dir(handlers) if not name.startswith('_')]
    handler_funcs = []

    for name in all_names:
        obj = getattr(handlers, name)
        if callable(obj) and name not in KNOWN_NON_HANDLERS:
            handler_funcs.append(name)

    handler_set = set(handler_funcs)
    description_set = set(HANDLER_DESCRIPTIONS.keys())

    # Exclude meta-handlers that aren't real handler functions (routed in
    # router.py, no api.handlers function): dynamic fallback, the no-data
    # sentinel, and the orientation intents (greeting/help, acknowledgment).
    description_set.discard("dynamic_query")
    description_set.discard("unanswerable")
    description_set.discard("query_help")
    description_set.discard("acknowledgment")

    print(f"[TEST 1] All handlers have descriptions")
    print(f"  Handlers in api.handlers: {len(handler_set)}")
    print(f"  Descriptions in HANDLER_DESCRIPTIONS: {len(description_set)}")
    print()

    # Check for handlers without descriptions
    missing_descriptions = handler_set - description_set
    if missing_descriptions:
        print(f"  ❌ MISSING DESCRIPTIONS:")
        for name in sorted(missing_descriptions):
            print(f"     - {name}")
        print()
        assert False, f"Missing descriptions for {len(missing_descriptions)} handlers: {missing_descriptions}"

    print(f"  ✓ All {len(handler_set)} handlers have descriptions")
    print()

    # Check for descriptions without handlers (informational warning)
    extra_descriptions = description_set - handler_set
    if extra_descriptions:
        print(f"  ⚠️  EXTRA DESCRIPTIONS (no matching handler):")
        for name in sorted(extra_descriptions):
            print(f"     - {name}")
        print(f"  Note: This is OK for deprecated handlers or planned features")
        print()

    print("[TEST 2] Entity-scope bulk handlers have descriptions")
    from api.router import ENTITY_SCOPE_BULK_HANDLERS

    missing_bulk_descriptions = []
    for handler_name in ENTITY_SCOPE_BULK_HANDLERS:
        if handler_name not in HANDLER_DESCRIPTIONS:
            missing_bulk_descriptions.append(handler_name)

    if missing_bulk_descriptions:
        print(f"  ❌ MISSING BULK HANDLER DESCRIPTIONS:")
        for name in missing_bulk_descriptions:
            print(f"     - {name}")
        print()
        assert False, f"Missing descriptions for bulk handlers: {missing_bulk_descriptions}"

    print(f"  ✓ All {len(ENTITY_SCOPE_BULK_HANDLERS)} bulk handlers have descriptions")
    print()

    print("="*80)
    print("Results: All tests passed!")
    print("="*80)

if __name__ == "__main__":
    test_handler_descriptions_complete()
