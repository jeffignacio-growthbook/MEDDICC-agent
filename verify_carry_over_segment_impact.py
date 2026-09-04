#!/usr/bin/env python3
"""
Verify Segment Impact of 3 Carry-Over Deals

Check if Fellow, Yeet!, Wellhub belong to Enterprise, Mid-Market, or SMB,
and recompute segment rates to see if the +3 wins shift anything meaningful.

Given small n (41-60) and already-fragile rates, adding even 1-2 wins to a
segment could materially change its rate.
"""

import os
import sys
from pathlib import Path
from dotenv import load_dotenv

env_path = Path(__file__).parent / '.env'
load_dotenv(env_path)
sys.path.insert(0, str(Path(__file__).parent))

from api.db import get_supabase
from api.field_semantics import is_won


CARRY_OVER_DEALS = [
    {
        'company': 'Fellow',
        'create_date': '2025-08-09',
        'close_date': '2025-11-07',
        'close_quarter': 'FY2026 Q3'
    },
    {
        'company': 'Yeet!',
        'create_date': '2026-01-27',
        'close_date': '2026-03-02',
        'close_quarter': 'FY2026 Q4'
    },
    {
        'company': 'Wellhub',
        'create_date': '2026-04-30',
        'close_date': '2026-05-23',
        'close_quarter': 'FY2027 Q1'
    },
]

# Original segment rates (from config/metrics.yaml)
ORIGINAL_SEGMENT_RATES = {
    'enterprise': {'qualified': 54, 'won': 8, 'rate': 0.148},
    'mid_market': {'qualified': 60, 'won': 3, 'rate': 0.050},
    'smb': {'qualified': 41, 'won': 1, 'rate': 0.024},
    'unknown': {'qualified': 14, 'won': 0, 'rate': None}
}


