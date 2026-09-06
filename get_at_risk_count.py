#!/usr/bin/env python3
"""Get at-risk deals count using the handlers.py definition."""
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent))
sys.path.insert(0, str(Path(__file__).parent / 'api'))

from dotenv import load_dotenv
load_dotenv()

from db import get_supabase
import asyncio

sb = get_supabase()

async def main():
    from handlers import query_deals_at_risk

    # Query at-risk deals with no date filter (all active deals)
    result = await query_deals_at_risk({}, sb)

    print("=" * 100)
    print("AT-RISK DEALS (q012)")
    print("=" * 100)
    print()
    print(f"Total at-risk: {result.get('total_at_risk', 0)}")
    print()

    if result.get('deals_at_risk'):
        print("Sample deals:")
        for deal in result['deals_at_risk'][:5]:
            print(f"  - {deal['company_name']}: ${deal['deal_value']:,.0f}")
            print(f"    Overall score: {deal['overall_score']}")
            print(f"    Risk flags: {', '.join(deal['risk_flags'])}")
            print()

    print()
    print("DEFINITION:")
    print("  Deals where any MEDDICC component required at the current stage")
    print("  is below the threshold band to advance (stage-aware requirements)")
    print()
    print("SOURCE: api/handlers.py query_deals_at_risk() function")

if __name__ == '__main__':
    asyncio.run(main())
