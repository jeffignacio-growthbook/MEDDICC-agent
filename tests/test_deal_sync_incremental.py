"""
Incremental deal sync, part 2: `etl_deals.py --mode incremental` and the
checkpoint rules. This is the boundary logic the transcript-ETL cutoff bug
got wrong.

Runs the real etl_deals.main(), HubSpotDealsClient (keyset fetch, retries),
deal_sync and SupabaseWriter.upsert_deal against a stateful fake HubSpot
(filters, index-lag hiding) and a fake Supabase (per-row failure injection).

Rules pinned, each with a planted-bug control where one makes sense:
  1. No checkpoint: exit 1, nothing fetched or written. (The first full sync
     sets it; see 9.)
  2. Window = checkpoint - 30 min, inclusive (GTE, epoch ms): a deal exactly
     on the boundary is synced, one 1 ms earlier isn't.
  3. Success advances the checkpoint to min(max hs_lastmodifieddate seen,
     fetch start). It never uses the runner's clock alone and never goes
     backwards.
  4. Any failure (company batch, a Supabase upsert) leaves the checkpoint
     where it was, and the next run re-reads the same window. Control:
     advancing despite failures (the transcript-ETL shape) loses a deal.
  5. A failed checkpoint write exits 1; the rerun is idempotent.
  6. A late-indexed deal (hidden from search when first modified) is still
     synced by the next run, thanks to the overlap. Control: a strict `>`
     with no overlap drops it for good (transcript-ETL cause C).
  7. Two edits between runs: the latest state is written.
  8. Nothing changed: exit 0, checkpoint unchanged, no crash (the 0-deal
     division in the batch step).
  9. A successful full (analytics) sync sets the checkpoint; a failed one
     doesn't.
 10. Backlog over MAX_INCREMENTAL_DEALS: exit 1, no fetch, checkpoint
     unchanged.
"""
import contextlib
import io
import json
import os
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

import requests

REPO = Path(__file__).parent.parent
sys.path.insert(0, str(REPO / "scripts"))
sys.path.insert(0, str(REPO))

import deal_sync  # noqa: E402
import etl_deals  # noqa: E402
import hubspot_deals  # noqa: E402
import supabase_client  # noqa: E402

BASE = "https://api.hubapi.com"
MIN = 60_000
NOW = int(time.time() * 1000)


def iso(ms):
    return datetime.fromtimestamp(ms / 1000, timezone.utc).strftime("%Y-%m-%dT%H:%M:%S.") + f"{ms % 1000:03d}Z"


def _resp(status, body):
    r = requests.Response()
    r.status_code = status
    r._content = json.dumps(body).encode()
    r.url = BASE
    return r


