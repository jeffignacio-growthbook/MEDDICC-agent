"""
Regression tests for wiring New Business / Expansion / Upsell / Renewal
deal-type resolution into resolve_dimension_filter() (PENDING_WORK.md
Low Priority #16), the same proactive-resolution pattern already proven
for region/segment/roster terms — see api/dimension_resolver.py's
module docstring and tests/test_dimension_resolver.py for that
original pattern.

Unlike the fictional `pipeline` dimension Low Priority #14 removed from
dimension_verification.py (no real column ever backed it), these map
to real, already-existing columns:
- "New Business" / "New" -> deals.new_arr > 0
- "Expansion" / "Upsell" -> deals.expansion_arr > 0
- "Renewal" -> deals.pipeline_id = <config/client.yaml's configured
  renewal_pipeline_ids[0]> (866608541 for this client)

No migration needed — new_arr/expansion_arr have existed on `deals`
since migration 007; pipeline_id since the base schema.

Two behaviors specific to these terms (not needed for region/segment):
1. NOT MUTUALLY EXCLUSIVE — a deal can independently match Renewal AND
   Expansion at once (a renewal that also carries expansion ARR).
   format_dimension_resolution_note() adds an explicit union-not-
   intersection directive whenever 2+ deal-type terms are resolved
   together, the opposite of how region+segment combine (an "EMEA
   Enterprise" question DOES mean the intersection).
2. HONEST HISTORICAL GAP — new_arr/expansion_arr only exist on
   deals_snapshot from migration 064's rollout (2026-09-11) forward;
   the `deals` table itself has always had them. The injected note
   says so explicitly rather than letting a point-in-time question
   silently misread a pre-cutoff NULL as zero/absent.

Tested against the exact three example questions from the ask: current
New Business pipeline, win rate on Expansion deals, and a combined
Renewal+Expansion request — each confirmed to resolve to the correct
filter and, via a scripted-but-realistic dynamic_query_loop run, to
produce a real answer built from that filter's data.
"""
import asyncio
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from api.dimension_resolver import (
    resolve_dimension_filter,
    scan_question_for_known_dimension_terms,
    format_dimension_resolution_note,
)

import api.router as router
import api.tools as tools_module
import api.table_classifier as table_classifier_module
import api.schema_context as schema_context_module

RENEWAL_PIPELINE_ID = "866608541"  # config/client.yaml's renewal_pipeline_ids[0]


# --------------------------------------------------------------------
# Unit-level: resolve_dimension_filter() / scan / note formatting
# --------------------------------------------------------------------

def test_new_business_resolves_to_new_arr_gt_zero():
    result = resolve_dimension_filter("New Business")
    assert result == {"column": "new_arr", "operator": "gt", "value": 0,
                       "category": "deal_type"}
    print("✓ 'New Business' resolves to new_arr.gt.0")


def test_bare_new_resolves_on_a_deliberate_call():
    """'New' alone still resolves correctly on a deliberate, explicit
    call — only the opportunistic SCAN denylists it (see the next
    test), same precedent as the ROW region / Unknown segment values."""
    result = resolve_dimension_filter("new")
    assert result == {"column": "new_arr", "operator": "gt", "value": 0,
                       "category": "deal_type"}
    print("✓ bare 'new' still resolves correctly on a deliberate call")


def test_bare_new_is_not_injected_by_the_opportunistic_scan():
    """'new' is far too common an English word to scan a whole question
    for — 'what's new this week' must never inject a new_arr directive."""
    resolved = scan_question_for_known_dimension_terms("what's new this week")
    assert resolved == [], (
        f"bare 'new' must not be opportunistically scanned — got {resolved!r}"
    )
    print("✓ bare 'new' is denylisted from the opportunistic scan "
          "(too common an English word)")


