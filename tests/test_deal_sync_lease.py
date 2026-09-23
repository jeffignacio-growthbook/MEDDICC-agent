"""
Incremental deal sync: a full sync and an incremental run never write at the
same time.

Why: the full sync (cron 7 5,17 * * *, 8-12 min) and the hourly incremental
(cron 17 * * * *) sit ten minutes apart, and scheduled starts on this repo
drift by hours. Until now the only guard was a shared GitHub Actions
concurrency group. That has two gaps:
  - the manual workflows that also run `etl_deals.py --mode analytics`
    (run-analytics-etl, load-segments, recompute-deal-status,
    resync-forecast-category) aren't in the group;
  - a group holds one running and one pending run, and a newly queued run
    cancels the pending one, so a queued incremental can cancel a pending
    full sync.
Any etl_deals.py run that writes Supabase now first takes a lease in the
database (deal_sync_leases, migration 071, via the atomic
acquire_deal_sync_lease() function). When another run holds it:
  - an incremental run skips: exit 0, no writes, checkpoint unchanged. The
    next hourly run re-reads the window, so nothing is lost;
  - a full (or any other) run waits up to LEASE_WAIT_S for it, then exits 1
    without writing.
The lease expires after LEASE_TTL_S (a crashed runner can't block syncs for
ever). It is renewed before the write phase; a run that lost it writes
nothing and exits 1. It is released on every exit path.

The race the lease prevents, pinned by the planted control (lease disabled):
a full sync fetches deal 1 (old value) and deal 2 doesn't exist yet. While
it's still running, deal 1 is edited, deal 2 is created, and an incremental
run writes both. Then the full sync writes its stale deal 1 over the newer
value, and its reconciliation finds deal 2 (not in its listing, but live in
HubSpot) and fails the run with a false "missing from the full listing".

Here two real etl_deals.main() runs execute concurrently in two threads
against shared fakes. The full sync is paused mid-run (after its HubSpot
listing, before any write) while the incremental run is attempted.
"""
import contextlib
import io
import os
import sys
import threading
import time
from pathlib import Path

REPO = Path(__file__).parent.parent
sys.path.insert(0, str(REPO / "tests"))
sys.path.insert(0, str(REPO / "scripts"))

import test_deal_sync_full_reconciliation as recon  # noqa: E402  (direct GET route)
import test_deal_sync_incremental as base  # noqa: E402
import deal_sync  # noqa: E402
import etl_deals  # noqa: E402
import hubspot_deals  # noqa: E402
import supabase_client  # noqa: E402

MIN, NOW = base.MIN, base.NOW
PAUSE_PATH = "/crm/v4/associations/deals/companies/batch/read"


class Hub(recon.Hub):
    """Pauses the first thread that reaches the deal->company association
    read (just after the deal listing, before any Supabase write) until
    released."""

    def __init__(self):
        super().__init__()
        self.pause_thread = None
        self.paused = threading.Event()
        self.resume = threading.Event()

    def request(self, method, url, timeout=None, params=None, json=None):
        if (url.endswith(PAUSE_PATH) and self.pause_thread is not None
                and threading.current_thread() is self.pause_thread and not self.resume.is_set()):
            self.paused.set()
            assert self.resume.wait(10), "full sync never released"
        return super().request(method, url, timeout, params, json)


class _ThreadStdout(io.TextIOBase):
    """sys.stdout that keeps each thread's output apart."""

    def __init__(self):
        self.bufs = {}

    def write(self, s):
        self.bufs.setdefault(threading.get_ident(), io.StringIO()).write(s)
        return len(s)

    def text(self, ident):
        return self.bufs.get(ident, io.StringIO()).getvalue()


@contextlib.contextmanager
def _env(hub, db):
    """base.run()'s patching, done once so two main() calls can overlap."""
    class Writer(supabase_client.SupabaseWriter):
        def __init__(self):
            self.client = db

    def client_factory(api_key=None):
        c = hubspot_deals.HubSpotDealsClient(api_key="test")
        c.session = hub
        return c

    saved = (hubspot_deals.get_hubspot_deals_client, supabase_client.SupabaseWriter,
             sys.argv, os.environ.get("SUPABASE_URL"), time.sleep, sys.stdout)
    hubspot_deals.get_hubspot_deals_client = client_factory
    hubspot_deals.HubSpotDealsClient._closed_stage_ids = None
    supabase_client.SupabaseWriter = Writer
    os.environ["SUPABASE_URL"] = "https://fake.invalid"
    time.sleep = lambda s: None
    out = _ThreadStdout()
    sys.stdout = out
    try:
        yield out
    finally:
        (hubspot_deals.get_hubspot_deals_client, supabase_client.SupabaseWriter,
         sys.argv, url, time.sleep, sys.stdout) = saved
        if url is None:
            os.environ.pop("SUPABASE_URL", None)
        else:
            os.environ["SUPABASE_URL"] = url