class Hub:
    """Stateful fake HubSpot. deals: id -> dict(lm=ms, new_revenue=..., stage=..., hidden=bool)."""

    def __init__(self):
        self.deals = {}
        self.fail = {}
        self.searches = []
        self.headers = {}

    def put(self, did, lm, new_revenue="1000", stage="s1", hidden=False):
        self.deals[str(did)] = {"lm": lm, "new_revenue": new_revenue, "stage": stage, "hidden": hidden}

    def _props(self, did, d):
        return {"hs_object_id": did, "dealname": f"Deal {did}", "dealstage": d["stage"],
                "pipeline": "default", "closedate": "2026-12-01", "createdate": "2026-01-01",
                "hubspot_owner_id": "1", "new_revenue": d["new_revenue"], "expansion_revenue": "0",
                "incremental_arr": d["new_revenue"], "amount": d["new_revenue"],
                "hs_lastmodifieddate": iso(d["lm"])}

    def _match(self, did, d, f):
        v = d["lm"] if f["propertyName"] == "hs_lastmodifieddate" else int(did)
        x = int(f["value"])
        return {"GT": v > x, "GTE": v >= x, "LT": v < x, "LTE": v <= x}[f["operator"]]

    def request(self, method, url, timeout=None, params=None, json=None):
        path = url[len(BASE):]
        q = self.fail.get(path)
        if q:
            return _resp(q.pop(0), {"message": "planted"})
        if path == "/crm/v3/owners":
            return _resp(200, {"results": [{"id": "1", "email": "rep@example.com"}]})
        if path == "/crm/v3/pipelines/deals":
            return _resp(200, {"results": [{"stages": [{"id": "closedwon", "label": "Closed Won"}]}]})
        if path == "/crm/v3/objects/companies/search":
            return _resp(200, {"total": 0, "results": []})   # no changed companies (see company-pass test)
        if path == "/crm/v3/objects/deals" and (params or {}).get("archived") == "true":
            return _resp(200, {"results": []})      # no deleted deals (see test_deal_sync_deletions)
        if path == "/crm/v3/objects/deals/search":
            filters = [f for g in json.get("filterGroups", []) for f in g["filters"]]
            if any(f.get("operator") == "HAS_PROPERTY" for f in filters):
                return _resp(200, {"total": 0, "results": []})   # no merged-away ids
            self.searches.append(json)
            rows = sorted((int(i), i, d) for i, d in self.deals.items()
                          if not d["hidden"] and all(self._match(i, d, f) for f in filters))
            limit = json.get("limit", 100)
            return _resp(200, {"total": len(rows), "results": [
                {"id": i, "properties": self._props(i, d)} for _, i, d in rows[:limit]]})
        if path == "/crm/v4/associations/deals/companies/batch/read":
            return _resp(200, {"results": [{"from": {"id": x["id"]}, "to": [{"toObjectId": "C1"}]}
                                           for x in json["inputs"]]})
        if path == "/crm/v3/objects/companies/batch/read":
            return _resp(200, {"results": [{"id": "C1", "properties": {
                "name": "Co", "numberofemployees": "5000", "domain": "co.com"}}]})
        return _resp(404, {"message": f"unrouted {path}"})


class DB:
    """Fake Supabase: tables keyed by their natural key, with failure injection."""
    KEYS = {"deals": "deal_id", "deal_sync_checkpoints": "job"}

    def __init__(self):
        self.tables = {"deals": {}, "deal_sync_checkpoints": {}}
        self.fail_upsert_ids = set()
        self.fail_checkpoint_write = False

    def table(self, name):
        return _Q(self, name)

    def rpc(self, name, params):
        """tombstone_deal() for the no-deletions case; the deletion contract
        itself is tested in test_deal_sync_deletions.py."""
        return type("Call", (), {"execute": lambda self_: type("R", (), {"data": "absent"})()})()


class _Q:
    def __init__(self, db, name):
        self.db, self.name, self.filters, self.row = db, name, {}, None

    def select(self, *a):
        return self

    def eq(self, k, v):
        self.filters[k] = v
        return self

    def upsert(self, row, on_conflict=None):
        self.row = row
        return self

    def execute(self):
        t = self.db.tables[self.name]
        if self.row is not None:
            key = self.row[DB.KEYS[self.name]]
            if self.name == "deals" and key in self.db.fail_upsert_ids:
                raise RuntimeError(f"planted upsert failure for {key}")
            if self.name == "deal_sync_checkpoints" and self.db.fail_checkpoint_write:
                raise RuntimeError("planted checkpoint write failure")
            t[key] = {**t.get(key, {}), **self.row}
            return type("R", (), {"data": [self.row]})()
        rows = [r for r in t.values() if all(r.get(k) == v for k, v in self.filters.items())]
        return type("R", (), {"data": rows})()


