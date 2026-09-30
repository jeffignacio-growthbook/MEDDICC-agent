"""Tests for the filter-drop guard in the agent loop.

After free schema retries exhaust on a fetch_data call with filters,
the model must not be allowed to "solve" the error by silently dropping
the filter. The guard tracks filter columns used during schema-error
retries and blocks subsequent fetch_data calls to the same table that
omit previously-attempted filter columns.

Planted-bug controls: tests include cases where the guard should and
should not fire, and verify the exact error message structure.
"""
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "api"))
sys.path.insert(0, str(ROOT / "scripts"))

from api.agent_loop import _check_filter_drop, _normalize_filters


# ── Core guard logic ──────────────────────────────────────────────────────

def test_no_history_no_block():
    """No prior schema retries → no block."""
    result = _check_filter_drop("deals", [], {})
    assert result is None


def test_different_table_no_block():
    """Schema retries on table A don't block unfiltered queries on table B."""
    history = {"deals": {"deal_status"}}
    result = _check_filter_drop("analyses", [], history)
    assert result is None


def test_same_filters_no_block():
    """Retry with the same filter columns → allowed (model fixed format, not dropped)."""
    history = {"deals": {"deal_status"}}
    filters = _normalize_filters([{"column": "deal_status", "op": "eq", "value": "active"}])
    result = _check_filter_drop("deals", filters, history)
    assert result is None


def test_superset_filters_no_block():
    """More filters than before → allowed (model added precision)."""
    history = {"deals": {"deal_status"}}
    filters = _normalize_filters([
        {"column": "deal_status", "op": "eq", "value": "active"},
        {"column": "owner_id", "op": "eq", "value": "123"},
    ])
    result = _check_filter_drop("deals", filters, history)
    assert result is None


def test_empty_filters_blocked():
    """Dropping ALL filters after retries with filters → blocked."""
    history = {"deals": {"deal_status"}}
    result = _check_filter_drop("deals", [], history)
    assert result is not None
    assert "error" in result
    assert "filter_dropped" in result
    assert "deal_status" in result["error"]


def test_partial_filter_drop_blocked():
    """Dropping some but not all previously-attempted filter columns → blocked."""
    history = {"deals": {"deal_status", "pipeline_id"}}
    filters = _normalize_filters([{"column": "deal_status", "op": "eq", "value": "active"}])
    result = _check_filter_drop("deals", filters, history)
    assert result is not None
    assert "pipeline_id" in result["error"]


def test_filter_drop_error_structure():
    """Error dict has the right keys for the schema-retry system to recognize."""
    history = {"deals": {"deal_status"}}
    result = _check_filter_drop("deals", [], history)
    assert isinstance(result, dict)
    assert "error" in result
    assert "filter_dropped" in result
    assert result["filter_dropped"] is True


# ── Planted-bug controls ──────────────────────────────────────────────────

def test_planted_bug_guard_not_bypassed_by_column_in_select():
    """Moving a filter column to SELECT (what the trace showed) must still block."""
    history = {"deals": {"deal_status"}}
    result = _check_filter_drop("deals", [], history)
    assert result is not None, "Guard bypassed: filter column in SELECT but not in filters"


def test_planted_bug_empty_history_set_no_block():
    """Table in history but with empty column set → should not block."""
    history = {"deals": set()}
    result = _check_filter_drop("deals", [], history)
    assert result is None, "Guard fired with empty filter history"
