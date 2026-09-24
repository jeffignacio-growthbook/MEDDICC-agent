"""
Incremental deal sync, part 1: keyset paging on hs_object_id + checkpoint store.

Why (2026-09-23 audit, PENDING_WORK "Incremental deal sync"): HubSpot's
search cursor behaves as an offset. get_all_deals_including_closed() sorts by
hs_lastmodifieddate DESCENDING and pages with that cursor, so a deal edited
while the fetch is paging jumps to page 1, which has already been read, and is
skipped for that run. An incremental sync that pages the same way would have
the same hole, repeated every hour. Keyset paging (hs_object_id > last_id,
sorted by hs_object_id ascending) can't skip: the id never changes, so an edit
mid-run doesn't move anything.

The checkpoint is the transcript-ETL lesson (TRANSCRIPT_GAP_INVESTIGATION
2026-09-22 cause C / §4). It lives in Supabase deal_sync_checkpoints, is only
written by an explicit advance(), and refuses values that aren't epoch
milliseconds, because an ISO string with no timezone makes deals/search
return HTTP 400.

Pins, each with a planted-bug control:
  1. Keyset fetch returns every deal once, even when deals are edited between
     pages. Control: the same edits make the existing offset/lastmodified
     fetch skip a deal.
  2. Keyset and full fetch request one shared property list.
  3. Keyset fetch combines a caller filter (e.g. lastmodified >= window)
     with the id cursor.
  4. CheckpointStore: missing -> None, advance round-trips, bad values refused.
"""
import sys
from pathlib import Path

REPO = Path(__file__).parent.parent
sys.path.insert(0, str(REPO / "scripts"))

import hubspot_deals  # noqa: E402
import deal_sync  # noqa: E402


class FakeSearch:
    """A small deals/search: AND-ed filters (GT/GTE/LT/EQ on numeric or ms
    values), one sort, offset `after`, limit. `on_page(n, store)` runs after
    page n is served, to model edits happening mid-fetch."""

    def __init__(self, n_deals=250, on_page=None):
        self.deals = {str(1000 + i): {"hs_object_id": str(1000 + i),
                                      "hs_lastmodifieddate": 1_700_000_000_000 + i * 1000}
                      for i in range(n_deals)}
        self.on_page = on_page
        self.pages = 0
        self.bodies = []

    def _match(self, d, f):
        v, x = float(d[f["propertyName"]]), float(f["value"])
        return {"GT": v > x, "GTE": v >= x, "LT": v < x, "LTE": v <= x, "EQ": v == x}[f["operator"]]

    def post(self, endpoint, body):
        assert endpoint == "/crm/v3/objects/deals/search", endpoint
        self.bodies.append(body)
        filters = [f for g in body.get("filterGroups", []) for f in g["filters"]]
        rows = [d for d in self.deals.values() if all(self._match(d, f) for f in filters)]
        s = (body.get("sorts") or [{"propertyName": "hs_object_id", "direction": "ASCENDING"}])[0]
        rows.sort(key=lambda d: float(d[s["propertyName"]]), reverse=s["direction"] == "DESCENDING")
        start = int(body.get("after") or 0)
        page = rows[start:start + body["limit"]]
        resp = {"total": len(rows),
                "results": [{"id": d["hs_object_id"],
                             "properties": {k: str(v) for k, v in d.items()}} for d in page]}
        if start + body["limit"] < len(rows):
            resp["paging"] = {"next": {"after": str(start + body["limit"])}}
        self.pages += 1
        if self.on_page:
            self.on_page(self.pages, self.deals)
        return resp


def _client(fake):
    c = hubspot_deals.HubSpotDealsClient(api_key="test")
    c._post = fake.post
    return c


def _edit_old_deal_after_first_page(n, deals):
    # After page 1, edit a deal that would come on a later page of a
    # lastmodified-DESC listing: it jumps to the top (already read).
    if n == 1:
        deals["1010"]["hs_lastmodifieddate"] = 1_800_000_000_000


def test_keyset_fetch_returns_every_deal_despite_mid_fetch_edits():
    fake = FakeSearch(on_page=_edit_old_deal_after_first_page)
    got = _client(fake).search_deals_keyset()
    ids = [d["id"] for d in got]
    assert len(ids) == len(set(ids)) == 250, (len(ids), len(set(ids)))
    for body in fake.bodies:
        assert body["sorts"] == [{"propertyName": "hs_object_id", "direction": "ASCENDING"}]
        assert "after" not in body, "keyset paging must not use the offset cursor"
    print("✓ keyset fetch: all 250 deals exactly once while a deal is edited mid-fetch")


def _legacy_offset_fetch(post):
    """The pre-2026-09-23 get_all_deals_including_closed() paging, verbatim
    in shape: lastmodified DESC + the search cursor (an offset)."""
    body = {"filterGroups": [], "properties": list(hubspot_deals.HubSpotDealsClient.DEAL_SYNC_PROPERTIES),
            "sorts": [{"propertyName": "hs_lastmodifieddate", "direction": "DESCENDING"}], "limit": 100}
    out, after = [], None
    while True:
        if after:
            body["after"] = after
        r = post("/crm/v3/objects/deals/search", body)
        out.extend(r.get("results", []))
        after = r.get("paging", {}).get("next", {}).get("after")
        if not after:
            return out


