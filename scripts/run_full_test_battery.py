#!/usr/bin/env python3
"""
Re-run full 24-question test battery after bug fixes.
Confirms fixes work and nothing regressed.
"""
import sys
import asyncio
import json
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent / "api"))
sys.path.insert(0, str(Path(__file__).parent))

from dotenv import load_dotenv
load_dotenv(Path(__file__).parent.parent / ".env")

from test_question import test_question

# Define all 24 questions across 5 categories
TEST_QUESTIONS = {
    # Category 1: Forecast Trust (CRO Priority #1)
    "Q1": "How trustworthy is this quarter's forecast?",
    "Q2": "What's the historical calibration for week 8 of the quarter?",
    "Q3": "Should I trust the commit number we have today?",

    # Category 2: Pipeline Coverage (CRO Priority #2)
    "Q4": "How much pipeline coverage do we have against goal?",
    "Q5": "What's our weighted pipeline against the stretch target?",
    "Q6": "Are we short of our Q4 target and by how much?",

    # Category 3: Deal Risk Assessment (CRO Priority #3)
    "Q7": "Which deals in my forecast are most at risk?",
    "Q8": "Show me deals at risk with missing champion scores",  # Edge case: specific MEDDICC component
    "Q9": "What deals have low economic buyer engagement?",  # Edge case: specific criterion
    "Q10": "Which late-stage deals have the worst MEDDICC coverage?",  # Edge case: stage + MEDDICC combo

    # Category 4: Rep Coaching (CRO Priority #4)
    "Q11": "Show me rep coaching opportunities for Sarah Johnson",  # Rep by name - BROKE in original
    "Q12": "What are the top coaching gaps across the team?",
    "Q13": "Which reps need help with discovery calls?",
    "Q14": "How is Mike doing on talk time ratio?",  # Edge case: Fireflies source_not_supported
    "Q15": "Show me coaching gaps for the East region",  # Edge case: requires region dimension

    # Category 5: Loss Concentration (CRO Priority #5)
    "Q16": "Where are we losing deals by segment?",
    "Q17": "What's our loss rate by rep?",
    "Q18": "Show me loss concentration in EMEA",  # Edge case: region filtering
    "Q19": "Which stage are we losing most deals at?",
    "Q20": "What's the breakdown of losses by country?",  # BROKE in original - data_dictionary bug

    # Category 6: Edge Cases & Curveballs
    "Q21": "How many deals do we have with ACME Corp?",  # Simple filter, not a primitive
    "Q22": "What was our win rate in Q1 2020?",  # Edge case: insufficient historical data
    "Q23": "How much pipeline do we have for non-existent segment XYZ?",  # Edge case: false premise
    "Q24": "Show me forecast trust broken down by sales rep",  # Edge case: dimension not supported by primitive
}

# Original results for comparison (from the first test run)
ORIGINAL_RESULTS = {
    "Q1": {"verdict": "BROKE", "handler": "forecast_trust", "error": "column deals.amount does not exist"},
    "Q7": {"verdict": "BROKE", "handler": "deal_risk_assessor", "error": "column deals.amount does not exist"},
    "Q11": {"verdict": "BROKE", "handler": "rep_coaching", "error": "operator does not exist: text[] ~~* unknown"},
    "Q20": {"verdict": "BROKE", "handler": "unanswerable", "error": "routed to unanswerable despite having country dimension"},
    # Others were CORRECT-AND-HONEST or SKIPPED
}