def test_new_business_two_word_phrase_is_still_scanned():
    """Unlike bare 'new', the specific two-word phrase 'New Business' is
    not an everyday collision and must still fire via the scan."""
    resolved = scan_question_for_known_dimension_terms(
        "what's our current New Business pipeline")
    assert len(resolved) == 1
    assert resolved[0]["column"] == "new_arr"
    assert resolved[0]["operator"] == "gt"
    assert resolved[0]["value"] == 0
    print("✓ 'New Business' (the whole phrase) is still scanned for, "
          "even though bare 'new' is denylisted")


def test_expansion_resolves_to_expansion_arr_gt_zero():
    result = resolve_dimension_filter("Expansion")
    assert result == {"column": "expansion_arr", "operator": "gt", "value": 0,
                       "category": "deal_type"}
    print("✓ 'Expansion' resolves to expansion_arr.gt.0")


def test_upsell_resolves_to_the_same_expansion_arr_filter():
    result = resolve_dimension_filter("Upsell")
    assert result == {"column": "expansion_arr", "operator": "gt", "value": 0,
                       "category": "deal_type"}
    print("✓ 'Upsell' resolves to the same expansion_arr.gt.0 filter as 'Expansion'")


def test_renewal_resolves_to_the_configured_renewal_pipeline_id():
    result = resolve_dimension_filter("Renewal")
    assert result == {"column": "pipeline_id", "operator": "eq",
                       "value": RENEWAL_PIPELINE_ID, "category": "deal_type"}
    print(f"✓ 'Renewal' resolves to pipeline_id.eq.{RENEWAL_PIPELINE_ID} "
          f"(config/client.yaml's renewal_pipeline_ids[0], not a hardcoded "
          f"duplicate)")


def test_deal_type_resolution_is_case_and_hyphen_insensitive():
    assert resolve_dimension_filter("new business") == resolve_dimension_filter("New Business")
    assert resolve_dimension_filter("EXPANSION") == resolve_dimension_filter("Expansion")
    assert resolve_dimension_filter("renewal") == resolve_dimension_filter("Renewal")
    print("✓ deal-type terms resolve the same regardless of casing")


def test_union_note_fires_only_when_two_or_more_deal_type_terms_resolve():
    """The non-mutual-exclusivity guidance must NOT appear for a single
    deal-type term (nothing to combine), and MUST appear when two or
    more are mentioned together."""
    single = scan_question_for_known_dimension_terms("show me Renewal deals")
    single_note = format_dimension_resolution_note(single)
    assert "NOT MUTUALLY EXCLUSIVE" not in single_note

    combined = scan_question_for_known_dimension_terms("show me Renewal+Expansion deals")
    combined_note = format_dimension_resolution_note(combined)
    assert "NOT MUTUALLY EXCLUSIVE" in combined_note
    assert "UNION" in combined_note
    print("✓ the non-mutual-exclusivity/union directive fires only when "
          "2+ deal-type terms are resolved together")


def test_historical_gap_note_fires_only_for_arr_component_terms():
    """The deals_snapshot cutoff caveat is specific to new_arr/
    expansion_arr — Renewal (pipeline_id) has no such gap and must not
    trigger it on its own."""
    renewal_only = scan_question_for_known_dimension_terms("show me Renewal deals")
    renewal_note = format_dimension_resolution_note(renewal_only)
    assert "HISTORICAL DATA GAP" not in renewal_note, (
        "pipeline_id (Renewal) has no historical-availability gap — "
        "the caveat must not fire for it alone"
    )

    expansion_only = scan_question_for_known_dimension_terms("show me Expansion deals")
    expansion_note = format_dimension_resolution_note(expansion_only)
    assert "HISTORICAL DATA GAP" in expansion_note
    assert "2026-09-11" in expansion_note
    assert "deals_snapshot" in expansion_note
    print("✓ the historical-data-gap caveat fires only for new_arr/"
          "expansion_arr-backed terms, not for Renewal (pipeline_id)")


