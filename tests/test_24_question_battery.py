#!/usr/bin/env python3
"""
24-Question Regression Battery

Permanent test covering 5 categories of CRO agent questions.
Ensures no regressions in core routing, synthesis, or handler logic.

Run: PYTHONPATH=. python3 tests/test_24_question_battery.py

Categories:
1. Pipeline & Forecast (6 questions)
2. Win/Loss Analysis (5 questions)
3. Activity & Engagement (5 questions)
4. MEDDICC & Deal Quality (4 questions)
5. Territory & Accounts (4 questions)
"""

import sys
import os
import asyncio
from pathlib import Path

# Setup paths
repo_root = Path(__file__).parent.parent
sys.path.insert(0, str(repo_root))
sys.path.insert(0, str(repo_root / "scripts"))
sys.path.insert(0, str(repo_root / "api"))

from dotenv import load_dotenv
load_dotenv(repo_root / ".env")

from api.router import route_question
from api.db import get_supabase

# 24-question battery organized by category
BATTERY = {
    "Pipeline & Forecast": [
        "What's in our pipeline for this quarter?",
        "Show me pipeline by owner",
        "What's our forecast for Q4?",
        "Which deals moved forward this week?",
        "What deals are at risk?",
        "Show me the pipeline waterfall"
    ],
    "Win/Loss Analysis": [
        "Why are we losing deals?",
        "What are our win rates by segment?",
        "Show me closed won deals this quarter",
        "What's our average deal size?",
        "How long does it take to close deals?"
    ],
    "Activity & Engagement": [
        "Which deals have no recent activity?",
        "Show me call activity by rep",
        "What deals closed without any calls?",
        "Which prospects are most engaged?",
        "Show me email open rates by campaign"
    ],
    "MEDDICC & Deal Quality": [
        "Which deals are missing MEDDICC scores?",
        "Show me deals with low champion scores",
        "What's our average MEDDICC score by stage?",
        "Which deals have identified economic buyers?"
    ],
    "Territory & Accounts": [
        "Show me pipeline by region",
        "Which accounts have multiple opportunities?",
        "What's our coverage in enterprise accounts?",
        "Show me new logo pipeline"
    ]
}


async def test_question(question: str, category: str, q_num: int, total: int):
    """Test a single question through full production routing"""
    sb = get_supabase()

    persona = {
        "name": "Test User",
        "email": "test@test.com",
        "role": "executive"
    }

    print(f"\n[{q_num}/{total}] {category}: {question}")
    print("-" * 80)

    try:
        result = await route_question(
            question,
            user_id="test_battery",
            persona=persona,
            sb=sb,
            history=[]
        )

        handler = result.get('handler_name', 'unknown')
        answer = result.get('answer', '')

        # Extract key metrics from answer
        verdict = "✅ PASS"
        notes = ""

        # Check for error indicators
        if not answer or len(answer) < 50:
            verdict = "⚠️  SHORT"
            notes = "Answer suspiciously short"
        elif "error" in answer.lower() or "cannot" in answer.lower():
            verdict = "⚠️  ERROR"
            notes = "Answer indicates error/limitation"
        elif "I don't" in answer or "I can't" in answer:
            verdict = "⚠️  DECLINE"
            notes = "Agent declined to answer"

        print(f"Handler: {handler}")
        print(f"Answer length: {len(answer)} chars")
        print(f"Verdict: {verdict}")
        if notes:
            print(f"Notes: {notes}")

        # Show first 200 chars of answer
        preview = answer[:200].replace('\n', ' ')
        print(f"Preview: {preview}...")

        return {
            "question": question,
            "category": category,
            "handler": handler,
            "verdict": verdict,
            "notes": notes,
            "answer_length": len(answer)
        }

    except Exception as e:
        print(f"❌ EXCEPTION: {str(e)[:200]}")
        return {
            "question": question,
            "category": category,
            "handler": "exception",
            "verdict": "❌ FAIL",
            "notes": str(e)[:200],
            "answer_length": 0
        }


async def main():
    print("=" * 80)
    print("24-QUESTION REGRESSION BATTERY")
    print("=" * 80)
    print("\nTesting full production routing through 5 categories")
    print("Each question goes through: classification → routing → handler → synthesis")
    print()

    results = []
    total_questions = sum(len(questions) for questions in BATTERY.values())
    q_num = 0

    for category, questions in BATTERY.items():
        print(f"\n{'=' * 80}")
        print(f"CATEGORY: {category}")
        print(f"{'=' * 80}")

        for question in questions:
            q_num += 1
            result = await test_question(question, category, q_num, total_questions)
            results.append(result)

    # Summary
    print(f"\n\n{'=' * 80}")
    print("BATTERY COMPLETE - SUMMARY")
    print(f"{'=' * 80}\n")

    passed = sum(1 for r in results if r["verdict"] == "✅ PASS")
    warned = sum(1 for r in results if "⚠️" in r["verdict"])
    failed = sum(1 for r in results if "❌" in r["verdict"])

    print(f"Total: {total_questions} questions")
    print(f"✅ Passed: {passed}")
    print(f"⚠️  Warnings: {warned}")
    print(f"❌ Failed: {failed}")
    print()

    # By category
    print("Results by category:")
    for category in BATTERY.keys():
        cat_results = [r for r in results if r["category"] == category]
        cat_pass = sum(1 for r in cat_results if r["verdict"] == "✅ PASS")
        print(f"  {category}: {cat_pass}/{len(cat_results)} passed")

    # Show warnings/failures
    issues = [r for r in results if r["verdict"] != "✅ PASS"]
    if issues:
        print(f"\n{'=' * 80}")
        print("ISSUES DETECTED")
        print(f"{'=' * 80}\n")
        for issue in issues:
            print(f"{issue['verdict']} {issue['category']}: {issue['question']}")
            print(f"   Handler: {issue['handler']}")
            if issue['notes']:
                print(f"   Notes: {issue['notes']}")
            print()

    # Exit code
    if failed > 0:
        print("❌ BATTERY FAILED - One or more questions threw exceptions")
        sys.exit(1)
    elif warned > 5:  # Allow some warnings, but not too many
        print("⚠️  BATTERY DEGRADED - Too many warnings (>5)")
        sys.exit(1)
    else:
        print("✅ BATTERY PASSED - All questions routed and answered")
        sys.exit(0)


if __name__ == "__main__":
    asyncio.run(main())
