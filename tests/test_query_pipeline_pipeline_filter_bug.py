"""
Regression test for PENDING_WORK.md Low Priority #17: query_pipeline()'s
pipeline_filter ("new_business" / "renewal") has been silently broken
since the handler's first commit (b75a3c1, 2026-09-06).

Symptom (real, reported): a live Slack question, "what's our current
New Business pipeline," shipped a confident, detailed answer titled
"Current New Business Pipeline" that included 11 deals sitting in
Upcoming Renewal / Renewal Engaged stages (deals in the renewal
pipeline that also carry real expansion_arr, correctly counted toward
the general "Incremental ARR Pipeline" metric, but which a
"New Business"-scoped answer must exclude) — with no caveat at all.

Root cause, confirmed via git blame + the actual comparison logic: the
filter compared `pipeline_id` (always the raw numeric HubSpot pipeline
id — "default" or the renewal pipeline's id, "866608541" for this
client) against the SUBSTRING "renewal":

    if pipeline_filter == "new_business" and "renewal" in pipeline_id.lower():
        continue
    if pipeline_filter == "renewal" and "renewal" not in pipeline_id.lower():
        continue

Neither "default" nor "866608541" ever contains the literal word
"renewal", so this check could never match either real value:
pipeline_filter="new_business" silently excluded NOTHING (every deal,
renewal-pipeline included, passed straight through — the exact
reported symptom), and pipeline_filter="renewal" silently excluded
EVERYTHING (always returned zero deals, the opposite failure, in the
same code).

This is a query_pipeline()-only bug: NOT the new deal-type resolver
built earlier tonight (Low Priority #16) — that only ever runs inside
the dynamic_query_loop, and dedicated handlers like query_pipeline()
are dispatched via a completely separate intent-classification path
that never calls resolve_dimension_filter()/scan_question_for_known_
dimension_terms() at all. Confirmed the response's own shape (Pipeline
by Stage / Pipeline by Owner / Top Deals by Size / Data Hygiene
Flags) is unique to query_pipeline()'s structured return value — no
dynamic_query_loop synthesis produces that shape.

Fixed with an exact-value comparison against field_semantics.py's
_RENEWAL_PIPELINE_ID — the SAME constant is_incremental_pipeline()
(used two lines above in this same function) already trusts, rather
than a third, differently-broken copy of the renewal-pipeline concept.
"""
import asyncio
import logging
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))
sys.path.insert(0, str(Path(__file__).parent.parent / "scripts"))

import api.handlers as handlers_module
from field_semantics import _RENEWAL_PIPELINE_ID


class _ListLogHandler(logging.Handler):
    def __init__(self):
        super().__init__()
        self.records = []

    def emit(self, record):
        self.records.append(self.format(record))


def _run_and_capture(coro_fn, *args, **kwargs):
    handler = _ListLogHandler()
    logger = logging.getLogger("api.handlers")
    logger.addHandler(handler)
    logger.setLevel(logging.INFO)
    result, error = None, None
    try:
        result = asyncio.run(coro_fn(*args, **kwargs))
    except Exception as e:
        error = e
    finally:
        logger.removeHandler(handler)
    return result, error, handler.records


class _FakeSupabase:
    pass


# A default-pipeline (New Business) deal and a renewal-pipeline deal
# that ALSO carries real expansion ARR — is_incremental_pipeline()
# correctly counts BOTH toward the general "Incremental ARR Pipeline"
# metric (the renewal one via its expansion_arr), matching the real
# reported incident shape exactly: a renewal-stage deal with real
# incremental ARR, which pipeline_filter="new_business" must exclude
# but the general (unfiltered) view correctly includes.
NEW_BUSINESS_DEAL = {
    "deal_id": "1", "company_name": "Acme", "deal_value": 100000,
    "stage": "qualifiedtobuy", "close_date": "2026-10-01",
    "owner_email": "rep@growthbook.io", "pipeline_id": "default",
    "expansion_arr": 0, "new_arr": 100000, "renewal_revenue": 0,
}
RENEWAL_DEAL_WITH_EXPANSION = {
    "deal_id": "2", "company_name": "RenewCo", "deal_value": 75000,
    "stage": "1297321619", "close_date": "2026-10-15",
    "owner_email": "rep@growthbook.io", "pipeline_id": _RENEWAL_PIPELINE_ID,
    "expansion_arr": 75000, "new_arr": 0, "renewal_revenue": 20000,
}
DEALS = [NEW_BUSINESS_DEAL, RENEWAL_DEAL_WITH_EXPANSION]


def _fake_select_all(sb, table, columns=None, filters=None):
    if table == "deals":
        return DEALS
    return []


