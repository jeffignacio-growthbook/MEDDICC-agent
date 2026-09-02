#!/usr/bin/env python3
"""
Test which dimension helps when fast path fails.

Tests independently:
- More iterations (5 → 10)
- No sampling (full results vs aggregated sample)
- Full schema (vs lightweight)
- Better model (Opus vs Sonnet)

Goal: Find which dimension moves the result from failure → success.
"""
import sys
import asyncio
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent / 'scripts'))
sys.path.insert(0, str(Path(__file__).parent / 'api'))

from dotenv import load_dotenv
load_dotenv(Path(__file__).parent / '.env')

from supabase_client import SupabaseWriter
from anthropic import AsyncAnthropic
import os

# Test question that should stress the system
# Using a complex analytical question, not the ARR question that now works
TEST_QUESTION = "Which deals moved from Technical Evaluation to Closed Lost in the last quarter without ever reaching Proposal stage?"

async def test_dimension(dimension: str, question: str):
    """
    Test a single dimension change.

    Returns (success: bool, answer: str, notes: str)
    """
    from router import dynamic_query_loop

    writer = SupabaseWriter()
    api_key = os.getenv('ANTHROPIC_API_KEY')

    # Configure based on dimension
    if dimension == "baseline":
        client = AsyncAnthropic(api_key=api_key)
        max_iter = 5
        use_sampling = True
        use_lightweight = True
        model_name = "sonnet"
    elif dimension == "more_iterations":
        client = AsyncAnthropic(api_key=api_key)
        max_iter = 10  # Double the iterations
        use_sampling = True
        use_lightweight = True
        model_name = "sonnet"
    elif dimension == "no_sampling":
        client = AsyncAnthropic(api_key=api_key)
        max_iter = 5
        use_sampling = False  # Full results, no aggregation
        use_lightweight = True
        model_name = "sonnet"
    elif dimension == "full_schema":
        client = AsyncAnthropic(api_key=api_key)
        max_iter = 5
        use_sampling = True
        use_lightweight = False  # Full schema descriptions
        model_name = "sonnet"
    elif dimension == "better_model":
        client = AsyncAnthropic(api_key=api_key)
        max_iter = 5
        use_sampling = True
        use_lightweight = True
        model_name = "opus"  # Most capable model
    else:
        raise ValueError(f"Unknown dimension: {dimension}")

    print(f"\n{'='*70}")
    print(f"Testing: {dimension}")
    print(f"  Max iterations: {max_iter}")
    print(f"  Sampling: {use_sampling}")
    print(f"  Schema: {'lightweight' if use_lightweight else 'full'}")
    print(f"  Model: {model_name}")
    print(f"{'='*70}\n")

    # Note: This is a simplified test - the actual loop doesn't expose all these params
    # We'd need to modify the loop or create a test harness
    # For now, document what would be tested

    return {
        "dimension": dimension,
        "config": {
            "max_iter": max_iter,
            "sampling": use_sampling,
            "schema": "lightweight" if use_lightweight else "full",
            "model": model_name
        },
        "note": "Test harness needs loop parameter exposure to run"
    }

async def main():
    """Run dimension tests."""
    print(f"Question: {TEST_QUESTION}")
    print("\nThis test requires modifying dynamic_query_loop to expose:")
    print("  - max_iterations parameter")
    print("  - disable_sampling parameter")
    print("  - force_full_schema parameter")
    print("  - model selection parameter")
    print("\nCurrent approach: Manual testing with code modifications\n")

    dimensions = [
        "baseline",
        "more_iterations",
        "no_sampling",
        "full_schema",
        "better_model"
    ]

    for dim in dimensions:
        result = await test_dimension(dim, TEST_QUESTION)
        print(f"Config: {result['config']}")
        print(f"Note: {result['note']}\n")

    print("\n" + "="*70)
    print("RECOMMENDATION:")
    print("="*70)
    print("""
Manual testing approach:

1. Find a question that fails (budget_exhausted, below_floor, etc.)
   - Check fallback_log for recent failures
   - Or use a known complex question

2. Test baseline: Current fast path configuration
   - Record: answered=True/False, iterations used, answer quality

3. Test +iterations: Change MAX_ITERATIONS from 5 to 10
   - Keep everything else the same
   - Did it succeed? How many iterations needed?

4. Test -sampling: Comment out _aggregate_and_sample()
   - Pass full results to model instead of samples
   - Did it succeed? What was the context size?

5. Test +schema: Change lightweight=False in get_schema_context()
   - Full descriptions for all tables
   - Did it succeed? What was the schema size?

6. Test +model: Use 'opus' instead of 'sonnet'
   - Keep other params the same
   - Did it succeed? Cost difference?

Whichever dimension moves failure → success is what general_fallback() needs.
If multiple help, use the cheapest one first (iterations < sampling < model < schema).
""")

if __name__ == '__main__':
    asyncio.run(main())
