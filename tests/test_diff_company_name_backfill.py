"""
Regression tests for the 2026-09-11 (round 6) "some deals named, others
bare deal_ids in the SAME answer" defect.

Live report, exact deal_ids: 60069831015, 60785721693, 61475205473
(stage changes) and 63436694904, 64174280502 (new to scope) all showed
up as bare numeric IDs, while other deals in the same answer — including
OTHER Sales Pipeline deals in the "Dropped from Scope" section — showed
real company names.

ROOT CAUSE (confirmed by code inspection, not guessed): the
id_scoped_enrichment_lookup shortcut's deal_id list is chosen entirely
by the MODEL (see _is_id_scoped_enrichment_call's own docstring — "the
model already picked the exact deal_ids it wants") — and it picks that
list BEFORE diff_snapshots() has even run, since the diff is only
computed later, inside _finalize_from_data. Nothing ever guaranteed the
model's guess covered every deal_id the deterministic diff actually
surfaces. In the live incident it covered the obviously-dropped deals
but missed several stage-changed and newly-entered ones from the same
run — exactly the shape reproduced here. This is NOT a genuine data gap
(HubSpot company_name missing for those 5 deals) — it's an incomplete
enrichment call, closed by forcing one more deterministic lookup for
whatever the model's earlier guess missed.

Fix: collect_diff_deal_ids() + attach_company_names()
(api/snapshot_diff.py) plus a forced backfill filter_table call in
api/router.py's _finalize_from_data, wired in right after
diff_snapshots() runs. Every diff entry (stage_changes,
population_entries, population_exits, owner_changes) gets a
company_name field attached — real, or explicitly None when genuinely
unknown, never silently absent. The finalize prompt was also updated so
a genuinely-unknown name renders as "deal_id X (name not in CRM)" with
segment/pipeline/deal_value context, never a bare opaque ID, covering
the case where quote #1 (a real data gap) turns out to be true instead.
"""
import asyncio
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from api.snapshot_diff import diff_snapshots, collect_diff_deal_ids, attach_company_names

CURRENT_DATE = "2026-09-08"
PRIOR_DATE = "2026-07-27"

# The exact reported deal_ids missing names, playing the stage-change
# and population-entry roles from the live report.
STAGE_CHANGE_IDS = ["60069831015", "60785721693", "61475205473"]
NEW_ENTRY_IDS = ["63436694904", "64174280502"]
# A population-exit deal the model's (incomplete) enrichment call DID
# cover, matching the live report's "Dropped from Scope" section, which
# was fully named.
EXIT_ID_COVERED = "70000000001"


def _row(deal_id, snapshot_date, stage_id, stage_order, segment="Enterprise",
         region="EMEA", owner_email="james.shannon@growthbook.io",
         pipeline_id="default", deal_value=100000):
    return {
        "deal_id": deal_id, "snapshot_date": snapshot_date, "stage_id": stage_id,
        "stage_order": stage_order, "segment": segment, "region": region,
        "owner_email": owner_email, "pipeline_id": pipeline_id, "deal_value": deal_value,
    }


def _build_diff():
    current_rows = (
        [_row(d, CURRENT_DATE, "presentationscheduled", 3) for d in STAGE_CHANGE_IDS]
        + [_row(d, CURRENT_DATE, "appointmentscheduled", 1) for d in NEW_ENTRY_IDS]
    )
    prior_rows = (
        [_row(d, PRIOR_DATE, "appointmentscheduled", 1) for d in STAGE_CHANGE_IDS]
        + [_row(EXIT_ID_COVERED, PRIOR_DATE, "appointmentscheduled", 1, segment="SMB")]
    )
    return diff_snapshots(current_rows, prior_rows)


def test_collect_diff_deal_ids_covers_every_category():
    diff_result = _build_diff()
    ids = collect_diff_deal_ids(diff_result)
    for d in STAGE_CHANGE_IDS:
        assert d in ids, f"stage-changed deal {d} must be in the collected id set"
    for d in NEW_ENTRY_IDS:
        assert d in ids, f"newly-entered deal {d} must be in the collected id set"
    assert EXIT_ID_COVERED in ids, "population-exit deal must be in the collected id set"
    print("✓ collect_diff_deal_ids covers stage_changes, population_entries, and population_exits")


