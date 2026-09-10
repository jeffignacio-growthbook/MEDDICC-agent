"""
Regression tests for the 2026-09-11 round-5 fix: three consecutive
live-test failures (unfinished scratchpad narration, narrating twice
instead of tool-calling, then losing the enrichment lookup's own data)
were three different failure MODES of one root cause — the model was
being asked to compute a two-snapshot stage-change diff in free text,
which is a deterministic set operation, not a reasoning task an LLM
should ever perform in prose.

diff_snapshots() (api/snapshot_diff.py) computes that diff in code.
These tests cover:

1. Pure correctness of diff_snapshots() against the EXACT row-count
   shape from the incident logs (29-row current snapshot, 31-row prior
   snapshot) — stage changes, population entries/exits, owner-change
   asides, and the stage_order-with-stage_id-fallback comparison logic.

2. rows_for_snapshot_date() extracting the right rows from
   accumulated_data's raw steps.

3. End-to-end proof that dynamic_query_loop's _finalize_from_data now
   hands the model an ALREADY-COMPUTED structured diff instead of asking
   it to produce one — the finalize prompt sent to the LLM must contain
   the computed result and an explicit "do not recompute" instruction,
   never the old generic "answer this question now" prompt, whenever
   both snapshot anchors are present.
"""
import asyncio
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from api.snapshot_diff import diff_snapshots, rows_for_snapshot_date

CURRENT_DATE = "2026-09-08"
PRIOR_DATE = "2026-07-27"


def _row(deal_id, snapshot_date, stage_id, stage_order, owner_email="jake@x.com",
         region="EMEA", segment="Enterprise"):
    return {
        "deal_id": deal_id, "snapshot_date": snapshot_date, "stage_id": stage_id,
        "stage_order": stage_order, "owner_email": owner_email,
        "region": region, "segment": segment,
    }


def _incident_shape():
    """The exact row-count shape from tonight's logs: 29 in the current
    snapshot, 31 in the prior — 29 deals present in both (all advancing
    from appointmentscheduled/order 1 to qualifiedtobuy/order 2), and 2
    deals present only in the prior snapshot (population exits)."""
    current_rows = [
        _row(str(2000 + i), CURRENT_DATE, "qualifiedtobuy", 2)
        for i in range(29)
    ]
    prior_rows = [
        _row(str(2000 + i), PRIOR_DATE, "appointmentscheduled", 1)
        for i in range(31)
    ]
    return current_rows, prior_rows


def test_incident_shape_produces_correct_complete_diff_immediately():
    current_rows, prior_rows = _incident_shape()
    result = diff_snapshots(current_rows, prior_rows)

    assert result["current_count"] == 29
    assert result["prior_count"] == 31
    assert len(result["stage_changes"]) == 29, (
        "all 29 deals present in both snapshots moved from "
        "appointmentscheduled to qualifiedtobuy — every one must be a "
        "stage change"
    )
    assert len(result["population_exits"]) == 2, (
        "deals 2029 and 2030 exist only in the 31-row prior snapshot"
    )
    assert result["population_entries"] == []
    assert result["owner_changes"] == []
    assert result["skipped_missing_deal_id"] == 0

    exit_ids = {row["deal_id"] for row in result["population_exits"]}
    assert exit_ids == {"2029", "2030"}

    change_ids = {c["deal_id"] for c in result["stage_changes"]}
    assert change_ids == {str(2000 + i) for i in range(29)}

    sample = next(c for c in result["stage_changes"] if c["deal_id"] == "2000")
    assert sample["prior_stage_id"] == "appointmentscheduled"
    assert sample["current_stage_id"] == "qualifiedtobuy"
    assert sample["direction"] == "advanced"
    print("✓ the exact 29/31-row incident shape produces a correct, "
          "complete diff (29 stage changes, 2 exits) with no LLM diffing")


def test_population_entries_are_new_deals_in_current_only():
    current_rows = [_row("A", CURRENT_DATE, "qualifiedtobuy", 2),
                     _row("B", CURRENT_DATE, "qualifiedtobuy", 2)]
    prior_rows = [_row("A", PRIOR_DATE, "qualifiedtobuy", 2)]
    result = diff_snapshots(current_rows, prior_rows)
    assert [r["deal_id"] for r in result["population_entries"]] == ["B"]
    assert result["stage_changes"] == []
    print("✓ a deal present only in the current snapshot is a population entry, not a stage change")