def _start(mode, result):
    """Run main() in a thread. argv is read once by argparse at the top of
    main(), so callers set sys.argv, start, and wait for the run to pass that
    point before changing argv for the next run."""
    sys.argv = ["etl_deals.py", "--mode", mode]

    def target():
        result["ident"] = threading.get_ident()
        result["code"] = etl_deals.main()
    t = threading.Thread(target=target, daemon=True)
    t.start()
    return t


def _race(hub, db):
    """Full sync paused after its listing; deal 1 edited and deal 2 created
    in HubSpot; an incremental run attempted; then the full sync resumed.
    Returns (full result, incremental result, deal 1 value right after the
    incremental run, stdout)."""
    base.seed(db, NOW - 60 * MIN)
    hub.put(1, NOW - 90 * MIN, new_revenue="1000")
    db.tables["deals"]["1"] = {"deal_id": "1", "arr_usd": 1000.0}
    full, inc = {}, {}
    with _env(hub, db) as out:
        tf = _start("analytics", full)
        hub.pause_thread = tf
        assert hub.paused.wait(10), "full sync never reached the pause point:\n" + out.text(full.get("ident"))
        hub.put(1, NOW - 1 * MIN, new_revenue="5000")          # edited mid-full-sync
        hub.put(2, NOW - 1 * MIN, new_revenue="700")           # created mid-full-sync
        hub.direct["2"] = 200
        ti = _start("incremental", inc)
        ti.join(10)
        assert not ti.is_alive(), "incremental run hung (waiting on the full sync?)"
        after_inc = {k: dict(v) for k, v in db.tables["deals"].items()}
        hub.resume.set()
        tf.join(10)
        assert not tf.is_alive()
        return full, inc, after_inc, out


def test_incremental_during_full_sync_is_blocked_without_writing():
    hub, db = Hub(), recon.DB()
    full, inc, after_inc, out = _race(hub, db)
    inc_out, full_out = out.text(inc["ident"]), out.text(full["ident"])
    assert inc["code"] == 0, inc_out[-800:]
    assert "skipped" in inc_out.lower() and "lease" in inc_out.lower(), inc_out[-800:]
    assert after_inc == {"1": {"deal_id": "1", "arr_usd": 1000.0}}, \
        f"the incremental run must not write while the full sync holds the lease: {after_inc}"
    assert full["code"] == 0, full_out[-1200:]
    # the full sync fetched deal 1 before the edit; the checkpoint it sets is
    # capped at its fetch start, so the next incremental window re-reads it
    assert base.cp(db) < NOW - 1 * MIN, base.cp(db)
    assert db.tables["deal_sync_leases"] == {}, "lease must be released"
    code, nxt = base.run(hub, db)
    assert code == 0, nxt[-600:]
    assert db.tables["deals"]["1"]["arr_usd"] == 5000.0 and "2" in db.tables["deals"]
    print("✓ incremental attempted while a full sync is mid-run: skipped on the lease "
          "(exit 0, no writes); the full sync finished cleanly (exit 0) and released it; "
          "the next incremental picked up the mid-run edit and the new deal")


def test_without_the_lease_the_runs_race():
    """Planted bug: no lease (the GitHub concurrency group was the only guard)."""
    hub, db = Hub(), recon.DB()
    saved = deal_sync.SyncLease.acquire, deal_sync.SyncLease.renew
    deal_sync.SyncLease.acquire = lambda self, wait_s=0: True
    deal_sync.SyncLease.renew = lambda self: True
    try:
        full, inc, after_inc, out = _race(hub, db)
    finally:
        deal_sync.SyncLease.acquire, deal_sync.SyncLease.renew = saved
    full_out = out.text(full["ident"])
    assert inc["code"] == 0 and after_inc["1"]["arr_usd"] == 5000.0, "control: the incremental run wrote mid-full-sync"
    assert db.tables["deals"]["1"]["arr_usd"] == 1000.0, "control: stale full-sync value overwrote it"
    assert full["code"] == 1 and "missing from the full listing" in full_out, full_out[-800:]
    print("✓ control: without the lease the incremental run writes deal 1 = 5000 mid-full-sync, "
          "the full sync then overwrites it with its stale 1000, and fails on a false "
          "'missing from the full listing' for the deal created meanwhile")


def _hold(db, holder="someone-else", mode="incremental", expires_in_s=600):
    db.tables["deal_sync_leases"]["deals"] = {
        "job": "deals", "holder": holder, "mode": mode,
        "expires_at": db.now() + expires_in_s}