def run(hub, db, mode="incremental"):
    """One real etl_deals.main() run; returns (exit code, stdout)."""
    client = hubspot_deals.HubSpotDealsClient(api_key="test")
    client.session = hub
    hubspot_deals.HubSpotDealsClient._closed_stage_ids = None

    class Writer(supabase_client.SupabaseWriter):
        def __init__(self):
            self.client = db

    saved = (hubspot_deals.get_hubspot_deals_client, supabase_client.SupabaseWriter,
             sys.argv, os.environ.get("SUPABASE_URL"), time.sleep)
    hubspot_deals.get_hubspot_deals_client = lambda api_key=None: client
    supabase_client.SupabaseWriter = Writer
    sys.argv = ["etl_deals.py", "--mode", mode]
    os.environ["SUPABASE_URL"] = "https://fake.invalid"
    time.sleep = lambda s: None
    out = io.StringIO()
    try:
        with contextlib.redirect_stdout(out):
            code = etl_deals.main()
    finally:
        (hubspot_deals.get_hubspot_deals_client, supabase_client.SupabaseWriter,
         sys.argv, url, time.sleep) = saved
        if url is None:
            os.environ.pop("SUPABASE_URL", None)
        else:
            os.environ["SUPABASE_URL"] = url
    return code, out.getvalue()


def cp(db):
    row = db.tables["deal_sync_checkpoints"].get("deals")
    return row["watermark_ms"] if row else None


def seed(db, ms):
    db.tables["deal_sync_checkpoints"]["deals"] = {"job": "deals", "watermark_ms": ms}


# ── 1 ────────────────────────────────────────────────────────────────────────
def test_no_checkpoint_exits_one_and_touches_nothing():
    hub, db = Hub(), DB()
    hub.put(1, NOW - 5 * MIN)
    code, out = run(hub, db)
    assert code == 1, out[-600:]
    assert "no checkpoint" in out.lower()
    assert hub.searches == [] and db.tables["deals"] == {} and cp(db) is None
    print("✓ no checkpoint: exit 1, no HubSpot search, nothing written, checkpoint still absent")


# ── 2 + 3 ────────────────────────────────────────────────────────────────────
def test_window_is_checkpoint_minus_30min_inclusive_and_advances_on_success():
    hub, db = Hub(), DB()
    c = NOW - 60 * MIN
    seed(db, c)
    hub.put(10, c - 30 * MIN)        # exactly on the window boundary -> in
    hub.put(11, c - 30 * MIN - 1)    # 1 ms before -> out
    hub.put(12, c - 29 * MIN)        # inside the overlap -> in
    hub.put(13, NOW - 2 * MIN)       # recent -> in
    code, out = run(hub, db)
    assert code == 0, out[-800:]
    assert set(db.tables["deals"]) == {"10", "12", "13"}, sorted(db.tables["deals"])
    first = hub.searches[0]["filterGroups"][0]["filters"][0]
    assert first == {"propertyName": "hs_lastmodifieddate", "operator": "GTE",
                     "value": str(c - 30 * MIN)}, first
    assert cp(db) == NOW - 2 * MIN, (cp(db), NOW - 2 * MIN)
    assert "Checkpoint:" in out and "advanced" in out
    print("✓ window = checkpoint−30min inclusive (boundary in, 1 ms earlier out); "
          "checkpoint advanced to the max hs_lastmodifieddate seen")


def test_watermark_capped_at_fetch_start_and_never_regresses():
    hub, db = Hub(), DB()
    seed(db, NOW - 10 * MIN)
    hub.put(20, NOW + 60 * MIN)      # clock-skewed future timestamp
    code, out = run(hub, db)
    assert code == 0, out[-600:]
    assert NOW - 10 * MIN < cp(db) <= int(time.time() * 1000), cp(db)
    assert cp(db) < NOW + 60 * MIN, "watermark must be capped at the fetch start"

    hub2, db2 = Hub(), DB()
    seed(db2, NOW - 1 * MIN)
    hub2.put(21, NOW - 20 * MIN)     # only an overlap re-read, older than the checkpoint
    code, out = run(hub2, db2)
    assert code == 0 and cp(db2) == NOW - 1 * MIN, (code, cp(db2))
    print("✓ watermark capped at fetch start (future-skewed deal can't push it ahead); "
          "an overlap-only run never moves it backwards")


