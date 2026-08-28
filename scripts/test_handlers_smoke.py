#!/usr/bin/env python3
"""
Smoke test: call each registered handler with plausible params.

Catches signature mismatches before production. Two production failures
in two runs (both signature errors) warranted this test.
"""

import sys
import asyncio
from pathlib import Path
from datetime import date

# Add api and scripts to path
sys.path.insert(0, str(Path(__file__).parent.parent))
sys.path.insert(0, str(Path(__file__).parent))

from api import handlers
from api.router import HANDLER_DESCRIPTIONS
from api.time_resolver import resolve_time_window
from api.db import get_supabase


# Meta handlers that don't dispatch (handled inline in router)
META_HANDLERS = {"unanswerable", "dynamic_query", "query_help", "acknowledgment"}


async def smoke_test_all_handlers():
    """Call each registered handler with plausible params to catch signature errors."""

    print("[TEST] Smoke testing all registered handlers against live Supabase")

    # Connect to Supabase
    try:
        sb = get_supabase()
        print(f"  Connected to Supabase")
    except Exception as e:
        print(f"  ❌ Failed to connect to Supabase: {e}")
        return 1

    # Prepare plausible test params for handlers
    test_params = {
        "time_window": resolve_time_window({"period": "current_quarter"}),
        "owner_email": "test@example.com",
        "company_name": "Test Company",
        "deal_id": "12345",
        "stage": "Discovery",
        "component": "champion",
        "proposed_score": 7,
        "correction_reason": "test correction",
        "segment": "Enterprise",
        "view": "movement",
    }

    passed = []
    failed = []
    skipped = []

    # Test each registered handler
    for handler_name in sorted(HANDLER_DESCRIPTIONS.keys()):
        # Skip meta handlers (not dispatchable)
        if handler_name in META_HANDLERS:
            skipped.append((handler_name, "meta handler"))
            continue

        # Get handler function
        handler_fn = getattr(handlers, handler_name, None)
        if not handler_fn:
            failed.append((handler_name, "handler not found in handlers module"))
            continue

        # Try to call it
        try:
            result = await handler_fn(test_params, sb)

            # Verify result is a dict
            if not isinstance(result, dict):
                failed.append((handler_name, f"returned {type(result).__name__}, not dict"))
                continue

            # Success
            passed.append(handler_name)
            print(f"  ✓ {handler_name}")

        except TypeError as e:
            # Signature mismatch
            failed.append((handler_name, f"TypeError: {e}"))
            print(f"  ✗ {handler_name}: {e}")

        except Exception as e:
            # Other error (could be data-related, not necessarily a signature issue)
            # Still pass if it's a runtime error, not a signature error
            error_msg = str(e)
            if "argument" in error_msg or "parameter" in error_msg or "signature" in error_msg:
                failed.append((handler_name, f"Signature error: {e}"))
                print(f"  ✗ {handler_name}: {e}")
            else:
                # Runtime error with valid signature (e.g., no data found)
                passed.append(handler_name)
                print(f"  ✓ {handler_name} (runtime error ok: {error_msg[:50]}...)")

    # Report summary
    print(f"\n{'='*70}")
    print(f"SMOKE TEST RESULTS")
    print(f"{'='*70}")
    print(f"Passed: {len(passed)}")
    print(f"Failed: {len(failed)}")
    print(f"Skipped: {len(skipped)} (meta handlers)")

    if failed:
        print(f"\n❌ FAILED HANDLERS:")
        for handler_name, error in failed:
            print(f"  - {handler_name}: {error}")
        return 1

    if skipped:
        print(f"\nℹ️  SKIPPED (meta handlers, inline in router):")
        for handler_name, reason in skipped:
            print(f"  - {handler_name}: {reason}")

    print(f"\n✓ All {len(passed)} dispatchable handlers have valid signatures")
    return 0


def main():
    """Run smoke test."""
    # Load .env if it exists
    try:
        from dotenv import load_dotenv
        load_dotenv()
    except ImportError:
        pass

    print("=" * 70)
    print("HANDLER SMOKE TEST")
    print("=" * 70)
    print("Testing all registered handlers against live Supabase")
    print("This catches signature mismatches before production")
    print("=" * 70)
    print()

    try:
        result = asyncio.run(smoke_test_all_handlers())
        return result
    except Exception as e:
        print(f"\n❌ Smoke test failed: {e}")
        import traceback
        traceback.print_exc()
        return 1


if __name__ == "__main__":
    sys.exit(main())
