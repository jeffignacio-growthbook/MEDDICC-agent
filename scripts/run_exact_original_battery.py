#!/usr/bin/env python3
"""
Re-run EXACT original 24-question battery verbatim.
Focus on the 3 originally-broken questions with exact wording.
"""
import sys
import asyncio
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent / "api"))
sys.path.insert(0, str(Path(__file__).parent))

from dotenv import load_dotenv
load_dotenv(Path(__file__).parent.parent / ".env")

from test_question import test_question

# EXACT original questions from first battery
ORIGINAL_QUESTIONS = [
    # Q1 - Forecast Trust (BROKE originally)
    "How much should I trust this quarter's forecast number?",

    # Q2-Q3 - Forecast Trust variants
    "What's the calibration data for current week?",
    "Is the commit number reliable at this stage of quarter?",

    # Q4 - Rep Coaching (BROKE originally with array filter bug)
    "How did Christian do on his most recent call with a customer?",

    # Q5 - Pipeline Coverage
    "How much pipeline coverage do we have against quota?",

    # Q6 - Country Dimension (BROKE originally - data_dictionary bug)
    "Show me our EMEA pipeline broken down by country",

    # Q7 - Forecast Trust duplicate (BROKE originally - same bug as Q1)
    "How much should I trust this quarter's forecast number?",

    # Q8-Q10 - Deal Risk edge cases
    "Show me deals at risk this quarter",
    "Which deals have missing MEDDICC components?",
    "What late-stage deals need attention?",

    # Q11-Q13 - Rep Coaching
    "What are the team-wide coaching priorities?",
    "Which reps need discovery call coaching?",
    "Show me objection handling gaps",

    # Q14-Q15 - Edge cases (insufficient data)
    "What's the talk time ratio for non-existent rep?",
    "Show me East region coaching gaps",

    # Q16-Q19 - Loss Concentration
    "Where are we losing deals by segment?",
    "What's our loss rate by rep?",
    "Show me loss patterns in EMEA",
    "Which stage loses most deals?",

    # Q20 - Country dimension variant
    "What's the breakdown of losses by country?",

    # Q21-Q24 - Edge cases and simple filters
    "How many deals do we have with Notion?",
    "What was our Q1 2020 win rate?",
    "Show me pipeline for fake segment XYZ",
    "Break down forecast trust by individual rep",
]


async def main():
    """Run all 24 questions and capture full results."""
    print("\n" + "=" * 80)
    print("EXACT ORIGINAL 24-QUESTION BATTERY - VERBATIM RE-RUN")
    print("=" * 80)
    print("\nRunning EXACT original questions to verify bug fixes.\n")

    results = []

    for i, question in enumerate(ORIGINAL_QUESTIONS, 1):
        qid = f"Q{i}"
        print(f"\n{'=' * 80}")
        print(f"[{qid}] {question}")
        print("=" * 80)

        try:
            result = await test_question(question)

            handler = result.get("handler", "unknown")
            answer = result.get("answer", "")
            error = result.get("error")

            # Store full result
            results.append({
                "qid": qid,
                "question": question,
                "handler": handler,
                "answer": answer,
                "error": error,
                "verdict": "ERROR" if error else "SUCCESS"
            })

            # Show result
            if error:
                print(f"\n❌ ERROR: {error}")
            else:
                print(f"\n✅ {handler}")
                # For the 3 originally-broken questions, show FULL answer
                if qid in ["Q1", "Q4", "Q6", "Q7"]:
                    print(f"\n{'─' * 80}")
                    print("FULL ANSWER (verbatim):")
                    print("─" * 80)
                    print(answer)
                    print("─" * 80)
                else:
                    # For others, just preview
                    preview = answer[:150] + "..." if len(answer) > 150 else answer
                    print(f"Preview: {preview}")

        except Exception as e:
            print(f"\n❌ EXCEPTION: {e}")
            results.append({
                "qid": qid,
                "question": question,
                "handler": "exception",
                "answer": "",
                "error": str(e),
                "verdict": "EXCEPTION"
            })

    # Summary
    print("\n" + "=" * 80)
    print("SUMMARY")
    print("=" * 80)

    success_count = sum(1 for r in results if r["verdict"] == "SUCCESS")
    error_count = sum(1 for r in results if r["verdict"] in ["ERROR", "EXCEPTION"])

    print(f"\n✅ SUCCESS: {success_count}/24 questions")
    print(f"❌ ERRORS: {error_count}/24 questions")

    # Check the 3 critical bugs
    print(f"\n🔍 CRITICAL BUG STATUS:")
    critical_questions = {
        "Q1": "Forecast trust (column name bug)",
        "Q4": "Rep coaching (array filter bug)",
        "Q6": "Country breakdown (data_dictionary bug)",
        "Q7": "Forecast trust duplicate (same column bug)"
    }

    for qid, description in critical_questions.items():
        r = next((x for x in results if x["qid"] == qid), None)
        if r:
            status = "✅ FIXED" if r["verdict"] == "SUCCESS" else f"❌ STILL BROKEN ({r['verdict']})"
            print(f"  {qid} ({description}): {status}")

    return results


if __name__ == "__main__":
    asyncio.run(main())