# ── 4 ────────────────────────────────────────────────────────────────────────
def test_any_failure_leaves_checkpoint_and_next_run_rereads():
    for label, arm in [
        ("company batch", lambda hub, db: hub.fail.__setitem__(
            "/crm/v4/associations/deals/companies/batch/read", [500] * 5)),
        ("supabase upsert", lambda hub, db: db.fail_upsert_ids.add("31")),
    ]:
        hub, db = Hub(), DB()
        c = NOW - 60 * MIN
        seed(db, c)
        hub.put(30, NOW - 3 * MIN)
        hub.put(31, NOW - 2 * MIN, new_revenue="777")
        arm(hub, db)
        code, out = run(hub, db)
        assert code == 1, (label, out[-600:])
        assert cp(db) == c, f"{label}: checkpoint moved on a failed run"
        assert "unchanged" in out
        hub.fail.clear()
        db.fail_upsert_ids.clear()
        code, out = run(hub, db)
        assert code == 0, (label, out[-600:])
        assert db.tables["deals"]["31"]["new_arr"] == 777.0, label
        assert cp(db) == NOW - 2 * MIN, label
    print("✓ company-batch failure and upsert failure: exit 1, checkpoint unchanged; "
          "next run re-reads the window and lands the missed deal")


def test_advancing_on_partial_failure_loses_a_deal():
    """Planted bug: the transcript-ETL shape. Advance the checkpoint even
    though the run failed; the unwritten deal falls behind the window."""
    hub, db = Hub(), DB()
    seed(db, NOW - 120 * MIN)
    hub.put(40, NOW - 100 * MIN, new_revenue="4000")   # upsert fails this run
    hub.put(41, NOW - 1 * MIN)
    db.fail_upsert_ids.add("40")
    saved = etl_deals._checkpoint_may_advance
    etl_deals._checkpoint_may_advance = lambda problems: True
    try:
        run(hub, db)
    finally:
        etl_deals._checkpoint_may_advance = saved
    db.fail_upsert_ids.clear()
    run(hub, db)
    assert "40" not in db.tables["deals"], "planted bug should have lost deal 40"
    print("✓ control: advancing despite a failed upsert permanently skips deal 40 "
          "(its lastmodified is now behind the window)")


# ── 5 ────────────────────────────────────────────────────────────────────────
def test_checkpoint_write_failure_exits_one_and_rerun_is_idempotent():
    hub, db = Hub(), DB()
    c = NOW - 60 * MIN
    seed(db, c)
    hub.put(50, NOW - 3 * MIN, new_revenue="500")
    db.fail_checkpoint_write = True
    code, out = run(hub, db)
    assert code == 1 and cp(db) == c, (code, cp(db))
    assert "checkpoint write failed" in out.lower()
    db.fail_checkpoint_write = False
    code, out = run(hub, db)
    assert code == 0 and cp(db) == NOW - 3 * MIN
    assert db.tables["deals"]["50"]["new_arr"] == 500.0
    print("✓ checkpoint write failure: exit 1, checkpoint unchanged; rerun rewrites the same "
          "deal identically and advances")


# ── 6 ────────────────────────────────────────────────────────────────────────
def _late_index_scenario(hub, db):
    seed(db, NOW - 120 * MIN)
    hub.put(60, NOW - 10 * MIN, hidden=True)   # modified, not yet searchable
    hub.put(61, NOW - 5 * MIN)
    run(hub, db)                                 # sees 61 only; checkpoint -> NOW-5min
    hub.deals["60"]["hidden"] = False            # index catches up; lastmodified unchanged
    run(hub, db)


def test_late_indexed_deal_is_caught_by_the_overlap():
    hub, db = Hub(), DB()
    _late_index_scenario(hub, db)
    assert "60" in db.tables["deals"], "overlap should re-read the late-indexed deal"
    print("✓ a deal modified 10 min ago but indexed late is synced by the next run (30-min overlap)")