def test_population_exits_are_deals_dropped_from_prior():
    current_rows = [_row("A", CURRENT_DATE, "qualifiedtobuy", 2)]
    prior_rows = [_row("A", PRIOR_DATE, "qualifiedtobuy", 2),
                   _row("B", PRIOR_DATE, "qualifiedtobuy", 2)]
    result = diff_snapshots(current_rows, prior_rows)
    assert [r["deal_id"] for r in result["population_exits"]] == ["B"]
    print("✓ a deal present only in the prior snapshot is a population exit")


def test_owner_change_with_no_stage_change_is_a_separate_aside():
    """The exact live-incident detail: deal 59680315298's owner changed
    (Christian -> Scott Keller) with no stage change — must be its own
    category, never folded into stage_changes or silently dropped into
    unchanged."""
    current_rows = [_row("59680315298", CURRENT_DATE, "qualifiedtobuy", 2,
                          owner_email="scott@x.com")]
    prior_rows = [_row("59680315298", PRIOR_DATE, "qualifiedtobuy", 2,
                        owner_email="christian@x.com")]
    result = diff_snapshots(current_rows, prior_rows)
    assert result["stage_changes"] == []
    assert len(result["owner_changes"]) == 1
    change = result["owner_changes"][0]
    assert change["deal_id"] == "59680315298"
    assert change["prior_owner_email"] == "christian@x.com"
    assert change["current_owner_email"] == "scott@x.com"
    print("✓ an owner change with no stage change is its own labeled category, not folded into stage_changes")


def test_same_stage_and_owner_is_unchanged():
    current_rows = [_row("A", CURRENT_DATE, "qualifiedtobuy", 2)]
    prior_rows = [_row("A", PRIOR_DATE, "qualifiedtobuy", 2)]
    result = diff_snapshots(current_rows, prior_rows)
    assert result["stage_changes"] == []
    assert result["owner_changes"] == []
    assert result["unchanged_deal_ids"] == ["A"]
    print("✓ a deal with no stage or owner change lands in unchanged_deal_ids")


def test_stage_order_is_the_primary_comparison_falling_back_to_stage_id():
    # stage_order differs but stage_id happens to be missing on one side —
    # still detected as changed via stage_order.
    current_rows = [{"deal_id": "A", "snapshot_date": CURRENT_DATE, "stage_order": 3}]
    prior_rows = [{"deal_id": "A", "snapshot_date": PRIOR_DATE, "stage_order": 1}]
    result = diff_snapshots(current_rows, prior_rows)
    assert len(result["stage_changes"]) == 1
    assert result["stage_changes"][0]["direction"] == "advanced"

    # stage_order missing on one side — falls back to stage_id comparison.
    current_rows2 = [{"deal_id": "B", "snapshot_date": CURRENT_DATE,
                       "stage_id": "qualifiedtobuy", "stage_order": None}]
    prior_rows2 = [{"deal_id": "B", "snapshot_date": PRIOR_DATE,
                     "stage_id": "appointmentscheduled", "stage_order": 1}]
    result2 = diff_snapshots(current_rows2, prior_rows2)
    assert len(result2["stage_changes"]) == 1, (
        "a missing stage_order on one side must not hide a real stage_id "
        "change — a backfill gap should never silently mask a real move"
    )
    assert result2["stage_changes"][0]["direction"] == "unknown", (
        "direction can't be determined without both stage_order values"
    )
    print("✓ stage_order is the primary comparison; a missing stage_order falls back to stage_id, never hides a change")


def test_rows_missing_deal_id_are_skipped_and_counted():
    current_rows = [_row("A", CURRENT_DATE, "qualifiedtobuy", 2),
                     {"snapshot_date": CURRENT_DATE, "stage_id": "qualifiedtobuy"}]  # no deal_id
    prior_rows = [_row("A", PRIOR_DATE, "appointmentscheduled", 1)]
    result = diff_snapshots(current_rows, prior_rows)
    assert result["skipped_missing_deal_id"] == 1
    assert len(result["stage_changes"]) == 1
    print("✓ rows missing deal_id are skipped and counted, not silently dropped or crashed on")


