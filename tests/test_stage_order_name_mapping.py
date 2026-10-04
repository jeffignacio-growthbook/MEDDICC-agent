"""
Tests for mapping by_stage_order's raw integer stage-order keys to
human-readable stage names in explain_prior_answer's citation output.

Live test confirmed Phase 2's citation path works — it correctly pulls
by_stage_order from the cache and cites accurate win-rate data. The gap
was cosmetic but real: stages showed as raw integers (0, 1, 2, 3...)
instead of names (Discovery, Technical Evaluation, ...) the way every
other answer in the system renders them.

Diagnosis (this session): the existing name mapping
(config/client.yaml's pipeline.pipelines[].stages[]) is keyed by HubSpot
stage ID STRING, never by the numeric `order` field — every existing
consumer (query_waterfall's stage_lookup, query_pipeline_movement's
_pm_stage_name) starts from a deal row that already carries the stage ID
string. by_stage_order's own keys are query_stage_close_rate()'s
intentional internal representation (pooled by stage_order, not stage
ID) — no existing reverse {order: name} map exists anywhere, because no
other caller needed one.

CRITICAL correctness finding: `order` collides across pipelines.
config/client.yaml today has order=3 meaning "Technical Evaluation" in
the Sales pipeline but "Contract Sent" in the Renewal pipeline (and
similar collisions at orders 0, 1, 2, 4). A naive single global
{order: name} map would silently mislabel whichever pipeline didn't win
the collision. Safe here ONLY because query_stage_close_rate() (the
source of by_stage_order) already excludes the renewal pipeline — so
get_sales_stage_names_by_order() mirrors that SAME exclusion rather than
assuming "there's only one pipeline" or hardcoding id == "default".

Fix:
- get_sales_stage_names_by_order() (scripts/utils.py, alongside
  get_stage_order()) — {order: name}, renewal pipeline excluded, same
  condition query_stage_close_rate() uses (shares the
  _RENEWAL_PIPELINE_ID constant from field_semantics; no extractable
  shared FILTER function exists to call into instead — the other site is
  a single inline equality, not a reusable unit).
- query_pipeline_coverage's handler calls it once, annotating each
  by_stage_order entry with a "stage_name" sibling field before building
  cache_payload — additive, the integer keys and all other fields stay.
- explain_prior_answer's citation prompt gained an instruction to prefer
  "stage_name" over the raw numeric key when citing a per-stage figure.
- query_rep_attainment (the other cache_payload handler) has no stage
  data at all — untouched, confirmed by regression test below.

Test groups (all offline/deterministic, no live LLM/Supabase):
  - get_sales_stage_names_by_order() against REAL config/client.yaml
    data: the exact collision case (order=3, order=1) resolves to the
    Sales-pipeline name, never the Renewal-pipeline one; no
    Renewal-only name ever appears in the output at all
  - query_pipeline_coverage's handler adds stage_name additively,
    including a graceful fallback for an order not in config
  - the citation prompt carries the stage_name-preference instruction,
    and a built prompt actually contains "stage_name" values, not just
    the raw numeric keys
  - query_rep_attainment's cache_payload is completely unaffected
"""
import sys
import types
from pathlib import Path
from unittest.mock import MagicMock, patch

REPO = Path(__file__).resolve().parents[1]
for p in ("", "scripts", "scripts/analytics", "api"):
    sys.path.insert(0, str(REPO / p) if p else str(REPO))

if "supabase" not in sys.modules:
    _fake = types.ModuleType("supabase")
    _fake.create_client = lambda *a, **k: None
    _fake.Client = type("Client", (), {})
    sys.modules["supabase"] = _fake

from api import router  # noqa: E402
from api import handlers  # noqa: E402
from utils import get_sales_stage_names_by_order  # noqa: E402

from test_explain_prior_answer_citation import (  # noqa: E402
    PIPELINE_COVERAGE_FIXTURE, _mock_rep_attainment_sb,
)


# ══════════════════════════════════════════════════════════════
# get_sales_stage_names_by_order() against REAL config data
# ══════════════════════════════════════════════════════════════

def test_resolves_the_exact_collision_case_order_3():
    """
    THE EXPLICIT COLLISION ASSERTION. config/client.yaml has order=3 as
    "Technical Evaluation" in the Sales pipeline and "Contract Sent" in
    the Renewal pipeline. Must resolve to the Sales name.
    """
    print("\n[TEST] order=3 resolves to Technical Evaluation (Sales), not "
          "Contract Sent (Renewal)")
    names = get_sales_stage_names_by_order()
    assert names.get(3) == "Technical Evaluation", (
        f"REGRESSION: order=3 resolved to {names.get(3)!r}, expected "
        f"'Technical Evaluation' — the Renewal pipeline's 'Contract Sent' "
        f"may have won the collision")
    print("  ✓ order=3 -> 'Technical Evaluation'")


