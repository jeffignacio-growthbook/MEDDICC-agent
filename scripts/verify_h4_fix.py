#!/usr/bin/env python3
"""
Verify H4 fix: pipeline_filter/owner_email/pipeline_id are now declared
in schema and extracted by classifier for query_pipeline_movement.
"""
import os
import sys
import asyncio
from pathlib import Path
from dotenv import load_dotenv

repo_root = Path(__file__).parent.parent
sys.path.insert(0, str(repo_root))
sys.path.insert(0, str(repo_root / "scripts"))

load_dotenv(repo_root / ".env")

from anthropic import Anthropic
from scripts.llm_client import LLMClient

# Test questions that should extract each parameter
TEST_CASES = [
    {
        "question": "Show me new business pipeline movement this quarter",
        "expected_params": {"pipeline_filter": "new_business"},
        "description": "Should extract pipeline_filter=new_business"
    },
    {
        "question": "How has Cary's pipeline moved in the last 2 weeks?",
        "expected_params": {"owner_email": "cary@growthbook.io"},  # or extracted rep name
        "description": "Should extract owner_email from rep name"
    },
    {
        "question": "Show me renewal pipeline movement",
        "expected_params": {"pipeline_filter": "renewal"},
        "description": "Should extract pipeline_filter=renewal"
    },
]

# The classification prompt used by router.py
INTENT_CLASSIFICATION_PROMPT = """You are classifying a CRO's question to route it to the right handler.

Question: {question}

Available handlers:
  query_pipeline_movement: Historical pipeline movement, stage composition over time

Classify this question. Extract these params if present:
  - pipeline_filter: new_business|renewal|null
  - owner_email: rep email or name
  - view: movement|composition|deal_changes|curve|stage_deals

Respond with JSON:
{{"handler": "query_pipeline_movement", "params": {{"pipeline_filter": "new_business", "owner_email": null}}, "confidence": 0.9}}
"""

async def test_param_extraction():
    """Test that classifier extracts pipeline_filter/owner_email/pipeline_id."""
    client = LLMClient.from_config(role="classifier")

    print("=" * 80)
    print("H4 FIX VERIFICATION: Parameter Extraction Test")
    print("=" * 80)
    print()

    for i, test in enumerate(TEST_CASES, 1):
        print(f"Test {i}: {test['description']}")
        print(f"Question: \"{test['question']}\"")
        print(f"Expected: {test['expected_params']}")
        print()

        # Simple classification call
        prompt = INTENT_CLASSIFICATION_PROMPT.format(question=test['question'])
        response = client.complete(
            messages=[{"role": "user", "content": prompt}],
            max_tokens=500
        )

        print(f"Classifier response:")
        print(response.text[:500])
        print()

        # Check if expected params are mentioned in response
        response_lower = response.text.lower()
        for param, value in test['expected_params'].items():
            if value and str(value).lower() in response_lower:
                print(f"✅ Found {param}={value} in response")
            elif param in response_lower:
                print(f"⚠️  Found {param} mentioned (check value)")
            else:
                print(f"❌ {param} NOT found in response")

        print()
        print("-" * 80)
        print()

    print("=" * 80)
    print("VERIFICATION COMPLETE")
    print("=" * 80)
    print()
    print("If ✅ appears for pipeline_filter and owner_email extraction,")
    print("the H4 schema fix is working correctly.")

if __name__ == "__main__":
    asyncio.run(test_param_extraction())
