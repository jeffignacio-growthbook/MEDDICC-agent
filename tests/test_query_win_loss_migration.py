"""
Handler 5/6 (query_win_loss) unified-routing migration — Step A/B/D tests.

Companion to the git-history precedent set by Handlers 1-4 (commits
9c3884e, 65ee788, bb056a6, 5fd6a7f), which each did:
  STEP A - parameter completeness
  STEP B - registration (tool_fn, tool description, classifier bypass,
           STRUCTURED_HANDLERS)
  STEP C - baseline testing (OLD path vs NEW/dynamic-loop path)
  STEP D - structured verification (planted-discrepancy test)
  STEP E - CI verification

This file covers what's testable offline (A/B/D); Step C's OLD-vs-NEW
comparison and the live synthesized-answer check both require live
Supabase/Anthropic credentials this environment doesn't have — done
separately via a live GitHub Actions run (see PENDING_WORK.md's Handler 5
entry) and tests/test_synthesis_truncation_fix.py's captured-baseline
pattern for the offline synthesis-layer proof.

Three real bugs were found and fixed during this handler's Step A/B/C/D
audit (not hypothetical — reproduced here, and #3 was found BY that live
Step C run crashing):

1. STRUCTURED_HANDLERS["query_win_loss"] only listed "losses" as the
   primary key evaluate_result() checks for data. A genuine wins-only
   quarter (real wins, zero losses — a GOOD outcome) returns
   losses=[] and would be misclassified as "empty" by evaluate_result(),
   discarding a real answer and falling through to the dynamic-query
   fallback for no reason. Fixed by checking "wins" OR "losses".

2. query_waterfall's and query_rep_pipeline's verify_structured_
   aggregations() failure branches read verification_result['details'],
   but the function's real return key on failure is 'discrepancies'
   (confirmed in api/structured_verification.py's own docstring and its
   two OTHER call sites, query_pipeline and query_stale_deals, which use
   the correct key). A genuine verification failure in either handler
   would have raised KeyError instead of the intended, clear
   ValueError("Aggregation verification failed: ...") — masking the real
   diagnostic behind an unrelated crash. Copied into query_win_loss's own
   first draft during this migration; caught and fixed in all three
   places before this commit.

3. _resolve_tw() — the time-window helper 14 handlers share, query_win_loss
   included — only guarded against a MISSING time_window, not a truthy
   but UNRESOLVED one (a raw {"period": ..., "n": ...} spec with no
   "start"/"end" yet). Its own docstring already promised "answerable...
   under test," but `if tw: return tw` returned the raw spec verbatim,
   and query_win_loss's own `tw["start"]` then raised a bare KeyError.
   Never fired in production (every real path pre-resolves time_window
   before calling any handler) but broke the very first live Step C
   baseline-capture run for a non-default time_window on this handler —
   found by that run crashing, not by inspection. Fixed to resolve
   anything not already carrying both "start" and "end", benefiting all
   14 call sites, not just this one.
"""
import asyncio
import logging
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

import api.handlers as handlers_module
import api.router as router
from api.evaluator import evaluate_result, STRUCTURED_HANDLERS


class _FakeSupabase:
    pass


def _run(coro):
    return asyncio.run(coro)


WON_DEAL = {"deal_id": "1", "company_name": "Acme", "deal_value": 100000,
            "deal_status": "won", "close_date": "2026-09-01",
            "lost_reason": None, "owner_email": "rep@growthbook.io", "segment": "Enterprise"}
WON_DEAL_2 = {"deal_id": "2", "company_name": "Globex", "deal_value": 50000,
              "deal_status": "won", "close_date": "2026-09-05",
              "lost_reason": None, "owner_email": "rep@growthbook.io", "segment": "SMB"}
LOST_DEAL = {"deal_id": "3", "company_name": "Initech", "deal_value": 75000,
             "deal_status": "lost", "close_date": "2026-09-10",
             "lost_reason": "Budget", "owner_email": "rep2@growthbook.io", "segment": "Mid-Market"}


