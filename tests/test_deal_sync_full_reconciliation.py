"""
Incremental deal sync, part 5: the full sync as safety net.

With the hourly incremental carrying freshness, the full analytics sync moves
to every ~12h. Its job is to catch whatever the incremental path could miss:

  1. It pages by hs_object_id (keyset) instead of the offset cursor sorted by
     lastmodified, which skips a deal edited mid-fetch
     (test_deal_sync_keyset_and_checkpoint shows that skip with the legacy
     paging).
  2. Reconciliation: every deal in Supabase that the complete HubSpot listing
     didn't return, and that the deletion pass (part 3) didn't explain, is
     looked up directly:
       - 404 and not in HubSpot's recycle bin: purged from HubSpot. Tombstone
         it (reason purged_from_hubspot). Snapshots are kept because the
         deletion date is unknown.
       - still exists in HubSpot: a real gap in the listing. Exit 1 and report
         it; don't auto-fix.
     Reconciliation only runs after a clean run, since a partial one would
     make every unwritten deal look like an orphan.
  3. The schedule: full sync ~12h, hourly incremental, both alerting (their
     writes are serialised by the sync lease, test_deal_sync_lease).

Planted control: without reconciliation, a deal purged from HubSpot stays in
Supabase indefinitely.
"""
import sys
from pathlib import Path

import yaml

REPO = Path(__file__).parent.parent
sys.path.insert(0, str(REPO / "tests"))
sys.path.insert(0, str(REPO / "scripts"))

import test_deal_sync_deletions as dele  # noqa: E402  (fakes with rpc + snapshots)
import test_deal_sync_incremental as base  # noqa: E402
import etl_deals  # noqa: E402

MIN, NOW = base.MIN, base.NOW


class Hub(dele.Hub):
    def __init__(self):
        super().__init__()
        self.direct = {}   # id -> 200 | 404 for GET /crm/v3/objects/deals/{id}

    def request(self, method, url, timeout=None, params=None, json=None):
        path = url[len(base.BASE):]
        if method == "GET" and path.startswith("/crm/v3/objects/deals/") and path.count("/") == 5:
            did = path.rsplit("/", 1)[1]
            status = self.direct.get(did, 404)
            return base._resp(status, {"id": did} if status == 200 else {"message": "not found"})
        return super().request(method, url, timeout, params, json)


DB = dele.DB   # the shared fake pages select_all() via .range()


def test_full_sync_pages_by_object_id():
    hub, db = Hub(), DB()
    for i in range(1, 4):
        hub.put(i, NOW - i * MIN)
    code, out = base.run(hub, db, mode="analytics")
    assert code == 0, out[-600:]
    deal_searches = [s for s in hub.searches
                     if not any(f.get("operator") == "HAS_PROPERTY"
                                for g in s.get("filterGroups", []) for f in g["filters"])]
    assert deal_searches and all(
        s["sorts"] == [{"propertyName": "hs_object_id", "direction": "ASCENDING"}] and "after" not in s
        for s in deal_searches), deal_searches
    print("✓ full analytics sync fetches with keyset paging (hs_object_id ascending, no offset cursor)")


def _orphan(db, did):
    db.tables["deals"][did] = {"deal_id": did, "deal_status": "active"}
    db.snapshots.append({"deal_id": did, "snapshot_date": "2026-09-21"})


def test_purged_orphan_is_tombstoned_keeping_snapshots():
    hub, db = Hub(), DB()
    hub.put(1, NOW - 2 * MIN)
    _orphan(db, "800")                   # in Supabase, gone from HubSpot, not archived
    code, out = base.run(hub, db, mode="analytics")
    assert code == 0, out[-800:]
    assert "800" not in db.tables["deals"]
    t = db.tables["deleted_deals"]["800"]
    assert t["reason"] == "purged_from_hubspot" and t["removed_snapshot_rows"] is None
    assert db.snapshots == [{"deal_id": "800", "snapshot_date": "2026-09-21"}]
    assert "Reconciliation:" in out and "1 purged" in out
    print("✓ orphan purged from HubSpot (404, not archived): tombstoned as purged_from_hubspot, snapshots kept")


