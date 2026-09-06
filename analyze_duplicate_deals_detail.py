#!/usr/bin/env python3
"""
Analyze Duplicate Deals in Detail

For companies with multiple Aug 9 migration deals (LeoVegas 7x, 7shifts 9x, etc.):
Pull full records side by side and determine if they represent:
- Distinct historical opportunities (different amounts/dates/products), OR
- Source system duplication (near-identical data fragmented across records)

Do NOT default to "keep all" - check if amounts/dates are near-identical.
"""

import os
import sys
from pathlib import Path
from collections import defaultdict
from datetime import datetime
from dotenv import load_dotenv

env_path = Path(__file__).parent / '.env'
load_dotenv(env_path)
sys.path.insert(0, str(Path(__file__).parent))

from api.db import get_supabase


DUPLICATE_COMPANIES = [
    ('LeoVegas', 7),
    ('7shifts', 9),
    ('InvestEngine', 2),
    ('higgsfield.ai', 2),
]


def format_date(date_str):
    """Format date for display."""
    if not date_str:
        return 'None'
    return date_str[:10] if len(date_str) >= 10 else date_str


def are_amounts_similar(amounts, threshold=0.05):
    """
    Check if amounts are near-identical (within threshold).
    threshold=0.05 means 5% variance
    """
    non_null = [a for a in amounts if a is not None]
    if len(non_null) <= 1:
        return False

    avg = sum(non_null) / len(non_null)
    if avg == 0:
        return all(a == 0 for a in non_null)

    # Check if all amounts within threshold of average
    for amt in non_null:
        variance = abs(amt - avg) / avg
        if variance > threshold:
            return False
    return True


def are_dates_overlapping(dates, window_days=30):
    """Check if dates cluster within a window."""
    non_null = [d for d in dates if d]
    if len(non_null) <= 1:
        return False

    try:
        date_objs = [datetime.fromisoformat(d[:10]) for d in non_null]
        date_objs.sort()

        # Check if all dates within window_days of first date
        first = date_objs[0]
        for dt in date_objs[1:]:
            if (dt - first).days > window_days:
                return False
        return True
    except:
        return False


