#!/usr/bin/env python3
"""
Find Copper Source Markers

Check every Aug 9 deal for actual source markers:
- hs_object_source
- hs_object_source_label
- hs_object_source_id
- Custom properties referencing Copper/import

If a real marker exists, use it instead of created_at date proxy.
Report: present on all, some, or none of 1,510?
"""

import os
import sys
from pathlib import Path
from collections import defaultdict
from dotenv import load_dotenv

env_path = Path(__file__).parent / '.env'
load_dotenv(env_path)
sys.path.insert(0, str(Path(__file__).parent))

from api.db import get_supabase


def main():
    supabase = get_supabase()

    print("=" * 80)
    print("COPPER SOURCE MARKER SEARCH")
    print("=" * 80)
    print()

    print("Objective: Find the RIGHT exclusion criterion")
    print("  - If source markers exist: use those (not created_at proxy)")
    print("  - If markers don't exist: document reliance on date proxy")
    print()

    # Get all Aug 9 deals
    print("Fetching all Aug 9 deals...")
    aug9_deals = supabase.table('deals') \
        .select('*') \
        .gte('created_at', '2026-08-09T00:00:00') \
        .lte('created_at', '2026-08-09T23:59:59') \
        .execute()

    print(f"Total Aug 9 deals: {len(aug9_deals.data)}")
    print()

    if not aug9_deals.data:
        print("No deals found")
        return

    # Check what fields are available
    sample = aug9_deals.data[0]
    all_fields = list(sample.keys())

    print(f"Total fields per deal: {len(all_fields)}")
    print()

    # Look for standard HubSpot source fields
    print("Step 1: Checking standard HubSpot source fields")
    print("-" * 80)
    print()

    standard_source_fields = [
        'hs_object_source',
        'hs_object_source_label',
        'hs_object_source_id',
        'hs_created_by_user_id',
        'hs_createdate',
        'createdate'
    ]

    found_fields = {}

    for field in standard_source_fields:
        if field in all_fields:
            # Collect unique values
            values = defaultdict(int)
            for deal in aug9_deals.data:
                val = deal.get(field)
                if val is not None:
                    values[str(val)] += 1

            if values:
                found_fields[field] = values
                print(f"{field}:")
                sorted_vals = sorted(values.items(), key=lambda x: -x[1])
                for val, count in sorted_vals[:10]:
                    pct = count / len(aug9_deals.data) * 100
                    copper_marker = " ← COPPER MARKER?" if 'copper' in val.lower() else ""
                    print(f"  {val}: {count} ({pct:.1f}%){copper_marker}")
                if len(sorted_vals) > 10:
                    print(f"  ... and {len(sorted_vals) - 10} more")
                print()

    if not found_fields:
        print("  No standard source fields populated")
        print()

    # Look for custom fields with Copper/migration keywords
    print()
    print("Step 2: Searching for custom fields with Copper/migration keywords")
    print("-" * 80)
    print()

    copper_keywords = ['copper', 'import', 'migration', 'source', 'origin', 'crm', 'zapier', 'piesync']

    custom_fields = [f for f in all_fields if any(kw in f.lower() for kw in copper_keywords)]

    if custom_fields:
        print(f"Found {len(custom_fields)} fields with keywords:")
        for field in custom_fields:
            print(f"  - {field}")
        print()

        # Check values in these fields
        for field in custom_fields:
            values = defaultdict(int)
            for deal in aug9_deals.data:
                val = deal.get(field)
                if val is not None:
                    values[str(val)] += 1

            if values:
                print(f"{field}:")
                sorted_vals = sorted(values.items(), key=lambda x: -x[1])
                for val, count in sorted_vals[:5]:
                    pct = count / len(aug9_deals.data) * 100
                    print(f"  {val}: {count} ({pct:.1f}%)")
                if len(sorted_vals) > 5:
                    print(f"  ... and {len(sorted_vals) - 5} more")
                print()
    else:
        print("  No custom fields with Copper/migration keywords found")
        print()

    # Look for any field with "copper" value
    print()
    print("Step 3: Checking ALL fields for 'Copper' values")
    print("-" * 80)
    print()

    copper_value_fields = []

    for field in all_fields:
        has_copper = False
        for deal in aug9_deals.data[:100]:  # Sample first 100
            val = deal.get(field)
            if val and 'copper' in str(val).lower():
                has_copper = True
                break

        if has_copper:
            copper_value_fields.append(field)

    if copper_value_fields:
        print(f"Found Copper values in {len(copper_value_fields)} fields:")
        for field in copper_value_fields:
            print(f"  - {field}")

            # Show examples
            examples = []
            for deal in aug9_deals.data[:20]:
                val = deal.get(field)
                if val and 'copper' in str(val).lower():
                    examples.append((deal.get('company_name'), val))
                if len(examples) >= 3:
                    break

            for company, val in examples:
                print(f"      {company}: {val}")
            print()
    else:
        print("  No fields contain 'Copper' in their values")
        print()

    # Summary and recommendation
    print()
    print("=" * 80)
    print("FINDINGS & RECOMMENDATION")
    print("=" * 80)
    print()

    if found_fields or copper_value_fields:
        print("✓ SOURCE MARKERS FOUND")
        print()

        if found_fields:
            print("Standard HubSpot fields populated:")
            for field in found_fields.keys():
                print(f"  - {field}")

        if copper_value_fields:
            print("\nFields containing 'Copper' values:")
            for field in copper_value_fields:
                print(f"  - {field}")

        print()
        print("RECOMMENDATION:")
        print("  Use the most reliable field as exclusion criterion:")
        print()

        # Determine which field is best
        if found_fields:
            best_field = None
            best_coverage = 0

            for field, values in found_fields.items():
                total_populated = sum(values.values())
                coverage = total_populated / len(aug9_deals.data)

                print(f"  {field}: {total_populated}/{len(aug9_deals.data)} ({coverage:.1%}) populated")

                if coverage > best_coverage:
                    best_coverage = coverage
                    best_field = field

            print()
            if best_coverage >= 0.90:
                print(f"  → Use {best_field} (≥90% coverage)")
                print(f"    WHERE {best_field} IN ({list(found_fields[best_field].keys())[:3]}...)")
            else:
                print(f"  → WARNING: Best field only {best_coverage:.1%} coverage")
                print(f"    May need to combine with created_at fallback")

    else:
        print("✗ NO SOURCE MARKERS FOUND")
        print()
        print("  Neither standard HubSpot fields nor custom properties")
        print("  contain migration/Copper markers.")
        print()
        print("RECOMMENDATION:")
        print("  Must use created_at = '2026-08-09' as proxy")
        print()
        print("  Exclusion criterion:")
        print("    WHERE created_at >= '2026-08-09 00:00:00'")
        print("      AND created_at <= '2026-08-09 23:59:59'")
        print()
        print("  Limitation: This is a DATE PROXY, not semantic marker")
        print("  - Cannot distinguish migration from same-day native creation")
        print("  - Future migrations would need manual date adjustment")
        print("  - Document this limitation in metrics.yaml")

    print()

    # Export findings
    output_file = 'copper_source_markers_findings.txt'
    with open(output_file, 'w') as f:
        f.write("Copper Source Markers Search\n")
        f.write("=" * 80 + "\n\n")
        f.write(f"Total Aug 9 deals: {len(aug9_deals.data)}\n\n")

        if found_fields:
            f.write("Standard fields found:\n")
            for field, values in found_fields.items():
                f.write(f"  {field}: {len(values)} unique values\n")
            f.write("\n")

        if copper_value_fields:
            f.write("Fields with Copper values:\n")
            for field in copper_value_fields:
                f.write(f"  {field}\n")
            f.write("\n")

        if not found_fields and not copper_value_fields:
            f.write("No source markers found - must use created_at proxy\n")

    print(f"Full findings written to: {output_file}")


if __name__ == '__main__':
    main()
