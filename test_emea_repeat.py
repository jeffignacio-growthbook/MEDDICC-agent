#!/usr/bin/env python3
"""
Re-run the exact same EMEA query 3 times to check if segment naming
is consistent or intermittent.

Original test showed: "$20K won (closed out of $1.12M segment)"
New test showed: "Mid-Market: -$20K"

Which is the real pattern?
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

async def run_single_test(run_num):
    """Run one instance of the test."""
    from api.router import route_question
    from api.db import get_supabase

    print(f"Run {run_num}: {question}")
    print()

    sb = get_supabase()

    result = await route_question(
        question=question,
        user_id=f"test_emea_repeat_{run_num}",
        persona=None,
        history=[],
        sb=sb,
        thread_ts=f"test_{datetime.now().strftime('%Y%m%d_%H%M%S')}_{run_num}"
    )

    answer = result.get("answer", "")

    # Check for explicit segment names
    segments = ['Enterprise', 'Mid-Market', 'SMB', 'Unknown']
    segments_found = [s for s in segments if s in answer]

    # Check for dollar-value implicit references
    import re
    # Pattern: $X.XXM segment, $XXXk segment, etc.
    dollar_segment_refs = re.findall(r'\$[\d,]+\.?\d*[KkMm]?\s+segment', answer)

    print("Answer excerpt (first 600 chars):")
    print(answer[:600])
    print("...")
    print()

    print(f"Segment names found: {segments_found} ({len(segments_found)}/4)")
    print(f"Dollar-value implicit refs: {len(dollar_segment_refs)}")
    if dollar_segment_refs:
        print(f"  Examples: {dollar_segment_refs[:3]}")
    print()

    return {
        "run": run_num,
        "segments_explicit": len(segments_found),
        "dollar_refs": len(dollar_segment_refs),
        "answer": answer
    }

async def run_all():
    """Run 3 instances of the same test."""
    results = []

    for i in range(1, 4):
        print("=" * 70)
        print()
        result = await run_single_test(i)
        results.append(result)

        if i < 3:
            # Small delay between runs
            await asyncio.sleep(2)

    return results

print("=" * 70)
print("EMEA QUERY REPEAT TEST (3 runs)")
print("=" * 70)
print()

results = asyncio.run(run_all())

print("=" * 70)
print("ANALYSIS")
print("=" * 70)
print()

explicit_counts = [r['segments_explicit'] for r in results]
dollar_counts = [r['dollar_refs'] for r in results]

print(f"Run 1: {explicit_counts[0]}/4 explicit, {dollar_counts[0]} dollar refs")
print(f"Run 2: {explicit_counts[1]}/4 explicit, {dollar_counts[1]} dollar refs")
print(f"Run 3: {explicit_counts[2]}/4 explicit, {dollar_counts[2]} dollar refs")
print()

avg_explicit = sum(explicit_counts) / len(explicit_counts)
total_dollar = sum(dollar_counts)

if avg_explicit >= 3.5:
    print("✅ CONSISTENT EXPLICIT NAMING")
    print(f"   Average {avg_explicit:.1f}/4 segment names present")
    print(f"   Dollar-value references: {total_dollar} across 3 runs")
    print()
    print("VERDICT: Original test with dollar-value references was COINCIDENTAL.")
    print("The aggregation fix did NOT cause segment name regression.")
    print()
    print("RECOMMENDATION: No additional instruction needed.")
elif avg_explicit <= 1.0:
    print("❌ CONSISTENT IMPLICIT NAMING")
    print(f"   Average {avg_explicit:.1f}/4 segment names present")
    print(f"   Dollar-value references: {total_dollar} across 3 runs")
    print()
    print("VERDICT: Aggregation instruction IS discouraging explicit names.")
    print()
    print("RECOMMENDATION: Add explicit dimension name instruction.")
else:
    print("⚠️  INTERMITTENT BEHAVIOR")
    print(f"   Average {avg_explicit:.1f}/4 segment names present")
    print(f"   Varies across runs: {explicit_counts}")
    print()
    print("VERDICT: LLM phrasing varies naturally, but should stabilize with")
    print("explicit instruction if users need consistent naming.")
    print()
    print("RECOMMENDATION: Add dimension name instruction for consistency.")

print()
print("=" * 70)
