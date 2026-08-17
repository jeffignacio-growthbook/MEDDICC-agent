#!/usr/bin/env python3
"""
Local 4-Turn Test: Verify entity-aware extraction and token budget.

Tests the router directly without going through the HTTP API.
"""

import sys
import asyncio
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

async def test_4turn():
    """Test entity-aware extraction in multi-turn conversation."""
    from api.router import dynamic_query_loop, logger
    from api.db import get_supabase
    import anthropic
    import os
    import logging

    # Show info logs
    logger.setLevel(logging.INFO)

    print("="*80)
    print("4-TURN LOCAL TEST")
    print("="*80)
    print()

    sb = get_supabase()
    client = anthropic.Anthropic(api_key=os.environ.get("ANTHROPIC_API_KEY"))

    # Turn 1: Entity discovery query
    print("[TURN 1] Entity discovery: appointmentscheduled deals with high champion score")
    question1 = "What deals are in appointmentscheduled stage with champion_score > 7?"

    result1 = await dynamic_query_loop(
        question=question1,
        history=[],
        params={},
        sb=sb,
        client=client
    )

    print(f"\n  Answer length: {len(result1.get('answer', ''))} chars")
    print(f"  Tool results rows: {len(result1.get('tool_results', {}).get('rows', []))}")
    print(f"  Token usage: {result1.get('token_usage', {})}")

    # Extract entity IDs from tool results
    entity_ids = []
    tool_rows = result1.get('tool_results', {}).get('rows', [])
    for row in tool_rows:
        if 'deal_id' in row:
            entity_ids.append(row['deal_id'])

    print(f"  Extracted {len(set(entity_ids))} unique deal_ids")
    print()

    # Turn 2: Entity-scope follow-up
    print("[TURN 2] Entity-scope follow-up: which deals are at risk?")
    question2 = "Which of those deals are at risk?"

    # Build cache_payload with entity context
    cache_payload = {
        'entity_ids': list(set(entity_ids)),
        'entity_type': 'deal_id',
        'source_table': result1.get('tool_results', {}).get('table', 'deals')
    }

    result2 = await dynamic_query_loop(
        question=question2,
        history=[{
            'question': question1,
            'answer': result1.get('answer', ''),
            'cache_payload': cache_payload
        }],
        params={},
        sb=sb,
        client=client
    )

    print(f"\n  Answer length: {len(result2.get('answer', ''))} chars")
    print(f"  Tool results rows: {len(result2.get('tool_results', {}).get('rows', []))}")
    print(f"  Token usage: {result2.get('token_usage', {})}")
    print()

    # Aggregate metrics
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

    # Success criteria
    checks = [
        ("Token budget under 20K", total_tokens < 20000),
        ("Turn 1 extracted entities", len(entity_ids) > 0),
        ("Turn 2 has answer", len(result2.get('answer', '')) > 0),
        ("Turn 1 has answer", len(result1.get('answer', '')) > 0),
    ]

    print("Success Criteria:")
    for check_name, passed in checks:
        status = "✅" if passed else "❌"
        print(f"  {status} {check_name}")

    all_passed = all(passed for _, passed in checks)
    print()
    print("="*80)
    print(f"Overall: {'✅ PASS' if all_passed else '❌ FAIL'}")
    print("="*80)

    return all_passed

if __name__ == "__main__":
    result = asyncio.run(test_4turn())
    sys.exit(0 if result else 1)
