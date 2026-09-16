#!/usr/bin/env python3
"""
Test Ryan's original question through dynamic_query_loop to verify
assess_deal_risk is actually selected and called, not just registered.

Question: "please look at all hubspot deals in the 'negotiating' or
'awaiting signature' stages and assess them based on likelihood to
close vs risk"
"""
import os
import sys
import asyncio
import json
from pathlib import Path
from dotenv import load_dotenv

# Load .env
load_dotenv(Path(__file__).parent.parent / ".env")

# Setup paths
repo_root = Path(__file__).parent.parent
sys.path.insert(0, str(repo_root))
sys.path.insert(0, str(repo_root / "scripts"))

from scripts.supabase_client import create_resilient_supabase_client
from scripts.llm_client import LLMClient

# Initialize clients
sb = create_resilient_supabase_client(
    os.environ["SUPABASE_URL"],
    os.environ["SUPABASE_SERVICE_KEY"]
)

# Use LLMClient wrapper (router.py expects client.complete() method)
client = LLMClient.from_config(role="generator")

# Import router after path setup
from api.router import dynamic_query_loop

async def test_ryan_question():
    """Test if dynamic_query_loop selects assess_deal_risk for Ryan's question."""

    question = (
        "please look at all hubspot deals in the 'negotiating' or "
        "'awaiting signature' stages and assess them based on likelihood "
        "to close vs risk"
    )

    print("=" * 80)
    print("TESTING: Ryan's Original Question Through dynamic_query_loop")
    print("=" * 80)
    print()
    print(f"Question: {question}")
    print()
    print("Calling dynamic_query_loop...")
    print("-" * 80)

    # Call dynamic_query_loop with properly initialized params
    history = []

    # Initialize params with time_window (required by dynamic_query_loop_core)
    from api.time_resolver import resolve_time_window
    time_window = resolve_time_window({"period": "current_quarter"})

    params = {
        "time_window": time_window
    }

    try:
        result = await dynamic_query_loop(
            question=question,
            history=history,
            params=params,
            sb=sb,
            client=client
        )

        print()
        print("=" * 80)
        print("RESULT ANALYSIS")
        print("=" * 80)
        print()

        # Check if assess_deal_risk was called
        tool_results = result.get("tool_results", {})

        # Look for assess_deal_risk in the result structure
        assessed_deals = tool_results.get("assessed_deals")
        summary = tool_results.get("summary")

        if assessed_deals is not None:
            print("✅ assess_deal_risk WAS CALLED")
            print()
            print(f"Deals assessed: {len(assessed_deals)}")
            if summary:
                print(f"Summary:")
                print(f"  High risk:          {summary.get('high_risk', 0)}")
                print(f"  Moderate risk:      {summary.get('moderate_risk', 0)}")
                print(f"  Low risk:           {summary.get('low_risk', 0)}")
                print(f"  Insufficient data:  {summary.get('insufficient_data', 0)}")
            print()

            # Show a sample deal to verify MEDDICC deferral
            if assessed_deals:
                print("Sample deal (verify MEDDICC deferral):")
                sample = assessed_deals[0]
                print(f"  Company: {sample.get('company_name')}")
                print(f"  Label: {sample.get('overall_label')}")
                print(f"  MEDDICC status: {sample.get('meddicc_status')}")
                print(f"  Risk factors:")
                for rf in sample.get('risk_factors', []):
                    print(f"    - {rf}")

            return True
        else:
            print("❌ assess_deal_risk WAS NOT CALLED")
            print()
            print("Tool results structure:")
            print(json.dumps(tool_results, indent=2)[:500])
            print()
            print("This indicates the classifier did NOT route to assess_deal_risk.")
            print("GAP: Registration alone doesn't solve routing - classifier doesn't")
            print("recognize this phrasing as an assess_deal_risk query.")

            return False

    except Exception as e:
        print()
        print(f"❌ ERROR: {e}")
        import traceback
        traceback.print_exc()
        return False

if __name__ == "__main__":
    result = asyncio.run(test_ryan_question())
    sys.exit(0 if result else 1)
