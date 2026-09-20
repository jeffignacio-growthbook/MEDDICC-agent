#!/usr/bin/env python3
"""
Audit country-as-dimension for Marketing/RevOps-lead Priority #2.

Checks:
1. Country data existence and quality in deals table
2. Need for canonicalization (variants, duplicates)
3. Relationship to region dimension
4. Historical usage in query logs
5. Gap analysis (dimension resolver vs full primitive)
"""
import os
import sys
from pathlib import Path
from collections import Counter

# Load env
from dotenv import load_dotenv
load_dotenv()

sys.path.insert(0, str(Path(__file__).parent))

from supabase_client import create_resilient_supabase_client, select_all

def audit_country_data_quality():
    """Task 1: Check country data existence and quality."""
    print("=" * 70)
    print("TASK 1: Country Data Existence and Quality")
    print("=" * 70)

    sb = create_resilient_supabase_client(
        os.environ["SUPABASE_URL"],
        os.environ["SUPABASE_KEY"]
    )

    # Check schema
    print("\n[1a] Checking deals table schema for country fields")
    result = sb.table("deals").select("*").limit(1).execute()
    if result.data:
        columns = result.data[0].keys()
        country_cols = [col for col in columns if 'country' in col.lower()]
        print(f"  → Country-related columns found: {country_cols}")
    else:
        print("  → No data in deals table")
        return

    # Get all country values
    print("\n[1b] Fetching all deals with country data")
    deals = select_all(sb, "deals", columns="company_country,deal_id,stage,company_name")
    print(f"  → Total deals: {len(deals)}")

    # Count by country
    country_counts = Counter(d.get('company_country') for d in deals)
    sorted_countries = sorted(country_counts.items(), key=lambda x: x[1], reverse=True)

    null_count = country_counts[None]
    print(f"\n[1c] Null/blank analysis")
    print(f"  → Null/blank countries: {null_count} ({null_count/len(deals)*100:.1f}%)")
    print(f"  → Non-null deals: {len(deals) - null_count} ({(len(deals) - null_count)/len(deals)*100:.1f}%)")
    print(f"  → Distinct non-null values: {len([k for k in country_counts.keys() if k is not None])}")

    print(f"\n[1d] Top 15 country values by frequency")
    for country, count in sorted_countries[:15]:
        if country is not None:
            print(f"  → '{country}': {count} deals ({count/len(deals)*100:.1f}%)")

    print(f"\n[1e] Complete list of all non-null country values")
    non_null_countries = sorted([c for c in country_counts.keys() if c is not None])
    for country in non_null_countries:
        count = country_counts[country]
        print(f"  → '{country}': {count} deals ({count/len(deals)*100:.1f}%)")

    return deals, country_counts, non_null_countries


def audit_canonicalization_need(non_null_countries, country_counts):
    """Task 2: Check if canonicalization is needed."""
    print("\n" + "=" * 70)
    print("TASK 2: Canonicalization Need Assessment")
    print("=" * 70)

    # Check for case variants
    print("\n[2a] Checking for case variants")
    lowercased = {}
    for country in non_null_countries:
        lower = country.lower()
        if lower not in lowercased:
            lowercased[lower] = []
        lowercased[lower].append(country)

    case_variants = {k: v for k, v in lowercased.items() if len(v) > 1}
    if case_variants:
        print(f"  → Found {len(case_variants)} case variant groups:")
        for lower, versions in case_variants.items():
            counts = [country_counts[v] for v in versions]
            print(f"    • {lower}: {versions} (counts: {counts})")
    else:
        print("  → No case variants found (data is case-consistent)")

    # Check for common abbreviation patterns
    print("\n[2b] Checking for common abbreviation patterns")
    abbrev_patterns = {
        'USA': ['US', 'USA', 'United States', 'United States of America', 'U.S.', 'U.S.A.'],
        'UK': ['UK', 'United Kingdom', 'GB', 'Great Britain', 'U.K.'],
        'UAE': ['UAE', 'United Arab Emirates', 'U.A.E.']
    }

    found_variants = False
    for standard, variants in abbrev_patterns.items():
        found = [c for c in non_null_countries if c in variants]
        if len(found) > 1:
            found_variants = True
            counts = [country_counts[c] for c in found]
            print(f"  → {standard}: found {found} (counts: {counts})")
        elif len(found) == 1:
            print(f"  → {standard}: only '{found[0]}' present ({country_counts[found[0]]} deals)")

    if not found_variants:
        print("  → No abbreviation variants found")

    # Check for semantic variants (same country, different names)
    print("\n[2c] Checking for semantic variants")
    semantic_variants = {
        'Netherlands': ['Netherlands', 'The Netherlands'],
        'Russia': ['Russia', 'Russian Federation'],
        'Czech Republic': ['Czech Republic', 'Czechia'],
        'Korea': ['South Korea', 'Republic of Korea', 'Korea'],
    }

    found_semantic = False
    for standard, variants in semantic_variants.items():
        found = [c for c in non_null_countries if c in variants]
        if len(found) > 1:
            found_semantic = True
            counts = [country_counts[c] for c in found]
            total = sum(counts)
            print(f"  → {standard}: found {found}")
            print(f"    Counts: {counts}, total: {total} deals")
        elif len(found) == 1:
            print(f"  → {standard}: only '{found[0]}' present ({country_counts[found[0]]} deals)")

    # Check for whitespace/punctuation issues
    print("\n[2d] Checking for whitespace/punctuation issues")
    ws_issues = []
    for country in non_null_countries:
        if country != country.strip():
            ws_issues.append(f"'{country}' has leading/trailing whitespace")
        if '  ' in country:
            ws_issues.append(f"'{country}' has double spaces")

    if ws_issues:
        print(f"  → Found {len(ws_issues)} whitespace issues:")
        for issue in ws_issues:
            print(f"    • {issue}")
    else:
        print("  → No whitespace/punctuation issues found")

    # Recommendation
    print("\n[2e] Canonicalization recommendation")
    if case_variants or found_variants or found_semantic or ws_issues:
        print("  → CANONICALIZATION NEEDED")
        print("    Reasons:")
        if case_variants:
            print(f"    • Case variants present ({len(case_variants)} groups)")
        if found_variants:
            print("    • Abbreviation variants present")
        if found_semantic:
            print("    • Semantic variants present (same country, different names)")
        if ws_issues:
            print(f"    • Whitespace issues present ({len(ws_issues)} cases)")
        print("\n    Recommended approach:")
        print("    • Create country canonicalization mapping (config file or function)")
        print("    • Use ilike/fuzzy matching in resolve_dimension_filter()")
        print("    • Similar to existing owner_email canonicalization")
    else:
        print("  → CANONICALIZATION NOT NEEDED")
        print("    Data is already clean - exact-match filtering sufficient")


