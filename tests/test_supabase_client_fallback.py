"""
2026-09-11: a live GitHub Actions CI run (ubuntu-latest, a fresh `pip
install -r requirements.txt` with no venv) failed twice, identically
(ruled out as a one-run flake) with:

    ImportError: cannot import name 'ClientOptions' from 'supabase'
    (unknown location)

at api/db.py's top-level `from supabase import create_client, Client,
ClientOptions` — the import added for the retry-transport fix earlier
the same night. This could NOT be reproduced in this sandbox even in a
genuinely fresh, isolated virtualenv install of the identical pinned
requirements — the specific trigger in GitHub's hosted runner is still
unknown (tracked in PENDING_WORK.md as a follow-up investigation, not
blocking this fix).

The actual risk: an unguarded top-level ClientOptions import crashes
the ENTIRE app before anything runs, in any environment where this
reproduces — including, plausibly, Railway's own deploy process. That
turns "some requests occasionally fail and retry" into "the app is
down," a strictly worse outcome than the connection bug the retry
transport was built to fix in the first place.

Fixed by moving the ClientOptions import inside create_resilient_
supabase_client()'s own try block (scripts/supabase_client.py) — lazy,
not top-level — so any import-time failure building the resilient
client degrades to a plain create_client(url, key) with no retry
protection, logs a clear warning, and never propagates. api/db.py's
own top-level import was also fixed (it no longer imports ClientOptions
directly at all — that's now entirely create_resilient_supabase_
client()'s concern).

This file proves the trap actually springs, the same standard as every
other gate this session: not just that the happy path works (that was
already covered when the retry transport shipped), but that FORCING
the exact failure shape still produces a working client, not a crash.
"""
import builtins
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))
sys.path.insert(0, str(Path(__file__).parent.parent / "scripts"))

import supabase_client as sc
from supabase import Client


def _install_blocked_import(blocked_name):
    """Monkeypatches builtins.__import__ so `from supabase import
    <blocked_name>` raises ImportError, exactly reproducing the CI
    failure shape, while every other import (including `from supabase
    import create_client, Client`) proceeds normally. Returns a
    restore() callable."""
    orig_import = builtins.__import__

    def fake_import(name, globals=None, locals=None, fromlist=(), level=0):
        if name == "supabase" and fromlist and blocked_name in fromlist:
            raise ImportError(
                f"simulated: cannot import name '{blocked_name}' from "
                f"'supabase' (unknown location)"
            )
        return orig_import(name, globals, locals, fromlist, level)

    builtins.__import__ = fake_import

    def restore():
        builtins.__import__ = orig_import

    return restore


def test_happy_path_still_uses_the_retry_transport_when_available():
    """Regression control: when ClientOptions imports fine (the normal
    case, and what this sandbox's environment actually has), the
    resilient transport must still be wired in — this fix must not
    accidentally disable the retry protection in the common case."""
    client = sc.create_resilient_supabase_client(
        "https://example.supabase.co", "fake-key")
    assert isinstance(client, Client)
    # postgrest's own Client exposes the underlying httpx.Client as .session
    transport = client.postgrest.session._transport
    assert isinstance(transport, sc._RetryOnDeadConnectionTransport), (
        f"expected the retry transport wired in on the happy path — got: "
        f"{type(transport)!r}"
    )
    print("✓ the happy path still wires in the retry transport when ClientOptions is available")


def test_forced_client_options_import_failure_still_returns_a_working_client():
    """The core fix, proven by forcing the exact failure shape from the
    live CI log: 'from supabase import ClientOptions' raising ImportError
    must NOT propagate out of create_resilient_supabase_client() — it
    must degrade to a plain, working client instead."""
    restore = _install_blocked_import("ClientOptions")
    try:
        client = sc.create_resilient_supabase_client(
            "https://example.supabase.co", "fake-key")
    finally:
        restore()

    assert isinstance(client, Client), (
        f"expected a real, working Supabase client even with ClientOptions "
        f"import blocked — got: {type(client)!r}"
    )
    print("✓ a forced ClientOptions ImportError still produces a working, plain Supabase client")


