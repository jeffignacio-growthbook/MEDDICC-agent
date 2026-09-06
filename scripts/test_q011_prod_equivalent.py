#!/usr/bin/env python3
"""
Test q011 with FULL production-equivalent context.

Earlier test used minimal context (no semantic_context, no history, no roster).
This test includes ALL production context to match what Railway sees.
"""
import sys
import os
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))
from api.router import build_intent_prompt, _extract_json

sys.path.insert(0, str(Path(__file__).parent))
from sdr_utils import today_in_reporting_tz

import anthropic

api_key = os.getenv("ANTHROPIC_API_KEY")
if not api_key:
    print("ERROR: ANTHROPIC_API_KEY not set")
    sys.exit(1)

client = anthropic.Anthropic(api_key=api_key)

question = "What is our pipeline this quarter?"
num_runs = 10

print("=" * 80)
print("Q011 PRODUCTION-EQUIVALENT ROUTING TEST")
print("=" * 80)
print(f"\nQuestion: \"{question}\"")
print(f"Runs: {num_runs}")
print(f"\nIncludes: semantic_context (fiscal calendar, pipelines), roster, history")
print()
print("=" * 80)
print()

# Build FULL production-equivalent intent prompt
today = today_in_reporting_tz().isoformat()
current_quarter = "Q3_FY2027"

# Production includes roster_text
roster_text = """Jake (jake@growthbook.io)
Christian (christian@growthbook.io)
Cary (cary@growthbook.io)
James Shannon (james.shannon@growthbook.io)
Scott Keller (scott.keller@growthbook.io)"""

# Production has conversation history (using empty for first question)
history = "[]"

# This will load semantic_context automatically
intent_prompt = build_intent_prompt(
    today=today,
    current_quarter=current_quarter,
    history=history,
    question=question,
    roster_text=roster_text
)

print(f"Intent prompt length: {len(intent_prompt)} chars")
print(f"Includes semantic_context: {'SEMANTIC CONTEXT' in intent_prompt}")
print(f"Includes roster: {bool(roster_text)}")
print()

results = []

for i in range(1, num_runs + 1):
    print(f"[{i}/{num_runs}] ", end="", flush=True)

    try:
        response = client.messages.create(
            model="claude-haiku-4-5-20251001",
            max_tokens=300,
            system="Respond with valid JSON only. No markdown, no backticks, no explanation.",
            messages=[{"role": "user", "content": intent_prompt}]
        )

        intent = _extract_json(response.content[0].text)

        if not intent:
            print("❌ PARSE FAILURE")
            results.append({"run": i, "handler": "parse_failure", "confidence": 0.0})
            continue

        handler = intent.get("handler", "unknown")
        confidence = intent.get("confidence", 0.0)

        if handler == "query_pipeline":
            print(f"✅ query_pipeline (confidence: {confidence:.2f})")
        elif handler == "query_waterfall":
            print(f"❌ query_waterfall (confidence: {confidence:.2f}) — MISROUTE")
        else:
            print(f"⚠️  {handler} (confidence: {confidence:.2f})")

        results.append({
            "run": i,
            "handler": handler,
            "confidence": confidence
        })

    except Exception as e:
        print(f"❌ ERROR: {e}")
        results.append({"run": i, "handler": "error", "confidence": 0.0})

print()
print("=" * 80)
print("RESULTS SUMMARY")
print("=" * 80)
print()

pipeline_count = sum(1 for r in results if r["handler"] == "query_pipeline")
waterfall_count = sum(1 for r in results if r["handler"] == "query_waterfall")
other_count = sum(1 for r in results if r["handler"] not in ["query_pipeline", "query_waterfall"])

print(f"query_pipeline: {pipeline_count}/{num_runs}")
print(f"query_waterfall: {waterfall_count}/{num_runs}")
if other_count > 0:
    print(f"Other handlers: {other_count}/{num_runs}")
print()

pipeline_results = [r for r in results if r["handler"] == "query_pipeline"]
if pipeline_results:
    confidences = [r["confidence"] for r in pipeline_results]
    avg_conf = sum(confidences) / len(confidences)
    min_conf = min(confidences)
    max_conf = max(confidences)
    print(f"query_pipeline confidence: avg={avg_conf:.2f}, min={min_conf:.2f}, max={max_conf:.2f}")
    print()

print("=" * 80)
if pipeline_count == num_runs:
    print("✅ PASS: All runs routed to query_pipeline (production-equivalent)")
    sys.exit(0)
elif waterfall_count > 0:
    print(f"❌ FAIL: {waterfall_count}/{num_runs} misrouted to query_waterfall")
    print("   semantic_context or other production context causing instability")
    sys.exit(1)
else:
    print(f"⚠️  PARTIAL: {pipeline_count}/{num_runs} correct, {other_count} unexpected")
    sys.exit(1)