def audit_region_relationship(deals):
    """Task 3: Check relationship to region dimension."""
    print("\n" + "=" * 70)
    print("TASK 3: Relationship to Region Dimension")
    print("=" * 70)

    # Check if region column exists
    print("\n[3a] Checking for region field in deals")
    if deals and len(deals) > 0:
        sample = deals[0]
        region_cols = [col for col in sample.keys() if 'region' in col.lower()]
        print(f"  → Region-related columns: {region_cols}")

        if region_cols:
            region_col = region_cols[0]
            print(f"\n[3b] Analyzing region distribution")
            region_counts = Counter(d.get(region_col) for d in deals)
            print(f"  → Distinct regions: {len([r for r in region_counts.keys() if r is not None])}")
            for region, count in sorted(region_counts.items(), key=lambda x: x[1], reverse=True)[:10]:
                if region is not None:
                    print(f"    • '{region}': {count} deals")

            # Check country-region overlap
            print(f"\n[3c] Checking country-region composition")
            emea_deals = [d for d in deals if d.get(region_col) == 'EMEA']
            if emea_deals:
                emea_countries = Counter(d.get('company_country') for d in emea_deals)
                print(f"  → EMEA deals: {len(emea_deals)}")
                print(f"  → Distinct countries in EMEA: {len([c for c in emea_countries.keys() if c is not None])}")
                print("  → Top countries in EMEA:")
                for country, count in sorted(emea_countries.items(), key=lambda x: x[1], reverse=True)[:10]:
                    if country is not None:
                        print(f"    • '{country}': {count} deals")
            else:
                print("  → No EMEA deals found")
        else:
            print("  → No region column found in deals table")
    else:
        print("  → No deals data available")

    print("\n[3d] Composition recommendation")
    print("  → Check resolve_dimension_filter() implementation for region")
    print("  → Determine if country should be:")
    print("    • Independent dimension (can filter by country alone)")
    print("    • Composed with region (filter by region AND country)")
    print("    • Both (support 'EMEA' and 'EMEA + France' separately)")