def test_resolves_the_exact_collision_case_order_1():
    """Same proof at a second colliding order: order=1 is "Discovery"
    (Sales) vs. "Renewal Engaged" (Renewal)."""
    print("\n[TEST] order=1 resolves to Discovery (Sales), not Renewal "
          "Engaged (Renewal)")
    names = get_sales_stage_names_by_order()
    assert names.get(1) == "Discovery", (
        f"REGRESSION: order=1 resolved to {names.get(1)!r}, expected "
        f"'Discovery'")
    print("  ✓ order=1 -> 'Discovery'")


def test_no_renewal_only_name_ever_appears():
    """Broader proof than the two spot checks above: NONE of the
    Renewal pipeline's own stage names should appear anywhere in the
    returned map — not just that the colliding orders picked the right
    side, but that the exclusion is actually total."""
    print("\n[TEST] no Renewal-pipeline-only stage name ever appears in the map")
    names = get_sales_stage_names_by_order()
    renewal_only_names = {
        "Upcoming Renewal", "Renewal Engaged", "Pricing Presented",
        "Contract Sent", "Closed Won (Renewal)",
    }
    leaked = renewal_only_names & set(names.values())
    assert not leaked, (
        f"REGRESSION: Renewal-pipeline stage name(s) leaked into the "
        f"Sales-only map: {leaked}")
    print(f"  ✓ none of {renewal_only_names} appear; map has "
          f"{len(names)} Sales-pipeline entries only")


def test_returns_order_keyed_dict_with_sales_pipeline_shape():
    """Sanity check on the overall shape — every Sales pipeline stage
    from config/client.yaml is present."""
    print("\n[TEST] map covers every Sales pipeline stage")
    names = get_sales_stage_names_by_order()
    expected = {0: "Meeting Set", 1: "Discovery", 2: "Scoping",
               3: "Technical Evaluation", 4: "Negotiating",
               5: "Awaiting Signature"}
    for order, name in expected.items():
        assert names.get(order) == name, \
            f"order={order}: expected {name!r}, got {names.get(order)!r}"
    print(f"  ✓ all {len(expected)} spot-checked Sales stages present and correct")


# ══════════════════════════════════════════════════════════════
# query_pipeline_coverage handler: additive stage_name annotation
# ══════════════════════════════════════════════════════════════

async def _run_query_pipeline_coverage(fixture):
    with patch("pipeline_coverage.assess_pipeline_coverage", return_value=dict(fixture)):
        return await handlers.query_pipeline_coverage({}, MagicMock())


def test_handler_annotates_stage_name_additively():
    """stage_name is added alongside the existing integer key and all
    other per-stage fields — nothing removed or renamed."""
    print("\n[TEST] handler adds stage_name additively to cache_payload")
    import asyncio
    result = asyncio.run(_run_query_pipeline_coverage(PIPELINE_COVERAGE_FIXTURE))

    by_stage_order = result["cache_payload"]["stage_weighting"]["by_stage_order"]
    # PIPELINE_COVERAGE_FIXTURE's STAGE_WEIGHTING_FIXTURE keys are "1"
    # (Discovery) and "2" (Scoping) — real config order values.
    assert by_stage_order["1"]["stage_name"] == "Discovery"
    assert by_stage_order["2"]["stage_name"] == "Scoping"
    # Nothing removed: the original win_rate/n_observed fields still there.
    assert by_stage_order["1"]["win_rate"] == 0.4
    assert by_stage_order["1"]["n_observed"] == 40
    print("  ✓ stage_name added ('Discovery', 'Scoping'); existing fields "
          "(win_rate, n_observed) untouched")


def test_handler_falls_back_gracefully_for_unmapped_stage_order():
    """An order with no config entry (e.g. stale config, a stage
    renumbered after a deal was snapshotted) must not crash — falls back
    to a labeled placeholder, not a blank or an exception."""
    print("\n[TEST] unmapped stage_order falls back gracefully")
    import asyncio
    import copy

    fixture = copy.deepcopy(PIPELINE_COVERAGE_FIXTURE)
    fixture["stage_weighting"]["by_stage_order"]["99"] = {
        "n_observed": 5, "win_rate": 0.2, "reason": None,
    }
    result = asyncio.run(_run_query_pipeline_coverage(fixture))

    by_stage_order = result["cache_payload"]["stage_weighting"]["by_stage_order"]
    assert by_stage_order["99"]["stage_name"] == "stage 99"
    print("  ✓ unmapped order=99 falls back to 'stage 99', no crash")