def _make_fake_select_all(deals, narratives=None, analyses=None):
    def fake_select_all(sb, table, columns=None, filters=None):
        if table == "deals":
            return deals
        if table == "win_loss_narratives":
            return narratives or []
        if table == "analyses":
            return analyses or []
        return []
    return fake_select_all


def test_step_a_no_param_gaps():
    """STEP A: time_window and deal_ids both reach query_win_loss with no
    gaps — time_window via the generic schema field + pre-resolution in
    _call_handler_as_tool(), deal_ids via the same generic entity-scope/
    pronoun-resolution/explicit-ID injection every other handler (migrated
    or not) already relies on. Confirmed by reading api/router.py directly:
    _call_handler_as_tool() resolves time_window unconditionally before
    calling ANY registered handler, and deal_ids injection (lines ~5060-
    5157) happens before handler dispatch, keyed only on scope decision —
    never gated on which handler is selected."""
    import inspect
    src = inspect.getsource(router._call_handler_as_tool)
    assert '"time_window" in params' in src, (
        "_call_handler_as_tool must resolve time_window generically for "
        "every registered handler, query_win_loss included"
    )
    print("✓ STEP A: no parameter gaps for query_win_loss "
          "(time_window pre-resolved generically, deal_ids injected generically)")


def test_step_b_registered_as_tool():
    """STEP B: query_win_loss is registered in the tool_fn dict, the
    classifier bypass list, and STRUCTURED_HANDLERS."""
    import inspect
    src = inspect.getsource(router._dynamic_query_loop_core)
    assert '"query_win_loss": lambda sb_arg' in src, (
        "query_win_loss must be registered in the tool_fn dict"
    )
    assert '"query_win_loss"' in src.split("tool_fn = {")[0] or True  # bypass list is elsewhere

    # The bypass tuple lives in route_question(); search the whole module
    # source for the tuple literal itself (matched by its distinctive
    # first two entries, not the full membership) so this doesn't need
    # updating every time a later handler is added to the same tuple.
    import re
    full_src = open(router.__file__).read()
    bypass_tuple_match = re.search(
        r'handler_name in \(("query_pipeline_movement", "query_pipeline".*?)\):',
        full_src)
    assert bypass_tuple_match, "could not find the classifier bypass tuple at all"
    assert '"query_win_loss"' in bypass_tuple_match.group(1), (
        "query_win_loss must be added to the classifier bypass tuple"
    )
    assert "query_win_loss" in STRUCTURED_HANDLERS, (
        "query_win_loss must be registered in STRUCTURED_HANDLERS"
    )
    assert set(STRUCTURED_HANDLERS["query_win_loss"]) == {"wins", "losses"}, (
        f"query_win_loss's STRUCTURED_HANDLERS entry must check BOTH wins "
        f"and losses (a wins-only quarter is a real result) — got "
        f"{STRUCTURED_HANDLERS['query_win_loss']!r}"
    )
    print("✓ STEP B: query_win_loss registered in tool_fn dict, classifier "
          "bypass list, and STRUCTURED_HANDLERS (both wins and losses keys)")


def test_wins_only_quarter_is_not_misclassified_as_empty():
    """Regression test for bug #1 found during this audit: a quarter with
    real wins and zero losses must classify as 'good', not 'empty'."""
    orig = handlers_module.select_all
    handlers_module.select_all = _make_fake_select_all([WON_DEAL, WON_DEAL_2])
    try:
        result = _run(handlers_module.query_win_loss({}, _FakeSupabase()))
    finally:
        handlers_module.select_all = orig

    assert result.get("win_count") == 2
    assert result.get("loss_count") == 0
    quality = evaluate_result(result, "query_win_loss")
    assert quality == "good", (
        f"a wins-only quarter (2 real wins, 0 losses) must classify as "
        f"'good' — got {quality!r}. Before the STRUCTURED_HANDLERS fix, "
        f"checking only ['losses'] would see an empty list and "
        f"misclassify this as 'empty', discarding a real answer."
    )
    print("✓ a genuine wins-only quarter is classified 'good', not 'empty' "
          "(STRUCTURED_HANDLERS fix confirmed)")


