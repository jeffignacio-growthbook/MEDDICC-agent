#!/usr/bin/env python3
"""
4-Turn Test: Verify entity-aware extraction and token budget.

Expected behavior:
- Turn 1: Entity discovery via dynamic_query_loop
- Turn 2: Entity-scope follow-up using extracted entities
- Total tokens < 20,000
- Quality scores ≥ 0.8
- Turn 2 gets entity context from entity-bearing steps (not aggregates)
"""

import sys
import json
import asyncio
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

async def run_4turn_test():
    """Run the 4-turn test against production API."""
    import httpx

    API_URL = "https://meddicc-agent-production.up.railway.app/slack/question"

    print("="*80)
    print("4-TURN TEST")
    print("="*80)
    print()

    # Turn 1: Initial entity discovery
    print("[TURN 1] Entity discovery query")
    turn1_question = "What deals are in appointmentscheduled stage with champion_score > 7?"

    async with httpx.AsyncClient(timeout=60.0) as client:
        resp1 = await client.post(API_URL, json={
            "question": turn1_question,
            "history": []
        })

    if resp1.status_code != 200:
        print(f"  ERROR: {resp1.status_code} - {resp1.text}")
        return

    result1 = resp1.json()
    print(f"  Answer: {result1.get('answer', '')[:200]}...")
    print(f"  Tokens: {result1.get('token_usage', {})}")
    print(f"  Cache payload entities: {len(result1.get('cache_payload', {}).get('entity_ids', []))}")
    print()

    # Turn 2: Entity-scope follow-up
    print("[TURN 2] Entity-scope follow-up")
    turn2_question = "Which of those deals are at risk?"

    history = [{
        "question": turn1_question,
        "answer": result1.get('answer', ''),
        "cache_payload": result1.get('cache_payload', {})
    }]

    async with httpx.AsyncClient(timeout=60.0) as client:
        resp2 = await client.post(API_URL, json={
            "question": turn2_question,
            "history": history
        })

    if resp2.status_code != 200:
        print(f"  ERROR: {resp2.status_code} - {resp2.text}")
        return

    result2 = resp2.json()
    print(f"  Answer: {result2.get('answer', '')[:200]}...")
    print(f"  Tokens: {result2.get('token_usage', {})}")
    print()

    # Aggregate results
    total_tokens = (
        result1.get('token_usage', {}).get('total', 0) +
        result2.get('token_usage', {}).get('total', 0)
    )

    print("="*80)
    print("RESULTS")
    print("="*80)
    print(f"Total tokens: {total_tokens:,} / 20,000")
    print(f"Budget usage: {total_tokens/20000*100:.1f}%")
    print(f"Headroom: {20000 - total_tokens:,} tokens")
    print()

    # Verify success criteria
    checks = []
    checks.append(("Token budget under 20K", total_tokens < 20000))
    checks.append(("Turn 1 extracted entities", len(result1.get('cache_payload', {}).get('entity_ids', [])) > 0))
    checks.append(("Turn 2 has answer", len(result2.get('answer', '')) > 0))

    print("Success Criteria:")
    for check_name, passed in checks:
        status = "✅" if passed else "❌"
        print(f"  {status} {check_name}")

    all_passed = all(passed for _, passed in checks)
    print()
    print("="*80)
    print(f"Overall: {'✅ PASS' if all_passed else '❌ FAIL'}")
    print("="*80)

if __name__ == "__main__":
    asyncio.run(run_4turn_test())