def test_diff_snapshots_is_pure_and_handles_empty_input():
    assert diff_snapshots([], []) == {
        "stage_changes": [], "population_entries": [], "population_exits": [],
        "owner_changes": [], "unchanged_deal_ids": [], "current_count": 0,
        "prior_count": 0, "skipped_missing_deal_id": 0,
    }
    print("✓ diff_snapshots handles empty input without error")


def test_rows_for_snapshot_date_extracts_and_dedupes_by_deal_id():
    accumulated_data = {
        "step_0_raw": {"rows": [
            {"deal_id": "A", "snapshot_date": CURRENT_DATE, "stage_id": "x"},
            {"deal_id": "B", "snapshot_date": PRIOR_DATE, "stage_id": "y"},
        ]},
        "step_1_raw": {"rows": [
            {"deal_id": "C", "snapshot_date": CURRENT_DATE, "stage_id": "z"},
        ]},
        "step_1": {"rows": [  # aggregated (non-raw) step — must be ignored
            {"deal_id": "D", "snapshot_date": CURRENT_DATE, "stage_id": "should not appear"},
        ]},
    }
    current = rows_for_snapshot_date(accumulated_data, CURRENT_DATE)
    current_ids = {r["deal_id"] for r in current}
    assert current_ids == {"A", "C"}, (
        "must union rows from ALL _raw steps matching the date, and "
        "ignore non-_raw (aggregated) steps"
    )
    prior = rows_for_snapshot_date(accumulated_data, PRIOR_DATE)
    assert {r["deal_id"] for r in prior} == {"B"}
    assert rows_for_snapshot_date(accumulated_data, None) == []
    print("✓ rows_for_snapshot_date unions matching _raw steps and ignores aggregated steps")


# --- End-to-end: the model must never be asked to compute the diff itself ---

import api.router as router
import api.tools as tools_module
import api.table_classifier as table_classifier_module
import api.schema_context as schema_context_module

QUESTION = "which enterprise deals changed stage in the last 2 weeks in EMEA"
ENRICHMENT_DEAL_IDS = [str(2000 + i) for i in range(11)]
ENRICHMENT_ROWS = [
    {"deal_id": ENRICHMENT_DEAL_IDS[i], "company_name": f"Company{i}"}
    for i in range(11)
]


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
        assert idx < len(self._responses)
        return _FakeResponse(self._responses[idx])


def _make_filter_table_stub(call_log):
    current_rows, prior_rows = _incident_shape()

    async def fake_filter_table(sb, table=None, columns=None, filters=None,
                                 limit=200, order_by=None):
        call_log.append({"table": table, "columns": columns, "filters": filters})
        snap_date = None
        deal_id_in = None
        for f in (filters or []):
            if len(f) >= 2 and f[1] == "snapshot_date":
                snap_date = f[2]
            if len(f) >= 2 and f[1] == "deal_id" and f[0] in ("in_", "in"):
                deal_id_in = f[2]
        if deal_id_in is not None:
            wanted = set(deal_id_in)
            rows = [r for r in ENRICHMENT_ROWS if r["deal_id"] in wanted]
        elif snap_date == CURRENT_DATE:
            rows = current_rows
        elif snap_date == PRIOR_DATE:
            rows = prior_rows
        else:
            rows = []
        return {"rows": rows, "table": table}
    return fake_filter_table


class _FakeSupabase:
    pass


def _run_end_to_end(fake_client):
    filter_table_calls = []
    orig_filter_table = tools_module.filter_table
    orig_classify = table_classifier_module.classify_relevant_tables
    orig_get_schema = schema_context_module.get_schema_context
    orig_resolve_anchor_dates = router.resolve_snapshot_anchor_dates

    tools_module.filter_table = _make_filter_table_stub(filter_table_calls)
    table_classifier_module.classify_relevant_tables = (
        lambda question, client: ["deals_snapshot"])
    schema_context_module.get_schema_context = (
        lambda sb, tables_with_descriptions=None, lightweight=False:
            "TABLE: deals_snapshot\n  deal_id, stage_id, stage_order, region, segment, snapshot_date\n")
    router.resolve_snapshot_anchor_dates = (
        lambda sb, time_window: (CURRENT_DATE, PRIOR_DATE))

    try:
        result = asyncio.run(router.dynamic_query_loop(
            question=QUESTION,
            history=[],
            params={"time_window": {"label": "last 2 weeks",
                                     "start": "2026-08-25", "end": "2026-09-08"}},
            sb=_FakeSupabase(),
            client=fake_client,
        ))
    finally:
        tools_module.filter_table = orig_filter_table
        table_classifier_module.classify_relevant_tables = orig_classify
        schema_context_module.get_schema_context = orig_get_schema
        router.resolve_snapshot_anchor_dates = orig_resolve_anchor_dates

    return result, fake_client, filter_table_calls


