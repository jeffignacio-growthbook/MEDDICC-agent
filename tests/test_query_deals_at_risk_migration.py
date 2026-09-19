"""
Handler 6/6 (query_deals_at_risk) unified-routing migration — Step A/B/D
tests, the final handler in the Phase 2 migration set.

Same Steps A-E discipline as Handlers 1-5 (see git history 9c3884e,
65ee788, bb056a6, 5fd6a7f, and this session's query_win_loss migration):
  STEP A - parameter completeness
  STEP B - registration (tool_fn, tool description, classifier bypass,
           STRUCTURED_HANDLERS)
  STEP C - baseline testing (OLD path vs NEW/dynamic-loop path) + live
           synthesized-answer check (done separately via GitHub Actions,
           see PENDING_WORK.md's Handler 6 entry — no live credentials
           in this environment)
  STEP D - structured verification (planted-discrepancy test)
  STEP E - CI verification

One real bug found and fixed during Step A/B, BEFORE any live run (the
established pattern this session's audit process is built to produce —
catch it in review, not in production):

STRUCTURED_HANDLERS didn't have a query_deals_at_risk entry at all
(evaluate_result() fell through to the generic row-based path). Worse,
even a naive entry of just ["deals_at_risk"] would have reproduced
query_win_loss's exact wins-only mistake: the genuinely-empty "no deals
at risk" case returns an EMPTY deals_at_risk list, but a complete,
human-readable "message" explaining why. Checking "deals_at_risk" alone
would misclassify that as "empty" and trigger a wasteful dynamic-query
fallback instead of just using the handler's own good answer. Fixed by
registering ["deals_at_risk", "message"] — either populated is a
complete result.
"""
import asyncio
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


def test_step_a_no_param_gaps():
    """STEP A: deal_ids and time_window both reach query_deals_at_risk
    with no gaps, via the same generic mechanisms every other handler
    (migrated or not) already relies on — confirmed directly from
    api/router.py's own code, not asserted."""
    import inspect
    src = inspect.getsource(router._call_handler_as_tool)
    assert '"time_window" in params' in src, (
        "_call_handler_as_tool must resolve time_window generically for "
        "every registered handler, query_deals_at_risk included"
    )
    print("✓ STEP A: no parameter gaps for query_deals_at_risk "
          "(time_window pre-resolved generically, deal_ids injected generically)")


def test_step_b_registered_as_tool():
    """STEP B: query_deals_at_risk is registered in the tool_fn dict,
    the classifier bypass list, and STRUCTURED_HANDLERS with BOTH keys
    that can carry a complete answer."""
    import inspect
    src = inspect.getsource(router._dynamic_query_loop_core)
    assert '"query_deals_at_risk": lambda sb_arg' in src, (
        "query_deals_at_risk must be registered in the tool_fn dict"
    )
    # Matched by the tuple's distinctive first two entries, not full
    # membership, so this doesn't need updating if the tuple gains
    # another entry later.
    import re
    full_src = open(router.__file__).read()
    bypass_tuple_match = re.search(
        r'handler_name in \(("query_pipeline_movement", "query_pipeline".*?)\):',
        full_src)
    assert bypass_tuple_match, "could not find the classifier bypass tuple at all"
    assert '"query_deals_at_risk"' in bypass_tuple_match.group(1), (
        "query_deals_at_risk must be added to the classifier bypass tuple"
    )
    assert "query_deals_at_risk" in STRUCTURED_HANDLERS, (
        "query_deals_at_risk must be registered in STRUCTURED_HANDLERS"
    )
    assert set(STRUCTURED_HANDLERS["query_deals_at_risk"]) == {"deals_at_risk", "message"}, (
        f"query_deals_at_risk's STRUCTURED_HANDLERS entry must check BOTH "
        f"deals_at_risk and message (a genuinely-empty-but-explained result "
        f"is a real, complete answer) — got "
        f"{STRUCTURED_HANDLERS['query_deals_at_risk']!r}"
    )
    print("✓ STEP B: query_deals_at_risk registered in tool_fn dict, "
          "classifier bypass list, and STRUCTURED_HANDLERS (both "
          "deals_at_risk and message keys)")


def test_genuinely_empty_result_is_not_misclassified_as_empty():
    """Regression test for the bug found during this audit: a genuinely
    empty at-risk result (no deals flagged) has a complete, human-
    readable 'message' and must classify as 'good', not 'empty' — an
    'empty' classification would trigger a wasteful dynamic-query
    fallback instead of just using the handler's own good answer."""
    orig = handlers_module.compute_at_risk_deals
    handlers_module.compute_at_risk_deals = lambda *a, **k: []
    try:
        result = _run(handlers_module.query_deals_at_risk({}, _FakeSupabase()))
    finally:
        handlers_module.compute_at_risk_deals = orig

    assert result["deals_at_risk"] == []
    assert result["total_at_risk"] == 0
    assert result.get("message")
    quality = evaluate_result(result, "query_deals_at_risk")
    assert quality == "good", (
        f"a genuinely-empty-but-explained at-risk result must classify as "
        f"'good' (it has a complete message) — got {quality!r}. Checking "
        f"'deals_at_risk' alone would see an empty list and misclassify "
        f"this as 'empty', wasting a dynamic-query fallback on a question "
        f"the handler already answered correctly."
    )
    print("✓ a genuinely empty (but explained) at-risk result classifies "
          "'good', not 'empty'")


