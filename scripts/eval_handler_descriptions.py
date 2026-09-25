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

    # A handler is what the router can dispatch: it awaits
    # getattr(handlers, name)(params, sb), so every async callable reachable
    # on api.handlers (wherever it is defined: query_upcoming_renewals comes
    # from api.handlers_renewal). Decided by rule, not a hand-kept exclusion
    # list: #30 imported incremental_arr into api.handlers, nobody added it
    # to the old KNOWN_NON_HANDLERS list, and this eval (the gate's first
    # step) failed from 2026-09-23, so none of the gate's later checks ran.
    # Sync helpers (stage_label, compute_cycle_time, incremental_arr, ...)
    # are not dispatchable and are not counted.
    import inspect
    handler_funcs = [name for name, obj in vars(handlers).items()
                     if not name.startswith('_') and inspect.iscoroutinefunction(obj)]

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