def test_incomplete_enrichment_leaves_a_gap_that_backfill_must_close():
    """Reproduces the exact live shape: the model's enrichment lookup
    only covered the exit deal, leaving the stage-change and new-entry
    deals with no known name — collect_diff_deal_ids minus what the
    model actually looked up is exactly the 5 reported ids."""
    diff_result = _build_diff()
    needed = collect_diff_deal_ids(diff_result)
    # What the model's (incomplete) enrichment call covered, matching
    # the live report: only the obviously-dropped deal got a name.
    model_covered = {EXIT_ID_COVERED: "Technogym"}
    missing = sorted(needed - set(model_covered))
    assert missing == sorted(STAGE_CHANGE_IDS + NEW_ENTRY_IDS), (
        f"expected exactly the 5 reported deal_ids to be missing after "
        f"the model's incomplete enrichment call — got {missing}"
    )
    print("✓ the model's incomplete enrichment call reproduces exactly "
          "the 5 reported missing deal_ids as a gap")


def test_attach_company_names_fills_real_names_and_leaves_none_for_unknown():
    diff_result = _build_diff()
    company_names = {
        EXIT_ID_COVERED: "Technogym",
        "60069831015": "Acme Corp",
        "60785721693": "Beta Inc",
        # 61475205473, 63436694904, 64174280502 deliberately left unresolved
        # (simulating: still genuinely unknown even after the backfill call).
    }
    attach_company_names(diff_result, company_names)

    stage_by_id = {e["deal_id"]: e for e in diff_result["stage_changes"]}
    assert stage_by_id["60069831015"]["company_name"] == "Acme Corp"
    assert stage_by_id["60785721693"]["company_name"] == "Beta Inc"
    assert stage_by_id["61475205473"]["company_name"] is None, (
        "a deal_id with no resolved name must get company_name=None "
        "explicitly, never silently omitted or invented"
    )
    entries_by_id = {r["deal_id"]: r for r in diff_result["population_entries"]}
    assert entries_by_id["63436694904"]["company_name"] is None
    assert entries_by_id["64174280502"]["company_name"] is None
    exits_by_id = {r["deal_id"]: r for r in diff_result["population_exits"]}
    assert exits_by_id[EXIT_ID_COVERED]["company_name"] == "Technogym"
    print("✓ attach_company_names fills real names and leaves an explicit "
          "None (never invented) for deals still genuinely unresolved")


# --- End-to-end: the router forces the missing backfill automatically ---

import api.router as router
import api.tools as tools_module
import api.table_classifier as table_classifier_module
import api.schema_context as schema_context_module


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


class _FakeSupabase:
    pass


REAL_NAMES = {
    EXIT_ID_COVERED: "Technogym",
    "60069831015": "Acme Corp",
    "60785721693": "Beta Inc",
    "61475205473": "Gamma LLC",
    "63436694904": "Delta Co",
    "64174280502": "Epsilon Ltd",
}


def _make_filter_table_stub(call_log):
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
            rows = [{"deal_id": d, "company_name": REAL_NAMES[d]}
                    for d in deal_id_in if d in REAL_NAMES]
        elif snap_date == CURRENT_DATE:
            rows = ([_row(d, CURRENT_DATE, "presentationscheduled", 3) for d in STAGE_CHANGE_IDS]
                    + [_row(d, CURRENT_DATE, "appointmentscheduled", 1) for d in NEW_ENTRY_IDS])
        elif snap_date == PRIOR_DATE:
            rows = ([_row(d, PRIOR_DATE, "appointmentscheduled", 1) for d in STAGE_CHANGE_IDS]
                    + [_row(EXIT_ID_COVERED, PRIOR_DATE, "appointmentscheduled", 1, segment="SMB")])
        else:
            rows = []
        return {"rows": rows, "table": table}
    return fake_filter_table


def _run(fake_client):
    filter_calls = []
    orig_filter_table = tools_module.filter_table
    orig_classify = table_classifier_module.classify_relevant_tables
    orig_get_schema = schema_context_module.get_schema_context
    orig_resolve_anchor_dates = router.resolve_snapshot_anchor_dates

    tools_module.filter_table = _make_filter_table_stub(filter_calls)
    table_classifier_module.classify_relevant_tables = (
        lambda q, client: ["deals_snapshot"])
    schema_context_module.get_schema_context = (
        lambda sb, tables_with_descriptions=None, lightweight=False:
            "TABLE: deals_snapshot\n  deal_id, stage_id, stage_order, region, segment, snapshot_date\n")
    router.resolve_snapshot_anchor_dates = (
        lambda sb, time_window: (CURRENT_DATE, PRIOR_DATE))

    try:
        result = asyncio.run(router.dynamic_query_loop(
            question="which enterprise deals changed stage in the last 2 weeks in EMEA",
            history=[],
            params={"time_window": {"label": "last 2 weeks",
                                     "start": "2026-08-25", "end": "2026-09-08"}},
            sb=_FakeSupabase(),
            client=fake_client,
        ))
        return result, filter_calls
    finally:
        tools_module.filter_table = orig_filter_table
        table_classifier_module.classify_relevant_tables = orig_classify
        schema_context_module.get_schema_context = orig_get_schema
        router.resolve_snapshot_anchor_dates = orig_resolve_anchor_dates