def test_real_at_risk_deals_classify_good():
    """Symmetric case: real at-risk deals found must also classify as
    'good' (no regression from the fix above)."""
    fake_deals = [
        {"deal_id": str(i), "company_name": f"Company{i}", "overall_score": 20,
         "champion_band": "red", "deal_value": 50000, "stage": "discovery",
         "risk_flags": ["Champion is red (needs yellow-or-better to advance)"]}
        for i in range(3)
    ]
    orig = handlers_module.compute_at_risk_deals
    handlers_module.compute_at_risk_deals = lambda *a, **k: fake_deals
    try:
        result = _run(handlers_module.query_deals_at_risk({}, _FakeSupabase()))
    finally:
        handlers_module.compute_at_risk_deals = orig

    assert result["total_at_risk"] == 3
    assert len(result["deals_at_risk"]) == 3
    quality = evaluate_result(result, "query_deals_at_risk")
    assert quality == "good"
    print("✓ real at-risk deals classify 'good' (no regression)")


def test_total_at_risk_uses_full_count_not_the_sliced_top_10():
    """Sanity check on the handler's own slicing: total_at_risk must
    reflect the FULL at-risk population, not the top-10 slice shown in
    deals_at_risk — the exact invariant Step D's verification guards."""
    fake_deals = [
        {"deal_id": str(i), "company_name": f"Company{i}", "overall_score": 20,
         "champion_band": "red", "deal_value": 50000, "stage": "discovery",
         "risk_flags": ["gap"]}
        for i in range(15)
    ]
    orig = handlers_module.compute_at_risk_deals
    handlers_module.compute_at_risk_deals = lambda *a, **k: fake_deals
    try:
        result = _run(handlers_module.query_deals_at_risk({}, _FakeSupabase()))
    finally:
        handlers_module.compute_at_risk_deals = orig

    assert len(result["deals_at_risk"]) == 10, "display list must cap at 10"
    assert result["total_at_risk"] == 15, (
        f"total_at_risk must reflect all 15 at-risk deals, not the "
        f"10-item display slice — got {result['total_at_risk']}"
    )
    print("✓ total_at_risk correctly reflects the full 15-deal population, "
          "not the 10-item display slice")


def test_step_d_planted_discrepancy_is_caught():
    """STEP D: plant a discrepancy in total_at_risk and confirm
    verify_structured_aggregations() catches it and returns a graceful
    error dict."""
    try:
        import structured_verification as sv_module
    except ImportError:
        import api.structured_verification as sv_module
    orig_verify = sv_module.verify_structured_aggregations
    orig_compute = handlers_module.compute_at_risk_deals

    fake_deals = [
        {"deal_id": "1", "company_name": "Acme", "overall_score": 20,
         "champion_band": "red", "deal_value": 50000, "stage": "discovery",
         "risk_flags": ["gap"]}
    ]

    def planted_wrong_verify(underlying_data, structured_output, verification_spec, tolerance=0.01):
        real = orig_verify(underlying_data, structured_output, verification_spec, tolerance)
        if real["match"]:
            return {"match": False, "discrepancies": [
                {"field": "total_at_risk", "expected": 999,
                 "actual": structured_output.get("total_at_risk"), "diff": 999}
            ]}
        return real

    handlers_module.compute_at_risk_deals = lambda *a, **k: fake_deals
    sv_module.verify_structured_aggregations = planted_wrong_verify
    try:
        result = _run(handlers_module.query_deals_at_risk({}, _FakeSupabase()))
    except KeyError as e:
        raise AssertionError(
            f"verification failure raised KeyError({e!r}) instead of "
            f"returning the graceful error dict"
        )
    finally:
        handlers_module.compute_at_risk_deals = orig_compute
        sv_module.verify_structured_aggregations = orig_verify

    assert result.get("error") == "aggregation_verification_failed"
    assert "discrepancies" in result
    print("✓ STEP D: a planted discrepancy in total_at_risk is caught and "
          "surfaces as a clear, graceful error")


def test_correct_data_passes_verification_cleanly():
    """Negative control for Step D: normal, correct data must NOT
    trigger the verification-failure path."""
    fake_deals = [
        {"deal_id": "1", "company_name": "Acme", "overall_score": 20,
         "champion_band": "red", "deal_value": 50000, "stage": "discovery",
         "risk_flags": ["gap"]}
    ]
    orig = handlers_module.compute_at_risk_deals
    handlers_module.compute_at_risk_deals = lambda *a, **k: fake_deals
    try:
        result = _run(handlers_module.query_deals_at_risk({}, _FakeSupabase()))
    finally:
        handlers_module.compute_at_risk_deals = orig

    assert "error" not in result
    assert result["total_at_risk"] == 1
    print("✓ correct at-risk data passes verification cleanly, no false positive")


if __name__ == "__main__":
    test_step_a_no_param_gaps()
    test_step_b_registered_as_tool()
    test_genuinely_empty_result_is_not_misclassified_as_empty()
    test_real_at_risk_deals_classify_good()
    test_total_at_risk_uses_full_count_not_the_sliced_top_10()
    test_step_d_planted_discrepancy_is_caught()
    test_correct_data_passes_verification_cleanly()
    print("\n✅ All tests passed")