def test_renewal_pipeline_id_is_never_a_substring_match_for_renewal():
    """Structural proof of the root cause itself: the real renewal
    pipeline id is purely numeric and never contains the word
    "renewal" — confirming the old substring check could never have
    worked in either direction."""
    assert "renewal" not in _RENEWAL_PIPELINE_ID.lower(), (
        f"if this ever fails, the renewal pipeline id itself changed to "
        f"contain the word 'renewal' — re-check whether the substring "
        f"bug this test guards against is still real"
    )
    print(f"✓ the real renewal pipeline id ({_RENEWAL_PIPELINE_ID!r}) "
          f"never contains the substring 'renewal' — the old check "
          f"could never have matched it")


def test_no_pipeline_filter_includes_both_deals_via_incremental_arr():
    """Baseline (no pipeline_filter): both deals correctly count toward
    the general Incremental ARR pipeline — the renewal-pipeline deal
    via its real expansion_arr, matching is_incremental_pipeline()'s
    own documented definition. Confirms the fix below doesn't change
    the UNFILTERED case's behavior."""
    orig = handlers_module.select_all
    handlers_module.select_all = _fake_select_all
    try:
        result, error, _ = _run_and_capture(
            handlers_module.query_pipeline, {}, _FakeSupabase())
    finally:
        handlers_module.select_all = orig

    assert error is None, f"handler raised: {error!r}"
    assert result["total_deals"] == 2, (
        f"expected both deals counted in the unfiltered Incremental ARR "
        f"pipeline — got total_deals={result['total_deals']}"
    )
    names = {d["company_name"] for d in result["deals"]}
    assert names == {"Acme", "RenewCo"}
    print("✓ with no pipeline_filter, both deals correctly count toward "
          "the general Incremental ARR pipeline")


def test_pipeline_filter_new_business_excludes_the_renewal_pipeline_deal():
    """The core bug: pipeline_filter='new_business' must exclude the
    renewal-pipeline deal even though it has real expansion_arr — this
    is exactly the live incident (11 Upcoming Renewal/Renewal Engaged
    deals shipped under a 'New Business Pipeline' heading)."""
    orig = handlers_module.select_all
    handlers_module.select_all = _fake_select_all
    try:
        result, error, records = _run_and_capture(
            handlers_module.query_pipeline,
            {"pipeline_filter": "new_business"}, _FakeSupabase())
    finally:
        handlers_module.select_all = orig

    assert error is None, f"handler raised: {error!r}"
    names = {d["company_name"] for d in result["deals"]}
    assert names == {"Acme"}, (
        f"pipeline_filter='new_business' must exclude the renewal-"
        f"pipeline deal (RenewCo) — got: {names!r}. If RenewCo is "
        f"present, the substring-match bug ('renewal' in pipeline_id) "
        f"has regressed."
    )
    assert result["total_deals"] == 1

    filter_logs = [r for r in records if "[QUERY_PIPELINE_FILTER]" in r]
    assert filter_logs, "expected the filter log line to fire"
    assert "pipeline_filter='new_business'" in filter_logs[0], (
        f"expected pipeline_filter to be visible in the defensive log "
        f"line (previously invisible — see this file's module "
        f"docstring) — got: {filter_logs[0]!r}"
    )
    print("✓ pipeline_filter='new_business' correctly excludes the "
          "renewal-pipeline deal, and the filter is now visible in logs")


def test_pipeline_filter_renewal_returns_the_renewal_deal_not_zero():
    """The opposite-direction failure from the same bug:
    pipeline_filter='renewal' used to silently exclude EVERYTHING
    (since the substring check could never match), always returning
    zero deals. Must now correctly return the renewal-pipeline deal
    and exclude the New Business one."""
    orig = handlers_module.select_all
    handlers_module.select_all = _fake_select_all
    try:
        result, error, _ = _run_and_capture(
            handlers_module.query_pipeline,
            {"pipeline_filter": "renewal"}, _FakeSupabase())
    finally:
        handlers_module.select_all = orig

    assert error is None, f"handler raised: {error!r}"
    names = {d["company_name"] for d in result["deals"]}
    assert names == {"RenewCo"}, (
        f"pipeline_filter='renewal' must return the renewal-pipeline "
        f"deal and exclude the New Business one — got: {names!r}. The "
        f"old bug returned ZERO deals here in every case."
    )
    assert result["total_deals"] == 1
    print("✓ pipeline_filter='renewal' correctly returns the renewal-"
          "pipeline deal (the old bug always returned zero here)")


if __name__ == "__main__":
    test_renewal_pipeline_id_is_never_a_substring_match_for_renewal()
    test_no_pipeline_filter_includes_both_deals_via_incremental_arr()
    test_pipeline_filter_new_business_excludes_the_renewal_pipeline_deal()
    test_pipeline_filter_renewal_returns_the_renewal_deal_not_zero()
    print("\n✅ All tests passed")
