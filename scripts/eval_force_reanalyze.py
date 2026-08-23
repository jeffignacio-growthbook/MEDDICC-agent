#!/usr/bin/env python3
"""
Eval: FORCE_REANALYZE lever (get_effective_since_date).

The nightly is incremental — it re-scores a deal only when a call arrives that
is newer than the deal's last_analyzed date. That is correct for steady-state,
but it means a change to the scoring pipeline itself (e.g. the iteration-1 score
pin) never reaches already-analyzed deals until each one happens to get a new
call. FORCE_REANALYZE is the operational lever that zeroes the incremental
cutoff so a full re-score can be forced on demand.

This locks the contract:
  - default: cutoff = last_analyzed (skip already-analyzed calls)
  - never analyzed / unparseable date: cutoff = None (full history)
  - FORCE_REANALYZE truthy: cutoff = None regardless of last_analyzed
"""
import os
import sys
import types
from datetime import datetime
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
for p in ("", "scripts", "api"):
    sys.path.insert(0, str(REPO / p) if p else str(REPO))


def _stub_if_missing(name, **attrs):
    """Stub a heavy runtime dep only when it is not installed, so CI (which
    has the real modules) is unaffected. get_effective_since_date touches none
    of these — they are only run_nightly's import-time dependencies."""
    try:
        __import__(name)
    except Exception:
        m = types.ModuleType(name)
        for k, v in attrs.items():
            setattr(m, k, v)
        sys.modules[name] = m


_stub_if_missing("supabase", create_client=lambda *a, **k: None,
                 Client=type("Client", (), {}))
_stub_if_missing("pytz", timezone=lambda *a, **k: None, utc=None)
_stub_if_missing("anthropic", Anthropic=type("Anthropic", (), {}),
                 APIError=type("APIError", (Exception,), {}))

import run_nightly as rn  # noqa: E402

TS = "2026-08-23T22:43:08"
EXPECTED = datetime.fromisoformat(TS)
FAILS = []


def check(name, got, want):
    ok = got == want
    print(f"  {'✓' if ok else '✗'} {name}: {got!r}")
    if not ok:
        FAILS.append(f"{name}: got {got!r}, want {want!r}")


def run():
    print("FORCE_REANALYZE / get_effective_since_date")

    # Default (no env): the incremental guard is active.
    os.environ.pop("FORCE_REANALYZE", None)
    check("analyzed deal keeps its cutoff", rn.get_effective_since_date({"last_analyzed": TS}), EXPECTED)
    check("never-analyzed deal -> None", rn.get_effective_since_date({}), None)
    check("unparseable last_analyzed -> None", rn.get_effective_since_date({"last_analyzed": "not-a-date"}), None)

    # FORCE_REANALYZE overrides last_analyzed regardless of casing.
    for val in ("true", "TRUE", "True"):
        os.environ["FORCE_REANALYZE"] = val
        check(f"force ({val}) -> None", rn.get_effective_since_date({"last_analyzed": TS}), None)

    # Falsey values leave the guard active (default behavior).
    for val in ("false", "", "0", "no"):
        os.environ["FORCE_REANALYZE"] = val
        check(f"non-truthy ({val!r}) keeps cutoff", rn.get_effective_since_date({"last_analyzed": TS}), EXPECTED)
    os.environ.pop("FORCE_REANALYZE", None)

    if FAILS:
        print("\nFAIL:")
        for f in FAILS:
            print("  -", f)
        return 1
    print("\nPASS — force lever and incremental default both correct.")
    return 0


if __name__ == "__main__":
    sys.exit(run())