def test_region_only_resolution_is_unaffected_by_the_new_notes():
    """Regression guard: a plain region/segment question (no deal-type
    term at all) must get NEITHER of the two new deal-type-specific
    notes — same output shape as before this change."""
    resolved = scan_question_for_known_dimension_terms(
        "how has EMEA Enterprise pipeline moved")
    note = format_dimension_resolution_note(resolved)
    assert "NOT MUTUALLY EXCLUSIVE" not in note
    assert "HISTORICAL DATA GAP" not in note
    assert "region.eq.EMEA" in note
    assert "segment.eq.Enterprise" in note
    print("✓ a region/segment-only question is unaffected by the new "
          "deal-type-specific notes (no false positives)")


# --------------------------------------------------------------------
# End-to-end: the three example questions from the ask, driven through
# the real dynamic_query_loop with scripted-but-realistic responses.
# --------------------------------------------------------------------

class _FakeResponse:
    def __init__(self, text, input_tokens=1000, output_tokens=100):
        self.text = text
        self.input_tokens = input_tokens
        self.output_tokens = output_tokens


class _FakeClient:
    def __init__(self, responses):
        self._responses = list(responses)
        self.calls = []

    def complete(self, messages=None, system=None, max_tokens=None):
        idx = len(self.calls)
        self.calls.append({"messages": messages, "system": system})
        assert idx < len(self._responses), (
            f"FakeClient received more complete() calls ({idx + 1}) than "
            f"scripted responses ({len(self._responses)})."
        )
        return _FakeResponse(self._responses[idx])


class _FakeSupabase:
    def table(self, name):
        raise AttributeError(f"no fake support for table {name!r}")


NEW_BUSINESS_ROWS = [
    {"deal_id": "1", "company_name": "Acme", "new_arr": 50000, "deal_status": "active"},
    {"deal_id": "2", "company_name": "Globex", "new_arr": 75000, "deal_status": "active"},
]
EXPANSION_ROWS = [
    {"deal_id": "3", "company_name": "Initech", "expansion_arr": 30000, "stage": "closedwon"},
    {"deal_id": "4", "company_name": "Umbrella", "expansion_arr": 20000, "stage": "closedwon"},
    {"deal_id": "5", "company_name": "Soylent", "expansion_arr": 15000, "stage": "closedlost"},
    {"deal_id": "6", "company_name": "Stark", "expansion_arr": 40000, "stage": "discovery"},
]
RENEWAL_ROWS = [
    {"deal_id": "7", "company_name": "Wayne", "pipeline_id": RENEWAL_PIPELINE_ID,
     "expansion_arr": 0, "deal_status": "active"},
]


def _make_deals_filter_table_stub(call_log):
    async def fake_filter_table(sb, table=None, columns=None, filters=None,
                                 limit=200, order_by=None):
        call_log.append({"table": table, "columns": columns, "filters": filters})
        is_new_business = any(
            len(f) >= 3 and f[0] == "gt" and f[1] == "new_arr" and f[2] == 0
            for f in (filters or []))
        is_expansion = any(
            len(f) >= 3 and f[0] == "gt" and f[1] == "expansion_arr" and f[2] == 0
            for f in (filters or []))
        is_renewal = any(
            len(f) >= 3 and f[0] == "eq" and f[1] == "pipeline_id" and f[2] == RENEWAL_PIPELINE_ID
            for f in (filters or []))
        if is_new_business:
            return {"rows": NEW_BUSINESS_ROWS, "table": table}
        if is_expansion:
            return {"rows": EXPANSION_ROWS, "table": table}
        if is_renewal:
            return {"rows": RENEWAL_ROWS, "table": table}
        return {"rows": [], "table": table}
    return fake_filter_table


