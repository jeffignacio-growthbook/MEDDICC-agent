#!/usr/bin/env python3
"""
Local test CLI for CRO agent questions.

Runs questions through the SAME production code path used in Railway:
  classification → intent routing → dedicated handler OR dynamic_query_loop
  → tool dispatch → synthesis → verification

Uses real local Supabase/HubSpot credentials for read-only queries.
Prints full production log trace to stdout for debugging.

Usage:
  # Single question
  python scripts/test_question.py "What is the current pipeline?"

  # Multiple questions from file
  python scripts/test_question.py tests/regression_questions.txt

  # With specific user persona
  python scripts/test_question.py "Show my deals" --user-email cary@growthbook.io

Safety:
  READ-ONLY. route_question() does not write to HubSpot or Supabase.
  All handlers query only. The /slack/dm-intake endpoint (writes to
  user_personas) is not exposed by this script.

Environment:
  Requires: SUPABASE_URL, SUPABASE_SERVICE_KEY, ANTHROPIC_API_KEY, HUBSPOT_KEY
  Optional: SUPABASE_DB_URL (for data-dictionary checks)
"""

import sys
import os
import asyncio
import logging
from pathlib import Path

# Setup paths
repo_root = Path(__file__).parent.parent
sys.path.insert(0, str(repo_root))
sys.path.insert(0, str(repo_root / "scripts"))
sys.path.insert(0, str(repo_root / "api"))

from dotenv import load_dotenv
load_dotenv(repo_root / ".env")

# Configure logging to show all production log lines
logging.basicConfig(
    level=logging.INFO,
    format='%(message)s',  # Just the message, no extra formatting
    stream=sys.stdout
)

from api.router import route_question
from api.db import get_supabase, get_user_persona


async def test_question(question: str, user_email: str = None) -> dict:
    """
    Run a question through the full production pipeline.

    Args:
        question: The question to test
        user_email: Optional email for persona lookup (e.g., "cary@growthbook.io")

    Returns:
        dict with keys: answer, handler_name, answered, tool_results
    """
    sb = get_supabase()

    # Look up persona if email provided
    persona = None
    user_id = "test-cli"
    if user_email:
        # Try to find persona by email
        result = sb.table("user_personas").select("*").eq("email", user_email).execute()
        if result.data:
            persona = result.data[0]
            print(f"[TEST] Using persona: {persona.get('name')} ({persona.get('role')})")
        else:
            print(f"[TEST] No persona found for {user_email}, using default")

    # Empty history for test mode (no thread context)
    history = []
    thread_ts = "test-thread"

    print("=" * 80)
    print(f"QUESTION: {question}")
    print("=" * 80)
    print()

    # Run through production code path
    result = await route_question(
        question=question,
        user_id=user_id,
        persona=persona,
        history=history,
        sb=sb,
        thread_ts=thread_ts
    )

    print()
    print("=" * 80)
    print("RESULT")
    print("=" * 80)
    print(f"Handler: {result.get('handler_name', 'unknown')}")
    print(f"Answered: {result.get('answered', False)}")
    print()
    print("ANSWER:")
    print(result.get('answer', '(no answer)'))
    print()

    return result


async def test_questions_from_file(file_path: Path) -> list:
    """
    Run multiple questions from a file, one per line.

    Lines starting with # are treated as comments/section headers.
    Empty lines are skipped.

    Returns:
        list of results (one per question)
    """
    questions = []
    with open(file_path) as f:
        for line in f:
            line = line.strip()
            if line and not line.startswith('#'):
                questions.append(line)

    print(f"[TEST] Running {len(questions)} questions from {file_path}")
    print()

    results = []
    for i, question in enumerate(questions, 1):
        print()
        print(f"{'=' * 80}")
        print(f"QUESTION {i}/{len(questions)}")
        print(f"{'=' * 80}")
        result = await test_question(question)
        results.append(result)

        # Brief summary
        answered = result.get('answered', False)
        status = "✅ ANSWERED" if answered else "❌ FAILED"
        print(f"\n{status} (handler: {result.get('handler_name', 'unknown')})")
        print()

    # Final summary
    print()
    print("=" * 80)
    print("SUMMARY")
    print("=" * 80)
    total = len(results)
    answered = sum(1 for r in results if r.get('answered', False))
    print(f"Total questions: {total}")
    print(f"Answered: {answered}")
    print(f"Failed: {total - answered}")
    print()

    return results


def main():
    """CLI entry point."""
    if len(sys.argv) < 2:
        print(__doc__)
        sys.exit(1)

    input_arg = sys.argv[1]

    # Check for optional --user-email flag
    user_email = None
    if len(sys.argv) >= 4 and sys.argv[2] == "--user-email":
        user_email = sys.argv[3]

    # Check if input is a file or a question string
    input_path = Path(input_arg)
    if input_path.exists() and input_path.is_file():
        # Run questions from file
        asyncio.run(test_questions_from_file(input_path))
    else:
        # Run single question
        asyncio.run(test_question(input_arg, user_email=user_email))


if __name__ == "__main__":
    main()
