#!/usr/bin/env python3
"""
Test q012: At-risk deal count using compute_at_risk_deals()
"""
import sys
from pathlib import Path
from dotenv import load_dotenv

env_path = Path(__file__).parent.parent / ".env"
load_dotenv(env_path)

sys.path.insert(0, str(Path(__file__).parent.parent / "api"))
from db import get_supabase
from handlers import compute_at_risk_deals

def test_q012():
    sb = get_supabase()

    print("=" * 80)
    print("Q012: At-Risk Deals Count")
    print("=" * 80)
    print()

    # Compute at-risk using consolidated logic (pass sb client, it will fetch deals)
    at_risk = compute_at_risk_deals(sb)

    print(f"At-risk deals (via compute_at_risk_deals()): {len(at_risk)}")
    print()

    # Show sample
    print("Sample of at-risk deals:")
    for deal in at_risk[:5]:
        print(f"  {deal.get('company_name')} - Stage: {deal.get('stage')}")
        if deal.get('_at_risk_reason'):
            print(f"    Reason: {deal.get('_at_risk_reason')}")
    print()

    print("VERIFIED VALUE for q012:")
    print(f"  count: {len(at_risk)}")
    print(f"  definition: Stage-aware MEDDICC thresholds from compute_at_risk_deals()")
    print()

    return {"count": len(at_risk)}

if __name__ == "__main__":
    test_q012()