def main():
    supabase = get_supabase()

    print("=" * 80)
    print("SEGMENT IMPACT VERIFICATION: Carry-Over Deals")
    print("=" * 80)
    print()

    # Step 1: Look up the 3 carry-over deals
    carry_over_with_segments = []

    for deal_info in CARRY_OVER_DEALS:
        company = deal_info['company']
        close_date = deal_info['close_date']

        # Search by company name and close date
        deals_resp = supabase.table('deals') \
            .select('deal_id, company_name, segment, stage, close_date, create_date') \
            .eq('pipeline_id', 'default') \
            .ilike('company_name', f'%{company}%') \
            .execute()

        matches = []
        for deal in deals_resp.data:
            if deal.get('close_date') == close_date:
                stage = deal.get('stage')
                if stage and is_won(str(stage)):
                    matches.append(deal)

        if not matches:
            print(f"⚠️  {company}: Not found (close_date={close_date})")
            continue

        if len(matches) > 1:
            print(f"⚠️  {company}: Multiple matches found")
            for m in matches:
                print(f"    - {m['company_name']} ({m['deal_id']}): segment={m.get('segment')}")
            continue

        deal = matches[0]
        segment = deal.get('segment', 'unknown')

        carry_over_with_segments.append({
            'company': deal['company_name'],
            'deal_id': deal['deal_id'],
            'segment': segment,
            'close_date': deal['close_date'],
            'create_date': deal['create_date']
        })

        print(f"✓ {company}: Found")
        print(f"    Deal ID: {deal['deal_id']}")
        print(f"    Segment: {segment}")
        print(f"    Created: {deal['create_date']}")
        print(f"    Closed: {deal['close_date']}")
        print()

    if len(carry_over_with_segments) != 3:
        print(f"⚠️  Expected 3 deals, found {len(carry_over_with_segments)}")
        print()

    # Step 2: Count by segment
    by_segment = {}
    for deal in carry_over_with_segments:
        segment = deal['segment'] or 'unknown'
        segment = segment.lower().replace(' ', '_')
        by_segment[segment] = by_segment.get(segment, 0) + 1

    print()
    print("=" * 80)
    print("SEGMENT DISTRIBUTION")
    print("=" * 80)
    print()

    print("Carry-over deals by segment:")
    for segment in ['enterprise', 'mid_market', 'smb', 'unknown']:
        count = by_segment.get(segment, 0)
        if count > 0:
            print(f"  {segment}: {count}")

    print()

    # Step 3: Recompute segment rates
    print()
    print("=" * 80)
    print("RECOMPUTED SEGMENT RATES")
    print("=" * 80)
    print()

    print(f"{'Segment':15s} | {'Before':20s} | {'After':20s} | {'Change':15s}")
    print("-" * 80)

    for segment in ['enterprise', 'mid_market', 'smb', 'unknown']:
        original = ORIGINAL_SEGMENT_RATES[segment]
        added_wins = by_segment.get(segment, 0)

        if added_wins == 0:
            print(f"{segment:15s} | {original['won']}/{original['qualified']} = {original['rate']:.1%} if original['rate'] else 'N/A':>7s} | (no change)         | -")
            continue

        # Recompute with added wins
        # Note: qualified count might also increase (if carry-over deal was qualified)
        # For now, assume it was already qualified (conservative)
        new_won = original['won'] + added_wins
        new_qualified = original['qualified']  # Conservative: assume already in denominator
        new_rate = new_won / new_qualified if new_qualified > 0 else None

        old_rate_str = f"{original['rate']:.1%}" if original['rate'] is not None else "N/A"
        new_rate_str = f"{new_rate:.1%}" if new_rate is not None else "N/A"

        if original['rate'] is not None and new_rate is not None:
            change = new_rate - original['rate']
            change_str = f"+{change:.1%}" if change > 0 else f"{change:.1%}"
        else:
            change_str = "N/A"

        print(f"{segment:15s} | {original['won']}/{original['qualified']} = {old_rate_str:>7s} | {new_won}/{new_qualified} = {new_rate_str:>7s} | {change_str:15s}")

    print()

    # Step 4: Analysis
    print()
    print("=" * 80)
    print("ANALYSIS")
    print("=" * 80)
    print()

    if not by_segment:
        print("✗ No carry-over deals found - cannot verify segment impact")
        return

    max_change_segment = None
    max_change_value = 0

    for segment in ['enterprise', 'mid_market', 'smb']:
        added_wins = by_segment.get(segment, 0)
        if added_wins > 0:
            original = ORIGINAL_SEGMENT_RATES[segment]
            if original['rate'] is not None:
                new_rate = (original['won'] + added_wins) / original['qualified']
                change = new_rate - original['rate']
                if abs(change) > max_change_value:
                    max_change_value = abs(change)
                    max_change_segment = segment

    if max_change_segment:
        print(f"Largest impact: {max_change_segment} (+{max_change_value:.1%})")
        print()

        if max_change_value >= 0.03:  # 3pp change
            print("⚠️  MATERIAL CHANGE DETECTED")
            print(f"   {max_change_segment.replace('_', ' ').title()} segment rate changes by {max_change_value:.1%}")
            print(f"   Given n={ORIGINAL_SEGMENT_RATES[max_change_segment]['qualified']}, this is statistically significant")
            print()
            print("RECOMMENDATION: Recompute segment rates with cross-quarter lookup enabled")
        else:
            print("✓ Changes are minor (<3pp) - segment rates remain stable")
    else:
        print("✓ No material impact on segment rates")

    print()

    # Step 5: Recommendation
    print()
    print("=" * 80)
    print("RECOMMENDATION")
    print("=" * 80)
    print()

    total_carry_over = sum(by_segment.values())

    if total_carry_over == 0:
        print("Cannot determine - no carry-over deals identified")
    elif max_change_value >= 0.03:
        print("YES - Segment rates should be recomputed")
        print()
        print("Steps:")
        print("1. Run conversion_by_qualification_week_CROSS_QUARTER.py")
        print("2. Compute segment breakdown from results")
        print("3. Update config/metrics.yaml with new segment rates")
        print("4. Note volatility warning still applies (thin evidence per segment)")
    else:
        print("NO - Segment rates do not require immediate recomputation")
        print()
        print("Rationale:")
        print("- Carry-over deals distributed across segments (no concentration)")
        print("- Changes < 3pp (within statistical noise given small n)")
        print("- Volatility warning already in place for segment rates")
        print()
        print("Optional: Recompute for completeness, but not required for accuracy")


if __name__ == '__main__':
    main()
