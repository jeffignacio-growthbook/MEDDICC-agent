#!/usr/bin/env python3
"""
Test whether aggregate_results canonicalizes country variants during GROUP BY.

Tests the GROUP-BY path (not the filter path already proven).
"""
import sys
from pathlib import Path
import asyncio

sys.path.insert(0, str(Path(__file__).parent.parent))

from api.tools import aggregate_results


async def test_country_groupby_without_canonicalization():
    """Test current behavior: variants should show as separate rows."""
    print("\n" + "=" * 70)
    print("TEST: Country GROUP BY Canonicalization (Current Behavior)")
    print("=" * 70)

    # Simulate deals data with Netherlands variants
    deals = [
        {"company_country": "Netherlands", "deal_value": 100, "company_name": "Company A"},
        {"company_country": "Netherlands", "deal_value": 150, "company_name": "Company B"},
        {"company_country": "The Netherlands", "deal_value": 200, "company_name": "Company C"},
        {"company_country": "The Netherlands", "deal_value": 250, "company_name": "Company D"},
        {"company_country": "Germany", "deal_value": 300, "company_name": "Company E"},
    ]

    print(f"\nInput data: {len(deals)} deals")
    for deal in deals:
        print(f"  - {deal['company_name']}: {deal['company_country']}, ${deal['deal_value']}")

    # Group by company_country
    print("\nGrouping by company_country...")
    result = await aggregate_results(
        data=deals,
        group_by="company_country",
        aggregations={"deal_value": "sum"}
    )

    print(f"\nResult: {result['group_count']} groups")
    for row in result['rows']:
        print(f"  - {row['company_country']}: ${row['deal_value_sum']}")

    # Check if variants are separate
    countries_in_result = [row['company_country'] for row in result['rows']]

    print("\n" + "=" * 70)
    print("ANALYSIS")
    print("=" * 70)

    if "Netherlands" in countries_in_result and "The Netherlands" in countries_in_result:
        print("\n❌ GAP CONFIRMED:")
        print("   'Netherlands' and 'The Netherlands' appear as SEPARATE rows")
        print("   Canonicalization does NOT apply during GROUP BY")
        print("\n   Expected (with canonicalization):")
        print("     - Netherlands: $700 (250+200+150+100 combined)")
        print("\n   Actual (without canonicalization):")
        nl_sum = next(r['deal_value_sum'] for r in result['rows'] if r['company_country'] == 'Netherlands')
        the_nl_sum = next(r['deal_value_sum'] for r in result['rows'] if r['company_country'] == 'The Netherlands')
        print(f"     - Netherlands: ${nl_sum}")
        print(f"     - The Netherlands: ${the_nl_sum}")
        print(f"     - Total: ${nl_sum + the_nl_sum} (but split across 2 rows)")

        print("\n   Impact on motivating question:")
        print("   'Show me EMEA deals by country' would show:")
        print("     - Netherlands: 2 deals, $250")
        print("     - The Netherlands: 2 deals, $450")
        print("   Instead of:")
        print("     - Netherlands: 4 deals, $700 (combined)")

        return False  # Gap exists
    elif "Netherlands" in countries_in_result:
        print("\n✅ CANONICALIZATION WORKING:")
        print("   Both variants combined into single 'Netherlands' row")
        nl_sum = next(r['deal_value_sum'] for r in result['rows'] if r['company_country'] == 'Netherlands')
        print(f"   - Netherlands: ${nl_sum}")
        return True  # No gap
    else:
        print("\n⚠️  UNEXPECTED RESULT:")
        print(f"   Countries in result: {countries_in_result}")
        return None


async def main():
    result = await test_country_groupby_without_canonicalization()

    print("\n" + "=" * 70)
    print("CONCLUSION")
    print("=" * 70)

    if result is False:
        print("\n❌ REAL GAP IDENTIFIED:")
        print("   Country dimension resolver (FILTER path) ✓ Fixed")
        print("   Country aggregation canonicalization (GROUP BY path) ✗ Missing")
        print("\n   The motivating question 'Show me EMEA deals by country' will")
        print("   show Netherlands variants as separate rows in the breakdown.")
        print("\n   Fix needed: Apply canonicalization in aggregate_results() or")
        print("   wherever grouping happens before GROUP BY executes.")
        return 1
    elif result is True:
        print("\n✅ NO GAP:")
        print("   Canonicalization applies during GROUP BY.")
        return 0
    else:
        print("\n⚠️  TEST INCONCLUSIVE")
        return 1


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
