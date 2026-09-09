#!/usr/bin/env python3
"""
Test that verification gate can FORCE a retry when filter is missing.

This simulates what happens when the model's first query omits the region filter.
"""
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).parent
sys.path.insert(0, str(REPO_ROOT / 'api'))

from api.dimension_verification import verify_dimension_coverage

print("=" * 70)
print("VERIFICATION GATE - FORCED RETRY TEST")
print("=" * 70)
print()

# Simulate: Question asks about EMEA, but query didn't filter for it
question = "How has EMEA pipeline moved in the last 2 weeks"

# Simulate queries_run WITHOUT region filter (the bug case)
queries_run_bad = [
    {
        "tool": "filter_table",
        "params": {
            "table": "waterfall_weekly",
            "filters": [
                ["gte", "week_ending", "2026-08-24"],
                ["lte", "week_ending", "2026-09-09"]
            ]
            # NO region=eq.EMEA filter!
        },
        "rows_returned": 50
    }
]

# Simulate queries_run WITH region filter (correct case)
queries_run_good = [
    {
        "tool": "filter_table",
        "params": {
            "table": "waterfall_weekly",
            "filters": [
                ["gte", "week_ending", "2026-08-24"],
                ["lte", "week_ending", "2026-09-09"],
                ["eq", "region", "EMEA"]  # Has filter!
            ]
        },
        "rows_returned": 16
    }
]

print("Test 1: Query WITHOUT region filter (should FAIL verification)")
print("-" * 70)

verification_bad = verify_dimension_coverage(
    question=question,
    queries_run=queries_run_bad,
    accumulated_data={}
)

print(f"Verified: {verification_bad['verified']}")
print(f"Missing filters: {verification_bad['missing_filters']}")
if verification_bad['required_query']:
    print(f"Required query: {verification_bad['required_query']}")
print()

if not verification_bad['verified']:
    print("✅ CORRECT - Verification caught missing region filter")
else:
    print("❌ WRONG - Verification should have failed")

print()
print("Test 2: Query WITH region filter (should PASS verification)")
print("-" * 70)

verification_good = verify_dimension_coverage(
    question=question,
    queries_run=queries_run_good,
    accumulated_data={}
)

print(f"Verified: {verification_good['verified']}")
print(f"Missing filters: {verification_good['missing_filters']}")
print()

if verification_good['verified']:
    print("✅ CORRECT - Verification passed with proper filter")
else:
    print("❌ WRONG - Verification should have passed")

print()
print("=" * 70)
print("VERIFICATION LOGIC TEST COMPLETE")
print("=" * 70)
