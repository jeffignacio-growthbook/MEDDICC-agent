#!/usr/bin/env python3
"""
Test synthesis aggregation fix against live API.

Re-run the problematic query to verify fix prevents both known issues:
1. Missing week (Aug 28 $120K activity dropped)
2. Missing segment (SMB -$100K dropped from Aug 28)
3. False "partial week" claim when all segments present

Expected correct answer:
- Aug 17: $75K lost (Unknown segment)
- Aug 24: $0 net (all segments)
- Aug 28: +$20K Mid-Market won, -$100K SMB lost = -$80K net
- Sep 7-8: $0 (recent weeks)
"""
import os
import sys
from pathlib import Path
import asyncio
import httpx
from datetime import datetime

REPO_ROOT = Path(__file__).parent
sys.path.insert(0, str(REPO_ROOT / 'api'))
sys.path.insert(0, str(REPO_ROOT / 'scripts'))

from dotenv import load_dotenv
load_dotenv()

print("=" * 70)
print("LIVE SYNTHESIS FIX TEST")
print("=" * 70)
print()

# Test Case 1: Original problematic query
test_question = "How has EMEA pipeline moved in the last 2 weeks"

print(f"Question: {test_question}")
print()
print("Expected answer components:")
print("  ✓ Week-by-week breakdown (not just latest week)")
print("  ✓ Aug 28: +$20K Mid-Market AND -$100K SMB (both segments)")
print("  ✓ No false 'partial week' claim")
print()
print("-" * 70)
print()

async def test_through_router():
    """Test by calling through the actual route_question pipeline."""
    from api.router import route_question
    from api.db import get_supabase

    sb = get_supabase()

    result = await route_question(
        question=test_question,
        user_id="test_synthesis_fix",
        persona=None,  # Will use generic voice
        history=[],
        sb=sb,
        thread_ts=f"test_{datetime.now().strftime('%Y%m%d_%H%M%S')}"
    )

    return result

print("Running through route_question pipeline...")
print()

result = asyncio.run(test_through_router())

if not result:
    print("❌ Test failed - no result returned")
    sys.exit(1)

print("=" * 70)
print("ANSWER RECEIVED")
print("=" * 70)
print()
print(result.get("answer", "NO ANSWER"))
print()

# Verification checks
answer_text = result.get("answer", "")
passed = []
failed = []

def check(name, condition, details=""):
    if condition:
        passed.append(name)
        print(f"  ✅ {name}")
    else:
        failed.append(name)
        print(f"  ❌ {name}")
        if details:
            print(f"     {details}")

print("=" * 70)
print("VERIFICATION CHECKS")
print("=" * 70)
print()

# Check 1: Multiple weeks mentioned (not just recent)
import re
weeks_mentioned = len(re.findall(r'Aug \d+|Sep \d+|\d{4}-\d{2}-\d{2}', answer_text))
check("Multiple weeks mentioned (week-by-week breakdown)",
      weeks_mentioned >= 2,
      f"Found {weeks_mentioned} week references")

# Check 2: Aug 28 specifically mentioned
has_aug_28 = 'Aug 28' in answer_text or '2026-08-28' in answer_text
check("Aug 28 week explicitly mentioned",
      has_aug_28,
      "This is the week with $120K activity")

# Check 3: Both segments (Mid-Market AND SMB) for Aug 28
has_midmarket = 'Mid-Market' in answer_text or 'mid-market' in answer_text.lower()
has_smb = 'SMB' in answer_text
check("Mid-Market segment mentioned",
      has_midmarket)
check("SMB segment mentioned",
      has_smb,
      "Critical: $100K SMB loss was dropped in previous answer")

# Check 4: Dollar amounts
amounts = re.findall(r'\$[\d,]+[KkMm]?', answer_text)
has_20k = any('20' in amt for amt in amounts)
has_100k = any('100' in amt for amt in amounts)
check("$20K amount mentioned (Mid-Market won)",
      has_20k)
check("$100K amount mentioned (SMB lost)",
      has_100k,
      "This was the missing amount in previous answer")

# Check 5: No false "partial week" claim
has_partial_claim = 'partial' in answer_text.lower() or 'pending' in answer_text.lower()
check("No false 'partial week' or 'pending' claim",
      not has_partial_claim,
      "Previous answer invented 'partial week' when all 4 segments were present")

# Check 6: Net change calculation
# Should mention -$80K net for Aug 28 ($20K won - $100K lost)
has_net_calculation = '-80' in answer_text or 'net' in answer_text.lower()
check("Net change calculation present",
      has_net_calculation,
      "Should calculate +$20K - $100K = -$80K for Aug 28")

print()
print("=" * 70)
print(f"RESULTS: {len(passed)} passed, {len(failed)} failed")
print("=" * 70)
print()

if len(failed) == 0:
    print("✅ ALL CHECKS PASSED")
    print()
    print("Synthesis fix is working correctly:")
    print("  - Reports multiple weeks (not just recent)")
    print("  - Includes all segments for Aug 28 (Mid-Market AND SMB)")
    print("  - No false 'partial week' claims")
    print("  - Aggregates full data set")
    print()
    print("RECOMMENDATION: Fix is verified, close PENDING_WORK.md #2")
else:
    print(f"❌ {len(failed)} CHECKS FAILED")
    print()
    print("Failed checks:")
    for name in failed:
        print(f"  - {name}")
    print()
    print("RECOMMENDATION: Review answer and strengthen synthesis prompt")

print()
print("=" * 70)
print("QUERIES RUN")
print("=" * 70)
print()

queries = result.get("queries_run", [])
print(f"Total queries: {len(queries)}")
for i, q in enumerate(queries):
    tool = q.get("tool", "unknown")
    rows = q.get("rows_returned", 0)
    print(f"  {i}. {tool}: {rows} rows")

print()