def audit_historical_usage():
    """Task 4: Check historical usage in query logs."""
    print("\n" + "=" * 70)
    print("TASK 4: Historical Usage in Query Logs")
    print("=" * 70)

    sb = create_resilient_supabase_client(
        os.environ["SUPABASE_URL"],
        os.environ["SUPABASE_KEY"]
    )

    # Check query_cost_log
    print("\n[4a] Checking query_cost_log for country-related questions")

    # First check what columns exist
    sample = sb.table("query_cost_log").select("*").limit(1).execute()
    if sample.data:
        available_cols = list(sample.data[0].keys())
        # Select only columns that exist
        cols_to_select = []
        for col in ['question', 'handler_name', 'created_at', 'user_id']:
            if col in available_cols:
                cols_to_select.append(col)

        cost_logs = select_all(sb, "query_cost_log",
                              columns=",".join(cols_to_select))
    else:
        cost_logs = []

    country_questions = [
        log for log in cost_logs
        if log.get('question') and 'country' in log['question'].lower()
    ]

    print(f"  → Total queries in query_cost_log: {len(cost_logs)}")
    print(f"  → Queries mentioning 'country': {len(country_questions)}")

    if country_questions:
        print("\n  Sample country-related questions:")
        for log in country_questions[:5]:
            handler = log.get('handler_name', log.get('tool_name', 'unknown'))
            print(f"    • '{log['question'][:100]}...' (handler: {handler})")

    # Check learning_log
    print("\n[4b] Checking learning_log for country-related patterns")

    # First check what columns exist
    sample_learning = sb.table("learning_log").select("*").limit(1).execute()
    if sample_learning.data:
        available_learning_cols = list(sample_learning.data[0].keys())
        # Select only columns that exist
        learning_cols_to_select = []
        for col in ['question', 'learning_category', 'proposed_change', 'created_at', 'category']:
            if col in available_learning_cols:
                learning_cols_to_select.append(col)

        learning_logs = select_all(sb, "learning_log",
                                   columns=",".join(learning_cols_to_select))
    else:
        learning_logs = []

    country_learnings = [
        log for log in learning_logs
        if log.get('question') and 'country' in log['question'].lower()
    ]

    print(f"  → Total entries in learning_log: {len(learning_logs)}")
    print(f"  → Entries mentioning 'country': {len(country_learnings)}")

    if country_learnings:
        print("\n  Sample country-related learning signals:")
        for log in country_learnings[:5]:
            print(f"    • '{log['question'][:100]}...'")
            category = log.get('learning_category', log.get('category', 'unknown'))
            print(f"      Category: {category}")

    # Recommendation
    print("\n[4c] Usage frequency assessment")
    if len(country_questions) == 0 and len(country_learnings) == 0:
        print("  → ZERO historical usage found")
        print("    This is a one-off request, not a recurring pattern")
    elif len(country_questions) == 1 and len(country_learnings) == 0:
        print("  → SINGLE historical usage found (the motivating EMEA question)")
        print("    Cannot confirm recurring need from logs alone")
    else:
        print(f"  → MULTIPLE historical usages found ({len(country_questions)} + {len(country_learnings)})")
        print("    Confirms recurring need beyond one-off request")


def audit_gap_analysis():
    """Task 5: Determine the actual gap."""
    print("\n" + "=" * 70)
    print("TASK 5: Gap Analysis - What Needs to be Built")
    print("=" * 70)

    print("\n[5a] Checking resolve_dimension_filter() implementation")

    # Read the resolve_dimension_filter function
    resolve_file = Path(__file__).parent.parent / "api" / "dimension_resolver.py"
    if resolve_file.exists():
        with open(resolve_file) as f:
            content = f.read()

        # Check what dimensions are currently supported
        if 'def resolve_dimension_filter' in content:
            print("  → resolve_dimension_filter() exists")

            # Look for dimension handling
            dimensions_found = []
            for dim in ['owner', 'region', 'segment', 'stage', 'pipeline']:
                if f'"{dim}"' in content or f"'{dim}'" in content:
                    dimensions_found.append(dim)

            print(f"  → Currently supported dimensions: {dimensions_found}")
            print(f"  → Country in supported list: {'country' in dimensions_found}")
        else:
            print("  → resolve_dimension_filter() not found")
    else:
        print("  → dimension_resolver.py not found")

    print("\n[5b] Gap determination")
    print("  Checking if this is:")
    print("  • SMALL GAP: Just add country to resolve_dimension_filter()")
    print("    - Follow existing pattern for region/segment")
    print("    - Add canonicalization if needed (Task 2 findings)")
    print("    - 30-60 minute addition")
    print("  • LARGE GAP: Needs new primitive with aggregation/synthesis")
    print("    - Requires country-specific reasoning logic")
    print("    - Similar to forecast_trust/pipeline_coverage builds")
    print("    - Multi-hour build cycle")

    print("\n[5c] Recommendation")
    print("  Based on audit findings above:")
    print("  • If Task 2 shows clean data → Simple dimension resolver addition")
    print("  • If Task 2 shows variants → Canonicalization layer needed first")
    print("  • If Task 4 shows recurring usage → Higher priority")
    print("  • If resolve_dimension_filter supports region → Country follows same pattern")


def main():
    print("\n" + "=" * 70)
    print("COUNTRY-AS-DIMENSION AUDIT")
    print("Marketing/RevOps-lead Priority #2")
    print("=" * 70)
    print("\nMotivating question: Ryan/Lyndsie asked for country-level breakdown")
    print("of EMEA opportunities and deal value.")
    print("\nRegion (EMEA) already resolves via resolve_dimension_filter().")
    print("Country does not - only works via dynamic_query's generic filter_table().")
    print("")

    # Run all audit tasks
    try:
        # Task 1
        deals, country_counts, non_null_countries = audit_country_data_quality()

        # Task 2
        audit_canonicalization_need(non_null_countries, country_counts)

        # Task 3
        audit_region_relationship(deals)

        # Task 4
        audit_historical_usage()

        # Task 5
        audit_gap_analysis()

        print("\n" + "=" * 70)
        print("AUDIT COMPLETE")
        print("=" * 70)
        print("\nNext step: Review findings and determine build scope")
        print("before any implementation begins.")

    except Exception as e:
        print(f"\n❌ Audit failed: {e}")
        import traceback
        traceback.print_exc()
        return 1

    return 0


if __name__ == "__main__":
    sys.exit(main())
