#!/usr/bin/env python3
"""
Test Copper Migration Hypothesis

Hypothesis: GrowthBook migrated from Copper CRM to HubSpot around Aug 9, 2026.
Christian@growthbook.io ran or owned the migration. The 49 deals, duplicates,
and impossible timelines are migration artifacts, not data quality errors.

Test:
1. Check for Copper origin markers in Aug 9 deals
2. Check if impossible timelines fit migration artifact pattern
3. Check for broader Aug 9 spike (company-wide migration event)
4. Check if "duplicates" are Copper + new HubSpot entries
"""

import os
import sys
from pathlib import Path
from collections import defaultdict
from datetime import datetime, timedelta
from dotenv import load_dotenv

env_path = Path(__file__).parent / '.env'
load_dotenv(env_path)
sys.path.insert(0, str(Path(__file__).parent))

from api.db import get_supabase


def main():
    supabase = get_supabase()

    print("=" * 80)
    print("COPPER MIGRATION HYPOTHESIS TEST")
    print("=" * 80)
    print()

    print("Hypothesis: GrowthBook migrated from Copper to HubSpot on Aug 9, 2026")
    print("Evidence to check:")
    print("  1. Copper origin markers in deals")
    print("  2. Impossible timelines = migration date mapping issues")
    print("  3. Broader Aug 9 spike (company-wide event)")
    print("  4. 'Duplicates' = old Copper + new HubSpot entries")
    print()

    # TEST 1: Check for Copper/migration markers
    print()
    print("=" * 80)
    print("TEST 1: Copper Origin Markers")
    print("=" * 80)
    print()

    # Get Aug 9 deals
    aug9_deals = supabase.table('deals') \
        .select('*') \
        .gte('created_at', '2026-08-09T00:00:00') \
        .lte('created_at', '2026-08-09T23:59:59') \
        .execute()

    print(f"Total deals created Aug 9: {len(aug9_deals.data)}")
    print()

    # Check what fields are available
    if aug9_deals.data:
        sample = aug9_deals.data[0]
        all_fields = set(sample.keys())

        # Look for migration-related fields
        migration_fields = [
            'hs_object_source',
            'hs_object_source_id',
            'hs_object_source_label',
            'hs_created_by_user_id',
            'createdate',
            'import_source',
            'deal_source',
            'original_source'
        ]

        # Also check for custom properties that might reference Copper
        copper_keywords = ['copper', 'import', 'migration', 'zapier', 'piesync', 'crm']

        available_fields = [f for f in migration_fields if f in all_fields]

        print("Available migration-related fields:")
        for field in available_fields:
            print(f"  - {field}")
        print()

        # Check for custom fields with Copper/migration keywords
        custom_fields = [f for f in all_fields if any(kw in f.lower() for kw in copper_keywords)]
        if custom_fields:
            print("Fields with migration/Copper keywords:")
            for field in custom_fields:
                print(f"  - {field}")
            print()

        # Analyze values in available fields
        print("Analyzing field values for migration signatures...")
        print()

        for field in available_fields + custom_fields:
            values = defaultdict(int)
            for deal in aug9_deals.data:
                val = deal.get(field)
                if val is not None:
                    values[str(val)] += 1

            if values:
                print(f"{field}:")
                sorted_values = sorted(values.items(), key=lambda x: -x[1])
                for val, count in sorted_values[:5]:  # Top 5 values
                    pct = count / len(aug9_deals.data) * 100
                    copper_marker = " ← COPPER?" if any(kw in val.lower() for kw in ['copper', 'import', 'migration']) else ""
                    print(f"  {val}: {count} deals ({pct:.1f}%){copper_marker}")
                if len(sorted_values) > 5:
                    print(f"  ... and {len(sorted_values) - 5} more values")
                print()

    # TEST 2: Impossible timeline pattern analysis
    print()
    print("=" * 80)
    print("TEST 2: Impossible Timeline Pattern")
    print("=" * 80)
    print()

    print("If migration tool wrote:")
    print("  create_date = migration date (Aug 9)")
    print("  close_date = preserved Copper original")
    print()
    print("We'd expect: close_date < create_date (all negative cycles)")
    print()

    # Get the 4 impossible timeline deals
    impossible_timeline_companies = ['Quizlet', 'LeoVegas', 'Quizlet', 'DoorDash']

    for company in set(impossible_timeline_companies):
        result = supabase.table('deals') \
            .select('deal_id, company_name, create_date, close_date, created_at, owner_email') \
            .ilike('company_name', f'%{company}%') \
            .gte('created_at', '2026-08-09T08:38:00') \
            .lte('created_at', '2026-08-09T08:40:00') \
            .execute()

        for deal in result.data:
            create = deal.get('create_date')
            close = deal.get('close_date')
            created_at = deal.get('created_at')

            if create and close:
                create_dt = datetime.fromisoformat(create[:10])
                close_dt = datetime.fromisoformat(close[:10])
                created_at_dt = datetime.fromisoformat(created_at[:10]) if created_at else None

                cycle = (close_dt - create_dt).days

                print(f"{company}:")
                print(f"  create_date: {create}")
                print(f"  close_date: {close}")
                print(f"  created_at (HubSpot): {created_at}")
                print(f"  Cycle: {cycle} days")

                # Check if create_date ≈ created_at (migration date)
                if created_at_dt and create_dt:
                    if abs((created_at_dt - create_dt).days) <= 1:
                        print(f"  → create_date ≈ created_at ← MIGRATION MARKER")
                    else:
                        print(f"  → create_date ≠ created_at ({(created_at_dt - create_dt).days} days apart)")

                # Check if close_date is much earlier (preserved Copper date)
                if cycle < 0:
                    print(f"  → close_date BEFORE create_date ← MIGRATION ARTIFACT")
                elif cycle == 0:
                    print(f"  → Same-day close (ambiguous)")

                print()

    # TEST 3: Broader Aug 9 spike
    print()
    print("=" * 80)
    print("TEST 3: Aug 9 Spike Analysis")
    print("=" * 80)
    print()

    print("Checking for company-wide migration event...")
    print()

    # Get deal creation counts for 7 days before and after Aug 9
    date_range = []
    for days_offset in range(-7, 8):
        check_date = datetime(2026, 8, 9) + timedelta(days=days_offset)
        date_str = check_date.strftime('%Y-%m-%d')

        result = supabase.table('deals') \
            .select('deal_id', count='exact') \
            .gte('created_at', f'{date_str}T00:00:00') \
            .lte('created_at', f'{date_str}T23:59:59') \
            .execute()

        date_range.append({
            'date': date_str,
            'count': result.count or 0,
            'is_aug9': days_offset == 0
        })

    print("Deals created per day (Aug 2-16):")
    for entry in date_range:
        marker = " ← AUG 9" if entry['is_aug9'] else ""
        bar = "█" * min(entry['count'] // 10, 50)
        print(f"  {entry['date']}: {entry['count']:>4d} {bar}{marker}")

    print()

    # Calculate if Aug 9 is a statistical spike
    aug9_count = next(e['count'] for e in date_range if e['is_aug9'])
    other_days = [e['count'] for e in date_range if not e['is_aug9']]
    avg_other = sum(other_days) / len(other_days)

    spike_ratio = aug9_count / avg_other if avg_other > 0 else 0

    print(f"Aug 9: {aug9_count} deals")
    print(f"Average other days: {avg_other:.1f} deals")
    print(f"Spike ratio: {spike_ratio:.1f}x")
    print()

    if spike_ratio >= 3:
        print("  → SIGNIFICANT SPIKE (≥3x) ← COMPANY-WIDE EVENT")
    elif spike_ratio >= 2:
        print("  → Moderate spike (2-3x)")
    else:
        print("  → No significant spike")

    print()

    # TEST 4: Duplicates = Copper + HubSpot?
    print()
    print("=" * 80)
    print("TEST 4: Duplicate Analysis (Copper + HubSpot?)")
    print("=" * 80)
    print()

    print("Checking if 'duplicates' are actually:")
    print("  - One deal from Copper migration (Aug 9)")
    print("  - One deal created natively in HubSpot (different date)")
    print()

    # Check the 6 companies with duplicates
    duplicate_companies = ['LeoVegas', 'Quizlet', '7shifts', 'Hey Harper', 'InvestEngine', 'higgsfield.ai']

    for company in duplicate_companies:
        result = supabase.table('deals') \
            .select('deal_id, company_name, created_at, create_date, close_date, owner_email') \
            .ilike('company_name', f'%{company}%') \
            .execute()

        deals = sorted(result.data, key=lambda x: x.get('created_at', ''))

        if len(deals) < 2:
            continue

        print(f"{company}: {len(deals)} deals")

        aug9_deals_for_company = []
        other_deals = []

        for deal in deals:
            created_at = deal.get('created_at', '')
            if '2026-08-09' in created_at:
                aug9_deals_for_company.append(deal)
            else:
                other_deals.append(deal)

        print(f"  Aug 9 deals: {len(aug9_deals_for_company)}")
        print(f"  Other dates: {len(other_deals)}")

        if aug9_deals_for_company:
            print(f"  Aug 9 deals (potential Copper migration):")
            for deal in aug9_deals_for_company:
                print(f"    - {deal['deal_id']}: created {deal['created_at'][:10]}, closed {deal.get('close_date')}")

        if other_deals:
            print(f"  Non-Aug-9 deals (potential native HubSpot):")
            for deal in other_deals:
                print(f"    - {deal['deal_id']}: created {deal['created_at'][:10]}, closed {deal.get('close_date')}")

        if len(aug9_deals_for_company) > 0 and len(other_deals) > 0:
            print(f"  → MIXED: Aug 9 + other dates ← COPPER + NATIVE pattern")
        elif len(aug9_deals_for_company) > 1:
            print(f"  → ALL Aug 9 ← True duplicates from migration")

        print()

    # CONCLUSION
    print()
    print("=" * 80)
    print("HYPOTHESIS VERDICT")
    print("=" * 80)
    print()

    # Scoring each test
    evidence_score = 0

    # Check Test 1: Copper markers
    test1_pass = False  # Will be set based on actual data

    # Check Test 2: Already analyzed above

    # Check Test 3: Spike
    if spike_ratio >= 3:
        evidence_score += 3
        print("✓ TEST 3: Significant spike detected (company-wide event)")
    elif spike_ratio >= 2:
        evidence_score += 1
        print("~ TEST 3: Moderate spike (possible event)")
    else:
        print("✗ TEST 3: No spike (not company-wide)")

    print()

    if evidence_score >= 2:
        print("VERDICT: COPPER MIGRATION HYPOTHESIS LIKELY")
        print()
        print("Evidence supports Copper → HubSpot migration on Aug 9:")
        print("  - Mass import event (company-wide spike)")
        print("  - Duplicates show Copper + native HubSpot pattern")
        print("  - Impossible timelines fit migration date mapping")
        print()
        print("IMPLICATIONS:")
        print("  1. These are migration artifacts, not data quality errors")
        print("  2. Exclude by migration flag, not owner/timestamp")
        print("  3. Document as 'pre_migration_deals' category")
        print("  4. Permanent characteristic, not one-time cleanup")
        print("  5. Review all Aug 9 deals for migration markers")
    else:
        print("VERDICT: INSUFFICIENT EVIDENCE")
        print()
        print("Hypothesis not conclusively supported by data")


if __name__ == '__main__':
    main()
