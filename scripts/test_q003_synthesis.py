#!/usr/bin/env python3
"""
Test q003: "Which deals have no ARR recorded?"
Verify synthesis truncation fix - should surface ACTUAL count, not sample size.
"""
import sys
import os
from pathlib import Path
from dotenv import load_dotenv
import asyncio

env_path = Path(__file__).parent.parent / ".env"
load_dotenv(env_path)

sys.path.insert(0, str(Path(__file__).parent.parent / "api"))
from router import route_question
from db import get_supabase

async def test_q003():
    question = "Which deals have no ARR recorded?"

    print("=" * 80)
    print("Q003 TEST: Synthesis Truncation Fix")
    print("=" * 80)
    print(f"Question: {question}")
    print()

    # Get actual count from database
    sb = get_supabase()
    deals = sb.table("deals").select(
        "deal_id,company_name,expansion_arr,new_arr"
    ).eq("deal_status", "active").execute()

    no_arr_count = 0
    for deal in deals.data:
        expansion_arr = deal.get("expansion_arr") or 0
        new_arr = deal.get("new_arr") or 0
        if expansion_arr == 0 and new_arr == 0:
            no_arr_count += 1

    print(f"ACTUAL COUNT from database: {no_arr_count} deals")
    print()

    # Route through agent
    try:
        result = await route_question(question, user_id="test", thread_ts="test_q003", sb=sb)
        response_text = result.get("response", "")

        print("AGENT RESPONSE:")
        print("-" * 80)
        print(response_text)
        print("-" * 80)
        print()

        # Check if actual count appears in response
        if str(no_arr_count) in response_text:
            print(f"✅ PASS: Actual count ({no_arr_count}) appears in response")
        else:
            print(f"❌ FAIL: Actual count ({no_arr_count}) does NOT appear in response")
            print(f"   Check if response shows sample size instead of full count")

    except Exception as e:
        print(f"❌ ERROR: {e}")
        import traceback
        traceback.print_exc()

if __name__ == "__main__":
    asyncio.run(test_q003())
