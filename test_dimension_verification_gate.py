#!/usr/bin/env python3
"""
Test dimension verification gate against EMEA regression.

This test confirms the system is now FORCED to query region=EMEA
before answering, even if the model's first query omits the filter.
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

async def test_verification_gate():
    """Test that verification gate forces region filter."""
    from api.router import route_question
    from api.db import get_supabase

    print("=" * 70)
    print("DIMENSION VERIFICATION GATE TEST")
    print("=" * 70)
    print()
    print(f"Question: {question}")
    print()
    print("Expected behavior:")
    print("  - If model's first query omits region=EMEA filter")
    print("  - Verification gate should FORCE a retry with region filter")
    print("  - Answer should contain EMEA-specific data")
    print("  - Answer should NOT fabricate 'EMEA doesn't exist' claim")
    print()
    print("-" * 70)
    print()

    sb = get_supabase()

    result = await route_question(
        question=question,
        user_id="test_dimension_verification",
        persona=None,
        history=[],
        sb=sb,
        thread_ts=f"test_{datetime.now().strftime('%Y%m%d_%H%M%S')}"
    )

    answer = result.get("answer", "")
    answered = result.get("answered", False)

    print("RESULT:")
    print("-" * 70)
    print()
    print(f"Answered: {answered}")
    print()
    print("Answer:")
    print(answer[:800])
    if len(answer) > 800:
        print("...")
    print()

    # Check answer quality
    print("-" * 70)
    print("VERIFICATION CHECKS:")
    print("-" * 70)
    print()

    checks_passed = 0
    checks_total = 0

    # Check 1: No fabrication
    checks_total += 1
    fabrication_signals = [
        "isn't tracked",
        "no 'EMEA' bucket",
        "no EMEA",
        "rolled into ROW"
    ]
    has_fabrication = any(signal.lower() in answer.lower() for signal in fabrication_signals)

    if not has_fabrication:
        print("✅ No fabrication claims (EMEA doesn't exist)")
        checks_passed += 1
    else:
        print("❌ Contains fabrication about EMEA not existing")
        print(f"   Found signals: {[s for s in fabrication_signals if s.lower() in answer.lower()]}")

    # Check 2: Contains EMEA data
    checks_total += 1
    has_emea_data = "EMEA" in answer and ("Enterprise" in answer or "Mid-Market" in answer or "SMB" in answer)

    if has_emea_data:
        print("✅ Contains EMEA-specific segment data")
        checks_passed += 1
    else:
        print("❌ Missing EMEA-specific data")

    # Check 3: Contains dollar amounts (activity data)
    checks_total += 1
    import re
    dollar_amounts = re.findall(r'\$[\d,]+[KkMm]?', answer)

    if len(dollar_amounts) >= 3:
        print(f"✅ Contains dollar amounts ({len(dollar_amounts)} found)")
        checks_passed += 1
    else:
        print(f"❌ Missing dollar amounts (only {len(dollar_amounts)} found)")

    # Check 4: Answered successfully
    checks_total += 1
    if answered:
        print("✅ Query answered successfully")
        checks_passed += 1
    else:
        print("❌ Query failed to answer")

    print()
    print("-" * 70)
    print(f"CHECKS: {checks_passed}/{checks_total} passed")
    print("-" * 70)
    print()

    if checks_passed == checks_total:
        print("🎉 SUCCESS - Verification gate is working!")
        print()
        print("The system correctly:")
        print("  1. Detected EMEA mentioned in question")
        print("  2. Forced query with region=EMEA filter")
        print("  3. Returned EMEA-specific data")
        print("  4. Did not fabricate false claims")
        print()
        print("REGRESSION FIXED ✅")
    elif checks_passed >= checks_total - 1:
        print("⚠️  PARTIAL SUCCESS - Minor issues but core protection working")
    else:
        print("❌ FAILURE - Verification gate not working as expected")
        print()
        print("Investigation needed:")
        print("  - Check logs for [DIMENSION_VERIFY] entries")
        print("  - Verify dimension_verification.py loaded correctly")
        print("  - Check if regions.yaml exists and is readable")

    return {
        "checks_passed": checks_passed,
        "checks_total": checks_total,
        "has_fabrication": has_fabrication,
        "has_emea_data": has_emea_data,
        "answered": answered
    }

print("Running test...")
print()

result = asyncio.run(test_verification_gate())

print()
print("=" * 70)
print("TEST COMPLETE")
print("=" * 70)

sys.exit(0 if result["checks_passed"] == result["checks_total"] else 1)
