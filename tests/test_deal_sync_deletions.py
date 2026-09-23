"""
Incremental deal sync, part 3: deletions and merges reach Supabase.

Why: deals/search never returns archived (deleted) deals, so no sync ever
learns about a deletion. The Inditex ghost (29591984407, deleted 2026-08-11)
stayed 'active' in deals and in 12 snapshots for six weeks. Every sync run
(incremental and full) now lists HubSpot's deleted deals and the ids merged
into survivors, and tombstones any that are still in `deals`. It reuses the
deleted_deals table from migration 067, through the atomic tombstone_deal()
function (migration 070, which generalises 068):
  - deleted in HubSpot: move the row to deleted_deals and remove only the
    snapshot rows dated after the deletion day (pre-deletion history is real);
  - merged away: move the row, keep all snapshots (its history was real, it
    just continues under the survivor);
  - not in deals: no-op ('absent').
A failed deletion pass is a run failure: exit 1, checkpoint not advanced.

The SQL function is exercised live, inside a transaction forced to roll back
(see the PR). Here a fake rpc() mirrors its contract, and everything else is
the real etl_deals.main().

Pins, with planted controls:
  1. Archived deal still in deals: tombstoned, post-deletion snapshots out,
     pre-deletion kept, exit 0, checkpoint advances.
  2. Archived deal already gone from deals: nothing written.
  3. Merged-away id still in deals: tombstoned as merged_away, snapshots kept.
  4. The tombstone call fails: exit 1, checkpoint unchanged, deal still there.
  5. HubSpot's archived listing fails: exit 1, checkpoint unchanged.
  6. The full (analytics) sync runs the same pass.
  Controls: skipping the pass leaves the ghost; treating a failed pass as
  fine lets the checkpoint advance past it.
"""
import sys
from datetime import date
from pathlib import Path

REPO = Path(__file__).parent.parent
sys.path.insert(0, str(REPO / "tests"))
sys.path.insert(0, str(REPO / "scripts"))

import test_deal_sync_incremental as base  # noqa: E402  (stateful fakes + run())
import etl_deals  # noqa: E402

MIN, NOW = base.MIN, base.NOW


class Hub(base.Hub):
    def __init__(self):
        super().__init__()
        self.archived = {}   # id -> archivedAt ISO
        self.merged = {}     # survivor id -> [merged-away ids]

    def request(self, method, url, timeout=None, params=None, json=None):
        path = url[len(base.BASE):]
        q = self.fail.get(path)
        if path == "/crm/v3/objects/deals" and method == "GET" and (params or {}).get("archived") == "true":
            if q:
                return base._resp(q.pop(0), {"message": "planted"})
            return base._resp(200, {"results": [{"id": i, "archivedAt": at, "archived": True}
                                                for i, at in self.archived.items()]})
        if path == "/crm/v3/objects/deals/search":
            filters = [f for g in json.get("filterGroups", []) for f in g["filters"]]
            if any(f.get("operator") == "HAS_PROPERTY" for f in filters):
                self.searches.append(json)
                rows = [{"id": s, "properties": {"hs_object_id": s,
                                                 "hs_merged_object_ids": ";".join(m)}}
                        for s, m in sorted(self.merged.items())]
                cursor = next((int(f["value"]) for f in filters
                               if f["propertyName"] == "hs_object_id"), None)
                rows = [r for r in rows if cursor is None or int(r["id"]) > cursor]
                return base._resp(200, {"total": len(rows), "results": rows[:json.get("limit", 100)]})
        return super().request(method, url, timeout, params, json)


class DB(base.DB):
    KEYS = {**base.DB.KEYS, "deleted_deals": "deal_id"}

    def __init__(self):
        super().__init__()
        self.tables.update({"deleted_deals": {}})
        self.snapshots = []          # deals_snapshot rows (no natural single key)
        self.fail_rpc = False
        self.rpc_calls = []

    def rpc(self, name, params):
        db = self

        class Call:
            def execute(self_inner):
                assert name == "tombstone_deal", name
                db.rpc_calls.append(params)
                if db.fail_rpc:
                    raise RuntimeError("planted tombstone failure")
                return type("R", (), {"data": db._tombstone(**params)})()
        return Call()

    def _tombstone(self, p_deal_id, p_archived_at, p_reason, p_source):
        """Mirror of SQL tombstone_deal() (migration 070)."""
        row = self.tables["deals"].get(p_deal_id)
        if row is None:
            return "absent"
        cut = None
        if p_archived_at:
            d = date.fromisoformat(p_archived_at[:10])
            cut = date.fromordinal(d.toordinal() + 1)
        removed = [s for s in self.snapshots if s["deal_id"] == p_deal_id
                   and cut is not None and date.fromisoformat(s["snapshot_date"]) >= cut]
        self.tables["deleted_deals"][p_deal_id] = {
            "deal_id": p_deal_id, "hubspot_archived_at": p_archived_at, "reason": p_reason,
            "source": p_source, "deal_row": dict(row), "removed_snapshot_rows": removed or None}
        self.snapshots = [s for s in self.snapshots if s not in removed]
        del self.tables["deals"][p_deal_id]
        return "tombstoned"


def _ghost_setup(hub, db, deal_id="900", archived_at="2026-08-11T23:26:35.181Z"):
    db.tables["deals"][deal_id] = {"deal_id": deal_id, "deal_status": "active"}
    for d in ("2026-08-03", "2026-08-10", "2026-08-11", "2026-08-12", "2026-08-17", "2026-09-21"):
        db.snapshots.append({"deal_id": deal_id, "snapshot_date": d})
    if archived_at:
        hub.archived[deal_id] = archived_at


