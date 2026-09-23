"""
Incremental deal sync, part 4: company changes reach their deals.

Why: segment, company_employee_count, company_domain and company_id come
from the associated company record. A company edit (e.g. a new employee count
that moves a deal from Mid-Market to Enterprise) never touches the deal's
hs_lastmodifieddate (confirmed in the 2026-09-23 audit), so a deals-only
window can't see it. The incremental run also searches companies modified in
the same window (keyset-paged), maps them to their deals, and re-reads any not
already fetched through the normal transform.

Pins, with a planted control:
  1. A company modified in the window re-syncs its (unmodified) deal with the
     new company data. Control: without the pass, the deal keeps the stale
     segment.
  2. A company modified before the window pulls nothing.
  3. A deal both modified and linked to a changed company is fetched once.
  4. A company-association failure is a run failure: exit 1, checkpoint
     unchanged.
  5. More changed companies than MAX_COMPANY_PASS: the pass is skipped
     visibly in the RUN SUMMARY (the full sync covers company fields), and
     the deal window is still synced.
"""
import sys
from pathlib import Path

REPO = Path(__file__).parent.parent
sys.path.insert(0, str(REPO / "tests"))
sys.path.insert(0, str(REPO / "scripts"))

import test_deal_sync_incremental as base  # noqa: E402
import deal_sync  # noqa: E402

MIN, NOW = base.MIN, base.NOW


class Hub(base.Hub):
    def __init__(self):
        super().__init__()
        self.companies = {}      # id -> {lm, employees}
        self.deal_company = {}   # deal id -> company id
        self.deal_reads = []

    def company(self, cid, lm, employees):
        self.companies[str(cid)] = {"lm": lm, "employees": employees}

    def request(self, method, url, timeout=None, params=None, json=None):
        path = url[len(base.BASE):]
        q = self.fail.get(path)
        if q:
            return base._resp(q.pop(0), {"message": "planted"})
        if path == "/crm/v3/objects/companies/search":
            filters = [f for g in json.get("filterGroups", []) for f in g["filters"]]

            def ok(cid, c):
                for f in filters:
                    v = c["lm"] if f["propertyName"] == "hs_lastmodifieddate" else int(cid)
                    x = int(f["value"])
                    if not {"GT": v > x, "GTE": v >= x}[f["operator"]]:
                        return False
                return True
            rows = sorted((int(i), i) for i, c in self.companies.items() if ok(i, c))
            limit = json.get("limit", 100)
            return base._resp(200, {"total": len(rows), "results": [
                {"id": i, "properties": {"hs_object_id": i}} for _, i in rows[:limit]]})
        if path == "/crm/v4/associations/companies/deals/batch/read":
            return base._resp(200, {"results": [
                {"from": {"id": x["id"]},
                 "to": [{"toObjectId": int(d)} for d, c in self.deal_company.items() if c == x["id"]]}
                for x in json["inputs"]]})
        if path == "/crm/v3/objects/deals/batch/read":
            ids = [x["id"] for x in json["inputs"]]
            self.deal_reads.append(ids)
            return base._resp(200, {"results": [
                {"id": i, "properties": self._props(i, self.deals[i])} for i in ids if i in self.deals]})
        if path == "/crm/v4/associations/deals/companies/batch/read":
            return base._resp(200, {"results": [
                {"from": {"id": x["id"]}, "to": ([{"toObjectId": int(self.deal_company[x["id"]])}]
                                                 if x["id"] in self.deal_company else [])}
                for x in json["inputs"]]})
        if path == "/crm/v3/objects/companies/batch/read":
            return base._resp(200, {"results": [
                {"id": x["id"], "properties": {"name": f"Co {x['id']}", "domain": f"c{x['id']}.com",
                                               "numberofemployees": str(self.companies[x["id"]]["employees"])}}
                for x in json["inputs"] if x["id"] in self.companies]})
        return super().request(method, url, timeout, params, json)


def _setup(hub, db, company_lm, employees):
    base.seed(db, NOW - 60 * MIN)
    hub.put(500, NOW - 400 * MIN)              # deal NOT modified in the window
    hub.deal_company["500"] = "77"
    hub.company("77", company_lm, employees)
    db.tables["deals"]["500"] = {"deal_id": "500", "segment": "SMB", "company_employee_count": 40}