def test_router_forces_backfill_for_deal_ids_the_model_missed():
    """End-to-end reproduction: the model's enrichment lookup only asks
    for the exit deal's name (reproducing exactly what happened live) —
    the router must notice the diff needs 5 more names and force one
    additional filter_table call for exactly those ids, unprompted."""
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
    # The model's enrichment call ONLY asks about the exit deal — this
    # is the exact incomplete-guess shape from the live incident.
    incomplete_enrichment_call = json.dumps({"tool": "filter_table", "params": {
        "table": "deals", "columns": ["deal_id", "company_name"],
        "filters": [["in_", "deal_id", [EXIT_ID_COVERED]]],
    }})
    final_answer = json.dumps({"answer": "All deals named correctly."})

    fake_client = _FakeClient([current_call, prior_call, incomplete_enrichment_call, final_answer])
    result, filter_calls = _run(fake_client)

    backfill_calls = [c for c in filter_calls if c["table"] == "deals"
                      and c["filters"] != [["in_", "deal_id", [EXIT_ID_COVERED]]]]
    assert len(backfill_calls) == 1, (
        f"expected exactly one forced backfill call for the ids the "
        f"model's enrichment call missed — got {len(backfill_calls)}: "
        f"{filter_calls}"
    )
    backfilled_ids = set(backfill_calls[0]["filters"][0][2])
    assert backfilled_ids == set(STAGE_CHANGE_IDS + NEW_ENTRY_IDS), (
        f"the forced backfill must cover exactly the 5 reported "
        f"deal_ids the model's enrichment call missed — got {backfilled_ids}"
    )

    finalize_messages = fake_client.calls[-1]["messages"]
    serialized = json.dumps(finalize_messages, default=str)
    for name in ("Acme Corp", "Beta Inc", "Gamma LLC", "Delta Co", "Epsilon Ltd"):
        assert name in serialized, (
            f"{name!r} must appear in the finalize context after the "
            f"forced backfill — the model must never be left to show a "
            f"bare deal_id for a name the system was able to look up"
        )
    print("✓ the router notices the model's enrichment call missed 5 "
          "deal_ids the diff needs named and forces exactly the right "
          "backfill call, unprompted")


def test_diff_result_sent_to_model_has_every_deal_named():
    """Direct check on the diff_result JSON embedded in the finalize
    prompt: every one of the 5 previously-bare deal_ids must now carry
    its real company_name, not just the ones the model happened to
    enrich."""
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
    incomplete_enrichment_call = json.dumps({"tool": "filter_table", "params": {
        "table": "deals", "columns": ["deal_id", "company_name"],
        "filters": [["in_", "deal_id", [EXIT_ID_COVERED]]],
    }})
    final_answer = json.dumps({"answer": "All deals named correctly."})

    fake_client = _FakeClient([current_call, prior_call, incomplete_enrichment_call, final_answer])
    result, _ = _run(fake_client)

    finalize_prompt_text = fake_client.calls[-1]["messages"][-1]["content"]
    start = finalize_prompt_text.find("{")
    end = finalize_prompt_text.rfind("}\n\nUsing")
    diff_json_text = finalize_prompt_text[start:finalize_prompt_text.index("\n\n", start)]
    # Simpler: just parse out the embedded diff JSON by locating the
    # known marker text around it.
    marker = "exact, final, structured result:\n\n"
    idx = finalize_prompt_text.index(marker) + len(marker)
    end_idx = finalize_prompt_text.index("\n\nUsing ONLY this structured result", idx)
    diff_json = json.loads(finalize_prompt_text[idx:end_idx])

    stage_names = {e["deal_id"]: e["company_name"] for e in diff_json["stage_changes"]}
    entry_names = {r["deal_id"]: r["company_name"] for r in diff_json["population_entries"]}
    assert stage_names["60069831015"] == "Acme Corp"
    assert stage_names["60785721693"] == "Beta Inc"
    assert stage_names["61475205473"] == "Gamma LLC"
    assert entry_names["63436694904"] == "Delta Co"
    assert entry_names["64174280502"] == "Epsilon Ltd"
    print("✓ the diff_result JSON embedded in the finalize prompt has "
          "every one of the 5 previously-bare deal_ids correctly named")


if __name__ == "__main__":
    test_collect_diff_deal_ids_covers_every_category()
    test_incomplete_enrichment_leaves_a_gap_that_backfill_must_close()
    test_attach_company_names_fills_real_names_and_leaves_none_for_unknown()
    test_router_forces_backfill_for_deal_ids_the_model_missed()
    test_diff_result_sent_to_model_has_every_deal_named()
    print("\n✅ All tests passed")
