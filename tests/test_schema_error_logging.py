#!/usr/bin/env python3
"""
Schema-error diagnostic logging: when a fetch_data call fails schema
validation, the agent loop now logs the actual table, columns, filters
attempted, plus the error message — not just "free retry (N remaining)".

Item 1 of the "schema injection follow-up" plan: making future schema
errors diagnosable from production logs.
"""
import json
import logging
import sys
from pathlib import Path
from unittest.mock import patch, AsyncMock, MagicMock

REPO = Path(__file__).parent.parent
sys.path.insert(0, str(REPO / "tests"))
sys.path.insert(0, str(REPO))
sys.path.insert(0, str(REPO / "scripts"))
sys.path.insert(0, str(REPO / "api"))

import pytest  # noqa: E402

from api.agent_loop import run_agent_loop, MAX_SCHEMA_RETRIES  # noqa: E402


def _make_client(steps):
    """FakeClient that returns pre-scripted tool calls in sequence."""
    client = MagicMock()
    idx = [0]
    def complete(messages, system, max_tokens=600):
        i = idx[0]
        idx[0] = i + 1
        resp = MagicMock()
        if i < len(steps):
            resp.text = json.dumps(steps[i])
        else:
            resp.text = json.dumps({"tool": "deliver", "params": {
                "answer": "Done", "sources": [], "plan_used": []}})
        return resp
    client.complete = complete
    return client


def _fetch_data(table, columns=None, filters=None):
    return {"tool": "fetch_data", "params": {
        "query": f"get {table} data",
        "table": table,
        "columns": columns or [],
        "filters": filters or [],
    }}


def _deliver(answer="Done"):
    return {"tool": "deliver", "params": {
        "answer": answer, "sources": [], "plan_used": []}}


@pytest.mark.asyncio
async def test_schema_error_logs_table_columns_filters():
    """Schema error log line includes table, columns, filters, and error text."""
    steps = [
        _fetch_data("deals", columns=["id", "name", "amount", "owner"]),
        _deliver("Pipeline total: $2.4M"),
    ]
    client = _make_client(steps)

    schema_error_result = {
        "error": "Unknown SELECT columns for table 'deals': ['id', 'name', 'amount', 'owner']. "
                 "Queryable columns: ['deal_id', 'deal_value', 'owner_email']",
        "unknown_select_columns": ["id", "name", "amount", "owner"],
    }

    with patch("api.agent_loop._get_schema_for_prompt", return_value=""), \
         patch("api.agent_loop._execute_fetch_data", new_callable=AsyncMock) as mock_fetch, \
         patch("api.agent_loop._find_matching_primitive", return_value=None):
        # First call → schema error; second → deliver (bypass)
        mock_fetch.return_value = schema_error_result

        captured = []
        original_info = logging.getLogger("api.agent_loop").info
        def capture_log(msg, *args):
            formatted = msg % args if args else msg
            captured.append(formatted)
        with patch.object(logging.getLogger("api.agent_loop"), "info", side_effect=capture_log):
            result = await run_agent_loop("What is pipeline?", client)

    schema_logs = [l for l in captured if "schema error" in l]
    assert len(schema_logs) >= 1, f"No schema error log found. Captured: {captured}"
    log_line = schema_logs[0]
    assert "table='deals'" in log_line, f"table not in log: {log_line}"
    assert "columns=" in log_line and "'amount'" in log_line, f"columns not in log: {log_line}"
    assert "Unknown SELECT columns" in log_line, f"error text not in log: {log_line}"
    print("✓ schema error log includes table, columns, and error text")


@pytest.mark.asyncio
async def test_schema_error_log_includes_filters():
    """Filters are captured in the diagnostic log line."""
    steps = [
        {"tool": "fetch_data", "params": {
            "query": "get deals data",
            "table": "deals",
            "columns": ["deal_id"],
            "filters": [{"column": "bad_col", "op": "eq", "value": "x"}],
        }},
        _deliver(),
    ]
    client = _make_client(steps)

    filter_error_result = {
        "error": "Can't filter deals on ['bad_col']: not a queryable column",
        "unknown_filter_columns": ["bad_col"],
    }

    with patch("api.agent_loop._get_schema_for_prompt", return_value=""), \
         patch("api.agent_loop._execute_fetch_data", new_callable=AsyncMock) as mock_fetch, \
         patch("api.agent_loop._find_matching_primitive", return_value=None):
        mock_fetch.return_value = filter_error_result

        captured = []
        def capture_log(msg, *args):
            captured.append(msg % args if args else msg)
        with patch.object(logging.getLogger("api.agent_loop"), "info", side_effect=capture_log):
            await run_agent_loop("Show deals", client)

    schema_logs = [l for l in captured if "schema error" in l]
    assert len(schema_logs) >= 1, f"No schema error log. Captured: {captured}"
    log_line = schema_logs[0]
    assert "filters=" in log_line, f"filters not in log: {log_line}"
    assert "bad_col" in log_line, f"filter column not in log: {log_line}"
    print("✓ schema error log includes filters")


if __name__ == "__main__":
    import asyncio
    asyncio.run(test_schema_error_logs_table_columns_filters())
    asyncio.run(test_schema_error_log_includes_filters())
    print("\n✅ All schema error logging tests passed")
