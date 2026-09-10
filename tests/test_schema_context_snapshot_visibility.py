"""
Regression test for the root cause of the 2026-09-11 budget-exhaustion
defect: deals_snapshot.region and deals_snapshot.segment exist in Postgres
(migration 060) and have been populated by scripts/analytics/
snapshot_deals.py since 2026-09-08, but were never registered in the
data_dictionary table — and api/schema_context.py's get_schema_context()
builds the dynamic query loop's ENTIRE view of "what columns exist" from
data_dictionary rows with is_queryable=true, not from the real Postgres
schema. A column missing from data_dictionary is invisible to the model
regardless of whether it's actually queryable — which is exactly why the
model stated "the snapshot data doesn't include segment or region
columns" (true of what it was shown, false of the real table) and burned
an extra iteration re-querying deals for them.

This test proves the MECHANISM: once a data_dictionary row exists for a
column (as migration 062 adds for deals_snapshot.region/segment), it
becomes visible in the schema text handed to the model — without needing
a live Supabase connection to verify migration 062 was actually applied.
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from api.schema_context import _build_schema_context


class _FakeQuery:
    """Mimics the .select().eq().range().execute() chain select_all() uses."""

    def __init__(self, rows):
        self._all_rows = rows
        self._filtered = rows

    def select(self, *_a, **_kw):
        return self

    def eq(self, column, value):
        self._filtered = [r for r in self._filtered if r.get(column) == value]
        return self

    def range(self, start, end):
        self._page = self._filtered[start:end + 1]
        return self

    def execute(self):
        class _Result:
            pass
        r = _Result()
        r.data = self._page
        return r


class _FakeSupabase:
    def __init__(self, dictionary_rows):
        self._rows = dictionary_rows

    def table(self, name):
        assert name == "data_dictionary"
        return _FakeQuery(list(self._rows))


def _dict_row(table, column, is_queryable=True, description="", data_type="text"):
    return {
        "supabase_table": table,
        "supabase_column": column,
        "data_type": data_type,
        "description": description,
        "enum_values": None,
        "hubspot_name": None,
        "source": "supabase",
        "is_queryable": is_queryable,
    }


def test_column_missing_from_data_dictionary_is_invisible_to_the_model():
    """Reproduces the actual pre-migration-062 state: deals_snapshot exists
    with a few core columns registered, but region/segment are not — the
    exact gap that caused the model's wrong belief."""
    sb = _FakeSupabase([
        _dict_row("deals_snapshot", "deal_id"),
        _dict_row("deals_snapshot", "stage_id"),
        _dict_row("deals_snapshot", "owner_email"),
        # no region/segment rows — matches the pre-fix database state
    ])

    schema = _build_schema_context(sb, tables_with_descriptions=["deals_snapshot"],
                                    lightweight=True)

    assert "TABLE: deals_snapshot" in schema
    # The table's Purpose line deliberately mentions region/segment by name
    # (reinforcing to the model that they exist on THIS table once
    # registered) — so check for the actual column listing, not a bare
    # substring, to prove the column itself isn't enumerated.
    assert "  region (" not in schema, (
        "This reproduces the bug: region isn't in data_dictionary, so it "
        "must not be listed as a column of deals_snapshot"
    )
    assert "  segment (" not in schema
    print("✓ reproduces the defect: an unregistered column is invisible even though it exists in Postgres")


def test_column_registered_in_data_dictionary_becomes_visible():
    """After migration 062 (or equivalent) registers the two columns, the
    exact same schema-building code must list them for deals_snapshot —
    proving the fix mechanism works, independent of whether the live
    database has actually been migrated yet."""
    sb = _FakeSupabase([
        _dict_row("deals_snapshot", "deal_id"),
        _dict_row("deals_snapshot", "stage_id"),
        _dict_row("deals_snapshot", "owner_email"),
        _dict_row("deals_snapshot", "region",
                  description="Sales region AS OF this snapshot date"),
        _dict_row("deals_snapshot", "segment",
                  description="Company size segment AS OF this snapshot date"),
    ])

    schema = _build_schema_context(sb, tables_with_descriptions=["deals_snapshot"],
                                    lightweight=True)

    assert "TABLE: deals_snapshot" in schema
    assert "region (text)" in schema, schema
    assert "segment (text)" in schema, schema
    assert "Purpose:" in schema and "region" in schema.split("Purpose:")[1][:600], (
        "The deals_snapshot table description should mention region/segment "
        "are already point-in-time columns on this table"
    )
    print("✓ once registered, region/segment become visible to the model for deals_snapshot")


def test_non_queryable_column_stays_hidden():
    """is_queryable=false must still hide a column — the fix shouldn't
    accidentally make everything visible regardless of that flag."""
    sb = _FakeSupabase([
        _dict_row("deals_snapshot", "deal_id"),
        _dict_row("deals_snapshot", "region", is_queryable=False),
    ])
    schema = _build_schema_context(sb, tables_with_descriptions=["deals_snapshot"],
                                    lightweight=True)
    assert "  region (" not in schema
    print("✓ is_queryable=false still hides a column, as intended")


if __name__ == "__main__":
    test_column_missing_from_data_dictionary_is_invisible_to_the_model()
    test_column_registered_in_data_dictionary_becomes_visible()
    test_non_queryable_column_stays_hidden()
    print("\n✅ All tests passed")
