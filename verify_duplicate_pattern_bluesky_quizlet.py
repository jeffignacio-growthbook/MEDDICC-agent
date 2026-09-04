#!/usr/bin/env python3
"""
Verify Duplicate Pattern: Bluesky & Quizlet

Bluesky and Quizlet each appear TWICE in data quality errors (4 total deals).
Before accepting "scattered manual entry" as final explanation, check:

1. Who created/modified these 4 deals (same rep?)
2. When were they created (same batch? same time window?)
3. Any common properties (import source, integration, etc.)

Pattern history: Multiple times in this analysis, "no pattern" needed one more
layer of digging (pagination bug, Q3 -1, week-3=0 contradiction). Don't stop
at surface-level "scattered" if there's a systematic source.
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


# The 4 deals with duplicates
DUPLICATE_DEALS = [
    {'company': 'Bluesky', 'deal_id': '5369635703', 'create_date': '2026-01-12', 'close_date': '2026-01-12', 'cycle_days': 0},
    {'company': 'Bluesky', 'deal_id': '6212201883', 'create_date': '2026-07-07', 'close_date': '2026-07-07', 'cycle_days': 0},
    {'company': 'Quizlet', 'deal_id': '5681417580', 'create_date': '2026-02-23', 'close_date': '2026-01-13', 'cycle_days': -41},
    {'company': 'Quizlet', 'deal_id': '5401072420', 'create_date': '2026-01-15', 'close_date': '2026-01-15', 'cycle_days': 0},
]


def main():
    supabase = get_supabase()

    print("=" * 80)
    print("DUPLICATE PATTERN ANALYSIS: Bluesky & Quizlet")
    print("=" * 80)
    print()

    print("Context:")
    print("  Bluesky appears 2x (both zero-day cycles)")
    print("  Quizlet appears 2x (1 negative cycle, 1 zero-day)")
    print("  4 deals total from just 2 companies")
    print()
    print("Question: Is this coincidence or a systematic pattern?")
    print()

    # Step 1: Fetch full deal data for all 4
    deal_ids = [d['deal_id'] for d in DUPLICATE_DEALS]

    deals_resp = supabase.table('deals') \
        .select('*') \
        .in_('deal_id', deal_ids) \
        .execute()

    deals_by_id = {str(d['deal_id']): d for d in deals_resp.data}

    if len(deals_by_id) != 4:
        print(f"⚠️  Expected 4 deals, found {len(deals_by_id)}")
        print()

    # Step 2: Extract creation metadata
    print()
    print("=" * 80)
    print("DEAL METADATA")
    print("=" * 80)
    print()

    metadata_fields = [
        'hs_object_id',
        'hs_created_by_user_id',
        'hs_lastmodifieddate',
        'hs_object_source',
        'hs_object_source_id',
        'hs_object_source_label',
        'created_by',
        'deal_source',
        'createdate',
        'closedate',
        'owner_email',
        'ownerid'
    ]

    enriched_deals = []

    for deal_info in DUPLICATE_DEALS:
        deal_id = deal_info['deal_id']
        deal = deals_by_id.get(deal_id)

        if not deal:
            print(f"⚠️  {deal_info['company']} ({deal_id}): Not found")
            continue

        print(f"{deal_info['company']} (Deal {deal_id}):")
        print("-" * 60)

        metadata = {}
        for field in metadata_fields:
            value = deal.get(field)
            if value is not None:
                metadata[field] = value
                print(f"  {field}: {value}")

        print()

        enriched_deals.append({
            **deal_info,
            'metadata': metadata,
            'full_deal': deal
        })

    # Step 3: Look for patterns
    print()
    print("=" * 80)
    print("PATTERN ANALYSIS")
    print("=" * 80)
    print()

    # Pattern 1: Same creator
    creators = defaultdict(list)
    for deal in enriched_deals:
        creator = deal['metadata'].get('hs_created_by_user_id') or deal['metadata'].get('created_by')
        if creator:
            creators[str(creator)].append(deal)

    print("1. Creation User:")
    print("-" * 60)
    if creators:
        for creator, deals_list in sorted(creators.items(), key=lambda x: -len(x[1])):
            print(f"  User {creator}: {len(deals_list)} deals")
            for d in deals_list:
                print(f"    - {d['company']} ({d['deal_id']})")

        max_by_user = max(len(deals_list) for deals_list in creators.values())
        if max_by_user >= 3:
            print()
            print(f"  → {max_by_user}/4 deals by same user (PATTERN DETECTED)")
        elif max_by_user == 2:
            print()
            print(f"  → Multiple users, no concentration")
    else:
        print("  No creator information available")

    print()

    # Pattern 2: Timing clustering
    print("2. Creation Timing:")
    print("-" * 60)

    creation_times = []
    for deal in enriched_deals:
        create_datetime = deal['metadata'].get('createdate') or deal['create_date']
        if create_datetime:
            try:
                if 'T' in str(create_datetime):
                    dt = datetime.fromisoformat(str(create_datetime).replace('Z', '+00:00'))
                else:
                    dt = datetime.fromisoformat(str(create_datetime)[:10])
                creation_times.append({
                    'deal': deal,
                    'datetime': dt,
                    'date': dt.strftime('%Y-%m-%d'),
                    'time': dt.strftime('%H:%M:%S') if 'T' in str(create_datetime) else 'N/A'
                })
            except:
                pass

    if creation_times:
        creation_times.sort(key=lambda x: x['datetime'])

        for ct in creation_times:
            print(f"  {ct['date']} {ct['time']:>8s} - {ct['deal']['company']} ({ct['deal']['deal_id']})")

        # Check if all on same day
        dates = {ct['date'] for ct in creation_times}
        if len(dates) == 1:
            print()
            print(f"  → All 4 deals created on SAME DAY (PATTERN DETECTED)")
        elif len(dates) == 2:
            print()
            print(f"  → 4 deals across 2 dates (possible pattern)")
        else:
            print()
            print(f"  → Spread across {len(dates)} dates (scattered)")

        # Check time gap between first and last
        if len(creation_times) > 1:
            first = creation_times[0]['datetime']
            last = creation_times[-1]['datetime']
            gap = (last - first).total_seconds() / 3600  # hours

            print(f"  → Time span: {gap:.1f} hours")
            if gap < 24:
                print(f"     (All within 24 hours - possible batch)")
            elif gap < 168:  # 1 week
                print(f"     (Within 1 week - possible related)")
    else:
        print("  No timestamp data available")

    print()

    # Pattern 3: Same owner
    print("3. Deal Owner:")
    print("-" * 60)

    owners = defaultdict(list)
    for deal in enriched_deals:
        owner = deal['metadata'].get('owner_email') or deal['metadata'].get('ownerid')
        if owner:
            owners[str(owner)].append(deal)

    if owners:
        for owner, deals_list in sorted(owners.items(), key=lambda x: -len(x[1])):
            print(f"  {owner}: {len(deals_list)} deals")
            for d in deals_list:
                print(f"    - {d['company']} ({d['deal_id']})")

        max_by_owner = max(len(deals_list) for deals_list in owners.values())
        if max_by_owner >= 3:
            print()
            print(f"  → {max_by_owner}/4 deals by same owner (PATTERN DETECTED)")
    else:
        print("  No owner information available")

    print()

    # Pattern 4: Same source
    print("4. Object Source:")
    print("-" * 60)

    sources = defaultdict(list)
    for deal in enriched_deals:
        source = deal['metadata'].get('hs_object_source') or deal['metadata'].get('deal_source')
        if source:
            sources[str(source)].append(deal)

    if sources:
        for source, deals_list in sorted(sources.items(), key=lambda x: -len(x[1])):
            print(f"  {source}: {len(deals_list)} deals")

        max_by_source = max(len(deals_list) for deals_list in sources.values())
        if max_by_source >= 3:
            print()
            print(f"  → {max_by_source}/4 deals from same source (PATTERN DETECTED)")
    else:
        print("  No source information available")

    print()

    # Step 4: Cross-reference with other data quality errors
    print()
    print("=" * 80)
    print("CROSS-REFERENCE: All 8 Data Quality Errors")
    print("=" * 80)
    print()

    # Check if the patterns extend beyond Bluesky/Quizlet
    print("Checking if patterns apply to all 8 data quality errors...")
    print()

    ALL_DATA_QUALITY_IDS = [
        '5790911698',  # Make
        '5681417580',  # Quizlet
        '5755377954',  # BESTSECRET
        '5369635703',  # Bluesky
        '6212201883',  # Bluesky
        '6089749648',  # LeoVegas
        '5401072420',  # Quizlet
        '6023407620',  # knowunity.ai
    ]

    all_deals_resp = supabase.table('deals') \
        .select('deal_id, company_name, create_date, close_date, owner_email, hs_created_by_user_id') \
        .in_('deal_id', ALL_DATA_QUALITY_IDS) \
        .execute()

    all_creators = defaultdict(int)
    all_owners = defaultdict(int)

    for deal in all_deals_resp.data:
        creator = deal.get('hs_created_by_user_id')
        owner = deal.get('owner_email')

        if creator:
            all_creators[str(creator)] += 1
        if owner:
            all_owners[str(owner)] += 1

    if all_creators:
        print("Creators across all 8 data quality errors:")
        for creator, count in sorted(all_creators.items(), key=lambda x: -x[1]):
            print(f"  User {creator}: {count} deals")

        max_creator_count = max(all_creators.values())
        if max_creator_count >= 5:
            print()
            print(f"  → {max_creator_count}/8 deals by same creator (SYSTEMATIC PATTERN)")

    print()

    if all_owners:
        print("Owners across all 8 data quality errors:")
        for owner, count in sorted(all_owners.items(), key=lambda x: -x[1]):
            print(f"  {owner}: {count} deals")

        max_owner_count = max(all_owners.values())
        if max_owner_count >= 5:
            print()
            print(f"  → {max_owner_count}/8 deals by same owner (SYSTEMATIC PATTERN)")

    print()

    # Step 5: Conclusion
    print()
    print("=" * 80)
    print("CONCLUSION")
    print("=" * 80)
    print()

    patterns_found = []

    if creators and max(len(d) for d in creators.values()) >= 3:
        patterns_found.append("Same creator for 3+ deals")

    if creation_times and len({ct['date'] for ct in creation_times}) <= 2:
        patterns_found.append("Temporal clustering (≤2 dates)")

    if owners and max(len(d) for d in owners.values()) >= 3:
        patterns_found.append("Same owner for 3+ deals")

    if sources and max(len(d) for d in sources.values()) >= 3:
        patterns_found.append("Same source for 3+ deals")

    if patterns_found:
        print("⚠️  SYSTEMATIC PATTERN DETECTED")
        print()
        print("Patterns found:")
        for p in patterns_found:
            print(f"  - {p}")
        print()
        print("RECOMMENDATION:")
        print("  This is NOT 'scattered manual entry' - there's a systematic source.")
        print("  Investigate:")
        print("  1. Who is the common user/owner?")
        print("  2. What process created these deals?")
        print("  3. Can the process be fixed to prevent future occurrences?")
        print()
        print("  Update DATA_QUALITY_EXCLUSIONS_README.md to reflect systematic pattern.")
    else:
        print("✓ No systematic pattern detected")
        print()
        print("  Appears to be scattered manual entry as initially assessed.")
        print("  Bluesky/Quizlet appearing twice is coincidence, not concentration.")
        print()
        print("  'Scattered manual entry' explanation holds.")


if __name__ == '__main__':
    main()