def test_archived_deal_in_deals_is_tombstoned_with_post_deletion_snapshots():
    hub, db = Hub(), DB()
    base.seed(db, NOW - 60 * MIN)
    hub.put(1, NOW - 2 * MIN)
    _ghost_setup(hub, db)
    code, out = base.run(hub, db)
    assert code == 0, out[-800:]
    assert "900" not in db.tables["deals"]
    t = db.tables["deleted_deals"]["900"]
    assert t["reason"] == "deleted_in_hubspot" and t["deal_row"]["deal_status"] == "active"
    assert [s["snapshot_date"] for s in t["removed_snapshot_rows"]] == ["2026-08-12", "2026-08-17", "2026-09-21"]
    assert [s["snapshot_date"] for s in db.snapshots] == ["2026-08-03", "2026-08-10", "2026-08-11"]
    assert base.cp(db) == NOW - 2 * MIN
    assert "Deletions:" in out and "1 tombstoned" in out
    print("✓ archived deal still in deals: tombstoned; snapshots 08-12+ moved to the tombstone, "
          "08-03/08-10/08-11 kept; exit 0; checkpoint advanced")


def test_archived_deal_already_gone_is_a_noop():
    hub, db = Hub(), DB()
    base.seed(db, NOW - 60 * MIN)
    hub.archived["901"] = "2026-07-03T10:31:24.739Z"
    code, out = base.run(hub, db)
    assert code == 0 and db.tables["deleted_deals"] == {}, out[-600:]
    assert [c["p_deal_id"] for c in db.rpc_calls] == ["901"]
    print("✓ archived deal not in deals: tombstone_deal returns 'absent', nothing written")


def test_merged_away_id_in_deals_is_tombstoned_keeping_snapshots():
    hub, db = Hub(), DB()
    base.seed(db, NOW - 60 * MIN)
    _ghost_setup(hub, db, deal_id="902", archived_at=None)
    hub.merged["905"] = ["902", "903"]
    code, out = base.run(hub, db)
    assert code == 0, out[-800:]
    t = db.tables["deleted_deals"]["902"]
    assert t["reason"] == "merged_away" and "905" in t["source"]
    assert t["removed_snapshot_rows"] is None and len(db.snapshots) == 6
    print("✓ merged-away id still in deals: tombstoned as merged_away (survivor noted), all snapshots kept")


def test_tombstone_failure_exits_one_and_keeps_checkpoint():
    hub, db = Hub(), DB()
    c = NOW - 60 * MIN
    base.seed(db, c)
    hub.put(1, NOW - 2 * MIN)
    _ghost_setup(hub, db)
    db.fail_rpc = True
    code, out = base.run(hub, db)
    assert code == 1 and base.cp(db) == c, (code, base.cp(db), out[-600:])
    assert "900" in db.tables["deals"], "a failed tombstone must leave the deal in place"
    print("✓ tombstone call fails: exit 1, checkpoint unchanged, deal still in place")


def test_archived_listing_failure_exits_one_and_keeps_checkpoint():
    hub, db = Hub(), DB()
    c = NOW - 60 * MIN
    base.seed(db, c)
    hub.put(1, NOW - 2 * MIN)
    hub.fail["/crm/v3/objects/deals"] = [500] * 5
    code, out = base.run(hub, db)
    assert code == 1 and base.cp(db) == c, (code, out[-600:])
    print("✓ HubSpot archived listing fails after retries: exit 1, checkpoint unchanged")


def test_full_sync_runs_the_same_pass():
    hub, db = Hub(), DB()
    hub.put(1, NOW - 2 * MIN)
    _ghost_setup(hub, db)
    code, out = base.run(hub, db, mode="analytics")
    assert code == 0 and "900" not in db.tables["deals"], out[-600:]
    print("✓ full analytics sync tombstones the ghost too")


def test_skipping_the_pass_leaves_the_ghost():
    """Planted bug: no deletion pass (every sync before part 3)."""
    hub, db = Hub(), DB()
    base.seed(db, NOW - 60 * MIN)
    _ghost_setup(hub, db)
    saved = etl_deals._apply_deletions
    etl_deals._apply_deletions = lambda hubspot, sb: ("skipped", None)
    try:
        base.run(hub, db)
    finally:
        etl_deals._apply_deletions = saved
    assert "900" in db.tables["deals"], "control should leave the ghost"
    print("✓ control: without the pass the deleted deal stays in deals (the Inditex shape)")


def test_ignoring_a_failed_pass_lets_checkpoint_advance():
    """Planted bug: swallow the deletion failure instead of failing the run."""
    hub, db = Hub(), DB()
    c = NOW - 60 * MIN
    base.seed(db, c)
    hub.put(1, NOW - 2 * MIN)
    hub.fail["/crm/v3/objects/deals"] = [500] * 5
    real = etl_deals._apply_deletions

    def swallow(hubspot, sb):
        status, problem = real(hubspot, sb)
        return status, None
    etl_deals._apply_deletions = swallow
    try:
        code, out = base.run(hub, db)
    finally:
        etl_deals._apply_deletions = real
    assert code == 0 and base.cp(db) != c, "control should show the checkpoint advancing"
    print("✓ control: swallowing the failed pass exits 0 and advances the checkpoint "
          "(what the real code refuses to do)")


if __name__ == "__main__":
    test_archived_deal_in_deals_is_tombstoned_with_post_deletion_snapshots()
    test_archived_deal_already_gone_is_a_noop()
    test_merged_away_id_in_deals_is_tombstoned_keeping_snapshots()
    test_tombstone_failure_exits_one_and_keeps_checkpoint()
    test_archived_listing_failure_exits_one_and_keeps_checkpoint()
    test_full_sync_runs_the_same_pass()
    test_skipping_the_pass_leaves_the_ghost()
    test_ignoring_a_failed_pass_lets_checkpoint_advance()
    print("\n✅ All tests passed")