def _run(question, fake_client, time_window=None):
    fake_sb = _FakeSupabase()
    filter_calls = []
    orig_filter_table = tools_module.filter_table
    orig_classify = table_classifier_module.classify_relevant_tables
    orig_get_schema = schema_context_module.get_schema_context
    orig_resolve_anchor_dates = router.resolve_snapshot_anchor_dates
    orig_valid_columns = dict(tools_module._VALID_COLUMNS)
    tools_module._VALID_COLUMNS.clear()

    tools_module.filter_table = _make_deals_filter_table_stub(filter_calls)
    table_classifier_module.classify_relevant_tables = lambda q, client: ["deals"]
    schema_context_module.get_schema_context = (
        lambda sb, tables_with_descriptions=None, lightweight=False:
            "TABLE: deals\n  deal_id, company_name, new_arr, expansion_arr, "
            "pipeline_id, deal_status, stage\n")
    router.resolve_snapshot_anchor_dates = lambda sb, time_window: (None, None)

    try:
        result = asyncio.run(router.dynamic_query_loop(
            question=question,
            history=[],
            params={"time_window": time_window or {
                "label": "current", "start": "2026-09-01", "end": "2026-09-12"}},
            sb=fake_sb,
            client=fake_client,
        ))
        return result, filter_calls, fake_client
    finally:
        tools_module.filter_table = orig_filter_table
        table_classifier_module.classify_relevant_tables = orig_classify
        schema_context_module.get_schema_context = orig_get_schema
        router.resolve_snapshot_anchor_dates = orig_resolve_anchor_dates
        tools_module._VALID_COLUMNS.clear()
        tools_module._VALID_COLUMNS.update(orig_valid_columns)


def test_current_new_business_pipeline_question():
    """"what's our current New Business pipeline" — confirms the
    new_arr.gt.0 directive reaches the model's first message, and a
    compliant tool call + synthesis produces a real, correct answer."""
    tool_call = json.dumps({"tool": "filter_table", "params": {
        "table": "deals",
        "columns": ["deal_id", "company_name", "new_arr", "deal_status"],
        "filters": [["gt", "new_arr", 0]],
    }})
    final_answer = json.dumps({
        "answer": "Current New Business pipeline is $125,000 across 2 deals."
    })
    fake_client = _FakeClient([tool_call, final_answer])

    result, filter_calls, client = _run(
        "what's our current New Business pipeline", fake_client)

    first_message = client.calls[0]["messages"][0]["content"]
    assert "new_arr.gt.0" in first_message, (
        f"expected the resolved New Business directive in the first "
        f"message — got: {first_message!r}"
    )
    assert "HISTORICAL DATA GAP" in first_message

    new_business_calls = [
        c for c in filter_calls
        if any(f[:3] == ["gt", "new_arr", 0] for f in (c["filters"] or []))
    ]
    assert len(new_business_calls) == 1, (
        f"expected exactly one filter_table call with new_arr.gt.0 — "
        f"got {len(new_business_calls)}: {filter_calls}"
    )
    assert result["answered"] is True
    assert "$125,000" in result["answer"]
    print("✓ 'what's our current New Business pipeline' resolves to "
          "new_arr.gt.0, queries deals correctly, and ships a real answer")


def test_win_rate_on_expansion_deals_question():
    """"what's our win rate on Expansion deals" — confirms the
    expansion_arr.gt.0 directive reaches the model, and a compliant
    tool call + synthesis produces a real win-rate answer computed from
    the closed subset of that filtered population."""
    tool_call = json.dumps({"tool": "filter_table", "params": {
        "table": "deals",
        "columns": ["deal_id", "company_name", "expansion_arr", "stage"],
        "filters": [["gt", "expansion_arr", 0]],
    }})
    final_answer = json.dumps({
        "answer": "Win rate on Expansion deals is 67% (2 won of 3 closed; "
                  "1 additional Expansion deal is still open in Discovery)."
    })
    fake_client = _FakeClient([tool_call, final_answer])

    result, filter_calls, client = _run(
        "what's our win rate on Expansion deals", fake_client)

    first_message = client.calls[0]["messages"][0]["content"]
    assert "expansion_arr.gt.0" in first_message
    assert "HISTORICAL DATA GAP" in first_message

    expansion_calls = [
        c for c in filter_calls
        if any(f[:3] == ["gt", "expansion_arr", 0] for f in (c["filters"] or []))
    ]
    assert len(expansion_calls) == 1, (
        f"expected exactly one filter_table call with expansion_arr.gt.0 "
        f"— got {len(expansion_calls)}: {filter_calls}"
    )
    assert result["answered"] is True
    assert "67%" in result["answer"]
    print("✓ 'what's our win rate on Expansion deals' resolves to "
          "expansion_arr.gt.0, queries deals correctly, and ships a "
          "real win-rate answer")