def test_full_sync_waits_for_a_held_lease_then_fails_without_writing():
    hub, db = recon.Hub(), recon.DB()
    hub.put(1, NOW - 2 * MIN)
    _hold(db)
    saved = deal_sync.LEASE_WAIT_S
    deal_sync.LEASE_WAIT_S = 0
    try:
        code, out = base.run(hub, db, mode="analytics")
    finally:
        deal_sync.LEASE_WAIT_S = saved
    assert code == 1 and db.tables["deals"] == {} and base.cp(db) is None, out[-600:]
    assert "someone-else" in out and db.tables["deal_sync_leases"]["deals"]["holder"] == "someone-else"
    print("✓ full sync finds the lease held past its wait: exit 1, nothing written, "
          "the other run's lease untouched")


def test_full_sync_proceeds_once_the_holder_releases():
    hub, db = recon.Hub(), recon.DB()
    hub.put(1, NOW - 2 * MIN)
    _hold(db)
    polls = []

    def release_on_second_poll(name, params):
        polls.append(name)
        if name == "acquire_deal_sync_lease" and len(polls) == 2:
            db.tables["deal_sync_leases"].pop("deals", None)
    db.on_rpc = release_on_second_poll
    code, out = base.run(hub, db, mode="analytics")
    assert code == 0 and "1" in db.tables["deals"], out[-600:]
    assert polls.count("acquire_deal_sync_lease") >= 2
    print("✓ full sync waits on a held lease and runs once the holder releases it")


def test_expired_lease_is_taken_over():
    hub, db = recon.Hub(), recon.DB()
    base.seed(db, NOW - 60 * MIN)
    hub.put(1, NOW - 2 * MIN)
    _hold(db, holder="crashed-runner", expires_in_s=-1)
    code, out = base.run(hub, db)
    assert code == 0 and "1" in db.tables["deals"], out[-600:]
    assert db.tables["deal_sync_leases"] == {}
    print("✓ lease left by a crashed runner expires (TTL) and the next run takes it over")


def test_lease_lost_before_writing_means_no_writes():
    hub, db = recon.Hub(), recon.DB()
    c = NOW - 60 * MIN
    base.seed(db, c)
    hub.put(1, NOW - 2 * MIN)

    def steal(name, params):
        if name == "renew_deal_sync_lease":
            _hold(db, holder="thief")
    db.on_rpc = steal
    code, out = base.run(hub, db)
    assert code == 1 and db.tables["deals"] == {} and base.cp(db) == c, out[-600:]
    assert db.rpc_calls_named("tombstone_deal") == []
    assert db.tables["deal_sync_leases"]["deals"]["holder"] == "thief", "don't release someone else's lease"
    print("✓ lease lost before the write phase (expired and taken): nothing written, "
          "no deletions, checkpoint unchanged, exit 1, the new holder's lease kept")


def test_lease_released_on_a_failed_run():
    hub, db = recon.Hub(), recon.DB()
    base.seed(db, NOW - 60 * MIN)
    hub.put(1, NOW - 2 * MIN)
    db.fail_upsert_ids.add("1")
    code, out = base.run(hub, db)
    assert code == 1 and db.tables["deal_sync_leases"] == {}, out[-600:]
    hub2, db2 = recon.Hub(), recon.DB()     # early return: no checkpoint
    code, out = base.run(hub2, db2)
    assert code == 1 and db2.tables["deal_sync_leases"] == {}, out[-600:]
    print("✓ lease released after a failed run and after an early exit")


def test_workflows_rely_on_the_lease_not_a_shared_group():
    import yaml
    wf = REPO / ".github/workflows"
    full = yaml.safe_load((wf / "daily-analytics-etl.yml").read_text())
    inc = yaml.safe_load((wf / "hourly-deal-sync.yml").read_text())
    assert full["concurrency"]["group"] != inc["concurrency"]["group"], (
        "a shared group lets a queued incremental cancel a pending full sync; "
        "the DB lease serialises them instead")
    assert full["concurrency"]["cancel-in-progress"] is False
    assert inc["concurrency"]["cancel-in-progress"] is False
    print(f"✓ workflows: full sync group {full['concurrency']['group']!r}, incremental group "
          f"{inc['concurrency']['group']!r}; neither can cancel the other; the DB lease "
          "serialises their writes")


if __name__ == "__main__":
    test_incremental_during_full_sync_is_blocked_without_writing()
    test_without_the_lease_the_runs_race()
    test_full_sync_waits_for_a_held_lease_then_fails_without_writing()
    test_full_sync_proceeds_once_the_holder_releases()
    test_expired_lease_is_taken_over()
    test_lease_lost_before_writing_means_no_writes()
    test_lease_released_on_a_failed_run()
    test_workflows_rely_on_the_lease_not_a_shared_group()
    print("\n✅ All tests passed")
