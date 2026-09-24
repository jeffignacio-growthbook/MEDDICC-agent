#!/usr/bin/env python3
"""
filter_table() refuses a filter it cannot apply, instead of dropping it.

api/tools._validate_filters() used to discard any filter naming a column
that isn't registered as queryable for the table (data_dictionary). Nothing
in the result said so. The query ran without it and the unfiltered rows came
back as if the filter had applied: a question about EMEA got every region.
This is the same failure class as a test fake that ignores filters, but in
the query path the dynamic loop actually uses.

It has shipped wrong before. PENDING_WORK #14 (2026-09-12): a filter on the
fictional `pipeline` dimension was dropped, and a wrong-scoped answer went
out marked "verified". That fix removed the fictional dimension and made
dimension_verification distrust such filters. filter_table itself kept
dropping them: any column a model invents, misspells, or that is hidden
(is_queryable=false) or unregistered (today: sdr_metrics.tool_user_id,
sdr_users.tool_user_id and others).

Now filter_table returns an error naming the filters it could not apply,
the same way it already refuses an invalid operator, so the loop can
re-plan. Registered filters still apply, and a table with no
data_dictionary entries is still not validated. join_tables passes the
error through instead of joining on unfiltered rows; it also no longer
raises TypeError whenever its primary query finds rows (a second bug the
strict fake surfaced, see test_join_tables_joins_on_real_rows).

Runs the REAL filter_table against tests/strict_supabase.StrictSupabase.
"""
import asyncio
import sys
from pathlib import Path

REPO = Path(__file__).parent.parent
sys.path.insert(0, str(REPO / "tests"))
sys.path.insert(0, str(REPO))
sys.path.insert(0, str(REPO / "api"))
sys.path.insert(0, str(REPO / "scripts"))

import api.tools as tools  # noqa: E402
from strict_supabase import StrictSupabase  # noqa: E402

REGISTERED = ("deal_id", "snapshot_date", "stage_id", "deal_value", "region")
ROWS = [{"deal_id": "1", "snapshot_date": "2026-09-21", "stage_id": "s", "deal_value": 10,
         "region": "EMEA", "segment": "SMB"},
        {"deal_id": "2", "snapshot_date": "2026-09-21", "stage_id": "s", "deal_value": 20,
         "region": "NAM", "segment": "Enterprise"}]


def _sb():
    tools._VALID_COLUMNS.clear()           # module-level cache: rebuild per test
    dd = [{"supabase_table": "deals_snapshot", "supabase_column": c, "is_queryable": True}
          for c in REGISTERED]
    dd.append({"supabase_table": "deals_snapshot", "supabase_column": "segment", "is_queryable": False})
    return StrictSupabase({"data_dictionary": dd, "deals_snapshot": ROWS, "calls": []})


def _run(**kw):
    sb = _sb()
    return asyncio.run(tools.filter_table(sb, "deals_snapshot", **kw)), sb


def test_registered_filters_still_apply():
    r, _ = _run(columns=["deal_id", "deal_value"], filters=[["eq", "region", "EMEA"]])
    assert r.get("rows") == [{"deal_id": "1", "deal_value": 10}], r
    r, _ = _run(columns=["deal_id"], filters=[["eq", "region", "EMEA"]], order_by="deal_value desc")
    assert r.get("rows") == [{"deal_id": "1"}], r
    print("✓ a filter on a registered column is applied (paginated and order_by paths)")


def test_unknown_or_hidden_filter_column_is_refused_not_dropped():
    cases = {"invented": ["eq", "pipeline", "New Business"],
             "hidden (is_queryable=false)": ["eq", "segment", "SMB"],
             "misspelled": ["eq", "regoin", "EMEA"]}
    for name, f in cases.items():
        for kw in ({}, {"order_by": "deal_value desc"}):
            r, sb = _run(columns=["deal_id"], filters=[f, ["gte", "deal_value", 0]], **kw)
            assert "error" in r and "rows" not in r, (name, kw, r)
            assert f[1] in r["error"] and "not a queryable column" in r["error"], (name, r["error"])
            assert not [q for q in sb.queries if q["table"] == "deals_snapshot"], \
                f"{name}: the query ran without the filter"
    print("✓ a filter on an invented, hidden or misspelled column returns an error naming it; "
          "the query never runs without it (both paths)")


def test_error_lists_what_can_be_filtered():
    r, _ = _run(columns=["deal_id"], filters=[["eq", "regoin", "EMEA"]])
    for c in REGISTERED:
        assert c in r["error"], r["error"]
    print("✓ the error lists the table's queryable columns, so the loop can re-plan")


def test_unregistered_table_is_still_not_validated():
    tools._VALID_COLUMNS.clear()
    sb = StrictSupabase({"data_dictionary": [], "calls": [{"call_id": "c1", "deal_id": "1"}]})
    r = asyncio.run(tools.filter_table(sb, "calls", columns=["call_id"], filters=[["eq", "deal_id", "1"]]))
    assert r.get("rows") == [{"call_id": "c1"}], r
    print("✓ a table with no data_dictionary entries is not validated (unchanged)")


def test_join_tables_passes_the_error_through():
    sb = _sb()
    r = asyncio.run(tools.join_tables(sb, "deals_snapshot", "deal_id", "calls", "deal_id",
                                      primary_filters=[["eq", "pipeline", "x"]]))
    assert "error" in r and "pipeline" in r["error"], r
    print("✓ join_tables returns filter_table's error instead of joining on unfiltered rows")


def test_join_tables_joins_on_real_rows():
    """join_tables crashed whenever its primary query found rows:
    _validate_columns() returns (good, unavailable) since 2026-09-01, and
    join_tables still did ",".join() on that tuple (TypeError). It also has to
    select the foreign key itself, or (with only the selected columns coming
    back, as in Postgres) no joined row can be matched."""
    tools._VALID_COLUMNS.clear()
    sb = StrictSupabase({
        "data_dictionary": [{"supabase_table": t, "supabase_column": c, "is_queryable": True}
                            for t, cols in (("deals", ("deal_id", "company_name", "stage")),
                                            ("analyses", ("deal_id", "overall_score")))
                            for c in cols],
        "deals": [{"deal_id": "1", "company_name": "A", "stage": "s"},
                  {"deal_id": "2", "company_name": "B", "stage": "t"}],
        "analyses": [{"deal_id": "1", "overall_score": 70}, {"deal_id": "2", "overall_score": 40}]})
    r = asyncio.run(tools.join_tables(sb, "deals", "deal_id", "analyses", "deal_id",
                                      primary_filters=[["eq", "stage", "s"]],
                                      joined_columns=["overall_score"]))
    assert [(x["deal_id"], [a["overall_score"] for a in x["_analyses"]]) for x in r["rows"]] == [("1", [70])], r
    print("✓ join_tables joins: the stage filter applies, and deal 1 gets its analyses row "
          "(was TypeError on any primary row; the foreign key is selected even when not asked for)")


if __name__ == "__main__":
    test_registered_filters_still_apply()
    test_unknown_or_hidden_filter_column_is_refused_not_dropped()
    test_error_lists_what_can_be_filtered()
    test_unregistered_table_is_still_not_validated()
    test_join_tables_passes_the_error_through()
    test_join_tables_joins_on_real_rows()
    print("\n✅ All tests passed")
