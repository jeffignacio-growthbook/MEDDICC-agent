#!/usr/bin/env python3
"""
Test the three coaching handlers before Slack validation.
Simulates what the Slack agent would do for each question.
"""

import sys
import os
import asyncio
from pathlib import Path

# Add paths
sys.path.insert(0, str(Path(__file__).parent.parent / "api"))
sys.path.insert(0, str(Path(__file__).parent))

# Set credentials
os.environ['SUPABASE_URL'] = 'https://htgvkqycrwesdysustxd.supabase.co'
os.environ['SUPABASE_SERVICE_KEY'] = 'eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9.eyJpc3MiOiJzdXBhYmFzZSIsInJlZiI6Imh0Z3ZrcXljcndlc2R5c3VzdHhkIiwicm9sZSI6InNlcnZpY2Vfcm9sZSIsImlhdCI6MTc4NTg4NTI5MiwiZXhwIjoyMTAxNDYxMjkyfQ.aeJFp6OwucNplQClgNGcC6pFZu_zfVK7ATim_MC_Wn4'

from handlers import (
    query_pre_call_brief,
    query_coaching_priorities,
    query_call_quality
)
from supabase_client import SupabaseWriter


def print_result(title: str, result: dict):
    """Pretty print handler result."""
    import json
    print(f"\n{'=' * 80}")
    print(f"{title}")
    print('=' * 80)
    print(json.dumps(result, indent=2, default=str))
    print('=' * 80)


async def main():
    """Run all three coaching handler tests."""

    # Initialize Supabase
    writer = SupabaseWriter()
    sb = writer.client

    print("\n" + "=" * 80)
    print("COACHING HANDLERS SLACK VALIDATION TESTS")
    print("=" * 80)

    # Test 1: Pre-call brief for Skyscanner
    print("\n[TEST 1] prep me for my call with Skyscanner")
    print("Expected handler: query_pre_call_brief")

    try:
        result1 = await query_pre_call_brief(
            {"company": "Skyscanner"},
            sb
        )
        print_result("Test 1 Result: Pre-Call Brief", result1)

        # Validate response structure
        if "error" in result1:
            print(f"\n⚠️  Error: {result1['error']}")
        else:
            print("\n✅ Key fields present:")
            print(f"   - Company: {result1.get('company_name')}")
            print(f"   - MEDDICC overall: {result1.get('meddicc', {}).get('overall_score')}")
            print(f"   - Weakest components: {len(result1.get('meddicc', {}).get('weakest_components', []))}")
            print(f"   - Focus questions: {len(result1.get('focus_questions', []))}")
            print(f"   - Recent calls: {len(result1.get('recent_calls', []))}")
            print(f"   - Data gap: {result1.get('data_gap')}")
    except Exception as e:
        print(f"\n❌ Test 1 failed: {e}")
        import traceback
        traceback.print_exc()

    # Test 2: Coaching priorities
    print("\n\n[TEST 2] which reps need coaching this week?")
    print("Expected handler: query_coaching_priorities")

    try:
        result2 = await query_coaching_priorities(
            {"focus": "all"},
            sb
        )
        print_result("Test 2 Result: Coaching Priorities", result2)

        # Validate response structure
        if "error" in result2:
            print(f"\n⚠️  Error: {result2['error']}")
        else:
            print("\n✅ Key fields present:")
            if "by_owner" in result2:
                print(f"   - Grouped by owner: {len(result2.get('by_owner', {}))} reps")
                print(f"   - Total deals needing attention: {result2.get('total_deals_needing_attention')}")
                print(f"   - High urgency count: {result2.get('high_urgency_count')}")
            elif "priorities" in result2:
                print(f"   - Priorities: {len(result2.get('priorities', []))}")
                print(f"   - High urgency: {result2.get('high_urgency')}")
    except Exception as e:
        print(f"\n❌ Test 2 failed: {e}")
        import traceback
        traceback.print_exc()

    # Test 3: Call quality lookback
    print("\n\n[TEST 3] how did the last Skyscanner call go?")
    print("Expected handler: query_call_quality")

    try:
        result3 = await query_call_quality(
            {"company": "Skyscanner"},
            sb
        )
        print_result("Test 3 Result: Call Quality", result3)

        # Validate response structure
        if "error" in result3:
            print(f"\n⚠️  Error: {result3['error']}")
        else:
            print("\n✅ Key fields present:")
            print(f"   - Company: {result3.get('company_name')}")
            print(f"   - Latest call date: {result3.get('latest_call', {}).get('date')}")
            print(f"   - Latest call source: {result3.get('latest_call', {}).get('source')}")
            print(f"   - Quality score available: {bool(result3.get('quality_score'))}")
            print(f"   - Call history count: {result3.get('call_history_count')}")
            print(f"   - Data gap: {result3.get('data_gap')}")

            if result3.get('data_gap'):
                print(f"   - Note: {result3.get('note')}")
    except Exception as e:
        print(f"\n❌ Test 3 failed: {e}")
        import traceback
        traceback.print_exc()

    print("\n" + "=" * 80)
    print("VALIDATION TESTS COMPLETE")
    print("=" * 80)


if __name__ == "__main__":
    asyncio.run(main())
