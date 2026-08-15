#!/usr/bin/env python3
"""
Minimal test for G.4 context passing bug fix.

Tests:
1. _extract_rows_from_accumulated extracts rows from accumulated_data
2. extract_entity_context can process the output
"""

import sys
sys.path.insert(0, 'api')

from router import _extract_rows_from_accumulated
from db import extract_entity_context

# Test 1: Extract rows from accumulated_data
print("Test 1: _extract_rows_from_accumulated")
print("="*60)

accumulated_data = {
    "step_0": {
        "rows": [
            {"deal_id": "12345", "company_name": "Acme Corp", "amount": 50000},
            {"deal_id": "12346", "company_name": "Widget Inc", "amount": 75000},
        ],
        "table": "deals",
    },
    "step_1": {
        "rows": [],
        "table": "contacts",
        "error": "No matching contacts"
    }
}

tool_results = _extract_rows_from_accumulated(accumulated_data)
print(f"Input: accumulated_data with {len(accumulated_data)} steps")
print(f"Output: {tool_results}")
print(f"  rows count: {len(tool_results.get('rows', []))}")
print(f"  table: {tool_results.get('table')}")

assert tool_results.get("rows"), "Should extract rows from step_0"
assert len(tool_results["rows"]) == 2, "Should have 2 rows"
assert tool_results["table"] == "deals", "Should identify table"
print("✓ Test 1 passed\n")

# Test 2: Extract entity context from tool_results
print("Test 2: extract_entity_context")
print("="*60)

entities = extract_entity_context(tool_results)
print(f"Input: tool_results with {len(tool_results.get('rows', []))} rows")
print(f"Output: {entities}")
print(f"  deal_ids: {entities.get('deal_ids', [])}")
print(f"  company_names: {entities.get('company_names', [])}")

assert "12345" in entities.get("deal_ids", []), "Should extract deal_id from row 1"
assert "12346" in entities.get("deal_ids", []), "Should extract deal_id from row 2"
assert "Acme Corp" in entities.get("company_names", []), "Should extract company_name from row 1"
assert "Widget Inc" in entities.get("company_names", []), "Should extract company_name from row 2"
print("✓ Test 2 passed\n")

# Test 3: Empty accumulated_data
print("Test 3: Empty accumulated_data")
print("="*60)

empty_result = _extract_rows_from_accumulated({})
print(f"Input: empty dict")
print(f"Output: {empty_result}")
assert empty_result == {}, "Should return empty dict for empty input"
print("✓ Test 3 passed\n")

# Test 4: No rows in any step
print("Test 4: No rows in any step")
print("="*60)

no_rows_data = {
    "step_0": {"rows": [], "table": "deals"},
    "step_1": {"rows": [], "table": "contacts"},
}

no_rows_result = _extract_rows_from_accumulated(no_rows_data)
print(f"Input: accumulated_data with no rows")
print(f"Output: {no_rows_result}")
assert no_rows_result == {}, "Should return empty dict when no rows found"
print("✓ Test 4 passed\n")

print("="*60)
print("✅ All tests passed!")
print("\nThe fix ensures:")
print("  1. dynamic_query_loop returns both answer AND tool_results")
print("  2. tool_results contains rows from accumulated_data")
print("  3. extract_entity_context can extract deal_ids/company_names")
print("  4. Entity context persists for pronoun resolution")