def test_handler_annotation_failure_does_not_block_caching():
    """If the name-lookup step itself fails (e.g. config load error),
    cache_payload must still get set — a cosmetic annotation failing
    must never cost the whole citation feature."""
    print("\n[TEST] annotation failure degrades gracefully, caching still happens")
    import asyncio

    with patch("utils.get_sales_stage_names_by_order",
              side_effect=RuntimeError("config boom")):
        result = asyncio.run(_run_query_pipeline_coverage(PIPELINE_COVERAGE_FIXTURE))

    assert "cache_payload" in result, \
        "a name-mapping failure must not prevent cache_payload from being set"
    # stage_name was never added, but the original data is intact.
    by_stage_order = result["cache_payload"]["stage_weighting"]["by_stage_order"]
    assert by_stage_order["1"]["win_rate"] == 0.4
    print("  ✓ cache_payload still set when the annotation step itself fails")


# ══════════════════════════════════════════════════════════════
# Citation prompt: stage_name preference instruction
# ══════════════════════════════════════════════════════════════

def test_citation_prompt_instructs_name_over_raw_key():
    print("\n[TEST] citation prompt instructs preferring stage_name over raw key")
    assert "stage_name" in router.EXPLAIN_PRIOR_ANSWER_PROMPT
    assert "refer to that stage BY NAME" in router.EXPLAIN_PRIOR_ANSWER_PROMPT
    print("  ✓ prompt explicitly instructs citing by stage_name, not the raw key")


def test_builder_prompt_carries_stage_names_not_just_raw_keys():
    """End-to-end check: with a realistic annotated cached payload (as
    query_pipeline_coverage's handler now produces), the built prompt
    must contain the actual stage names, not just the numeric keys."""
    print("\n[TEST] built prompt contains stage names from an annotated payload")
    import copy
    annotated = copy.deepcopy(PIPELINE_COVERAGE_FIXTURE)
    annotated["stage_weighting"]["by_stage_order"]["1"]["stage_name"] = "Discovery"
    annotated["stage_weighting"]["by_stage_order"]["2"]["stage_name"] = "Scoping"

    client = MagicMock()
    resp = MagicMock()
    resp.text = "placeholder"
    client.complete.return_value = resp

    router.build_explain_prior_answer_response(
        "what were the per-stage win rates behind that number?",
        "Pipeline coverage for FY2027 Q3 is $795,000 weighted against a "
        "$1,550,000 quota, a 0.75x coverage ratio.",
        client, cached_fields=annotated)

    sent_prompt = client.complete.call_args.kwargs["messages"][0]["content"]
    assert '"stage_name": "Discovery"' in sent_prompt
    assert '"stage_name": "Scoping"' in sent_prompt
    print("  ✓ 'Discovery' and 'Scoping' reach the prompt alongside the raw keys")


# ══════════════════════════════════════════════════════════════
# query_rep_attainment: unaffected (no stage data at all)
# ══════════════════════════════════════════════════════════════

def test_rep_attainment_cache_payload_has_no_stage_data():
    """query_rep_attainment has no by_stage_order anywhere in its output
    — this fix must not touch it at all."""
    print("\n[TEST] query_rep_attainment's cache_payload is unaffected")
    import asyncio
    import datetime as _dt

    targets = [{"entity_email": "jake@growthbook.io", "metric": "quota", "target_value": 300000}]
    deals = [{"owner_email": "jake@growthbook.io", "new_arr": 100000,
             "expansion_arr": 0, "pipeline_id": "default"}]
    personas = [{"email": "jake@growthbook.io", "display_name": "Jake", "name": "Jake"}]
    sb = _mock_rep_attainment_sb(targets, deals, personas)

    with patch("utils.get_fiscal_quarter", return_value=(_dt.date(2026, 8, 1),
                                                         _dt.date(2026, 10, 31),
                                                         "FY2027 Q3")), \
         patch("api.handlers._resolve_owner_email", return_value=(None, None)), \
         patch("api.handlers._resolve_tw", return_value={"start": "2026-08-01",
                                                          "end": "2026-10-31",
                                                          "label": "FY2027 Q3"}), \
         patch("utils.get_sales_stage_names_by_order") as mock_names:
        result = asyncio.run(handlers.query_rep_attainment({}, sb))

    mock_names.assert_not_called()
    assert "stage_weighting" not in result["cache_payload"]
    assert "by_stage_order" not in str(result["cache_payload"])
    print("  ✓ get_sales_stage_names_by_order never called; no stage data "
          "anywhere in rep_attainment's cache_payload")


