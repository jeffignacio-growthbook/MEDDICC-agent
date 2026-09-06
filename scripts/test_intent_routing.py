#!/usr/bin/env python3
"""
Test intent routing for Wave 4 rephrase questions.

Sends each rephrase through the real intent classifier and reports:
- Handler chosen
- Confidence score
- Whether it matches expected handler

This verifies routing durability with actual measurements, not expectations.
"""

import sys
import json
from pathlib import Path

# Add paths
sys.path.insert(0, str(Path(__file__).parent.parent / "api"))
from router import build_intent_prompt, _extract_json

# Import time utils for today/quarter
sys.path.insert(0, str(Path(__file__).parent))
from sdr_utils import today_in_reporting_tz

# Import anthropic client
import anthropic
import os

def test_intent_routing():
    """Test 6 rephrased questions through real intent classifier."""

    # Initialize client
    api_key = os.getenv("ANTHROPIC_API_KEY")
    if not api_key:
        print("ERROR: ANTHROPIC_API_KEY not set")
        return

    client = anthropic.Anthropic(api_key=api_key)

    # Test questions with expected handlers
    test_cases = [
        # Pipeline questions
        {
            "question": "what is our pipeline",
            "expected_handler": "query_pipeline",
            "category": "pipeline"
        },
        {
            "question": "how much open pipeline do we have",
            "expected_handler": "query_pipeline",
            "category": "pipeline"
        },
        {
            "question": "what's in the funnel this quarter",
            "expected_handler": "query_pipeline",
            "category": "pipeline"
        },
        # Cycle time questions
        {
            "question": "what's our average sales cycle",
            "expected_handler": "query_cycle_time",
            "category": "cycle_time"
        },
        {
            "question": "how long do deals take to close",
            "expected_handler": "query_cycle_time",
            "category": "cycle_time"
        },
        {
            "question": "cycle time by segment",
            "expected_handler": "query_cycle_time",
            "category": "cycle_time"
        },
    ]

    # Get today and current quarter
    today = today_in_reporting_tz().isoformat()
    current_quarter = "Q3_FY2027"  # Would normally compute this

    print("=" * 80)
    print("WAVE 4 INTENT ROUTING TEST - ACTUAL MEASUREMENTS")
    print("=" * 80)
    print()
    print("Testing 6 rephrased questions through real intent classifier...")
    print()

    results = []

    for i, test in enumerate(test_cases, 1):
        question = test["question"]
        expected = test["expected_handler"]
        category = test["category"]

        print(f"[{i}/6] Testing: \"{question}\"")
        print(f"      Expected handler: {expected}")

        # Build intent prompt
        intent_prompt = build_intent_prompt(
            today=today,
            current_quarter=current_quarter,
            history="[]",  # No history for this test
            question=question,
            roster_text=""  # No roster needed
        )

        # Call intent classifier
        try:
            response = client.messages.create(
                model="claude-haiku-4-5-20251001",  # Classifier model (from llm_client.py)
                max_tokens=300,
                system="Respond with valid JSON only. No markdown, no backticks, no explanation.",
                messages=[{"role": "user", "content": intent_prompt}]
            )

            # Extract JSON
            intent = _extract_json(response.content[0].text)

            if not intent:
                print(f"      ❌ PARSE FAILURE - Could not extract JSON")
                results.append({
                    "question": question,
                    "expected": expected,
                    "actual": "parse_failure",
                    "confidence": 0.0,
                    "match": False,
                    "category": category
                })
                print()
                continue

            actual_handler = intent.get("handler", "unknown")
            confidence = intent.get("confidence", 0.0)
            match = (actual_handler == expected)

            # Report result
            status = "✅ MATCH" if match else "❌ MISROUTE"
            print(f"      {status}")
            print(f"      Actual handler: {actual_handler}")
            print(f"      Confidence: {confidence:.2f}")

            if not match:
                print(f"      ⚠️  Routed to {actual_handler} instead of {expected}")

            results.append({
                "question": question,
                "expected": expected,
                "actual": actual_handler,
                "confidence": confidence,
                "match": match,
                "category": category
            })

        except Exception as e:
            print(f"      ❌ ERROR: {e}")
            results.append({
                "question": question,
                "expected": expected,
                "actual": "error",
                "confidence": 0.0,
                "match": False,
                "category": category,
                "error": str(e)
            })

        print()

    # Summary
    print("=" * 80)
    print("RESULTS SUMMARY")
    print("=" * 80)
    print()

    matches = sum(1 for r in results if r["match"])
    total = len(results)

    print(f"Overall: {matches}/{total} questions routed correctly ({matches/total*100:.1f}%)")
    print()

    # By category
    pipeline_results = [r for r in results if r["category"] == "pipeline"]
    pipeline_matches = sum(1 for r in pipeline_results if r["match"])
    print(f"Pipeline questions: {pipeline_matches}/{len(pipeline_results)} correct")

    cycle_results = [r for r in results if r["category"] == "cycle_time"]
    cycle_matches = sum(1 for r in cycle_results if r["match"])
    print(f"Cycle time questions: {cycle_matches}/{len(cycle_results)} correct")
    print()

    # Detailed results
    print("Detailed Results:")
    print()
    for r in results:
        match_symbol = "✅" if r["match"] else "❌"
        print(f"{match_symbol} \"{r['question']}\"")
        print(f"   Expected: {r['expected']}, Actual: {r['actual']}, Confidence: {r.get('confidence', 0):.2f}")
    print()

    # Verdict
    print("=" * 80)
    if matches == total:
        print("✅ ROUTING VERIFIED: All questions route to structural handlers")
        print("   Durability claim confirmed with actual measurements")
        return 0
    else:
        print("⚠️  ROUTING GAPS DETECTED: Some questions misroute")
        print(f"   {total - matches} question(s) did not reach structural handlers")
        print("   Durability partially compromised - prompt improvements needed")
        return 1


if __name__ == "__main__":
    sys.exit(test_intent_routing())