def test_offset_lastmodified_fetch_skips_under_the_same_edit():
    """Planted-bug control: the legacy full-fetch paging under the identical
    edit skips the deal, and the current full fetch doesn't."""
    fake = FakeSearch(on_page=_edit_old_deal_after_first_page)
    ids = {d["id"] for d in _legacy_offset_fetch(fake.post)}
    assert "1010" not in ids and len(ids) == 249, len(ids)
    fake2 = FakeSearch(on_page=_edit_old_deal_after_first_page)
    now = {d["id"] for d in _client(fake2).get_all_deals_including_closed()}
    assert len(now) == 250 and "1010" in now
    print("✓ control: legacy offset + lastmodified-DESC paging skips deal 1010 (249/250); "
          "get_all_deals_including_closed() now returns all 250")


def test_keyset_and_full_fetch_share_one_property_list():
    fake = FakeSearch(n_deals=3)
    c = _client(fake)
    c.search_deals_keyset()
    keyset_props = fake.bodies[-1]["properties"]
    c.get_all_deals_including_closed()
    full_props = fake.bodies[-1]["properties"]
    assert keyset_props == full_props == list(hubspot_deals.HubSpotDealsClient.DEAL_SYNC_PROPERTIES)
    for p in ("new_revenue", "expansion_revenue", "prior_arr", "renewal_revenue",
              "hs_lastmodifieddate", "hs_object_id"):
        assert p in keyset_props, p
    print(f"✓ keyset and full fetch request the same {len(keyset_props)} properties, "
          "incl. every ARR component, hs_lastmodifieddate and hs_object_id")


def test_keyset_fetch_combines_window_filter_with_id_cursor():
    fake = FakeSearch()
    since = 1_700_000_000_000 + 100 * 1000  # deals 1100..1249: two pages
    window = {"propertyName": "hs_lastmodifieddate", "operator": "GTE", "value": str(since)}
    got = _client(fake).search_deals_keyset(extra_filters=[window])
    assert [d["id"] for d in got] == [str(i) for i in range(1100, 1250)]
    assert len(fake.bodies) == 2, len(fake.bodies)
    first, second = (b["filterGroups"][0]["filters"] for b in fake.bodies)
    assert first == [window], first  # page 1: window only, no cursor yet
    assert window in second and {"propertyName": "hs_object_id", "operator": "GT",
                                 "value": "1199"} in second, second
    print("✓ window filter (lastmodified GTE, epoch ms) on every page, id cursor from page 2 "
          "(hs_object_id > 1199): exactly deals 1100-1249, boundary deal included")


sys.path.insert(0, str(Path(__file__).parent))
from strict_supabase import parse_select, check_column, check_write, project  # noqa: E402


class FakeTable:
    """deal_sync_checkpoints, read like Postgres (tests/strict_supabase.py):
    only selected columns come back; unknown columns raise."""
    def __init__(self, rows):
        self.rows, self._f, self._pending, self._cols = rows, {}, None, None

    def select(self, *a):
        self._f = {}
        self._cols = parse_select("deal_sync_checkpoints", *a)
        return self

    def eq(self, k, v):
        check_column("deal_sync_checkpoints", k)
        self._f[k] = v
        return self

    def upsert(self, row, on_conflict=None):
        check_write("deal_sync_checkpoints", row)
        self._pending = row
        return self

    def execute(self):
        if self._pending is not None:
            self.rows[self._pending["job"]] = dict(self._pending)
            self._pending = None
            return type("R", (), {"data": []})()
        data = [project(r, self._cols) for r in self.rows.values()
                if all(r.get(k) == v for k, v in self._f.items())]
        return type("R", (), {"data": data})()


class FakeSB:
    def __init__(self):
        self.rows = {}

    def table(self, name):
        assert name == "deal_sync_checkpoints", name
        return FakeTable(self.rows)


def test_checkpoint_store_round_trip_and_rejects_bad_values():
    sb = FakeSB()
    store = deal_sync.CheckpointStore(sb)
    assert store.get("deals") is None
    store.advance("deals", 1_789_581_853_150, run_id="r1", fetched=12, upserted=12)
    assert store.get("deals") == 1_789_581_853_150
    row = sb.rows["deals"]
    assert (row["run_id"], row["fetched"], row["upserted"]) == ("r1", 12, 12)
    for bad in ("2026-09-16T18:04:13", None, 1.5e12, -1, 10**10, True):
        try:
            store.advance("deals", bad, run_id="r2", fetched=0, upserted=0)
            raise AssertionError(f"accepted bad watermark {bad!r}")
        except ValueError:
            pass
    assert store.get("deals") == 1_789_581_853_150, "a refused advance must not change the checkpoint"
    print("✓ checkpoint: missing -> None; advance round-trips; ISO/None/float/negative/seconds/bool refused")


if __name__ == "__main__":
    test_keyset_fetch_returns_every_deal_despite_mid_fetch_edits()
    test_offset_lastmodified_fetch_skips_under_the_same_edit()
    test_keyset_and_full_fetch_share_one_property_list()
    test_keyset_fetch_combines_window_filter_with_id_cursor()
    test_checkpoint_store_round_trip_and_rejects_bad_values()
    print("\n✅ All tests passed")
