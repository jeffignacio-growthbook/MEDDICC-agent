#!/usr/bin/env python3
"""
Confirm SMB Rate Shift

Verify which specific deals caused SMB rate to shift from 2.4% to 7.3%.
Was it the 2 carry-over deals (Fellow, Yeet!) or something else?

Original: 1/41 = 2.4%
Updated: 3/41 = 7.3%

Expected: +2 wins from carry-over (Fellow, Yeet!)
"""

import os
import sys
from pathlib import Path
from dotenv import load_dotenv

env_path = Path(__file__).parent / '.env'
load_dotenv(env_path)
sys.path.insert(0, str(Path(__file__).parent))

from api.db import get_supabase


def main():
    supabase = get_supabase()

    print("=" * 80)
    print("SMB RATE SHIFT CONFIRMATION")
    print("=" * 80)
    print()

    # The 3 carry-over deals
    CARRY_OVER = [
        ('Fellow', '2025-08-09', '2025-11-07', 'FY2026 Q3'),
        ('Yeet!', '2026-01-27', '2026-03-02', 'FY2026 Q4'),
        ('Wellhub', '2026-04-30', '2026-05-23', 'FY2027 Q1'),
    ]

    print("Step 1: Verify carry-over deals and their segments")
    print("-" * 80)

    carry_over_segments = []

    for company, create_date, close_date, quarter in CARRY_OVER:
        result = supabase.table('deals') \
            .select('deal_id, company_name, segment, create_date, close_date') \
            .ilike('company_name', f'%{company}%') \
            .eq('close_date', close_date) \
            .execute()

        if result.data:
            deal = result.data[0]
            segment = deal.get('segment', 'unknown')
            carry_over_segments.append({
                'company': deal['company_name'],
                'segment': segment,
                'quarter': quarter
            })

            print(f"{company}:")
            print(f"  Segment: {segment}")
            print(f"  Quarter: {quarter}")
            print()
        else:
            print(f"⚠️  {company}: Not found")
            print()

    # Count by segment
    smb_count = sum(1 for d in carry_over_segments if (d['segment'] or '').lower() == 'smb')
    mid_market_count = sum(1 for d in carry_over_segments if (d['segment'] or '').lower() in ['mid-market', 'mid_market', 'midmarket'])
    enterprise_count = sum(1 for d in carry_over_segments if (d['segment'] or '').lower() == 'enterprise')

    print()
    print("Step 2: Segment distribution")
    print("-" * 80)
    print(f"SMB: {smb_count}")
    print(f"Mid-Market: {mid_market_count}")
    print(f"Enterprise: {enterprise_count}")
    print()

    # Verify the math
    print()
    print("Step 3: Confirm SMB rate calculation")
    print("-" * 80)

    ORIGINAL_SMB = {'qualified': 41, 'won': 1, 'rate': 0.024}

    new_won = ORIGINAL_SMB['won'] + smb_count
    new_rate = new_won / ORIGINAL_SMB['qualified']

    print(f"Original SMB:")
    print(f"  Won: {ORIGINAL_SMB['won']}/{ORIGINAL_SMB['qualified']} = {ORIGINAL_SMB['rate']:.1%}")
    print()

    print(f"After adding {smb_count} carry-over deal(s):")
    print(f"  Won: {new_won}/{ORIGINAL_SMB['qualified']} = {new_rate:.1%}")
    print()

    expected_rate = 0.073  # 3/41
    if abs(new_rate - expected_rate) < 0.001:
        print(f"✓ Matches expected rate (7.3%)")
        print()
        print(f"CONFIRMED: The SMB rate shift from 2.4% → 7.3% is caused by")
        print(f"adding {smb_count} carry-over deal(s) (Fellow, Yeet!) to SMB segment.")
    else:
        print(f"⚠️  Rate mismatch:")
        print(f"  Expected: 7.3%")
        print(f"  Calculated: {new_rate:.1%}")
        print()
        print("  This suggests:")
        print("  - Carry-over deals don't fully explain the shift, OR")
        print("  - There's another change we haven't accounted for")

    print()

    # Check Mid-Market impact
    if mid_market_count > 0:
        print()
        print("Step 4: Mid-Market impact")
        print("-" * 80)

        ORIGINAL_MM = {'qualified': 60, 'won': 3, 'rate': 0.050}

        new_mm_won = ORIGINAL_MM['won'] + mid_market_count
        new_mm_rate = new_mm_won / ORIGINAL_MM['qualified']

        print(f"Original Mid-Market:")
        print(f"  Won: {ORIGINAL_MM['won']}/{ORIGINAL_MM['qualified']} = {ORIGINAL_MM['rate']:.1%}")
        print()

        print(f"After adding {mid_market_count} carry-over deal(s):")
        print(f"  Won: {new_mm_won}/{ORIGINAL_MM['qualified']} = {new_mm_rate:.1%}")
        print()

        change = new_mm_rate - ORIGINAL_MM['rate']
        print(f"Change: +{change:.1%}")

        if change >= 0.03:
            print("  → Material change (≥3pp) - recomputation needed")
        else:
            print("  → Minor change (<3pp) - within noise")

    print()


if __name__ == '__main__':
    main()
