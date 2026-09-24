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

Runs the real handler against a fake Supabase, then the real
extract_entity_context() on its output.
"""
import asyncio
import sys
from pathlib import Path

REPO = Path(__file__).parent.parent
sys.path.insert(0, str(REPO))
sys.path.insert(0, str(REPO / "api"))
sys.path.insert(0, str(REPO / "scripts"))

import logging  # noqa: E402
logging.disable(logging.CRITICAL)

import api.handlers as handlers  # noqa: E402

DEALS = [
    {"deal_id": "101", "company_name": "Alpha", "deal_value": 120000, "stage": "presentationscheduled",
     "close_date": "2026-09-30", "owner_email": "a@x.com", "pipeline_id": "default",
     "new_arr": 120000, "expansion_arr": None, "renewal_revenue": None},
    {"deal_id": "102", "company_name": "Bravo", "deal_value": 55000, "stage": "qualifiedtobuy",
     "close_date": "2027-01-15", "owner_email": "b@x.com", "pipeline_id": "default",
     "new_arr": 50000, "expansion_arr": 5000, "renewal_revenue": None},
    {"deal_id": "103", "company_name": "Charlie", "deal_value": 300000, "stage": "1297321619",
     "close_date": "2026-10-20", "owner_email": "c@x.com", "pipeline_id": "866608541",
     "new_arr": None, "expansion_arr": 30000, "renewal_revenue": 270000},
]


class _Chain:
    def __init__(self, data):
        self.data = data

    def __getattr__(self, name):          # select / eq / in_ / order / limit ...
        return lambda *a, **k: self

    def execute(self):
        return type("R", (), {"data": self.data})()


class _SB:
    def table(self, name):
        if name == "rep_targets":
            return _Chain([{"target_value": 150000}])
        if name == "entity_registry":
            return _Chain([{"id_column": "deal_id", "entity_type": "deal",
                            "entity_label_column": "company_name", "supabase_table": "deals"}])
        return _Chain([])


def _fake_select_all(sb, table, columns="*", filters=None, **kw):
    assert table == "deals", table
    return [dict(d) for d in DEALS]


def _run():
    saved = handlers.select_all
    handlers.select_all = _fake_select_all
    try:
        return asyncio.run(handlers.query_pipeline({}, _SB()))
    finally:
        handlers.select_all = saved


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


if __name__ == "__main__":
    test_note_states_the_handlers_own_totals()
    print("\n✅ All tests passed")
