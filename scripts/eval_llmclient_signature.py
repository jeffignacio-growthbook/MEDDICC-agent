#!/usr/bin/env python3
"""
Regression tests for LLMClient signature drift.

Two live production bugs traced to the same root cause: LLMClient.complete()'s
signature changed and not every caller was updated.

  1. api/assessor.py passed model= → TypeError → swallowed → constant 0.50
     score. The quality gate was inert for two days.
  2. api/router.py's dynamic_query_loop referenced an undefined
     classifier_client → NameError → a failed handler became a 500 instead of
     a degraded answer.

The existing tests missed both because they mocked the client with a plain
MagicMock, which accepts ANY kwargs — so model= "passed" in the test but blew
up in production. These tests use a STRICT fake whose complete() has the real
signature, plus a static AST audit of every call site.
"""

import sys
import ast
import types
import inspect
import asyncio
import io
import contextlib
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO))
sys.path.insert(0, str(REPO / "scripts"))

# ── Offline import shim ─────────────────────────────────────────────────
# api.router transitively imports supabase (via api.db / supabase_client),
# which is not installed in the offline eval environment. Stub it — these
# tests never touch a real database.
if "supabase" not in sys.modules:
    _fake_supabase = types.ModuleType("supabase")
    _fake_supabase.create_client = lambda *a, **k: None

    class _FakeClient:  # noqa: D401 - placeholder for the type import
        pass

    _fake_supabase.Client = _FakeClient
    sys.modules["supabase"] = _fake_supabase

from llm_client import LLMClient  # noqa: E402


# ── A strict fake that enforces the REAL signature ──────────────────────

class _StrictFakeClient:
    """
    Mimics LLMClient.complete()'s exact signature: (messages, system=None,
    max_tokens=1000). Passing any other kwarg (model=, temperature=, ...)
    raises TypeError — exactly what the real client did in production.

    A plain MagicMock would silently accept the bad kwarg and hide the bug;
    that is why the previous tests passed while production was broken.
    """

    def __init__(self, text: str):
        self._text = text
        self.calls = []

    def complete(self, messages, system=None, max_tokens=1000):
        self.calls.append(
            {"messages": messages, "system": system, "max_tokens": max_tokens}
        )
        return types.SimpleNamespace(
            text=self._text, input_tokens=10, output_tokens=5
        )


# ── Test 1: static call-site audit ──────────────────────────────────────

def _allowed_complete_kwargs():
    """Keyword names the CURRENT complete() signature accepts (minus self)."""
    sig = inspect.signature(LLMClient.complete)
    return {
        name
        for name, p in sig.parameters.items()
        if name != "self"
        and p.kind in (p.POSITIONAL_OR_KEYWORD, p.KEYWORD_ONLY)
    }


def _complete_calls(tree):
    for node in ast.walk(tree):
        if (
            isinstance(node, ast.Call)
            and isinstance(node.func, ast.Attribute)
            and node.func.attr == "complete"
        ):
            yield node


def test_all_llmclient_call_sites_match_signature():
    """Static check: every .complete() call passes only kwargs the current
    signature accepts. Signature drift between LLMClient and its callers has
    now caused a silent quality-gate failure and a hard crash."""
    print("\n[TEST] all .complete() call sites match the signature")

    allowed = _allowed_complete_kwargs()
    print(f"  signature accepts kwargs: {sorted(allowed)}")

    # Production call sites only. eval_/test_ files legitimately drive mocks,
    # and migrate_router.py holds .complete( inside regex STRING literals
    # (never real Call nodes), so exclude those helper files by name.
    targets = sorted(
        set((REPO / "api").rglob("*.py")) | set((REPO / "scripts").rglob("*.py"))
    )
    offenders = []
    scanned = 0
    for path in targets:
        if path.name.startswith(("eval_", "test_")) or path.name.startswith("migrate"):
            continue
        try:
            tree = ast.parse(path.read_text())
        except SyntaxError:
            continue
        scanned += 1
        for call in _complete_calls(tree):
            bad = [kw.arg for kw in call.keywords if kw.arg and kw.arg not in allowed]
            if bad:
                offenders.append(
                    f"{path.relative_to(REPO)}:{call.lineno} passes {bad}"
                )

    print(f"  scanned {scanned} production files")
    assert not offenders, (
        "complete() call sites pass kwargs the signature rejects "
        "(each of these is a swallowed TypeError in production):\n  "
        + "\n  ".join(offenders)
    )
    print("  ✓ every production .complete() call matches the signature")


# ── Test 2: assessor returns a real score, not the 0.50 fallback ─────────

def test_assessor_returns_real_score_not_default():
    """The assessor must produce a computed score. A constant 0.50 means the
    call failed and the gate is inert. This went unnoticed for two days
    because 0.50 looks like a plausible score — the test asserts the call
    SUCCEEDED (via a strict-signature fake), not merely that a number came
    back."""
    print("\n[TEST] assessor returns the real computed score, not 0.50")

    from api.assessor import assess_correctness

    # Strict fake → if a bad kwarg (model=/temperature=) is reintroduced, this
    # raises TypeError, the assessor swallows it to 0.50, and the assert fails.
    fake = _StrictFakeClient('{"correct": true, "score": 0.83, "issue": null}')

    result = asyncio.run(
        assess_correctness(
            question="rank reps by open pipeline value",
            handler_used="query_rep_pipeline",
            tool_results={"deals": [1, 2, 3]},
            # No honest-gap signal words, so we exercise the real LLM path.
            answer=(
                "The three reps with the largest open pipeline this quarter, "
                "ranked by total deal value, with specific figures for each."
            ),
            client=fake,
            budget_used=0.0,
        )
    )

    assert fake.calls, "assessor must actually call complete()"
    # Prove it did NOT re-add a rejected kwarg: the strict fake would have
    # raised and collapsed the score to 0.50.
    assert result.get("score") == 0.83, (
        f"expected the computed 0.83 from the LLM, got {result.get('score')}. "
        "0.50 means complete() raised and was swallowed — the inert-gate bug."
    )
    print("  ✓ assessor returned computed 0.83 (call succeeded, gate live)")


