#!/usr/bin/env python3
"""Test the ARR query with null/zero counts fix."""
import sys
import asyncio
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent / 'scripts'))
sys.path.insert(0, str(Path(__file__).parent / 'api'))

from dotenv import load_dotenv
load_dotenv(Path(__file__).parent / '.env')

from supabase_client import SupabaseWriter
from router import dynamic_query_loop
from time_resolver import resolve_time_window
from llm_client import LLMClient
import os

async def main():
    """Run the ARR query test."""
    writer = SupabaseWriter()
    anthropic_client = LLMClient.from_config(role="generator")

    question = "Which deals have no ARR recorded?"
    history = []  # Empty conversation history
    params = {"time_window": resolve_time_window({})}

    print(f"Question: {question}")
    print("=" * 70)
    print()

    result = await dynamic_query_loop(
        question=question,
        history=history,
        params=params,
        sb=writer.client,
        client=anthropic_client
    )

    print("Result:")
    print(result)
    print()

    # Check if the answer contains "127"
    answer = result.get("answer", "")
    if "127" in answer:
        print("✓ SUCCESS: Answer contains ground truth count of 127")
    else:
        print("✗ INCOMPLETE: Answer does not contain 127")
        if "11" in answer or "+" in answer:
            print("  (Still showing incomplete count)")

if __name__ == '__main__':
    asyncio.run(main())