def analyze_company_duplicates(supabase, company_name, expected_count):
    """Analyze all deals for a company and determine duplication pattern."""

    print(f"\n{'=' * 80}")
    print(f"{company_name} - Expected {expected_count} deals")
    print('=' * 80)
    print()

    # Get all deals for this company
    result = supabase.table('deals') \
        .select('*') \
        .ilike('company_name', f'%{company_name}%') \
        .execute()

    deals = result.data

    if not deals:
        print(f"⚠️  No deals found for {company_name}")
        return None

    print(f"Found {len(deals)} deals total")
    print()

    # Separate Aug 9 from other
    aug9_deals = [d for d in deals if '2026-08-09' in (d.get('created_at') or '')]
    other_deals = [d for d in deals if '2026-08-09' not in (d.get('created_at') or '')]

    print(f"Aug 9 migration deals: {len(aug9_deals)}")
    print(f"Other deals: {len(other_deals)}")
    print()

    if len(aug9_deals) != expected_count:
        print(f"⚠️  Expected {expected_count} Aug 9 deals, found {len(aug9_deals)}")
        print()

    # Analyze Aug 9 deals in detail
    if aug9_deals:
        print(f"\nAug 9 Migration Deals - Side by Side Comparison:")
        print("-" * 80)

        # Display table header
        print(f"{'Deal ID':15s} | {'Amount':>12s} | {'Stage':20s} | {'Create':12s} | {'Close':12s} | {'Owner':25s}")
        print("-" * 120)

        # Sort by deal_id for consistency
        aug9_deals_sorted = sorted(aug9_deals, key=lambda x: str(x.get('deal_id', '')))

        for deal in aug9_deals_sorted:
            deal_id = str(deal.get('deal_id', 'None'))[:15]
            amount = deal.get('arr_usd')
            amount_str = f"${amount:,.0f}" if amount is not None else 'None'
            stage = (deal.get('stage') or 'None')[:18]
            create = format_date(deal.get('create_date'))
            close = format_date(deal.get('close_date'))
            owner = (deal.get('owner_email') or 'None')[:23]

            print(f"{deal_id:15s} | {amount_str:>12s} | {stage:20s} | {create:12s} | {close:12s} | {owner:25s}")

        print()

        # Similarity analysis
        print("Similarity Analysis:")
        print("-" * 80)

        amounts = [d.get('arr_usd') for d in aug9_deals]
        create_dates = [d.get('create_date') for d in aug9_deals]
        close_dates = [d.get('close_date') for d in aug9_deals]
        stages = [d.get('stage') for d in aug9_deals]

        # Check amounts
        amounts_similar = are_amounts_similar(amounts)
        if amounts_similar:
            avg_amt = sum(a for a in amounts if a) / len([a for a in amounts if a])
            print(f"  💰 Amounts: NEAR-IDENTICAL (avg ${avg_amt:,.0f}, <5% variance)")
        else:
            unique_amounts = len(set(a for a in amounts if a is not None))
            print(f"  💰 Amounts: DISTINCT ({unique_amounts} unique values)")

        # Check create dates
        create_clustered = are_dates_overlapping(create_dates, window_days=30)
        if create_clustered:
            print(f"  📅 Create Dates: CLUSTERED (within 30-day window)")
        else:
            print(f"  📅 Create Dates: SPREAD OUT (>30 days apart)")

        # Check close dates
        close_clustered = are_dates_overlapping(close_dates, window_days=30)
        if close_clustered:
            print(f"  📅 Close Dates: CLUSTERED (within 30-day window)")
        else:
            print(f"  📅 Close Dates: SPREAD OUT (>30 days apart)")

        # Check stages
        unique_stages = len(set(s for s in stages if s))
        if unique_stages == 1:
            print(f"  🎯 Stages: IDENTICAL (all '{stages[0]}')")
        else:
            print(f"  🎯 Stages: VARIED ({unique_stages} unique stages)")

        print()

        # Duplication score
        duplication_score = 0
        if amounts_similar:
            duplication_score += 3
        if create_clustered:
            duplication_score += 2
        if close_clustered:
            duplication_score += 2
        if unique_stages == 1:
            duplication_score += 1

        print(f"Duplication Score: {duplication_score}/8")
        print()

        # Verdict
        print("VERDICT:")
        if duplication_score >= 6:
            print("  🔴 HIGH LIKELIHOOD OF SOURCE DUPLICATION")
            print("     These appear to be fragmented/duplicate records from Copper")
            print("     Amounts, dates, and stages are too similar for distinct deals")
            print()
            print("  RECOMMENDATION: DEDUP - Keep only one record per company")
            print("     Suggest keeping deal with most complete data or earliest close_date")
        elif duplication_score >= 4:
            print("  🟡 MODERATE DUPLICATION LIKELIHOOD")
            print("     Some fields match, others differ")
            print("     Could be related deals (renewals, upsells) or partial duplicates")
            print()
            print("  RECOMMENDATION: MANUAL REVIEW")
            print("     Check if amounts represent different products/time periods")
            print("     If amounts identical → dedup; if distinct → keep separate")
        else:
            print("  🟢 LIKELY DISTINCT OPPORTUNITIES")
            print("     Different amounts, dates, or stages suggest separate deals")
            print("     May represent renewals, expansions, or separate product lines")
            print()
            print("  RECOMMENDATION: KEEP ALL")
            print("     These appear to be genuinely distinct historical opportunities")

        print()

        # Check for any ID fields that might indicate source system
        print("Additional Fields (may indicate source system):")
        sample = aug9_deals[0]
        id_fields = [k for k in sample.keys() if 'id' in k.lower() and k not in ['deal_id', 'company_id']]

        if id_fields:
            for field in id_fields[:5]:  # Show first 5
                values = [str(d.get(field, 'None')) for d in aug9_deals]
                unique_vals = len(set(values))
                print(f"  {field}: {unique_vals} unique values")
                if unique_vals == len(aug9_deals):
                    print(f"    → All unique (suggests distinct records)")
                elif unique_vals == 1:
                    print(f"    → All same (suggests batch import)")
        else:
            print("  No additional ID fields found")

        print()

    # Show non-Aug-9 deals for context
    if other_deals:
        print("\nNon-Aug-9 Deals (for context):")
        print("-" * 80)

        print(f"{'Deal ID':15s} | {'Created At':20s} | {'Amount':>12s} | {'Close':12s}")
        print("-" * 80)

        for deal in sorted(other_deals, key=lambda x: x.get('created_at', '')):
            deal_id = str(deal.get('deal_id', 'None'))[:15]
            created = (deal.get('created_at') or 'None')[:19]
            amount = deal.get('arr_usd')
            amount_str = f"${amount:,.0f}" if amount is not None else 'None'
            close = format_date(deal.get('close_date'))

            print(f"{deal_id:15s} | {created:20s} | {amount_str:>12s} | {close:12s}")

        print()
        print(f"  → These {len(other_deals)} deal(s) created outside Aug 9 migration")
        print(f"  → Likely native HubSpot entries (not Copper)")
        print()

    return {
        'company': company_name,
        'total_deals': len(deals),
        'aug9_deals': len(aug9_deals),
        'other_deals': len(other_deals),
        'duplication_score': duplication_score if aug9_deals else 0,
        'recommendation': 'DEDUP' if duplication_score >= 6 else ('REVIEW' if duplication_score >= 4 else 'KEEP')
    }


