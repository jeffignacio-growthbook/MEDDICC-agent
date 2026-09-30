"""
Tests for pre-dispatch filter format normalization.

The model's tool description tells it to pass filters as dicts:
  {"column": "deal_status", "op": "eq", "value": "active"}

But filter_table expects tuples: ("eq", "deal_status", "active").

The normalization in _execute_fetch_data must convert dict-format filters
to tuple-format before dispatching, so no retry is wasted.

Fixtures are taken from the real Railway logs (2026-09-30 01:22-01:25 UTC).
"""

import asyncio
import sys
from pathlib import Path
from unittest.mock import AsyncMock, patch, MagicMock
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))


# ── Fixture: the 4 real queries from Railway logs ─────────────────────────

REAL_QUERY_RETRY_3 = {
    "query": "active deals in default pipeline",
    "table": "deals",
    "columns": ["deal_id", "company_name", "deal_value", "stage",
                 "close_date", "segment"],
    "filters": [
        {"column": "deal_status", "op": "eq", "value": "active"},
        {"column": "pipeline_id", "op": "eq", "value": "default"},
    ],
}

REAL_QUERY_RETRY_0 = {
    "query": "active deals in default pipeline",
    "table": "deals",
    "columns": ["deal_id", "company_name", "deal_value", "stage",
                 "close_date", "segment"],
    "filters": [
        {"column": "deal_status", "value": "active"},
        {"column": "pipeline_id", "value": "default"},
    ],
}


def _normalize_filters(filters):
    """Import the normalization function from agent_loop."""
    from api.agent_loop import _normalize_filters as nf
    return nf(filters)


# ── Test 1: dict with column/op/value normalizes to (op, column, value) ──

def test_dict_with_op_normalizes():
    filters = [
        {"column": "deal_status", "op": "eq", "value": "active"},
        {"column": "pipeline_id", "op": "eq", "value": "default"},
    ]
    result = _normalize_filters(filters)
    assert result == [
        ("eq", "deal_status", "active"),
        ("eq", "pipeline_id", "default"),
    ]


# ── Test 2: dict without op defaults to "eq" ─────────────────────────────

def test_dict_without_op_defaults_eq():
    filters = [
        {"column": "deal_status", "value": "active"},
        {"column": "pipeline_id", "value": "default"},
    ]
    result = _normalize_filters(filters)
    assert result == [
        ("eq", "deal_status", "active"),
        ("eq", "pipeline_id", "default"),
    ]


# ── Test 3: tuple-format filters pass through unchanged ──────────────────

def test_tuple_passthrough():
    filters = [
        ("eq", "deal_status", "active"),
        ("gte", "close_date", "2026-01-01"),
    ]
    result = _normalize_filters(filters)
    assert result == [
        ("eq", "deal_status", "active"),
        ("gte", "close_date", "2026-01-01"),
    ]


# ── Test 4: list-format filters (3-element lists) pass through ───────────

def test_list_passthrough():
    filters = [
        ["eq", "deal_status", "active"],
        ["gte", "close_date", "2026-01-01"],
    ]
    result = _normalize_filters(filters)
    assert result == [
        ("eq", "deal_status", "active"),
        ("gte", "close_date", "2026-01-01"),
    ]


# ── Test 5: 2-element tuple gets None value ──────────────────────────────

def test_two_element_tuple():
    filters = [("is_", "lost_reason")]
    result = _normalize_filters(filters)
    assert result == [("is_", "lost_reason", None)]


# ── Test 6: empty / None filters ─────────────────────────────────────────

def test_empty_filters():
    assert _normalize_filters([]) == []
    assert _normalize_filters(None) == []


# ── Test 7: mixed formats ────────────────────────────────────────────────

def test_mixed_formats():
    filters = [
        {"column": "deal_status", "op": "eq", "value": "active"},
        ("gte", "close_date", "2026-01-01"),
        ["lt", "arr_usd", 50000],
    ]
    result = _normalize_filters(filters)
    assert result == [
        ("eq", "deal_status", "active"),
        ("gte", "close_date", "2026-01-01"),
        ("lt", "arr_usd", 50000),
    ]


# ── Test 8: real Railway query (retry 3) dispatches without schema error ─

def test_real_query_retry3_no_schema_error():
    """The exact query from retry 3 (3 remaining) should normalize and
    dispatch without triggering a schema error in filter_table."""
    from api.agent_loop import _normalize_filters as nf

    filters = REAL_QUERY_RETRY_3["filters"]
    normalized = nf(filters)

    # Every filter should be a 3-tuple with valid operator
    for f in normalized:
        assert isinstance(f, tuple), f"Expected tuple, got {type(f)}: {f}"
        assert len(f) == 3, f"Expected 3-tuple, got {len(f)}-tuple: {f}"
        assert f[0] in {"eq", "neq", "gt", "gte", "lt", "lte",
                         "like", "ilike", "is_", "in_"}, f"Bad op: {f[0]}"
        assert isinstance(f[1], str), f"Column should be str: {f[1]}"


