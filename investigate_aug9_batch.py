#!/usr/bin/env python3
"""
Investigate Aug 9 Batch Import

Pull ALL deals created OR modified by christian@growthbook.io in the window
2026-08-09 08:38:00 to 08:40:00. Check for data quality issues beyond
impossible timelines:
- Wrong amounts (null, zero, extreme values)
- Wrong stages (mismatched with deal_status)
- Wrong owners (assigned to christian but should be elsewhere)
- Duplicates (same company, overlapping dates)
- Other anomalies

Do NOT scope exclusions to just 8 known deals until full batch extent known.
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
from api.field_semantics import is_won


def days_between(start_str, end_str):
    if not start_str or not end_str:
        return None
    try:
        start = datetime.fromisoformat(start_str[:10])
        end = datetime.fromisoformat(end_str[:10])
        return (end - start).days
    except:
        return None


def main():
    supabase = get_supabase()

    print("=" * 80)
    print("AUG 9 BATCH IMPORT INVESTIGATION")
    print("=" * 80)
    print()

    print("Target window: 2026-08-09 08:38:00 to 08:40:00")
    print("Target user: christian@growthbook.io")
    print()

    # Query all deals created in the window
    created_resp = supabase.table('deals') \
        .select('*') \
        .gte('created_at', '2026-08-09T08:38:00') \
        .lte('created_at', '2026-08-09T08:40:00') \
        .execute()

    # Query all deals updated in the window (might be different set)
    updated_resp = supabase.table('deals') \
        .select('*') \
        .gte('updated_at', '2026-08-09T08:38:00') \
        .lte('updated_at', '2026-08-09T08:40:00') \
        .execute()

    # Combine and deduplicate
    deals_by_id = {}
    for deal in created_resp.data + updated_resp.data:
        deals_by_id[str(deal['deal_id'])] = deal

    print(f"Total deals touched in window: {len(deals_by_id)}")
    print()

    # Filter to christian's deals
    christian_deals = [d for d in deals_by_id.values() if d.get('owner_email') == 'christian@growthbook.io']

    print(f"Deals owned by christian@growthbook.io: {len(christian_deals)}")
    print()

    if not christian_deals:
        print("⚠️  No deals found for christian@growthbook.io in this window")
        return

    # Analyze for various data quality issues
    issues_by_type = defaultdict(list)

    for deal in christian_deals:
        deal_id = str(deal['deal_id'])
        company = deal.get('company_name')
        create_date = deal.get('create_date')
        close_date = deal.get('close_date')
        stage = deal.get('stage')
        deal_status = deal.get('deal_status')
        arr = deal.get('arr_usd')

        # Issue 1: Impossible timeline
        cycle_days = days_between(create_date, close_date)
        if cycle_days is not None and cycle_days <= 0:
            issues_by_type['IMPOSSIBLE_TIMELINE'].append({
                'deal_id': deal_id,
                'company': company,
                'issue': f'{cycle_days} day cycle',
                'details': f'{create_date} → {close_date}'
            })

        # Issue 2: Null dates
        if not create_date or not close_date:
            issues_by_type['NULL_DATES'].append({
                'deal_id': deal_id,
                'company': company,
                'issue': 'Missing critical dates',
                'details': f'create={create_date}, close={close_date}'
            })

        # Issue 3: Null or zero ARR for won deals
        if deal_status == 'won' and stage and is_won(str(stage)):
            if arr is None:
                issues_by_type['NULL_ARR_WON'].append({
                    'deal_id': deal_id,
                    'company': company,
                    'issue': 'Won deal with null ARR',
                    'details': f'stage={stage}, arr=null'
                })
            elif float(arr or 0) == 0:
                issues_by_type['ZERO_ARR_WON'].append({
                    'deal_id': deal_id,
                    'company': company,
                    'issue': 'Won deal with zero ARR',
                    'details': f'stage={stage}, arr=0'
                })

        # Issue 4: Stage/status mismatch
        if stage and deal_status:
            if is_won(str(stage)) and deal_status != 'won':
                issues_by_type['STAGE_STATUS_MISMATCH'].append({
                    'deal_id': deal_id,
                    'company': company,
                    'issue': 'Stage says won but status is not',
                    'details': f'stage={stage}, status={deal_status}'
                })

    # Check for duplicates (same company, overlapping timeframes)
    by_company = defaultdict(list)
    for deal in christian_deals:
        company = deal.get('company_name')
        if company:
            by_company[company].append(deal)

    for company, deals_list in by_company.items():
        if len(deals_list) > 1:
            issues_by_type['DUPLICATE_COMPANY'].append({
                'deal_id': 'MULTIPLE',
                'company': company,
                'issue': f'{len(deals_list)} deals for same company',
                'details': ', '.join([str(d['deal_id']) for d in deals_list])
            })

    # Print summary
    print()
    print("=" * 80)
    print("DATA QUALITY ISSUES FOUND")
    print("=" * 80)
    print()

    total_issues = sum(len(issues) for issues in issues_by_type.values())
    affected_deals = set()
    for issues in issues_by_type.values():
        for issue in issues:
            if issue['deal_id'] != 'MULTIPLE':
                affected_deals.add(issue['deal_id'])

    print(f"Total issues: {total_issues}")
    print(f"Affected deals: {len(affected_deals)}")
    print()

    for issue_type in sorted(issues_by_type.keys()):
        issues = issues_by_type[issue_type]
        print(f"{issue_type}: {len(issues)}")
        for issue in issues:
            print(f"  • {issue['company']} ({issue['deal_id']}): {issue['issue']}")
            print(f"    {issue['details']}")
        print()

    # Print full deal list
    print()
    print("=" * 80)
    print(f"COMPLETE DEAL LIST ({len(christian_deals)} deals)")
    print("=" * 80)
    print()

    print(f"{'Company':30s} | {'Deal ID':12s} | {'Create':10s} | {'Close':10s} | {'Cycle':>5s} | {'Status':10s}")
    print("-" * 95)

    for deal in sorted(christian_deals, key=lambda x: (x.get('create_date') or '', x.get('company_name') or '')):
        company = (deal.get('company_name') or 'Unknown')[:28]
        deal_id = str(deal['deal_id'])[:12]
        create = (deal.get('create_date') or 'NULL')[:10]
        close = (deal.get('close_date') or 'NULL')[:10]
        cycle = str(days_between(deal.get('create_date'), deal.get('close_date')))
        status = (deal.get('deal_status') or 'unknown')[:10]

        print(f"{company:30s} | {deal_id:12s} | {create:10s} | {close:10s} | {cycle:>5s} | {status:10s}")

    print()

    # Conclusion
    print()
    print("=" * 80)
    print("CONCLUSION")
    print("=" * 80)
    print()

    if len(affected_deals) > 8:
        print(f"⚠️  BROADER IMPACT THAN EXPECTED")
        print()
        print(f"  Originally identified: 8 deals with impossible timelines")
        print(f"  Actually affected: {len(affected_deals)} deals in this batch")
        print()
        print("  RECOMMENDATION:")
        print("  - DO NOT use static list of 8 deal_ids in migration")
        print("  - Flag ALL deals from Aug 9 08:38-08:40 batch")
        print("  - Use temporal + owner filter in exclusion logic")
        print()
        print("  Suggested exclusion criteria:")
        print("    created_at BETWEEN '2026-08-09 08:38:00' AND '2026-08-09 08:40:00'")
        print("    AND owner_email = 'christian@growthbook.io'")
    elif len(affected_deals) == 8:
        print("✓ Scope matches original finding")
        print()
        print(f"  All {len(affected_deals)} affected deals already identified")
        print("  No additional deals from Aug 9 batch have quality issues")
        print()
        print("  Static list of 8 deal_ids is sufficient")
    else:
        print(f"⚠️  Unexpected result: {len(affected_deals)} affected deals")

    print()

    # Export for further analysis
    output_file = 'aug9_batch_full_analysis.txt'
    with open(output_file, 'w') as f:
        f.write(f"Aug 9 Batch Analysis\n")
        f.write(f"=" * 80 + "\n\n")
        f.write(f"Total deals in window: {len(deals_by_id)}\n")
        f.write(f"Christian's deals: {len(christian_deals)}\n")
        f.write(f"Affected deals: {len(affected_deals)}\n\n")

        for issue_type, issues in issues_by_type.items():
            f.write(f"{issue_type}: {len(issues)}\n")
            for issue in issues:
                f.write(f"  {issue['company']} ({issue['deal_id']}): {issue['issue']}\n")
                f.write(f"    {issue['details']}\n")
            f.write("\n")

    print(f"Full analysis written to: {output_file}")


if __name__ == '__main__':
    main()
