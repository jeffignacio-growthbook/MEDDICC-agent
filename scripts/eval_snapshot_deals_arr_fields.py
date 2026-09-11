#!/usr/bin/env python3
"""
Regression coverage for snapshot_deals.py's new_arr/expansion_arr write
path (migration 064 / PENDING_WORK.md Low Priority #11).

Confirms:
1. new_arr and expansion_arr are read from `deals` and written into every
   new deals_snapshot row going forward.
2. renewal_revenue is untouched — not read, not written, not referenced
   anywhere in this file. Per migration 045's own documented rationale
   (deal_value already includes renewal ARR for renewal-pipeline deals via
   compute_deal_value(); this column is deliberately left NULL by design,
   confirmed correct by a prior investigation, not an oversight), and per
   explicit instruction not to touch it while fixing the genuinely-missing
   new_arr/expansion_arr columns.

Offline: stubs supabase and dotenv (this sandbox's ambient environment
lacks python-dotenv, a pre-existing unrelated gap — see PENDING_WORK.md),
patches the two data-access seams, and captures the batch upserted to
deals_snapshot instead of hitting a real DB.
"""
import sys
import types
from pathlib import Path
from datetime import date, timedelta
from unittest.mock import patch, MagicMock

REPO = Path(__file__).resolve().parent.parent
for p in ("scripts", "scripts/analytics", "."):
    sys.path.insert(0, str(REPO / p))

if "supabase" not in sys.modules:
    _fake = types.ModuleType("supabase")
    _fake.create_client = lambda *a, **k: None
    _fake.Client = type("Client", (), {})
    sys.modules["supabase"] = _fake

if "dotenv" not in sys.modules:
    _fake_dotenv = types.ModuleType("dotenv")
    _fake_dotenv.load_dotenv = lambda *a, **k: None
    sys.modules["dotenv"] = _fake_dotenv

import snapshot_deals  # noqa: E402

FAILS = []


def check(name, cond):
    print(f"  {'✓' if cond else '✗'} {name}")
    if not cond:
        FAILS.append(name)


class _FakeUpsertQuery:
    def __init__(self, sink, table_name):
        self.sink = sink
        self.table_name = table_name
        self._rows = None

    def upsert(self, rows, on_conflict=None):
        self._rows = rows
        return self

    def execute(self):
        # snapshot_deals.py upserts in batches (a list of row dicts).
        self.sink.setdefault(self.table_name, []).extend(self._rows)
        return MagicMock()


class _FakeSB:
    def __init__(self):
        self.written = {}

    def table(self, name):
        return _FakeUpsertQuery(self.written, name)


def _run_main(deals_rows):
    sb = _FakeSB()

    def fake_select_all(_sb, table, columns=None, filters=None, page_size=1000):
        if table == "deals":
            return list(deals_rows)
        return []

    with patch.object(sys.modules["supabase"], "create_client", return_value=sb), \
         patch("supabase_client.select_all", side_effect=fake_select_all), \
         patch.dict("os.environ", {"SUPABASE_URL": "https://x.test",
                                    "SUPABASE_SERVICE_KEY": "fake-key"}):
        snapshot_deals.main()

    return sb.written.get("deals_snapshot", [])


def test_new_arr_and_expansion_arr_flow_into_the_snapshot():
    long_ago = (date.today() - timedelta(days=400)).isoformat()
    deals = [{
        "deal_id": "d1", "pipeline_id": "default", "stage": "appointmentscheduled",
        "deal_value": 500.0, "close_date": "2099-01-01", "owner_email": "a@x.com",
        "deal_status": "active", "create_date": long_ago,
        "highest_stage_order_reached": 1, "forecast_category": None,
        "region": "NAM", "segment": "Enterprise",
        "new_arr": 300.0, "expansion_arr": 200.0,
    }]
    rows = _run_main(deals)
    check("exactly one snapshot row written", len(rows) == 1)
    row = rows[0]
    check("new_arr captured on the snapshot row", row.get("new_arr") == 300.0)
    check("expansion_arr captured on the snapshot row", row.get("expansion_arr") == 200.0)
    check("renewal_revenue is not present in the row at all (untouched)",
          "renewal_revenue" not in row)


def test_null_components_pass_through_as_null_not_zero():
    """A deal with genuinely blank new_arr/expansion_arr must snapshot as
    NULL, not silently coalesced to 0 — the write path shouldn't invent a
    fabrication that didn't exist in the read path."""
    long_ago = (date.today() - timedelta(days=400)).isoformat()
    deals = [{
        "deal_id": "d2", "pipeline_id": "default", "stage": "appointmentscheduled",
        "deal_value": None, "close_date": "2099-01-01", "owner_email": "a@x.com",
        "deal_status": "active", "create_date": long_ago,
        "highest_stage_order_reached": 1, "forecast_category": None,
        "region": None, "segment": None,
        "new_arr": None, "expansion_arr": None,
    }]
    rows = _run_main(deals)
    row = rows[0]
    check("new_arr is None, not 0", row.get("new_arr") is None)
    check("expansion_arr is None, not 0", row.get("expansion_arr") is None)


def test_renewal_revenue_never_referenced_in_source():
    """Static guard: renewal_revenue must not appear anywhere in
    snapshot_deals.py — not in the deals SELECT, not in the row dict. This
    fails loudly if a future edit accidentally starts touching it, which
    migration 045's own investigation concluded should not happen."""
    source = (REPO / "scripts" / "analytics" / "snapshot_deals.py").read_text()
    check("renewal_revenue does not appear anywhere in snapshot_deals.py",
          "renewal_revenue" not in source)


def run():
    print("=" * 72)
    print("SNAPSHOT_DEALS — new_arr/expansion_arr write path (migration 064)")
    print("=" * 72)
    for title, fn in (
        ("new_arr/expansion_arr flow into the snapshot; renewal_revenue untouched",
         test_new_arr_and_expansion_arr_flow_into_the_snapshot),
        ("null components pass through as null, not zero",
         test_null_components_pass_through_as_null_not_zero),
        ("renewal_revenue never referenced in source (static guard)",
         test_renewal_revenue_never_referenced_in_source),
    ):
        print(f"\n[{title}]")
        fn()

    print("\n" + "=" * 72)
    if FAILS:
        print(f"FAIL — {len(FAILS)}: {', '.join(FAILS)}")
        return 1
    print("PASS — new_arr/expansion_arr populate going forward; renewal_revenue untouched.")
    return 0


if __name__ == "__main__":
    sys.exit(run())