# ── Test 9: real Railway query (retry 0) dispatches without schema error ─

def test_real_query_retry0_no_schema_error():
    """The exact query from retry 0 (0 remaining, no 'op' key) should
    normalize with default 'eq' operator."""
    from api.agent_loop import _normalize_filters as nf

    filters = REAL_QUERY_RETRY_0["filters"]
    normalized = nf(filters)

    for f in normalized:
        assert isinstance(f, tuple)
        assert len(f) == 3
        assert f[0] == "eq"


# ── Test 10: _execute_fetch_data normalizes before calling filter_table ──

def test_execute_fetch_data_normalizes_filters():
    """End-to-end: _execute_fetch_data should normalize dict filters
    before passing them to filter_table, so filter_table never sees dicts."""
    from api.agent_loop import _execute_fetch_data

    captured_filters = {}

    async def mock_filter_table(sb, table, columns=None, filters=None,
                                limit=200, order_by=None):
        captured_filters["filters"] = filters
        return [{"deal_id": "d1", "deal_status": "active"}]

    with patch("api.tools.filter_table", mock_filter_table), \
         patch("api.tools._init_valid_columns", lambda sb: None), \
         patch("api.tools._VALID_COLUMNS", {"deals": {"deal_id", "deal_status", "pipeline_id",
                "company_name", "deal_value", "stage", "close_date", "segment"}}):
        result = asyncio.get_event_loop().run_until_complete(
            _execute_fetch_data(
                "active deals",
                REAL_QUERY_RETRY_3,
                MagicMock(),
            )
        )

    assert "error" not in result
    # The filters that reached filter_table must be tuples, not dicts
    for f in captured_filters["filters"]:
        assert isinstance(f, (tuple, list)), f"Dict leaked through: {f}"


# ── Test 11: grounding check catches non-existent table ──────────────────

def test_grounding_catches_bad_table():
    """Pre-dispatch grounding should reject a table not in data_dictionary
    with a helpful message, without consuming a retry slot."""
    from api.agent_loop import _ground_fetch_params

    dd = {
        "deals": {"deal_id", "company_name", "deal_status"},
        "deals_snapshot": {"deal_id", "snapshot_date"},
    }
    result = _ground_fetch_params("nonexistent_table", ["col1"], [], dd)
    assert result is not None
    assert "table" in result.get("error", "").lower()
    assert "deals" in str(result)  # suggests valid tables


# ── Test 12: grounding check catches bad columns ─────────────────────────

def test_grounding_catches_bad_columns():
    from api.agent_loop import _ground_fetch_params

    dd = {
        "deals": {"deal_id", "company_name", "deal_status", "arr_usd"},
    }
    result = _ground_fetch_params(
        "deals",
        ["deal_id", "fake_column", "also_fake"],
        [("eq", "deal_status", "active")],
        dd,
    )
    assert result is not None
    assert "fake_column" in str(result)
    assert "also_fake" in str(result)


# ── Test 13: grounding check catches bad filter columns ──────────────────

def test_grounding_catches_bad_filter_columns():
    from api.agent_loop import _ground_fetch_params

    dd = {
        "deals": {"deal_id", "company_name", "deal_status"},
    }
    result = _ground_fetch_params(
        "deals",
        ["deal_id"],
        [("eq", "invented_col", "x")],
        dd,
    )
    assert result is not None
    assert "invented_col" in str(result)


# ── Test 14: grounding passes valid query ────────────────────────────────

def test_grounding_passes_valid_query():
    from api.agent_loop import _ground_fetch_params

    dd = {
        "deals": {"deal_id", "company_name", "deal_status", "deal_value",
                  "stage", "close_date", "segment", "pipeline_id"},
    }
    result = _ground_fetch_params(
        "deals",
        ["deal_id", "company_name", "deal_value"],
        [("eq", "deal_status", "active")],
        dd,
    )
    assert result is None  # None means "no error, proceed"


# ── Test 15: grounding with empty data_dictionary skips check ────────────

def test_grounding_skips_when_no_dictionary():
    from api.agent_loop import _ground_fetch_params

    result = _ground_fetch_params("deals", ["col"], [], {})
    assert result is None


if __name__ == "__main__":
    import pytest
    raise SystemExit(pytest.main([__file__, "-v"]))
