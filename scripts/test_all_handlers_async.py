#!/usr/bin/env python3
"""
Test that all registered handlers are async.

Bug caught: query_upcoming_renewals was registered in HANDLER_DESCRIPTIONS but
declared as 'def' not 'async def'. The router awaits every handler, so a sync
handler raises TypeError at dispatch, AFTER classification succeeded — looks
like a routing bug but isn't.
"""

import sys
import inspect
from pathlib import Path

# Add api to path
sys.path.insert(0, str(Path(__file__).parent.parent))

from api import handlers
from api.router import HANDLER_DESCRIPTIONS


def test_all_registered_handlers_are_async():
    """The router awaits every handler. A sync handler raises TypeError at
    dispatch, after classification succeeded — looks like a routing bug and
    isn't."""

    print("[TEST] All registered handlers are async")

    missing_handlers = []
    sync_handlers = []

    for handler_name in HANDLER_DESCRIPTIONS.keys():
        # Skip meta handlers that don't dispatch (handled inline in router)
        if handler_name in ("unanswerable", "dynamic_query", "query_help", "acknowledgment"):
            continue

        # Check if handler exists
        handler_fn = getattr(handlers, handler_name, None)
        if not handler_fn:
            missing_handlers.append(handler_name)
            continue

        # Check if it's async
        if not inspect.iscoroutinefunction(handler_fn):
            sync_handlers.append(handler_name)

    meta_handlers = ["unanswerable", "dynamic_query", "query_help", "acknowledgment"]
    checked_count = len([h for h in HANDLER_DESCRIPTIONS if h not in meta_handlers])

    print(f"  Registered handlers: {len(HANDLER_DESCRIPTIONS)}")
    print(f"  Checked: {checked_count} (excluding meta handlers: {', '.join(meta_handlers)})")

    if missing_handlers:
        print(f"\n  ❌ Missing handlers (registered but not found in handlers module):")
        for name in missing_handlers:
            print(f"    - {name}")

    if sync_handlers:
        print(f"\n  ❌ Sync handlers (declared 'def' not 'async def'):")
        for name in sync_handlers:
            handler_fn = getattr(handlers, name)
            print(f"    - {name} at {handler_fn.__module__}.{handler_fn.__name__}")

    if missing_handlers or sync_handlers:
        raise AssertionError(
            f"Found {len(missing_handlers)} missing and {len(sync_handlers)} sync handlers. "
            "All registered handlers must exist and be async def."
        )

    print(f"  ✓ All registered handlers are async")


def main():
    """Run handler async compliance test."""
    print("=" * 70)
    print("HANDLER ASYNC COMPLIANCE TEST")
    print("=" * 70)

    try:
        test_all_registered_handlers_are_async()

        print("\n" + "=" * 70)
        print("RESULTS: 1 passed, 0 failed")
        print("=" * 70)
        return 0
    except AssertionError as e:
        print(f"\n  ❌ {e}")
        print("\n" + "=" * 70)
        print("RESULTS: 0 passed, 1 failed")
        print("=" * 70)
        return 1


if __name__ == "__main__":
    sys.exit(main())