# ── Test 3: dynamic fallback path runs without NameError ─────────────────

def test_dynamic_fallback_path_executes():
    """dynamic_query_loop runs without NameError. This is the fallback for
    handler failures, so a crash here turns a degraded answer into a 500."""
    print("\n[TEST] dynamic_query_loop executes without NameError")

    import api.router as R
    import api.table_classifier as TC
    import api.schema_context as SC

    recorded = {}

    def fake_classify(question, client):
        # The NameError bug passed an *undefined* name as this argument, so it
        # never reached here. Record the client to prove a real one arrives.
        recorded["client"] = client
        return ["deals"]

    def fake_schema(sb, tables_with_descriptions=None):
        return "SCHEMA"

    orig_classify = TC.classify_relevant_tables
    orig_schema = SC.get_schema_context
    TC.classify_relevant_tables = fake_classify
    SC.get_schema_context = fake_schema
    try:
        # Prose (no JSON braces) → the loop's "prose answer" branch returns
        # after a single complete() call, so we don't depend on tool internals.
        prose = (
            "Based on the pipeline data, the largest open deals this quarter "
            "total several million in value across the named accounts."
        )
        fake = _StrictFakeClient(prose)
        params = {
            "time_window": {
                "label": "FY2027 Q3",
                "start": "2026-05-01",
                "end": "2026-07-31",
            }
        }
        result = asyncio.run(
            R.dynamic_query_loop(
                question="what are the biggest open deals?",
                history=[],
                params=params,
                sb=None,
                client=fake,
                classifier_client=fake,
            )
        )
    finally:
        TC.classify_relevant_tables = orig_classify
        SC.get_schema_context = orig_schema

    assert isinstance(result, dict) and result.get("answer"), (
        "dynamic_query_loop must return an answer dict, not raise NameError"
    )
    assert recorded.get("client") is fake, (
        "classify_relevant_tables must receive a real client; the bug passed "
        "an undefined 'classifier_client' name here."
    )
    print("  ✓ fallback loop returned an answer with a real classifier client")


# ── Test 4: handler errors log the actual failure, not just the bucket ───

def test_handler_errors_log_the_exception():
    """A handler raising must log the exception, not only the routing
    decision. query_rep_pipeline's real failure (a returned error dict) was
    invisible in logs — only '→ error' was printed."""
    print("\n[TEST] handler errors log the actual failure")

    import api.router as R

    # (a) A handler that RAISES must log the exception message.
    async def raising_handler(params, sb):
        raise RuntimeError("boom-sentinel-42")

    buf = io.StringIO()
    with contextlib.redirect_stdout(buf):
        tr, quality = asyncio.run(
            R._run_precomputed_handler(raising_handler, "some_handler", {}, None)
        )
    out = buf.getvalue()
    assert quality == "error"
    assert "boom-sentinel-42" in out, (
        "a raising handler must log the exception message, not only the "
        f"routing decision. Captured:\n{out}"
    )
    print("  ✓ raised exception is logged with its message")

    # (b) A handler that RETURNS {"error": ...} must surface WHY — this is the
    #     exact query_rep_pipeline case ("owner_email required ...").
    async def error_dict_handler(params, sb):
        return {"error": "owner_email required — resolve rep name to email"}

    buf2 = io.StringIO()
    with contextlib.redirect_stdout(buf2):
        tr2, quality2 = asyncio.run(
            R._run_precomputed_handler(
                error_dict_handler, "query_rep_pipeline", {}, None
            )
        )
    out2 = buf2.getvalue()
    assert quality2 == "error"
    assert "owner_email required" in out2, (
        "a handler returning {'error': ...} must log the reason, not just "
        f"'→ error'. Captured:\n{out2}"
    )
    print("  ✓ returned error dict logs the reason, not just '→ error'")


def main():
    print("=" * 70)
    print("LLMCLIENT SIGNATURE-DRIFT REGRESSION TESTS")
    print("=" * 70)
    tests = [
        test_all_llmclient_call_sites_match_signature,
        test_assessor_returns_real_score_not_default,
        test_dynamic_fallback_path_executes,
        test_handler_errors_log_the_exception,
    ]
    passed = failed = 0
    for t in tests:
        try:
            t()
            passed += 1
        except AssertionError as e:
            failed += 1
            print(f"\n❌ FAILED: {t.__name__}")
            print(f"   {e}")
        except Exception as e:
            failed += 1
            print(f"\n❌ ERROR in {t.__name__}: {e}")
            import traceback

            traceback.print_exc()

    print("\n" + "=" * 70)
    print(f"RESULTS: {passed} passed, {failed} failed")
    print("=" * 70)
    return 0 if failed == 0 else 1


if __name__ == "__main__":
    sys.exit(main())
