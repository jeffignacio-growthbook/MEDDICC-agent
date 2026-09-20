#!/usr/bin/env python3
"""
Comprehensive test: all three country variant groups canonicalize during GROUP BY.
"""
import sys
from pathlib import Path
import asyncio

sys.path.insert(0, str(Path(__file__).parent.parent))

from api.tools import aggregate_results


async def test_all_country_variants():
    """Test all three variant groups: Netherlands, Russia, Czech Republic."""
    print("\n" + "=" * 70)
    print("COMPREHENSIVE TEST: All Country Variants in GROUP BY")
    print("=" * 70)

    # Simulate deals with all three variant groups
    deals = [
        # Netherlands variants
        {"company_country": "Netherlands", "deal_value": 100, "company_name": "NL Company 1"},
        {"company_country": "The Netherlands", "deal_value": 200, "company_name": "NL Company 2"},
        {"company_country": "Netherlands", "deal_value": 150, "company_name": "NL Company 3"},

        # Russia variants
        {"company_country": "Russia", "deal_value": 50, "company_name": "RU Company 1"},
        {"company_country": "Russian Federation", "deal_value": 75, "company_name": "RU Company 2"},

        # Czech Republic variants
        {"company_country": "Czech Republic", "deal_value": 120, "company_name": "CZ Company 1"},
        {"company_country": "Czechia", "deal_value": 80, "company_name": "CZ Company 2"},
        {"company_country": "Czech Republic", "deal_value": 100, "company_name": "CZ Company 3"},

        # Non-variant country (should pass through unchanged)
        {"company_country": "Germany", "deal_value": 300, "company_name": "DE Company"},
    ]

    print(f"\nInput: {len(deals)} deals across 7 country values")
    print("  Variants:")
    print("    - Netherlands (2) + The Netherlands (1) = 3 deals")
    print("    - Russia (1) + Russian Federation (1) = 2 deals")
    print("    - Czech Republic (2) + Czechia (1) = 3 deals")
    print("  Non-variant:")
    print("    - Germany (1) = 1 deal")

    result = await aggregate_results(
        data=deals,
        group_by="company_country",
        aggregations={"deal_value": "sum"}
    )

    print(f"\nOutput: {result['group_count']} groups")
    for row in sorted(result['rows'], key=lambda x: x['deal_value_sum'], reverse=True):
        # Count how many input deals contributed to this group
        if row['company_country'] == "Netherlands":
            actual_count = len([d for d in deals if d['company_country'] in ["Netherlands", "The Netherlands"]])
        elif row['company_country'] == "Russia":
            actual_count = len([d for d in deals if d['company_country'] in ["Russia", "Russian Federation"]])
        elif row['company_country'] == "Czech Republic":
            actual_count = len([d for d in deals if d['company_country'] in ["Czech Republic", "Czechia"]])
        else:
            actual_count = len([d for d in deals if d['company_country'] == row['company_country']])
        print(f"  - {row['company_country']}: ${row['deal_value_sum']} ({actual_count} deals)")

    print("\n" + "=" * 70)
    print("VERIFICATION")
    print("=" * 70)

    countries_in_result = {row['company_country'] for row in result['rows']}

    # Check Netherlands canonicalization
    if "Netherlands" in countries_in_result and "The Netherlands" not in countries_in_result:
        nl_sum = next(r['deal_value_sum'] for r in result['rows'] if r['company_country'] == 'Netherlands')
        expected_nl = 100 + 200 + 150  # 450
        print(f"\n✅ Netherlands: Combined correctly (${nl_sum}, expected ${expected_nl})")
        assert nl_sum == expected_nl, f"Netherlands sum mismatch: {nl_sum} != {expected_nl}"
    else:
        print(f"\n❌ Netherlands: NOT combined (found: {countries_in_result})")
        return False

    # Check Russia canonicalization
    if "Russia" in countries_in_result and "Russian Federation" not in countries_in_result:
        ru_sum = next(r['deal_value_sum'] for r in result['rows'] if r['company_country'] == 'Russia')
        expected_ru = 50 + 75  # 125
        print(f"✅ Russia: Combined correctly (${ru_sum}, expected ${expected_ru})")
        assert ru_sum == expected_ru, f"Russia sum mismatch: {ru_sum} != {expected_ru}"
    else:
        print(f"❌ Russia: NOT combined (found: {countries_in_result})")
        return False

    # Check Czech Republic canonicalization
    if "Czech Republic" in countries_in_result and "Czechia" not in countries_in_result:
        cz_sum = next(r['deal_value_sum'] for r in result['rows'] if r['company_country'] == 'Czech Republic')
        expected_cz = 120 + 80 + 100  # 300
        print(f"✅ Czech Republic: Combined correctly (${cz_sum}, expected ${expected_cz})")
        assert cz_sum == expected_cz, f"Czech Republic sum mismatch: {cz_sum} != {expected_cz}"
    else:
        print(f"❌ Czech Republic: NOT combined (found: {countries_in_result})")
        return False

    # Check Germany passes through
    if "Germany" in countries_in_result:
        de_sum = next(r['deal_value_sum'] for r in result['rows'] if r['company_country'] == 'Germany')
        print(f"✅ Germany: Passes through unchanged (${de_sum})")
    else:
        print(f"❌ Germany: Missing from results")
        return False

    # Verify group count
    if result['group_count'] == 4:
        print(f"✅ Group count: {result['group_count']} (correct - 7 input values → 4 canonical groups)")
    else:
        print(f"❌ Group count: {result['group_count']} (expected 4)")
        return False

    return True


async def main():
    result = await test_all_country_variants()

    print("\n" + "=" * 70)
    print("FINAL RESULT")
    print("=" * 70)

    if result:
        print("\n✅ ALL VARIANT GROUPS CANONICALIZE CORRECTLY IN GROUP BY")
        print("\n   Motivating question 'Show me EMEA deals by country' will now:")
        print("   - Combine 'Netherlands' + 'The Netherlands' → single 'Netherlands' row")
        print("   - Combine 'Russia' + 'Russian Federation' → single 'Russia' row")
        print("   - Combine 'Czech Republic' + 'Czechia' → single 'Czech Republic' row")
        print("\n   Both paths now canonicalize:")
        print("   ✓ FILTER path: resolve_dimension_filter() (fixed in 47e0963)")
        print("   ✓ GROUP BY path: aggregate_results() (fixed just now)")
        return 0
    else:
        print("\n❌ CANONICALIZATION FAILED")
        return 1


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