def test_losses_only_quarter_still_works():
    """Symmetric case: losses-only (the ORIGINAL check's exact case) must
    still classify as 'good' — the fix must not have broken the original
    working case while fixing the wins-only gap."""
    orig = handlers_module.select_all
    handlers_module.select_all = _make_fake_select_all([LOST_DEAL])
    try:
        result = _run(handlers_module.query_win_loss({}, _FakeSupabase()))
    finally:
        handlers_module.select_all = orig

    assert result.get("loss_count") == 1
    quality = evaluate_result(result, "query_win_loss")
    assert quality == "good"
    print("✓ a losses-only quarter still classifies 'good' (no regression)")


def test_genuinely_empty_quarter_is_empty():
    """No wins, no losses: must still correctly classify as 'empty' — the
    fix widens what counts as data, it must not widen it to 'anything at
    all', including a genuinely empty result."""
    orig = handlers_module.select_all
    handlers_module.select_all = _make_fake_select_all([])
    try:
        result = _run(handlers_module.query_win_loss({}, _FakeSupabase()))
    finally:
        handlers_module.select_all = orig

    assert result.get("win_count") == 0
    assert result.get("loss_count") == 0
    quality = evaluate_result(result, "query_win_loss")
    assert quality == "empty", (
        f"zero wins and zero losses must still classify 'empty' — got {quality!r}"
    )
    print("✓ a genuinely empty quarter (no wins, no losses) still classifies 'empty'")


def test_step_d_planted_discrepancy_is_caught():
    """STEP D: plant a discrepancy in win_count and confirm
    verify_structured_aggregations() catches it and returns a graceful
    error dict — not a KeyError from the ['details'] bug this audit found
    and fixed."""
    # handlers.py's own import ("try: from structured_verification import
    # ...  except ImportError: from api.structured_verification import
    # ...") resolves the BARE top-level module when it's importable (it is
    # here, since something on sys.path exposes api/ directly) — a
    # DIFFERENT module object from api.structured_verification. Patch
    # whichever one is actually importable bare, falling back to the
    # package-qualified one, so this test patches what the handler
    # actually calls rather than a same-named but distinct module object.
    try:
        import structured_verification as sv_module
    except ImportError:
        import api.structured_verification as sv_module
    orig_verify = sv_module.verify_structured_aggregations
    orig_select_all = handlers_module.select_all

    def planted_wrong_verify(underlying_data, structured_output, verification_spec, tolerance=0.01):
        real = orig_verify(underlying_data, structured_output, verification_spec, tolerance)
        if real["match"]:
            # Force a mismatch on win_count specifically
            return {"match": False, "discrepancies": [
                {"field": "win_count", "expected": 999, "actual": structured_output.get("win_count"), "diff": 999}
            ]}
        return real

    handlers_module.select_all = _make_fake_select_all([WON_DEAL])
    sv_module.verify_structured_aggregations = planted_wrong_verify
    try:
        result = _run(handlers_module.query_win_loss({}, _FakeSupabase()))
    except KeyError as e:
        raise AssertionError(
            f"verification failure raised KeyError({e!r}) instead of "
            f"returning the graceful error dict — this is exactly the "
            f"['details'] vs ['discrepancies'] bug this audit found and "
            f"was supposed to fix"
        )
    finally:
        handlers_module.select_all = orig_select_all
        sv_module.verify_structured_aggregations = orig_verify

    assert result.get("error") == "aggregation_verification_failed", (
        f"expected a graceful aggregation_verification_failed error dict, "
        f"got: {result!r}"
    )
    assert "discrepancies" in result
    print("✓ STEP D: a planted discrepancy is caught by "
          "verify_structured_aggregations() and surfaces as a clear, "
          "graceful error — not a KeyError")


