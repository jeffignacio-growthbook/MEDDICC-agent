#!/usr/bin/env python3
"""
Test if EMEA regression is reproducible.

Run the exact same query that failed in production to see if:
A) It fails again (systematic regression)
B) It works (one-off LLM variability)
"""
import os
import sys
from pathlib import Path
import asyncio
from datetime import datetime

REPO_ROOT = Path(__file__).parent
sys.path.insert(0, str(REPO_ROOT / 'api'))

from dotenv import load_dotenv
load_dotenv()

question = "How has EMEA pipeline moved in the last 2 weeks"

async def test_query():
    """Run the query and check if it filters by region correctly."""
    from api.router import route_question
    from api.db import get_supabase

    print("=" * 70)
    print("EMEA REGRESSION REPRODUCIBILITY TEST")
    print("=" * 70)
    print()
    print(f"Question: {question}")
    print()

    sb = get_supabase()

    result = await route_question(
        question=question,
        user_id="test_emea_regression_repro",
        persona=None,
        history=[],
        sb=sb,
        thread_ts=f"test_{datetime.now().strftime('%Y%m%d_%H%M%S')}"
    )

    answer = result.get("answer", "")
    queries = result.get("queries_run", [])

    print("Queries run:")
    for i, q in enumerate(queries):
        tool = q.get("tool", "unknown")
        params = q.get("params", {})
        rows = q.get("rows_returned", 0)

        print(f"  Query {i}: {tool} ({rows} rows)")

        if tool == "filter_table":
            table = params.get("table", "?")
            filters = params.get("filters", [])

            # Check if region filter present
            has_region_filter = any(
                f[0] == 'eq' and f[1] == 'region' for f in filters
            )

            print(f"    Table: {table}")
            print(f"    Filters: {filters}")
            if has_region_filter:
                print("    ✅ HAS region filter")
            else:
                print("    ❌ MISSING region filter")
    print()

    # Check answer for fabrications
    print("Answer excerpt:")
    print(answer[:600])
    print()

    # Check for specific claims
    fabrication_signals = [
        "isn't tracked",
        "no 'EMEA' bucket",
        "no EMEA",
        "rolled into ROW"
    ]

    has_fabrication = any(signal.lower() in answer.lower() for signal in fabrication_signals)

    print("Analysis:")
    if has_fabrication:
        print("  ❌ REGRESSION REPRODUCED")
        print("  Answer contains fabricated claims about EMEA not existing")
        print()
        print("  This is a SYSTEMATIC issue, not one-off LLM variability")
    else:
        # Check if EMEA data is present
        if "EMEA" in answer and ("Enterprise" in answer or "Mid-Market" in answer):
            print("  ✅ QUERY WORKED")
            print("  Answer contains EMEA-specific data")
            print()
            print("  Production failure was one-off LLM variability")
        else:
            print("  ⚠️  UNCLEAR")
            print("  Answer doesn't claim EMEA missing, but also doesn't show EMEA data")

    return {
        "queries": len(queries),
        "has_region_filter": any(
            q.get("tool") == "filter_table" and
            any(f[0] == 'eq' and f[1] == 'region'
                for f in q.get("params", {}).get("filters", []))
            for q in queries
        ),
        "has_fabrication": has_fabrication,
        "answer": answer
    }

result = asyncio.run(test_query())

print()
print("=" * 70)
print("VERDICT")
print("=" * 70)
print()

if result['has_fabrication']:
    print("🚨 SYSTEMATIC REGRESSION CONFIRMED")
    print()
    print("The model consistently:")
    print("  1. Queries without region filter")
    print("  2. Gets mixed data from all regions")
    print("  3. Fabricates claim that EMEA doesn't exist")
    print()
    print("This requires immediate fix - not another synthesis patch.")
    print()
    print("Root cause likely: Recent synthesis prompt changes (b830d2d, 0bdd0a5,")
    print("f1d42d7) made model too eager to answer from incomplete data instead")
    print("of continuing to drill down with additional queries.")
elif not result['has_region_filter']:
    print("⚠️  QUERY PATTERN REGRESSION (but no fabrication)")
    print()
    print("The model queried without region filter, but didn't fabricate.")
    print("This suggests synthesis prompt changes made model less thorough")
    print("in query generation, but didn't always lead to fabrications.")
else:
    print("✅ PRODUCTION FAILURE WAS ONE-OFF")
    print()
    print("Model correctly queried with region filter this time.")
    print("Production failure was LLM variability, not systematic regression.")
