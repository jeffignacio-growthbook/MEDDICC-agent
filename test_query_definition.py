#!/usr/bin/env python3
"""
Test query_definition handler.
"""

import sys
from pathlib import Path

REPO_ROOT = Path(__file__).parent
sys.path.insert(0, str(REPO_ROOT))

async def main():
    from api import handlers

    # Test 1: "at-risk" (pending definition)
    print("=" * 70)
    print("TEST 1: What does at-risk mean? (PENDING)")
    print("=" * 70)

    result = await handlers.query_definition({
        "question": "What does at-risk mean to you?"
    }, None)

    print(json.dumps(result, indent=2))
    print()

    # Test 2: "qualified" (should be defined)
    print("=" * 70)
    print("TEST 2: What counts as qualified? (DEFINED)")
    print("=" * 70)

    result = await handlers.query_definition({
        "question": "What counts as qualified?"
    }, None)

    print(json.dumps(result, indent=2))
    print()

    # Test 3: "forecast" (should have semantic definition)
    print("=" * 70)
    print("TEST 3: What does forecast mean? (SEMANTIC FACT)")
    print("=" * 70)

    result = await handlers.query_definition({
        "question": "How do you define forecast?"
    }, None)

    print(json.dumps(result, indent=2))
    print()

    # Test 4: Unknown term
    print("=" * 70)
    print("TEST 4: Unknown term")
    print("=" * 70)

    result = await handlers.query_definition({
        "question": "What is a purple unicorn?"
    }, None)

    print(json.dumps(result, indent=2))


if __name__ == '__main__':
    import asyncio
    import json
    asyncio.run(main())