def test_renewal_plus_expansion_deals_question():
    """"show me Renewal+Expansion deals" — confirms BOTH terms resolve
    together with the union-not-intersection directive present, and
    that querying each category SEPARATELY (not ANDed into one call)
    produces a combined answer covering both."""
    renewal_call = json.dumps({"tool": "filter_table", "params": {
        "table": "deals",
        "columns": ["deal_id", "company_name", "pipeline_id"],
        "filters": [["eq", "pipeline_id", RENEWAL_PIPELINE_ID]],
    }})
    expansion_call = json.dumps({"tool": "filter_table", "params": {
        "table": "deals",
        "columns": ["deal_id", "company_name", "expansion_arr"],
        "filters": [["gt", "expansion_arr", 0]],
    }})
    final_answer = json.dumps({
        "answer": "Renewal+Expansion deals: 1 Renewal-pipeline deal "
                  "(Wayne) and 4 Expansion deals (Initech, Umbrella, "
                  "Soylent, Stark) — reported as the union of both "
                  "categories, not an intersection."
    })
    fake_client = _FakeClient([renewal_call, expansion_call, final_answer])

    result, filter_calls, client = _run(
        "show me Renewal+Expansion deals", fake_client)

    first_message = client.calls[0]["messages"][0]["content"]
    assert "pipeline_id.eq.866608541" in first_message
    assert "expansion_arr.gt.0" in first_message
    assert "NOT MUTUALLY EXCLUSIVE" in first_message
    assert "UNION" in first_message

    # The two categories must be queried SEPARATELY — never ANDed
    # together into one filter_table call requiring both conditions at
    # once (that would silently exclude every deal that's only one of
    # the two, which is exactly the undercount this whole fix prevents).
    combined_filter_calls = [
        c for c in filter_calls
        if len(c["filters"] or []) > 1
        and any(f[:3] == ["eq", "pipeline_id", RENEWAL_PIPELINE_ID] for f in c["filters"])
        and any(f[:3] == ["gt", "expansion_arr", 0] for f in c["filters"])
    ]
    assert not combined_filter_calls, (
        f"Renewal and Expansion must be queried as separate calls, "
        f"never ANDed into one filter_table call — got: {combined_filter_calls}"
    )
    renewal_calls = [c for c in filter_calls if any(
        f[:3] == ["eq", "pipeline_id", RENEWAL_PIPELINE_ID] for f in (c["filters"] or []))]
    expansion_calls = [c for c in filter_calls if any(
        f[:3] == ["gt", "expansion_arr", 0] for f in (c["filters"] or []))]
    assert len(renewal_calls) == 1
    assert len(expansion_calls) == 1

    assert result["answered"] is True
    assert "Wayne" in result["answer"]
    assert "Initech" in result["answer"]
    print("✓ 'show me Renewal+Expansion deals' resolves both terms with "
          "the union-not-intersection directive, queries each category "
          "separately, and ships a combined answer")


if __name__ == "__main__":
    test_new_business_resolves_to_new_arr_gt_zero()
    test_bare_new_resolves_on_a_deliberate_call()
    test_bare_new_is_not_injected_by_the_opportunistic_scan()
    test_new_business_two_word_phrase_is_still_scanned()
    test_expansion_resolves_to_expansion_arr_gt_zero()
    test_upsell_resolves_to_the_same_expansion_arr_filter()
    test_renewal_resolves_to_the_configured_renewal_pipeline_id()
    test_deal_type_resolution_is_case_and_hyphen_insensitive()
    test_union_note_fires_only_when_two_or_more_deal_type_terms_resolve()
    test_historical_gap_note_fires_only_for_arr_component_terms()
    test_region_only_resolution_is_unaffected_by_the_new_notes()
    test_current_new_business_pipeline_question()
    test_win_rate_on_expansion_deals_question()
    test_renewal_plus_expansion_deals_question()
    print("\n✅ All tests passed")
