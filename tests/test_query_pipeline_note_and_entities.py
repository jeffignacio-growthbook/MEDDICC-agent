#!/usr/bin/env python3
"""
query_pipeline: its _synthesis_note states the handler's own computed totals,
and its deal rows carry deal_id so follow-ups can resolve them.

2026-09-24, first live answer after #43 ("what does our pipeline look like
this quarter?", routed to query_pipeline):
  1. The _synthesis_note hardcoded "$18.6M" and "verify it equals total_deals
     (306)", while the handler computed $22.5M over 213 deals. The model
     reported the real figures, but it was told to check against stale ones.
  2. Railway logged "[ENTITY] save_thread stored ZERO entities ... keys:
     [...'deals'...]": the `deals` rows had no deal_id, so
     extract_entity_context() found no entity-bearing list, and a follow-up
     ("which of those are at risk?") had nothing to resolve.

Runs the real handler against a strict fake Supabase, then the real
extract_entity_context() on its output.
"""
import asyncio
import sys
from pathlib import Path

REPO = Path(__file__).parent.parent
sys.path.insert(0, str(REPO))
sys.path.insert(0, str(REPO / "api"))
sys.path.insert(0, str(REPO / "scripts"))
sys.path.insert(0, str(REPO / "tests"))

import logging  # noqa: E402
logging.disable(logging.CRITICAL)

import api.handlers as handlers  # noqa: E402
from api.db import extract_entity_context  # noqa: E402

DEALS = [
    {"deal_id": "101", "company_name": "Alpha", "deal_value": 120000, "stage": "presentationscheduled",
     "close_date": "2026-09-30", "owner_email": "a@x.com", "pipeline_id": "default", "deal_status": "active",
     "new_arr": 120000, "expansion_arr": None, "renewal_revenue": None},
    {"deal_id": "102", "company_name": "Bravo", "deal_value": 55000, "stage": "qualifiedtobuy",
     "close_date": "2027-01-15", "owner_email": "b@x.com", "pipeline_id": "default", "deal_status": "active",
     "new_arr": 50000, "expansion_arr": 5000, "renewal_revenue": None},
    {"deal_id": "103", "company_name": "Charlie", "deal_value": 300000, "stage": "1297321619",
     "close_date": "2026-10-20", "owner_email": "c@x.com", "pipeline_id": "866608541", "deal_status": "active",
     "new_arr": None, "expansion_arr": 30000, "renewal_revenue": 270000},
]


def _sb(deals=None):
    """A strict fake (tests/strict_supabase.py): the REAL select_all runs
    against it, only selected columns come back, every filter applies.
    (Until 2026-09-24 this harness returned every deal whatever was selected
    or filtered, and a rep_targets row whatever period was asked for.)"""
    from strict_supabase import StrictSupabase
    from time_resolver import current_quarter_label
    return StrictSupabase({
        "deals": DEALS if deals is None else deals,
        "rep_targets": [{"period": current_quarter_label(), "level": "team",
                         "metric": "incremental_arr", "target_value": 150000},
                        {"period": "FY2099_Q1", "level": "team",
                         "metric": "incremental_arr", "target_value": 1}],
        "entity_registry": [{"id_column": "deal_id", "entity_type": "deal",
                             "entity_label_column": "company_name", "supabase_table": "deals"}],
    })


_SB = _sb          # importers call qp._SB()


def _run(params=None, deals=None):
    return asyncio.run(handlers.query_pipeline(params or {}, _sb(deals)))


def test_note_states_the_handlers_own_totals():
    r = _run()
    note = r["_synthesis_note"]
    total, count = r["total_pipeline"], r["total_deals"]
    assert (total, count) == (205000, 3), (total, count)
    assert f"${total:,.0f}" in note, (f"${total:,.0f}", note[:300])
    assert f"equals total_deals ({count})" in note, note
    for stale in ("$18.6M", "(306)"):
        assert stale not in note, f"stale hardcoded figure {stale!r} still in the note"
    print(f"✓ note states total_pipeline ${total:,.0f} and total_deals {count} from this call "
          "(no hardcoded $18.6M / 306)")


def test_deal_rows_carry_deal_id_and_entities_are_extracted():
    r = _run()
    assert all(d.get("deal_id") for d in r["deals"]), r["deals"]
    ctx = extract_entity_context(r, sb=_SB())
    assert sorted(ctx["deal_ids"]) == ["101", "102", "103"], ctx
    assert sorted(ctx["company_names"]) == ["Alpha", "Bravo", "Charlie"], ctx
    print("✓ deals rows carry deal_id; extract_entity_context stores all 3 deals "
          "(was zero: no entity-bearing list)")


def test_only_active_deals_are_read():
    """The strict fake applies the handler's own filters, so the fixture can
    carry deals the query must exclude (the old fake returned everything)."""
    closed = [dict(DEALS[0], deal_id="901", company_name="WonCo", deal_status="won", new_arr=999000),
              dict(DEALS[1], deal_id="902", company_name="LostCo", deal_status="lost", new_arr=888000)]
    r = _run(deals=DEALS + closed)
    assert (r["total_pipeline"], r["total_deals"]) == (205000, 3), (r["total_pipeline"], r["total_deals"])
    assert {d["deal_id"] for d in r["deals"]} == {"101", "102", "103"}, r["deals"]
    print("✓ won and lost deals in the table are filtered out by the handler's own deal_status "
          "filter: still $205,000 over 3 deals")


if __name__ == "__main__":
    test_note_states_the_handlers_own_totals()
    test_deal_rows_carry_deal_id_and_entities_are_extracted()
    test_only_active_deals_are_read()
    print("\n✅ All tests passed")
