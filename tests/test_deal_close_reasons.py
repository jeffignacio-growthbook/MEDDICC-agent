#!/usr/bin/env python3
"""
Close-reason ETL fetch fix + backfill (2026-09-25).

deals.lost_reason was 0% populated because the ETL never fetched HubSpot's
closed_lost_reason: DEAL_SYNC_PROPERTIES omitted it, and etl_deals.py did
props.get('closed_lost_reason', '') on a property the fetch never asked for,
silently turning "never fetched" into "confirmed empty". win_loss_narratives.
stated_reason (a verbatim copy of deals.lost_reason) inherited the same empty.

This pins:
  1. DEAL_SYNC_PROPERTIES now requests all four close-reason properties — the
     regression that would have caught the original bug.
  2. upsert_deal persists the three new columns when present.
  3. The backfill helpers (scripts/analytics/backfill_lost_reason.py):
     - deals_needing_update: only writes a non-empty new value that differs
       from the stored one (never clobbers a real value with an empty).
     - stated_reason_updates: the TARGETED win_loss_narratives backfill —
       fills stated_reason on narrative rows that ALREADY EXIST (exactly the
       rows generate_win_loss.py skips), from the now-populated
       deals.lost_reason. A plain generator re-run would never touch them.
"""
import sys
from pathlib import Path

REPO = Path(__file__).parent.parent
sys.path.insert(0, str(REPO / "tests"))
sys.path.insert(0, str(REPO))
sys.path.insert(0, str(REPO / "scripts"))
sys.path.insert(0, str(REPO / "scripts" / "analytics"))

import logging  # noqa: E402
logging.disable(logging.CRITICAL)

import hubspot_deals  # noqa: E402
import supabase_client  # noqa: E402
import backfill_lost_reason as bf  # noqa: E402

REASON_PROPERTIES = ("closed_lost_reason", "closed_lost_from", "dq_reason", "closed_won_reason")


def test_deal_sync_properties_request_every_close_reason():
    """The regression that would have caught the original bug: the fetch list
    must include the property the write path reads."""
    props = set(hubspot_deals.HubSpotDealsClient.DEAL_SYNC_PROPERTIES)
    missing = [p for p in REASON_PROPERTIES if p not in props]
    assert not missing, f"DEAL_SYNC_PROPERTIES omits {missing} — the exact 2026-09-25 fetch gap"
    print("✓ DEAL_SYNC_PROPERTIES requests closed_lost_reason, closed_lost_from, dq_reason, "
          "closed_won_reason")


class _FakeQ:
    def __init__(self, store):
        self.store, self._row = store, None

    def select(self, *a):
        return self

    def eq(self, *a):
        return self

    def upsert(self, row, on_conflict=None):
        self._row = row
        self.store.append(row)
        return self

    def insert(self, row):
        return self

    def execute(self):
        return type("R", (), {"data": []})()


class _FakeClient:
    def __init__(self):
        self.upserts = []

    def table(self, name):
        return _FakeQ(self.upserts)


def _writer():
    w = supabase_client.SupabaseWriter.__new__(supabase_client.SupabaseWriter)
    w.client = _FakeClient()
    return w


def test_upsert_deal_persists_the_new_reason_columns():
    w = _writer()
    w.upsert_deal({
        "deal_id": "D1", "deal_status": "lost", "lost_reason": "Unresponsive",
        "closed_lost_from": "Meeting Set", "dq_reason": "", "closed_won_reason": "",
    })
    row = w.client.upserts[-1]
    assert row["lost_reason"] == "Unresponsive"
    assert row["closed_lost_from"] == "Meeting Set"
    assert row["dq_reason"] == "" and row["closed_won_reason"] == ""
    # a won deal carries closed_won_reason, no lost fields
    w2 = _writer()
    w2.upsert_deal({"deal_id": "D2", "deal_status": "won", "closed_won_reason": "Displaced competitor"})
    row2 = w2.client.upserts[-1]
    assert row2["closed_won_reason"] == "Displaced competitor"
    print("✓ upsert_deal writes closed_lost_from / dq_reason / closed_won_reason when present")


def test_deals_backfill_only_writes_changed_nonempty_values():
    hs_by_id = {
        "A": {"closed_lost_reason": "Not a good fit (FF only)"},   # empty -> value: update
        "B": {"closed_lost_reason": "Unresponsive"},                # already stored: no update
        "C": {"closed_lost_reason": ""},                            # HubSpot empty: never clobber
        "D": {"closed_won_reason": "Won on price"},                 # won-side reason
    }
    current = {
        "A": {"lost_reason": ""},
        "B": {"lost_reason": "Unresponsive"},
        "C": {"lost_reason": "real value"},
        "D": {"closed_won_reason": ""},
    }
    updates = dict(bf.deals_needing_update(hs_by_id, current))
    assert updates["A"] == {"lost_reason": "Not a good fit (FF only)"}
    assert "B" not in updates                    # unchanged, not rewritten
    assert "C" not in updates                    # empty HubSpot value never clobbers a stored one
    assert updates["D"] == {"closed_won_reason": "Won on price"}
    print("✓ deals backfill writes only non-empty values that differ; never clobbers a stored value "
          "with an empty one")


def test_stated_reason_backfill_targets_existing_narratives():
    """The whole point: generate_win_loss.py SKIPS deals that already have a
    narrative row, so a plain re-run leaves their stated_reason empty forever.
    The targeted backfill fills exactly those rows from deals.lost_reason."""
    narratives = [
        {"deal_id": "N1", "stated_reason": ""},       # existing narrative, empty reason -> fill
        {"deal_id": "N2", "stated_reason": "Budget"},  # already filled -> leave alone
        {"deal_id": "N3", "stated_reason": ""},       # empty reason but no lost_reason source -> skip
    ]
    lost_reason_by_deal = {"N1": "Unresponsive", "N2": "Something else", "N3": ""}
    updates = dict(bf.stated_reason_updates(narratives, lost_reason_by_deal))
    assert updates == {"N1": "Unresponsive"}, updates
    print("✓ stated_reason backfill fills existing narratives with an empty reason from "
          "deals.lost_reason (the rows a generator re-run would skip); leaves filled ones and "
          "sourceless ones alone")


if __name__ == "__main__":
    test_deal_sync_properties_request_every_close_reason()
    test_upsert_deal_persists_the_new_reason_columns()
    test_deals_backfill_only_writes_changed_nonempty_values()
    test_stated_reason_backfill_targets_existing_narratives()
    print("\n✅ All tests passed")
