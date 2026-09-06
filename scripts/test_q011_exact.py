#!/usr/bin/env python3
"""
Test the EXACT q011 calibration phrasing through intent classifier.
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

print("=" * 80)
print("Q011 EXACT CALIBRATION PHRASING TEST")
print("=" * 80)
print(f"\nQuestion: \"{question}\"")
print()

# Build intent prompt
today = today_in_reporting_tz().isoformat()
current_quarter = "Q3_FY2027"

intent_prompt = build_intent_prompt(
    today=today,
    current_quarter=current_quarter,
    history="[]",
    question=question,
    roster_text=""
)

# Call intent classifier
response = client.messages.create(
    model="claude-haiku-4-5-20251001",
    max_tokens=300,
    system="Respond with valid JSON only. No markdown, no backticks, no explanation.",
    messages=[{"role": "user", "content": intent_prompt}]
)

# Extract JSON
intent = _extract_json(response.content[0].text)

if not intent:
    print("❌ PARSE FAILURE - Could not extract JSON")
    print(f"Raw response: {response.content[0].text}")
    sys.exit(1)

handler = intent.get("handler", "unknown")
confidence = intent.get("confidence", 0.0)
params = intent.get("params", {})

print(f"Handler: {handler}")
print(f"Confidence: {confidence:.2f}")
print(f"Params: {params}")
print()

if handler == "query_pipeline":
    print("✅ Routes to query_pipeline (structural fix handler)")

    # Check if unwanted filters in params
    has_stage_filter = "stage_filter" in params
    has_pipeline_filter = "pipeline_filter" in params

    if has_stage_filter or has_pipeline_filter:
        print(f"⚠️  WARNING: Params include filters that should NOT be there:")
        if has_stage_filter:
            print(f"   - stage_filter: {params['stage_filter']}")
        if has_pipeline_filter:
            print(f"   - pipeline_filter: {params['pipeline_filter']}")
        print("   This explains the over-filtering bug - intent classifier added filters!")
    else:
        print("✅ No unwanted filters in params - handler should return all active deals")
else:
    print(f"❌ MISROUTE: Routes to {handler}, not query_pipeline")
    print("   Structural fix bypassed completely")

print()
print("=" * 80)
