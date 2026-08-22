#!/usr/bin/env python3
"""
Eval: no handler in api/handlers.py raises on a missing param, and the
rep-name handlers resolve a person's name to an owner_email.

Why this exists (FIX_DYNAMIC_FALLBACK_PATTERN, PART 3):
  The most common user-visible failure in this system is
  "Hit query budget with partial data. Try a more specific question."
  Its root cause is always the same shape: a precomputed handler could not
  accept the input a person actually typed (a company name, a rep's first
  name), RAISED on a missing ID param, and dropped the whole request to the
  dynamic loop — which then burned the 20k query budget rediscovering data
  the handler already knew how to fetch, and returned nothing useful.

  So: every handler must return a clear error dict on a missing required
  param, never a KeyError. This test enumerates EVERY async handler in
  api/handlers.py and calls it with empty params behind a stub Supabase; any
  raise fails the test.
"""
import sys
import types
import inspect
import asyncio
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
for p in ("", "scripts", "api"):
    sys.path.insert(0, str(REPO / p) if p else str(REPO))

# Stub the supabase package so importing api.handlers / api.db works offline.
if "supabase" not in sys.modules:
    _f = types.ModuleType("supabase")
    _f.create_client = lambda *a, **k: None
    _f.Client = type("Client", (), {})
    sys.modules["supabase"] = _f


class MockSB:
    """Table-aware chainable Supabase stub.

    Returns the rows registered for a table (default: empty), and answers
    every PostgREST-style chain call (select/eq/ilike/in_/range/…/execute)
    that scripts.supabase_client.select_all builds, plus the direct
    upsert/insert chains a couple of write handlers use.
    """
    _CHAIN = {"select", "eq", "neq", "gt", "gte", "lt", "lte", "like",
              "ilike", "in_", "is_", "range", "order", "limit", "upsert",
              "insert", "update", "filter", "match", "single", "maybe_single"}

    def __init__(self, tables=None):
        self._tables = tables or {}
        self._cur = None

    def table(self, name):
        self._cur = name
        return self

    @property
    def not_(self):
        return self

    def execute(self):
        return types.SimpleNamespace(data=list(self._tables.get(self._cur, [])))

    def __getattr__(self, name):
        if name in MockSB._CHAIN:
            return lambda *a, **k: self
        raise AttributeError(name)


def _iter_handlers():
    """Every async handler function defined in api.handlers."""
    from api import handlers as H
    for name, fn in inspect.getmembers(H, inspect.iscoroutinefunction):
        if fn.__module__ != H.__name__:
            continue
        if name.startswith("_"):
            continue
        if name.split("_")[0] in ("query", "generate", "set", "submit"):
            yield name, fn


def test_no_handler_raises_on_missing_params():
    """Every handler returns a clear error dict on missing required params,
    never a KeyError. A raise drops to the dynamic loop, which burns the
    query budget and returns nothing useful — the most common user-visible
    failure in this system."""
    sb = MockSB()
    failures = []
    checked = 0
    for name, fn in _iter_handlers():
        checked += 1
        try:
            result = asyncio.run(fn({}, sb))
        except Exception as e:
            failures.append(f"{name} RAISED {type(e).__name__}: {e}")
            continue
        if not isinstance(result, dict):
            failures.append(f"{name} returned {type(result).__name__}, not a dict")
    return checked, failures


def test_rep_name_resolution():
    """query_rep_pipeline resolves a rep by first name, full name, email, or
    the classifier's rep_email alias — and returns an error dict (never a
    raise) when nothing resolves. This is the query_rep_pipeline case the
    task calls out explicitly."""
    from api.handlers import query_rep_pipeline
    personas = [{"email": "christian@growthbook.io",
                 "name": "Christian Vasquez", "display_name": "Christian"}]
    sb = MockSB({"user_personas": personas})
    cases = []

    def run(params):
        return asyncio.run(query_rep_pipeline(params, sb))

    r_first = run({"rep_name": "Christian"})
    cases.append(("first name resolves",
                  r_first.get("owner_email") == "christian@growthbook.io"
                  and "error" not in r_first))

    r_full = run({"owner": "Christian Vasquez"})
    cases.append(("full name resolves",
                  r_full.get("owner_email") == "christian@growthbook.io"))

    r_alias = run({"rep_email": "christian@growthbook.io"})
    cases.append(("classifier rep_email alias resolves",
                  r_alias.get("owner_email") == "christian@growthbook.io"))

    r_email = run({"owner_email": "christian@growthbook.io"})
    cases.append(("explicit owner_email passes through",
                  r_email.get("owner_email") == "christian@growthbook.io"))

    r_none = run({})
    cases.append(("no rep → error dict, not raise",
                  "error" in r_none and r_none.get("data_gap") is True))

    r_unknown = run({"rep_name": "Nobody McMissing"})
    cases.append(("unknown name → error dict, not raise",
                  "error" in r_unknown))

    return cases


def run():
    print("=" * 72)
    print("HANDLERS — no raise on missing params + rep-name resolution")
    print("=" * 72)
    passed = failed = 0

    checked, failures = test_no_handler_raises_on_missing_params()
    print(f"\n[TEST 1] {checked} handlers called with empty params:")
    if failures:
        failed += len(failures)
        for f in failures:
            print(f"  ❌ {f}")
    else:
        passed += 1
        print(f"  ✓ all {checked} handlers returned a dict, none raised")

    print("\n[TEST 2] query_rep_pipeline name resolution:")
    for label, ok in test_rep_name_resolution():
        if ok:
            passed += 1
            print(f"  ✓ {label}")
        else:
            failed += 1
            print(f"  ❌ {label}")

    print("\n" + "=" * 72)
    print(f"RESULTS: {passed} passed, {failed} failed")
    print("=" * 72)
    return 0 if failed == 0 else 1


if __name__ == "__main__":
    sys.exit(run())