def test_company_change_resyncs_its_unmodified_deal():
    hub, db = Hub(), base.DB()
    _setup(hub, db, company_lm=NOW - 5 * MIN, employees=20000)
    code, out = base.run(hub, db)
    assert code == 0, out[-800:]
    row = db.tables["deals"]["500"]
    assert row["company_employee_count"] == 20000 and row["segment"] != "SMB", row
    assert hub.deal_reads == [["500"]]
    assert "Company pass:" in out and "1 companies" in out
    print(f"✓ company 77 changed (40 → 20000 employees): its unmodified deal 500 was re-read "
          f"and now shows segment={row['segment']!r}")


def test_without_company_pass_the_segment_stays_stale():
    """Planted bug: deals-only incremental window (no company pass)."""
    hub, db = Hub(), base.DB()
    _setup(hub, db, company_lm=NOW - 5 * MIN, employees=20000)
    saved = deal_sync.company_pass
    deal_sync.company_pass = lambda hubspot, filters, already: ([], "disabled")
    try:
        base.run(hub, db)
    finally:
        deal_sync.company_pass = saved
    assert db.tables["deals"]["500"]["segment"] == "SMB"
    print("✓ control: without the company pass, deal 500 keeps the stale SMB segment")


def test_company_changed_before_window_pulls_nothing():
    hub, db = Hub(), base.DB()
    _setup(hub, db, company_lm=NOW - 200 * MIN, employees=20000)
    code, out = base.run(hub, db)
    assert code == 0 and hub.deal_reads == [] and db.tables["deals"]["500"]["segment"] == "SMB"
    print("✓ company modified before the window: no deal re-read")


def test_deal_modified_and_company_changed_is_fetched_once():
    hub, db = Hub(), base.DB()
    base.seed(db, NOW - 60 * MIN)
    hub.put(501, NOW - 3 * MIN)
    hub.deal_company["501"] = "78"
    hub.company("78", NOW - 4 * MIN, 300)
    code, out = base.run(hub, db)
    assert code == 0 and hub.deal_reads == [], "already in the deal window: no second read"
    assert "Deals fetched from HubSpot:        1" in out
    print("✓ deal in both the deal window and a changed company: fetched once")


def test_company_association_failure_exits_one_keeps_checkpoint():
    hub, db = Hub(), base.DB()
    _setup(hub, db, company_lm=NOW - 5 * MIN, employees=20000)
    c = base.cp(db)
    hub.fail["/crm/v4/associations/companies/deals/batch/read"] = [500] * 5
    code, out = base.run(hub, db)
    assert code == 1 and base.cp(db) == c, (code, out[-500:])
    print("✓ company→deal association read fails after retries: exit 1, checkpoint unchanged")


def test_company_pass_over_limit_is_skipped_visibly():
    hub, db = Hub(), base.DB()
    _setup(hub, db, company_lm=NOW - 5 * MIN, employees=20000)
    hub.put(502, NOW - 2 * MIN)
    for i in range(4):
        hub.company(str(90 + i), NOW - 5 * MIN, 10)
    saved = deal_sync.MAX_COMPANY_PASS
    deal_sync.MAX_COMPANY_PASS = 3
    try:
        code, out = base.run(hub, db)
    finally:
        deal_sync.MAX_COMPANY_PASS = saved
    assert code == 0 and "502" in db.tables["deals"], out[-600:]
    assert db.tables["deals"]["500"]["segment"] == "SMB"
    assert "Company pass:" in out and "skipped" in out
    print("✓ company pass over the limit: skipped and reported in RUN SUMMARY; deal window still synced")


if __name__ == "__main__":
    test_company_change_resyncs_its_unmodified_deal()
    test_without_company_pass_the_segment_stays_stale()
    test_company_changed_before_window_pulls_nothing()
    test_deal_modified_and_company_changed_is_fetched_once()
    test_company_association_failure_exits_one_keeps_checkpoint()
    test_company_pass_over_limit_is_skipped_visibly()
    print("\n✅ All tests passed")