def test_strict_gt_without_overlap_drops_the_late_indexed_deal():
    """Planted bug: transcript-ETL cause C, a strict `>` on the max value seen."""
    hub, db = Hub(), DB()
    saved = (deal_sync.OVERLAP_MS, deal_sync.WINDOW_OPERATOR)
    deal_sync.OVERLAP_MS, deal_sync.WINDOW_OPERATOR = 0, "GT"
    try:
        _late_index_scenario(hub, db)
    finally:
        deal_sync.OVERLAP_MS, deal_sync.WINDOW_OPERATOR = saved
    assert "60" not in db.tables["deals"], "planted no-overlap GT should have lost deal 60"
    print("✓ control: strict GT with no overlap drops the late-indexed deal for good")


# ── 7 ────────────────────────────────────────────────────────────────────────
def test_two_edits_between_runs_latest_state_wins():
    hub, db = Hub(), DB()
    seed(db, NOW - 60 * MIN)
    hub.put(70, NOW - 20 * MIN, new_revenue="100")
    hub.put(70, NOW - 4 * MIN, new_revenue="250")   # second edit before any sync
    code, out = run(hub, db)
    assert code == 0 and db.tables["deals"]["70"]["new_arr"] == 250.0
    print("✓ two edits between runs: the latest value (250) is written")


# ── 8 ────────────────────────────────────────────────────────────────────────
def test_nothing_changed_exits_zero_without_crashing():
    hub, db = Hub(), DB()
    c = NOW - 5 * MIN
    seed(db, c)
    code, out = run(hub, db)
    assert code == 0, out[-800:]
    assert cp(db) == c and db.tables["deals"] == {}
    print("✓ empty window: exit 0, no crash (0-deal batch step), checkpoint unchanged")


# ── 9 ────────────────────────────────────────────────────────────────────────
def test_full_sync_sets_checkpoint_only_on_success():
    hub, db = Hub(), DB()
    hub.put(90, NOW - 30 * MIN)
    hub.put(91, NOW - 3 * MIN)
    code, out = run(hub, db, mode="analytics")
    assert code == 0 and cp(db) == NOW - 3 * MIN, (code, cp(db), out[-600:])

    hub2, db2 = Hub(), DB()
    hub2.put(92, NOW - 3 * MIN)
    db2.fail_upsert_ids.add("92")
    code, out = run(hub2, db2, mode="analytics")
    assert code == 1 and cp(db2) is None
    print("✓ full analytics sync sets the checkpoint on success (bootstrap), not on failure")


# ── 10 ───────────────────────────────────────────────────────────────────────
def test_backlog_over_limit_exits_one_without_fetching():
    hub, db = Hub(), DB()
    c = NOW - 60 * MIN
    seed(db, c)
    for i in range(5):
        hub.put(100 + i, NOW - 2 * MIN)
    saved = deal_sync.MAX_INCREMENTAL_DEALS
    deal_sync.MAX_INCREMENTAL_DEALS = 3
    try:
        code, out = run(hub, db)
    finally:
        deal_sync.MAX_INCREMENTAL_DEALS = saved
    assert code == 1 and cp(db) == c and db.tables["deals"] == {}, (code, out[-500:])
    assert all(s.get("limit") == 1 for s in hub.searches), "only the count query may run"
    print("✓ backlog over the limit: exit 1 after a count-only query, nothing written, "
          "checkpoint unchanged")


if __name__ == "__main__":
    test_no_checkpoint_exits_one_and_touches_nothing()
    test_window_is_checkpoint_minus_30min_inclusive_and_advances_on_success()
    test_watermark_capped_at_fetch_start_and_never_regresses()
    test_any_failure_leaves_checkpoint_and_next_run_rereads()
    test_advancing_on_partial_failure_loses_a_deal()
    test_checkpoint_write_failure_exits_one_and_rerun_is_idempotent()
    test_late_indexed_deal_is_caught_by_the_overlap()
    test_strict_gt_without_overlap_drops_the_late_indexed_deal()
    test_two_edits_between_runs_latest_state_wins()
    test_nothing_changed_exits_zero_without_crashing()
    test_full_sync_sets_checkpoint_only_on_success()
    test_backlog_over_limit_exits_one_without_fetching()
    print("\n✅ All tests passed")