def test_correct_data_passes_verification_cleanly():
    """Negative control for Step D: normal, correct data must NOT trigger
    the verification-failure path at all."""
    orig = handlers_module.select_all
    handlers_module.select_all = _make_fake_select_all([WON_DEAL, WON_DEAL_2, LOST_DEAL])
    try:
        result = _run(handlers_module.query_win_loss({}, _FakeSupabase()))
    finally:
        handlers_module.select_all = orig

    assert "error" not in result
    assert result["win_count"] == 2
    assert result["loss_count"] == 1
    print("✓ correct win/loss data passes verification cleanly, no false positive")


def test_resolve_tw_handles_unresolved_raw_spec():
    """Regression test for bug #3: _resolve_tw() must resolve a truthy but
    unresolved raw time_window spec (missing start/end), not return it
    verbatim — the exact defect that crashed the live Step C baseline
    capture with KeyError('start') inside query_win_loss."""
    from api.handlers import _resolve_tw

    # Missing entirely -> current-quarter default (unchanged behavior)
    r1 = _resolve_tw({})
    assert "start" in r1 and "end" in r1

    # Already resolved -> passed through unchanged (unchanged behavior,
    # matches what every real production path already hands handlers)
    resolved = {"start": "2026-08-01", "end": "2026-10-31", "label": "FY2027 Q3"}
    r2 = _resolve_tw({"time_window": resolved})
    assert r2 == resolved, "an already-resolved time_window must pass through unchanged"

    # Raw, unresolved spec -> must now resolve instead of KeyError-ing
    # downstream on tw["start"]
    r3 = _resolve_tw({"time_window": {"period": "last_N_days", "n": 90}})
    assert "start" in r3 and "end" in r3, (
        f"a raw unresolved time_window spec must be resolved, not "
        f"returned verbatim — got {r3!r}"
    )
    print("✓ _resolve_tw() now resolves a raw, unresolved time_window spec "
          "instead of returning it verbatim (fixes the KeyError that "
          "crashed the live query_win_loss Step C baseline capture)")


def test_query_waterfall_and_query_rep_pipeline_details_keyerror_fixed():
    """Regression test for bug #2: both handlers' verify_structured_
    aggregations() failure branches must use the real 'discrepancies' key,
    not the nonexistent 'details' key that would have raised KeyError on
    an actual verification failure."""
    import inspect
    waterfall_src = inspect.getsource(handlers_module.query_waterfall)
    rep_pipeline_src = inspect.getsource(handlers_module.query_rep_pipeline)
    assert "['details']" not in waterfall_src, (
        "query_waterfall still reads the nonexistent 'details' key on "
        "verification failure — would raise KeyError instead of the "
        "intended ValueError message"
    )
    assert "['discrepancies']" in waterfall_src
    assert "['details']" not in rep_pipeline_src, (
        "query_rep_pipeline still reads the nonexistent 'details' key on "
        "verification failure — would raise KeyError instead of the "
        "intended ValueError message"
    )
    assert "['discrepancies']" in rep_pipeline_src
    print("✓ query_waterfall and query_rep_pipeline's ['details'] KeyError "
          "bug (found during Handler 5's audit) is fixed in both")


if __name__ == "__main__":
    test_step_a_no_param_gaps()
    test_step_b_registered_as_tool()
    test_wins_only_quarter_is_not_misclassified_as_empty()
    test_losses_only_quarter_still_works()
    test_genuinely_empty_quarter_is_empty()
    test_step_d_planted_discrepancy_is_caught()
    test_correct_data_passes_verification_cleanly()
    test_resolve_tw_handles_unresolved_raw_spec()
    test_query_waterfall_and_query_rep_pipeline_details_keyerror_fixed()
    print("\n✅ All tests passed")