async def run_test_battery():
    """Run all 24 questions and report results."""
    results = {}

    print("\n" + "=" * 80)
    print("FULL 24-QUESTION TEST BATTERY - POST-FIX RUN")
    print("=" * 80)
    print("\nTesting all 5 CRO primitives + edge cases against REAL production agent.")
    print("Confirming bugs are fixed and nothing regressed.\n")

    for qid in sorted(TEST_QUESTIONS.keys()):
        question = TEST_QUESTIONS[qid]
        print(f"\n[{qid}] {question}")
        print("-" * 80)

        try:
            result = await test_question(question)

            # Extract key fields
            handler = result.get("handler", "unknown")
            answer = result.get("answer", "")
            error = result.get("error")

            # Determine verdict
            if error:
                verdict = "ERROR"
                print(f"❌ ERROR: {error}")
            elif "insufficient_data" in str(result).lower() or "source_not_supported" in str(result).lower():
                verdict = "INSUFFICIENT_DATA"
                print(f"⚠️  {handler} → Insufficient data (expected for some edge cases)")
            elif "unanswerable" in handler.lower():
                verdict = "UNANSWERABLE"
                print(f"⚠️  Routed to unanswerable")
            else:
                verdict = "SUCCESS"
                print(f"✅ {handler} → Answer received")
                # Show first 150 chars of answer
                preview = answer[:150] + "..." if len(answer) > 150 else answer
                print(f"   Preview: {preview}")

            results[qid] = {
                "handler": handler,
                "verdict": verdict,
                "answer_preview": answer[:200] if answer else "",
                "error": error
            }

            # Compare to original if this was a broken question
            if qid in ORIGINAL_RESULTS:
                original = ORIGINAL_RESULTS[qid]
                if original["verdict"] == "BROKE" and verdict == "SUCCESS":
                    print(f"   🎉 FIX CONFIRMED: Was broken, now working!")
                elif original["verdict"] != "BROKE" and verdict != "SUCCESS":
                    print(f"   ⚠️  REGRESSION: Was {original['verdict']}, now {verdict}")

        except Exception as e:
            print(f"❌ EXCEPTION: {e}")
            results[qid] = {
                "handler": "exception",
                "verdict": "EXCEPTION",
                "error": str(e)
            }

    return results


async def analyze_results(results):
    """Analyze results and report summary."""
    print("\n" + "=" * 80)
    print("SUMMARY ANALYSIS")
    print("=" * 80)

    # Count by verdict
    by_verdict = {}
    for qid, result in results.items():
        verdict = result["verdict"]
        by_verdict[verdict] = by_verdict.get(verdict, 0) + 1

    print(f"\nResults by verdict:")
    for verdict, count in sorted(by_verdict.items()):
        print(f"  {verdict}: {count} questions")

    # Check the 3 originally-broken questions
    print(f"\n✅ ORIGINALLY BROKEN QUESTIONS (should now succeed):")
    broken_questions = ["Q1", "Q7", "Q11", "Q20"]
    for qid in broken_questions:
        if qid in results:
            result = results[qid]
            status = "✅ FIXED" if result["verdict"] == "SUCCESS" else f"❌ STILL BROKEN ({result['verdict']})"
            print(f"  {qid}: {status}")

    # Check for regressions (questions that were correct before)
    print(f"\n✅ REGRESSION CHECK (questions that should still work):")
    regression_count = 0
    for qid, result in results.items():
        if qid not in broken_questions and result["verdict"] in ["ERROR", "EXCEPTION"]:
            print(f"  ⚠️  {qid}: {result['verdict']} - POSSIBLE REGRESSION")
            regression_count += 1

    if regression_count == 0:
        print(f"  ✅ No regressions detected")

    # Report on edge cases (Q8-10, Q14-15, Q17-18, Q22-24)
    print(f"\n✅ EDGE CASE HANDLING (previously skipped):")
    edge_cases = ["Q8", "Q9", "Q10", "Q14", "Q15", "Q17", "Q18", "Q22", "Q23", "Q24"]
    for qid in edge_cases:
        if qid in results:
            result = results[qid]
            print(f"  {qid}: {result['verdict']} via {result['handler']}")


if __name__ == "__main__":
    print("Starting full test battery...")
    results = asyncio.run(run_test_battery())
    asyncio.run(analyze_results(results))

    # Write results to file for reference
    output_file = Path(__file__).parent.parent / "output" / "test_battery_results.json"
    output_file.parent.mkdir(exist_ok=True)
    with open(output_file, "w") as f:
        json.dump(results, f, indent=2)

    print(f"\n✅ Full results written to: {output_file}")
