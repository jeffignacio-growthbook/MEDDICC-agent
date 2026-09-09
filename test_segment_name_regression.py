#!/usr/bin/env python3
"""
Test whether segment name omission is consistent or coincidental.

Run 2-3 different queries that should mention segment/region names
and check if they're consistently replaced with dollar-value references.

Test Cases:
1. Same EMEA query (baseline)
2. Win rate by segment query (should mention Mid-Market, SMB, etc.)
3. Regional breakdown query (should mention NAM, EMEA, APAC)
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

print("=" * 70)
print("SEGMENT NAME REGRESSION TEST")
print("=" * 70)
print()

test_cases = [
    {
        "name": "Test 1: EMEA pipeline movement (baseline)",
        "question": "How has EMEA pipeline moved in the last 2 weeks",
        "expected_names": ["EMEA", "Mid-Market", "SMB", "Enterprise", "Unknown"],
        "type": "region+segment"
    },
    {
        "name": "Test 2: Win rate by segment",
        "question": "What is the win rate by segment in Q3 2026",
        "expected_names": ["Enterprise", "Mid-Market", "SMB"],
        "type": "segment"
    },
    {
        "name": "Test 3: Pipeline by region",
        "question": "Show me current pipeline by region",
        "expected_names": ["NAM", "EMEA", "APAC", "LATAM", "ROW"],
        "type": "region"
    }
]

async def run_test_case(test_case):
    """Run a single test case and analyze segment name usage."""
    from api.router import route_question
    from api.db import get_supabase

    print(f"{test_case['name']}")
    print(f"Question: {test_case['question']}")
    print()

    sb = get_supabase()

    result = await route_question(
        question=test_case['question'],
        user_id="test_segment_regression",
        persona=None,
        history=[],
        sb=sb,
        thread_ts=f"test_{datetime.now().strftime('%Y%m%d_%H%M%S')}"
    )

    answer = result.get("answer", "")

    print("Answer:")
    print(answer[:500] + "..." if len(answer) > 500 else answer)
    print()

    # Check for segment/region names
    names_found = []
    names_missing = []

    for name in test_case['expected_names']:
        if name in answer:
            names_found.append(name)
        else:
            names_missing.append(name)

    # Check for dollar-value references (signs of implicit naming)
    import re
    dollar_refs = re.findall(r'\$[\d,]+[KkMm]?\s+(segment|region|pipeline)', answer)

    print(f"Expected dimension names: {test_case['expected_names']}")
    print(f"Found explicitly: {names_found}")
    print(f"Missing: {names_missing}")
    print(f"Dollar-value references: {len(dollar_refs)} found")
    if dollar_refs:
        print(f"  Examples: {dollar_refs[:3]}")
    print()

    return {
        "test": test_case['name'],
        "type": test_case['type'],
        "total_names": len(test_case['expected_names']),
        "names_found": len(names_found),
        "names_missing": len(names_missing),
        "dollar_refs": len(dollar_refs),
        "explicit_ratio": len(names_found) / len(test_case['expected_names']),
        "answer_length": len(answer)
    }

async def run_all_tests():
    """Run all test cases and analyze pattern."""
    results = []

    for i, test_case in enumerate(test_cases, 1):
        print("-" * 70)
        print()
        result = await run_test_case(test_case)
        results.append(result)
        print("=" * 70)
        print()

        if i < len(test_cases):
            # Small delay between tests
            await asyncio.sleep(2)

    return results

# Run tests
print("Running test suite...")
print()
results = asyncio.run(run_all_tests())

print("=" * 70)
print("ANALYSIS")
print("=" * 70)
print()

# Summarize results
total_explicit = sum(r['names_found'] for r in results)
total_missing = sum(r['names_missing'] for r in results)
total_expected = sum(r['total_names'] for r in results)
total_dollar_refs = sum(r['dollar_refs'] for r in results)

print(f"Across {len(results)} test cases:")
print(f"  Expected dimension names: {total_expected}")
print(f"  Found explicitly: {total_explicit} ({total_explicit/total_expected*100:.1f}%)")
print(f"  Missing: {total_missing} ({total_missing/total_expected*100:.1f}%)")
print(f"  Dollar-value implicit refs: {total_dollar_refs}")
print()

# Per-test breakdown
print("Per-test results:")
for r in results:
    print(f"  {r['test']}")
    print(f"    Explicit names: {r['names_found']}/{r['total_names']} ({r['explicit_ratio']*100:.0f}%)")
    print(f"    Dollar refs: {r['dollar_refs']}")
    print()

# Determine pattern
if total_missing > total_expected * 0.5:
    print("❌ CONSISTENT PATTERN DETECTED")
    print()
    print("Segment/region names are consistently missing (>50% omission rate).")
    print()
    print("This suggests the aggregation instruction is inadvertently")
    print("discouraging the model from using explicit dimension labels.")
    print()
    print("RECOMMENDATION: Add explicit instruction to use dimension names")
    print('  e.g., "Use actual segment names (Mid-Market, SMB) and region')
    print('  names (EMEA, NAM) rather than dollar-value references"')
elif total_missing > total_expected * 0.2:
    print("⚠️  PARTIAL PATTERN DETECTED")
    print()
    print("Segment/region names sometimes missing (20-50% omission rate).")
    print()
    print("This could be coincidental or a weak side effect.")
    print()
    print("RECOMMENDATION: Monitor next few production queries.")
    print("If pattern persists, add dimension name instruction.")
else:
    print("✅ NO CONSISTENT PATTERN")
    print()
    print("Segment/region names are mostly present (<20% omission rate).")
    print()
    print("The original test case was likely coincidental phrasing.")
    print()
    print("RECOMMENDATION: No additional instruction needed.")

print()
print("=" * 70)
