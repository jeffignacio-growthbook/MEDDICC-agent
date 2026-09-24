#!/usr/bin/env python3
"""
tests/strict_supabase.StrictSupabase answers like PostgREST, driven through
the REAL supabase_client.select_all: only selected columns come back, every
filter applies with SQL NULL semantics, unknown tables and columns are
refused, and query shapes it doesn't model raise instead of guessing.
"""
import sys
from pathlib import Path

REPO = Path(__file__).parent.parent
sys.path.insert(0, str(REPO / "tests"))
sys.path.insert(0, str(REPO / "scripts"))
sys.path.insert(0, str(REPO))

from strict_supabase import StrictSupabase, StrictSupabaseError  # noqa: E402
from supabase_client import select_all  # noqa: E402

ROWS = [
    {"deal_id": "1", "company_name": "Acme", "deal_status": "active", "deal_value": 100, "close_date": "2026-09-30", "owner_email": "A@x.com"},
    {"deal_id": "2", "company_name": "Beta", "deal_status": "won", "deal_value": 50, "close_date": None, "owner_email": "b@x.com"},
    {"deal_id": "3", "company_name": "Gamma", "deal_status": "active", "deal_value": None, "close_date": "2026-11-01", "owner_email": None},
]


def _raises(fn, text):
    try:
        fn()
    except StrictSupabaseError as e:
        assert text in str(e), (text, str(e))
        return
    raise AssertionError(f"expected StrictSupabaseError containing {text!r}")


def test_projection_and_filters_through_real_select_all():
    sb = StrictSupabase({"deals": ROWS})
    got = select_all(sb, "deals", columns="deal_id,deal_value", filters=[("eq", "deal_status", "active")])
    assert got == [{"deal_id": "1", "deal_value": 100}, {"deal_id": "3", "deal_value": None}], got
    assert select_all(sb, "deals", "deal_id", [("gte", "deal_value", 60)]) == [{"deal_id": "1"}]
    assert select_all(sb, "deals", "deal_id", [("__not_null__", "close_date")]) == [{"deal_id": "1"}, {"deal_id": "3"}]
    assert select_all(sb, "deals", "deal_id", [("is_", "owner_email", "null")]) == [{"deal_id": "3"}]
    assert select_all(sb, "deals", "deal_id", [("ilike", "owner_email", "a@X.COM")]) == [{"deal_id": "1"}]
    assert select_all(sb, "deals", "deal_id", [("in_", "deal_id", ["2", "3"])]) == [{"deal_id": "2"}, {"deal_id": "3"}]
    assert select_all(sb, "deals", "deal_id", [("neq", "deal_status", "won")]) == [{"deal_id": "1"}, {"deal_id": "3"}]
    assert select_all(sb, "deals", "deal_id", [("lte", "close_date", "2026-10-31")]) == [{"deal_id": "1"}]
    assert select_all(sb, "deals", "deal_id", [("eq", "deal_id", 2)]) == [{"deal_id": "2"}], "numbers cast like Postgres"
    assert sb.selected("deals")[0] == ["deal_id", "deal_value"]
    print("✓ via the real select_all: projection, eq/neq/gte/lte/ilike/in_/is_/not-null, NULL never "
          "matches a comparison, numeric literals cast")


def test_null_semantics_under_not():
    sb = StrictSupabase({"deals": ROWS})
    q = lambda: sb.table("deals").select("deal_id")
    assert q().not_.eq("deal_status", "won").execute().data == [{"deal_id": "1"}, {"deal_id": "3"}]
    assert q().not_.gt("deal_value", 60).execute().data == [{"deal_id": "2"}], "NOT (NULL > 60) is not true"
    assert q().not_.in_("deal_id", ["1"]).execute().data == [{"deal_id": "2"}, {"deal_id": "3"}]
    print("✓ not_: a NULL never passes a negated comparison; NOT IS NULL is plain")


def test_order_limit_range_single():
    sb = StrictSupabase({"deals": ROWS})
    q = lambda: sb.table("deals").select("deal_id")
    assert [r["deal_id"] for r in q().order("deal_value").execute().data] == ["2", "1", "3"], "NULLS LAST asc"
    assert [r["deal_id"] for r in q().order("deal_value", desc=True).execute().data] == ["3", "1", "2"], "NULLS FIRST desc"
    assert q().order("deal_id").limit(1).execute().data == [{"deal_id": "1"}]
    assert q().order("deal_id").range(1, 2).execute().data == [{"deal_id": "2"}, {"deal_id": "3"}]
    assert q().eq("deal_id", "2").single().execute().data == {"deal_id": "2"}
    assert q().eq("deal_id", "9").maybe_single().execute().data is None
    _raises(lambda: q().single().execute(), "single()")
    rows = [{"deal_id": str(i)} for i in range(2500)]
    assert len(select_all(StrictSupabase({"deals": rows}), "deals", "deal_id")) == 2500, "real pagination"
    print("✓ order (NULLS LAST/FIRST), limit, range, single/maybe_single; select_all pages past 1,000")


def test_refuses_what_postgres_would():
    sb = StrictSupabase({"deals": ROWS})
    _raises(lambda: sb.table("deals").select("deal_id,amount").execute(), "deals.amount does not exist")
    _raises(lambda: sb.table("deelz"), "table 'deelz' does not exist")
    _raises(lambda: StrictSupabase({"deelz": []}), "table 'deelz' does not exist")
    _raises(lambda: sb.table("deals").select("deal_id").eq("bogus", 1), "deals.bogus does not exist")
    _raises(lambda: sb.table("deals").select("x:deal_id"), "does not model")
    _raises(lambda: sb.table("deals").select("deal_id").in_("deal_id", "12"), "bare string")
    _raises(lambda: sb.table("deals").select("deal_id").textSearch("x", "y"), "does not model .textSearch()")
    print("✓ refuses unknown tables/columns (select and filter), aliases, bare-string in_, and "
          "unmodelled methods")


def test_writes_are_recorded_not_applied():
    sb = StrictSupabase({"deals": ROWS})
    sb.table("deals").update({"deal_status": "lost"}).eq("deal_id", "1").execute()
    assert sb.writes == [{"table": "deals", "kind": "update", "payload": {"deal_status": "lost"},
                          "filters": [("eq", "deal_id", "1")]}], sb.writes
    assert sb.table("deals").select("deal_status").eq("deal_id", "1").execute().data == [{"deal_status": "active"}]
    _raises(lambda: sb.table("deals").upsert({"deal_id": "1", "amount": 5}), "deals.amount does not exist")
    _raises(lambda: sb.table("deals").insert([{"deal_id": "1"}, {"bogus": 1}]), "deals.bogus does not exist")
    print("✓ writes are recorded with their filters and not applied; a write naming an unknown "
          "column raises (PGRST204)")


if __name__ == "__main__":
    test_projection_and_filters_through_real_select_all()
    test_null_semantics_under_not()
    test_order_limit_range_single()
    test_refuses_what_postgres_would()
    test_writes_are_recorded_not_applied()
    print("\n✅ All tests passed")