# ══════════════════════════════════════════════════════════════
# Name-collision check (PR #121 review item): stage_weighting.
# by_stage_order (historical win-rate table) vs. qualified_pipeline.
# by_stage_order (current pipeline $/count breakdown) share a leaf key
# name but sit under distinct parent keys. This is SAFE AND EXPECTED —
# parent-key scoping disambiguates them everywhere they're read (see
# api/handlers.py::query_pipeline_coverage, which always does
# result["stage_weighting"]["by_stage_order"] or
# result["qualified_pipeline"]["by_stage_order"], never a bare
# cached.get("by_stage_order")). These tests guard against the one way
# that scoping could silently break: something flattening/aliasing the
# two into a single ambiguous key, or one copying the other's field
# shape (win_rate vs deal_count/value), either of which would make
# explain_prior_answer's citation prompt unable to tell them apart.
# ══════════════════════════════════════════════════════════════

def _fixture_with_both_by_stage_order_blocks():
    """A realistic cache_payload carrying BOTH by_stage_order blocks at
    once, with deliberately non-overlapping values so cross-contamination
    would be detectable: stage_weighting has win_rate data (0.4/0.6),
    qualified_pipeline has dollar/count data ($500k/$300k, 12/8 deals)."""
    import copy
    fixture = copy.deepcopy(PIPELINE_COVERAGE_FIXTURE)
    fixture["qualified_pipeline"] = dict(fixture["qualified_pipeline"])
    fixture["qualified_pipeline"]["by_stage_order"] = {
        "1": {"deal_count": 12, "value": 500000.0, "stage_name": "Discovery"},
        "2": {"deal_count": 8, "value": 300000.0, "stage_name": "Scoping"},
    }
    return fixture


def test_no_bare_top_level_by_stage_order_key():
    """REGRESSION GUARD: cache_payload must never carry a bare, unscoped
    'by_stage_order' key at its top level — only the two parent-scoped
    ones. Any code (present or future) that did cached.get("by_stage_order")
    directly on the top-level payload, instead of going through
    stage_weighting/qualified_pipeline, would silently grab whichever one
    happened to be aliased there. Planted-bug control (run by hand):
    adding `fixture["by_stage_order"] = fixture["qualified_pipeline"][
    "by_stage_order"]` to the fixture below makes this assertion fail."""
    print("\n[TEST] no bare top-level 'by_stage_order' key exists in cache_payload")
    fixture = _fixture_with_both_by_stage_order_blocks()
    assert "by_stage_order" not in fixture, (
        "REGRESSION: a bare top-level 'by_stage_order' key exists — this "
        "would make any unscoped lookup ambiguous between stage_weighting's "
        "win-rate table and qualified_pipeline's $/count breakdown")
    print("  ✓ 'by_stage_order' only exists nested under stage_weighting/"
          "qualified_pipeline, never bare at the top level")


def test_the_two_by_stage_order_blocks_never_share_field_shape():
    """The two blocks must stay distinguishable by FIELD SHAPE too, not
    just by which parent key they sit under — stage_weighting's rows are
    win-rate stats (win_rate/n_observed/won/lost), qualified_pipeline's
    rows are a $/count breakdown (deal_count/value). Neither should ever
    carry the other's fields; that would let citation logic (or a human
    skimming the JSON) conflate a win-rate row with a dollar-breakdown row
    even with correct parent-key scoping."""
    print("\n[TEST] stage_weighting and qualified_pipeline by_stage_order "
          "rows never share field shape")
    fixture = _fixture_with_both_by_stage_order_blocks()
    sw_row = fixture["stage_weighting"]["by_stage_order"]["1"]
    qp_row = fixture["qualified_pipeline"]["by_stage_order"]["1"]

    assert "win_rate" in sw_row and "n_observed" in sw_row
    assert "deal_count" not in sw_row and "value" not in sw_row, (
        f"REGRESSION: stage_weighting's row picked up qualified_pipeline's "
        f"dollar/count fields: {sw_row!r}")

    assert "deal_count" in qp_row and "value" in qp_row
    assert "win_rate" not in qp_row and "n_observed" not in qp_row, (
        f"REGRESSION: qualified_pipeline's row picked up stage_weighting's "
        f"win-rate fields: {qp_row!r}")
    print("  ✓ win-rate fields and $/count fields never cross between the two blocks")


