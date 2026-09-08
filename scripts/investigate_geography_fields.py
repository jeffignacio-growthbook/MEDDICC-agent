#!/usr/bin/env python3
"""
Investigate geography/country fields for region classification.

Checks companies and deals tables for:
- country fields (billing_country, company_country, hq_country, etc.)
- geography fields
- region fields
- location fields
"""

import os
import sys
from pathlib import Path
from dotenv import load_dotenv

env_path = Path(__file__).parent.parent / '.env'
load_dotenv(env_path)
sys.path.insert(0, str(Path(__file__).parent.parent))

from api.db import get_supabase

def check_geography_fields():
    sb = get_supabase()

    print("=" * 80)
    print("GEOGRAPHY FIELD INVESTIGATION")
    print("=" * 80)
    print()

    # Check deals table (companies table doesn't exist)
    print("=" * 80)
    print("DEALS TABLE")
    print("=" * 80)
    print()

    deals = sb.table('deals').select('*').limit(5).execute()
    if deals.data:
        all_cols = deals.data[0].keys()

        # Filter to geography-related columns
        geo_cols = sorted([
            k for k in all_cols
            if any(term in k.lower() for term in ['country', 'geo', 'region', 'location', 'address', 'city', 'state'])
        ])

        if geo_cols:
            print(f"Found {len(geo_cols)} geography-related columns:")
            print()
            for col in geo_cols:
                print(f"  - {col}")
                # Show sample values
                values = [d.get(col) for d in deals.data if d.get(col)]
                if values:
                    print(f"    Sample values: {values[:3]}")
                else:
                    print(f"    (all NULL in sample)")
                print()
        else:
            print("❌ NO geography-related columns found")
            print()
            print("All columns:")
            for col in sorted(all_cols):
                print(f"  - {col}")
    else:
        print("No deals data available")

    print()
    print("=" * 80)
    print("SUMMARY")
    print("=" * 80)
    print()

    # Determine if region classification is possible
    deals_geo = deals.data and any(
        any(term in k.lower() for term in ['country', 'geo', 'region'])
        for k in deals.data[0].keys()
    ) if deals.data else False

    if deals_geo:
        print("✅ Geography fields found in deals table - region classification possible")
    else:
        print("❌ NO geography fields found - must use owner-based proxy")
        print()
        print("Data gap identified:")
        print("  - No companies table exists")
        print("  - No geography fields on deals table")
        print("  - Region classification must use owner as proxy")


if __name__ == "__main__":
    check_geography_fields()