def test_finalize_prompt_hands_model_the_computed_diff_not_a_reasoning_task():
    """The core proof: once both snapshots are queried and the
    enrichment lookup completes (id_scoped_enrichment_lookup shortcut),
    the finalize prompt sent to the LLM must contain the ALREADY-COMPUTED
    diff_snapshots() result and explicitly forbid recomputing it — never
    the old "Stop calling tools... answer this question now" prompt that
    asked the model to produce the diff itself in prose."""
    current_call = json.dumps({"tool": "filter_table", "params": {
        "table": "deals_snapshot",
        "columns": ["deal_id", "stage_id", "stage_order", "region", "segment", "snapshot_date"],
        "filters": [["eq", "snapshot_date", CURRENT_DATE],
                    ["eq", "region", "EMEA"], ["eq", "segment", "Enterprise"]],
    }})
    prior_call = json.dumps({"tool": "filter_table", "params": {
        "table": "deals_snapshot",
        "columns": ["deal_id", "stage_id", "stage_order", "region", "segment", "snapshot_date"],
        "filters": [["eq", "snapshot_date", PRIOR_DATE],
                    ["eq", "region", "EMEA"], ["eq", "segment", "Enterprise"]],
    }})
    enrichment_call = json.dumps({"tool": "filter_table", "params": {
        "table": "deals", "columns": ["deal_id", "company_name"],
        "filters": [["in_", "deal_id", ENRICHMENT_DEAL_IDS]],
    }})
    final_answer = json.dumps({"answer": "*Stage changes*: 29 deals advanced from Discovery to Scoping."})

    fake_client = _FakeClient([current_call, prior_call, enrichment_call, final_answer])
    result, fake_client, filter_table_calls = _run_end_to_end(fake_client)

    assert len(fake_client.calls) == 4
    finalize_prompt_message = fake_client.calls[-1]["messages"][-1]
    finalize_text = finalize_prompt_message["content"]

    assert "ALREADY been computed" in finalize_text, (
        "the finalize prompt must tell the model the diff is already "
        "computed, not ask it to produce one"
    )
    assert "do NOT recompute" in finalize_text, (
        "the finalize prompt must explicitly forbid the model from "
        "recomputing the diff itself"
    )
    assert "\"stage_changes\"" in finalize_text, (
        "the actual diff_snapshots() JSON result must be embedded in "
        "the finalize prompt"
    )
    assert "Stop calling tools. Using ONLY the data already gathered" not in finalize_text, (
        "the OLD generic finalize prompt (which asked the model to "
        "produce the comparison itself) must not be used once a "
        "deterministic diff is available"
    )
    assert result["answered"] is True
    print("✓ the finalize prompt hands the model an already-computed "
          "structured diff and explicitly forbids recomputing it — the "
          "model is never asked to diff two snapshots in free text")


if __name__ == "__main__":
    test_incident_shape_produces_correct_complete_diff_immediately()
    test_population_entries_are_new_deals_in_current_only()
    test_population_exits_are_deals_dropped_from_prior()
    test_owner_change_with_no_stage_change_is_a_separate_aside()
    test_same_stage_and_owner_is_unchanged()
    test_stage_order_is_the_primary_comparison_falling_back_to_stage_id()
    test_rows_missing_deal_id_are_skipped_and_counted()
    test_diff_snapshots_is_pure_and_handles_empty_input()
    test_rows_for_snapshot_date_extracts_and_dedupes_by_deal_id()
    test_finalize_prompt_hands_model_the_computed_diff_not_a_reasoning_task()
    print("\n✅ All tests passed")