def main():
    supabase = get_supabase()

    print("=" * 80)
    print("DUPLICATE DEALS DETAILED ANALYSIS")
    print("=" * 80)
    print()

    print("Objective: Determine if duplicate Aug 9 deals are:")
    print("  - Distinct opportunities (different amounts/dates/products) → KEEP")
    print("  - Source system duplication (near-identical data) → DEDUP")
    print()

    results = []

    for company, expected_count in DUPLICATE_COMPANIES:
        result = analyze_company_duplicates(supabase, company, expected_count)
        if result:
            results.append(result)

    # Summary
    print("\n" + "=" * 80)
    print("SUMMARY & RECOMMENDATIONS")
    print("=" * 80)
    print()

    print(f"{'Company':20s} | {'Aug 9':>6s} | {'Other':>6s} | {'Score':>6s} | {'Recommendation':15s}")
    print("-" * 80)

    for r in results:
        print(f"{r['company']:20s} | {r['aug9_deals']:>6d} | {r['other_deals']:>6d} | {r['duplication_score']:>6d} | {r['recommendation']:15s}")

    print()

    dedup_count = sum(1 for r in results if r['recommendation'] == 'DEDUP')
    review_count = sum(1 for r in results if r['recommendation'] == 'REVIEW')
    keep_count = sum(1 for r in results if r['recommendation'] == 'KEEP')

    print(f"Companies requiring deduplication: {dedup_count}")
    print(f"Companies requiring manual review: {review_count}")
    print(f"Companies with distinct deals (keep all): {keep_count}")
    print()

    if dedup_count > 0:
        print("⚠️  ACTION REQUIRED:")
        print("   Companies flagged for DEDUP have near-identical data across multiple Aug 9 records")
        print("   This suggests fragmented Copper records, not distinct opportunities")
        print()
        print("   Next steps:")
        print("   1. For each DEDUP company: keep deal with most complete data")
        print("   2. Add redundant deal_ids to data_quality_exclusions table")
        print("   3. Flag reason as 'COPPER_DUPLICATE'")

    print()

    # Export findings
    output_file = 'duplicate_deals_analysis.txt'
    with open(output_file, 'w') as f:
        f.write("Duplicate Deals Analysis\n")
        f.write("=" * 80 + "\n\n")

        for r in results:
            f.write(f"{r['company']}\n")
            f.write(f"  Aug 9 deals: {r['aug9_deals']}\n")
            f.write(f"  Other deals: {r['other_deals']}\n")
            f.write(f"  Duplication score: {r['duplication_score']}/8\n")
            f.write(f"  Recommendation: {r['recommendation']}\n")
            f.write("\n")

    print(f"Full findings written to: {output_file}")


if __name__ == '__main__':
    main()
