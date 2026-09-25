#!/usr/bin/env python3
"""
scripts/eval_handler_descriptions.py (Pre-Merge Gate Tests, first step)
decides what a handler is by rule, not by a hand-kept exclusion list.

It listed every public callable in api.handlers minus KNOWN_NON_HANDLERS.
#30 (2026-09-23) imported incremental_arr into api.handlers; nobody added
it to the list, so the eval has failed ever since ("Missing descriptions
for 1 handlers: {'incremental_arr'}"), and because the gate stops at its
first failure, none of its later checks ran in CI from then on.

The router dispatches a classified intent as getattr(handlers, name)(params,
sb) and awaits it, so a handler is exactly an async callable reachable on
api.handlers, wherever it is defined (query_upcoming_renewals comes from
api.handlers_renewal). Sync helpers and imports can no longer break the
gate; an async handler without a description still does.
"""
import asyncio
import importlib.util
import sys
from pathlib import Path

REPO = Path(__file__).parent.parent
sys.path.insert(0, str(REPO))
sys.path.insert(0, str(REPO / "scripts"))

import logging  # noqa: E402
logging.disable(logging.CRITICAL)

import api.handlers as handlers  # noqa: E402

spec = importlib.util.spec_from_file_location("eval_hd", REPO / "scripts" / "eval_handler_descriptions.py")
eval_hd = importlib.util.module_from_spec(spec)
spec.loader.exec_module(eval_hd)


def _run():
    eval_hd.test_handler_descriptions_complete()


def test_passes_on_the_real_module():
    _run()
    print("✓ the eval passes on api.handlers as it is (incremental_arr import included)")


def test_an_imported_sync_helper_does_not_break_it():
    handlers.some_new_helper = lambda x: x
    try:
        _run()
    finally:
        del handlers.some_new_helper
    print("✓ a sync helper imported into api.handlers is not counted as a handler")


def test_an_async_handler_without_a_description_still_fails():
    async def query_undescribed(params, sb):
        return {}
    handlers.query_undescribed = query_undescribed
    try:
        try:
            _run()
        except AssertionError as e:
            assert "query_undescribed" in str(e), e
        else:
            raise AssertionError("an undescribed async handler must fail the eval")
    finally:
        del handlers.query_undescribed
    print("✓ an async handler with no HANDLER_DESCRIPTIONS entry still fails the eval")


if __name__ == "__main__":
    test_passes_on_the_real_module()
    test_an_imported_sync_helper_does_not_break_it()
    test_an_async_handler_without_a_description_still_fails()
    print("\n✅ All tests passed")