def test_forced_failure_logs_a_clear_warning_not_silence():
    """The fallback must be loud, not silent — a warning naming what
    happened, so a degraded environment shows up in logs rather than
    only being discoverable by noticing retries never happen."""
    import logging

    class _ListLogHandler(logging.Handler):
        def __init__(self):
            super().__init__()
            self.records = []

        def emit(self, record):
            self.records.append(self.format(record))

    handler = _ListLogHandler()
    logger = logging.getLogger("supabase_client")
    logger.addHandler(handler)
    logger.setLevel(logging.WARNING)

    restore = _install_blocked_import("ClientOptions")
    try:
        sc.create_resilient_supabase_client("https://example.supabase.co", "fake-key")
    finally:
        restore()
        logger.removeHandler(handler)

    matches = [r for r in handler.records if "[SUPABASE_RETRY]" in r]
    assert matches, f"expected a [SUPABASE_RETRY] warning on fallback — got: {handler.records!r}"
    assert "fall" in matches[0].lower() or "fallback" in matches[0].lower(), (
        f"expected the warning to name the fallback happening — got: {matches[0]!r}"
    )
    print("✓ the fallback logs a clear, findable warning rather than failing silently")


def test_any_exception_during_wiring_falls_back_not_just_importerror():
    """Broader than the exact reported bug: the fallback must catch ANY
    exception raised while building the resilient client (e.g. httpx's
    own transport construction failing for an unrelated reason), not
    only ImportError specifically — per the explicit ask that this
    handle 'any import-time failure', not one narrow exception type."""
    import supabase_client as sc_module

    orig_resilient_client = sc_module._resilient_httpx_client

    def broken_resilient_client():
        raise RuntimeError("simulated: unrelated failure building the httpx client")

    sc_module._resilient_httpx_client = broken_resilient_client
    try:
        client = sc_module.create_resilient_supabase_client(
            "https://example.supabase.co", "fake-key")
    finally:
        sc_module._resilient_httpx_client = orig_resilient_client

    assert isinstance(client, Client), (
        f"expected a working client even when the transport-building step "
        f"itself raises a non-ImportError exception — got: {type(client)!r}"
    )
    print("✓ any exception building the resilient transport falls back, not just ImportError")


def test_api_db_module_imports_cleanly_even_with_client_options_blocked():
    """The actual crash from the CI log happened at MODULE IMPORT TIME —
    `from supabase import create_client, Client, ClientOptions` at the
    top of api/db.py, before get_supabase() is ever called. Confirms
    api/db.py no longer imports ClientOptions directly at all (that
    risk now lives entirely inside create_resilient_supabase_client()'s
    own try block), so importing api.db can never raise on this."""
    import ast
    api_db_source = (Path(__file__).parent.parent / "api" / "db.py").read_text()
    tree = ast.parse(api_db_source)
    top_level_imports = [
        alias.name
        for node in ast.walk(tree)
        if isinstance(node, ast.ImportFrom) and node.module == "supabase"
        for alias in node.names
    ]
    assert "ClientOptions" not in top_level_imports, (
        f"api/db.py must not import ClientOptions directly at module level "
        f"— that's exactly the line that crashed in the live CI log. Found "
        f"top-level supabase imports: {top_level_imports!r}"
    )
    print("✓ api/db.py no longer imports ClientOptions at module level — "
          "that risk lives entirely inside create_resilient_supabase_client()")


if __name__ == "__main__":
    tests = [
        test_happy_path_still_uses_the_retry_transport_when_available,
        test_forced_client_options_import_failure_still_returns_a_working_client,
        test_forced_failure_logs_a_clear_warning_not_silence,
        test_any_exception_during_wiring_falls_back_not_just_importerror,
        test_api_db_module_imports_cleanly_even_with_client_options_blocked,
    ]
    failed = 0
    for t in tests:
        try:
            t()
        except AssertionError as e:
            failed += 1
            print(f"✗ {t.__name__}: {e}")
    if failed:
        print(f"\n{failed}/{len(tests)} tests FAILED")
        sys.exit(1)
    print(f"\n✅ All {len(tests)} tests passed")