def test_orphan_still_in_hubspot_fails_the_run_without_auto_fix():
    hub, db = Hub(), DB()
    hub.put(1, NOW - 2 * MIN)
    _orphan(db, "801")
    hub.direct["801"] = 200              # exists, but the listing didn't return it
    code, out = base.run(hub, db, mode="analytics")
    assert code == 1, out[-600:]
    assert "801" in db.tables["deals"] and "801" not in db.tables["deleted_deals"]
    assert "801" in out and "missing from the full listing" in out
    print("✓ orphan that still exists in HubSpot: exit 1 and reported, not tombstoned")


def test_reconciliation_skipped_when_the_run_had_failures():
    hub, db = Hub(), DB()
    hub.put(1, NOW - 2 * MIN)
    _orphan(db, "802")
    db.fail_upsert_ids.add("1")
    code, out = base.run(hub, db, mode="analytics")
    assert code == 1 and "802" in db.tables["deals"], out[-600:]
    assert "Reconciliation:" in out and "skipped" in out
    print("✓ run with failures: reconciliation skipped (a partial run can't identify orphans)")


def test_incremental_run_does_not_reconcile():
    hub, db = Hub(), DB()
    base.seed(db, NOW - 60 * MIN)
    hub.put(1, NOW - 2 * MIN)
    _orphan(db, "803")
    code, out = base.run(hub, db)
    assert code == 0 and "803" in db.tables["deals"], out[-600:]
    print("✓ incremental run leaves reconciliation to the full sync (a window isn't a complete listing)")


def test_without_reconciliation_the_purged_deal_stays():
    """Planted bug: full sync with no reconciliation (before part 5)."""
    hub, db = Hub(), DB()
    hub.put(1, NOW - 2 * MIN)
    _orphan(db, "804")
    saved = etl_deals._reconcile
    etl_deals._reconcile = lambda hubspot, sb, fetched_ids: ("disabled", None)
    try:
        base.run(hub, db, mode="analytics")
    finally:
        etl_deals._reconcile = saved
    assert "804" in db.tables["deals"]
    print("✓ control: without reconciliation the purged deal stays in Supabase")


def test_schedule_full_12h_hourly_incremental():
    full = yaml.safe_load((REPO / ".github/workflows/daily-analytics-etl.yml").read_text())
    inc = yaml.safe_load((REPO / ".github/workflows/hourly-deal-sync.yml").read_text())
    full_cron = full[True]["schedule"][0]["cron"]
    inc_cron = inc[True]["schedule"][0]["cron"]
    hours = full_cron.split()[1]
    runs_per_day = len(hours.split(",")) if "," in hours else (24 // int(hours.split("/")[1]) if "/" in hours else 1)
    assert runs_per_day == 2, f"full sync should run ~12-hourly, cron={full_cron!r}"
    assert inc_cron.split()[1] == "*", f"incremental should run hourly, cron={inc_cron!r}"
    # write serialisation is the DB lease, not a shared group
    # (test_deal_sync_lease.test_workflows_rely_on_the_lease_not_a_shared_group)
    print(f"✓ schedule: full sync {full_cron!r} (2/day), incremental {inc_cron!r} (hourly)")


def test_many_orphans_means_a_bad_listing_so_nothing_is_tombstoned():
    """Safety: a partial HubSpot listing must never become a mass deletion."""
    hub, db = Hub(), DB()
    hub.put(1, NOW - 2 * MIN)
    n = etl_deals.MAX_RECONCILE_ORPHANS + 5
    for i in range(n):
        _orphan(db, str(7000 + i))
    code, out = base.run(hub, db, mode="analytics")
    assert code == 1, out[-600:]
    assert db.tables["deleted_deals"] == {} and all(str(7000 + i) in db.tables["deals"] for i in range(n))
    print(f"✓ {n} orphans (> {etl_deals.MAX_RECONCILE_ORPHANS}): treated as a bad listing; exit 1, "
          "nothing tombstoned")


if __name__ == "__main__":
    test_full_sync_pages_by_object_id()
    test_purged_orphan_is_tombstoned_keeping_snapshots()
    test_orphan_still_in_hubspot_fails_the_run_without_auto_fix()
    test_reconciliation_skipped_when_the_run_had_failures()
    test_incremental_run_does_not_reconcile()
    test_without_reconciliation_the_purged_deal_stays()
    test_schedule_full_12h_hourly_incremental()
    test_many_orphans_means_a_bad_listing_so_nothing_is_tombstoned()
    print("\n✅ All tests passed")