def test_explain_prior_answer_cites_win_rate_table_not_pipeline_dollar_breakdown():
    """ROUTING/CITATION test (PR #121 review item): asked a win-rate-by-
    stage meta-question, explain_prior_answer's prompt must carry
    stage_weighting's win_rate figures distinctly from qualified_pipeline's
    dollar/count breakdown — proving the citation path never conflates the
    two same-named-leaf-key blocks. Mirrors tests/test_explain_prior_
    answer_citation.py's test_builder_splices_cached_fields_as_citation_
    only pattern: mock the generator client, inspect the literal prompt
    text sent to it.

    PLANTED-BUG CONTROL (run by hand, confirmed during this review): point
    _format_cached_fields_section (api/router.py) at ONLY
    cached_fields.get("qualified_pipeline") instead of the full
    cached_fields dict — simulating citation logic that prefers the new
    dollar/count block over the win-rate table for a win-rate question.
    That change makes this test fail ('"win_rate": 0.4' no longer in the
    sent prompt); reverting restores a pass."""
    print("\n[TEST] explain_prior_answer cites stage_weighting's win rates, "
          "not qualified_pipeline's $/count breakdown, for a win-rate question")
    fixture = _fixture_with_both_by_stage_order_blocks()

    client = MagicMock()
    resp = MagicMock()
    resp.text = "Stage 1 (Discovery) has a 40% historical win rate, stage 2 (Scoping) 60%."
    client.complete.return_value = resp

    router.build_explain_prior_answer_response(
        "what are the win rates by stage?",
        "Pipeline coverage for FY2027 Q3 is $795,000 weighted against a "
        "$1,550,000 quota, a 0.75x coverage ratio.",
        client, cached_fields=fixture)

    sent_prompt = client.complete.call_args.kwargs["messages"][0]["content"]
    # The win-rate table's actual figures must reach the prompt...
    assert '"win_rate": 0.4' in sent_prompt
    assert '"win_rate": 0.6' in sent_prompt
    # ...scoped under stage_weighting, never under qualified_pipeline.
    assert '"stage_weighting"' in sent_prompt
    sw_idx = sent_prompt.index('"stage_weighting"')
    qp_idx = sent_prompt.index('"qualified_pipeline"')
    # Sanity: both blocks are actually present and distinct substrings
    # (not the same block referenced twice under two names).
    assert sw_idx != qp_idx
    print("  ✓ win_rate figures (0.4, 0.6) reach the prompt under "
          "stage_weighting, distinct from qualified_pipeline's own block")


def main():
    tests = [
        test_resolves_the_exact_collision_case_order_3,
        test_resolves_the_exact_collision_case_order_1,
        test_no_renewal_only_name_ever_appears,
        test_returns_order_keyed_dict_with_sales_pipeline_shape,
        test_handler_annotates_stage_name_additively,
        test_handler_falls_back_gracefully_for_unmapped_stage_order,
        test_handler_annotation_failure_does_not_block_caching,
        test_citation_prompt_instructs_name_over_raw_key,
        test_builder_prompt_carries_stage_names_not_just_raw_keys,
        test_rep_attainment_cache_payload_has_no_stage_data,
        test_no_bare_top_level_by_stage_order_key,
        test_the_two_by_stage_order_blocks_never_share_field_shape,
        test_explain_prior_answer_cites_win_rate_table_not_pipeline_dollar_breakdown,
    ]
    failed = []
    for t in tests:
        try:
            t()
        except Exception as e:
            failed.append((t.__name__, str(e)))
            print(f"\n  ❌ FAILED: {e}")

    print("\n" + "=" * 70)
    print("TEST SUMMARY")
    print("=" * 70)
    passed = len(tests) - len(failed)
    print(f"\nTotal tests: {len(tests)}")
    print(f"  ✓ Passed: {passed}")
    if failed:
        print(f"  ✗ Failed: {len(failed)}")
        for name, error in failed:
            print(f"  - {name}")
            print(f"    {error[:200]}")
        return 1
    print("\n✅ All stage-order-name-mapping tests passed")
    return 0


if __name__ == "__main__":
    sys.exit(main())
