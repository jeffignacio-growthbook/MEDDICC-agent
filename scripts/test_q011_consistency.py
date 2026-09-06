#!/usr/bin/env python3
"""
Test q011 routing consistency after query_waterfall description fix.

Runs "What is our pipeline this quarter?" 10 times through intent classifier
to verify consistent routing to query_pipeline (not query_waterfall).

Pass criteria: 10/10 route to query_pipeline
Fail criteria: Even 1 misroute to query_waterfall indicates insufficient fix
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

# EXACT calibration question
question = "What is our pipeline this quarter?"
num_runs = 10

print("=" * 80)
print("Q011 ROUTING CONSISTENCY TEST")
print("=" * 80)
print(f"\nQuestion: \"{question}\"")
print(f"Runs: {num_runs}")
print(f"\nPass criteria: 10/10 route to query_pipeline")
print(f"Fail criteria: Even 1 misroute to query_waterfall")
print()
print("=" * 80)
print()

# Build intent prompt once
today = today_in_reporting_tz().isoformat()
current_quarter = "Q3_FY2027"

intent_prompt = build_intent_prompt(
    today=today,
    current_quarter=current_quarter,
    history="[]",
    question=question,
    roster_text=""
)

results = []

for i in range(1, num_runs + 1):
    print(f"[{i}/{num_runs}] ", end="", flush=True)

    # Call intent classifier
    try:
        response = client.messages.create(
            model="claude-haiku-4-5-20251001",
            max_tokens=300,
            system="Respond with valid JSON only. No markdown, no backticks, no explanation.",
            messages=[{"role": "user", "content": intent_prompt}]
        )

        # Extract JSON
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
            print(f"⚠️  {handler} (confidence: {confidence:.2f}) — UNEXPECTED")

        results.append({
            "run": i,
            "handler": handler,
            "confidence": confidence
        })

    except Exception as e:
        print(f"❌ ERROR: {e}")
        results.append({"run": i, "handler": "error", "confidence": 0.0, "error": str(e)})

print()
print("=" * 80)
print("RESULTS SUMMARY")
print("=" * 80)
print()

# Count results
pipeline_count = sum(1 for r in results if r["handler"] == "query_pipeline")
waterfall_count = sum(1 for r in results if r["handler"] == "query_waterfall")
other_count = sum(1 for r in results if r["handler"] not in ["query_pipeline", "query_waterfall"])

print(f"query_pipeline: {pipeline_count}/{num_runs}")
print(f"query_waterfall: {waterfall_count}/{num_runs}")
if other_count > 0:
    print(f"Other handlers: {other_count}/{num_runs}")
print()

# Confidence stats for query_pipeline routes
pipeline_results = [r for r in results if r["handler"] == "query_pipeline"]
if pipeline_results:
    confidences = [r["confidence"] for r in pipeline_results]
    avg_conf = sum(confidences) / len(confidences)
    min_conf = min(confidences)
    max_conf = max(confidences)
    print(f"query_pipeline confidence: avg={avg_conf:.2f}, min={min_conf:.2f}, max={max_conf:.2f}")
    print()

# Verdict
print("=" * 80)
if pipeline_count == num_runs:
    print("✅ PASS: All runs routed to query_pipeline consistently")
    print("   query_waterfall description fix is sufficient")
    sys.exit(0)
elif waterfall_count > 0:
    print(f"❌ FAIL: {waterfall_count}/{num_runs} runs misrouted to query_waterfall")
    print("   Description fix is INSUFFICIENT - structured gate (item 2) is MANDATORY")
    sys.exit(1)
else:
    print(f"⚠️  PARTIAL: {pipeline_count}/{num_runs} routed correctly, but {other_count} unexpected routes")
    print("   Review other handlers and consider structured gate")
    sys.exit(1)
