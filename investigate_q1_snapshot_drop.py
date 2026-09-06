#!/usr/bin/env python3
"""
Investigate Q1 Week 11-13 Snapshot Drop

Check if the 45% drop (685 -> 377 rows) is:
1. Normal quarter-end pattern (deals closing out)
2. Snapshot job behavior change
3. Q1-specific anomaly

Compare against Q3 and Q4 late-quarter patterns.
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


def analyze_quarter_end_pattern(sb, quarter_id):
    """Analyze how snapshots change in late-quarter weeks."""
    print(f"\n{quarter_id}")
    print("="*70)

    # Get week 8-13 row counts and deal_status distribution
    weeks_data = {}

    for week in range(8, 14):
        result = sb.table('deals_snapshot') \
            .select('deal_id, deal_status') \
            .eq('fiscal_quarter', quarter_id) \
            .eq('week_of_quarter', week) \
            .execute()

        if not result.data:
            continue

        # Count by deal_status
        status_counts = defaultdict(int)
        for row in result.data:
            status = row.get('deal_status', 'unknown')
            status_counts[status] += 1

        weeks_data[week] = {
            'total': len(result.data),
            'by_status': dict(status_counts)
        }

    # Print summary
    print(f"\n{'Week':>6} {'Total':>7} {'Active':>7} {'Won':>7} {'Lost':>7} {'Unknown':>7}")
    print("-"*55)

    for week in sorted(weeks_data.keys()):
        data = weeks_data[week]
        total = data['total']
        by_status = data['by_status']

        active = by_status.get('active', 0)
        won = by_status.get('won', 0)
        lost = by_status.get('lost', 0)
        unknown = by_status.get('unknown', 0)

        print(f"  {week:>4} {total:>7} {active:>7} {won:>7} {lost:>7} {unknown:>7}")

    # Calculate decline from week 10 to week 13
    if 10 in weeks_data and 13 in weeks_data:
        w10_total = weeks_data[10]['total']
        w13_total = weeks_data[13]['total']
        decline_pct = ((w13_total - w10_total) / w10_total * 100) if w10_total > 0 else 0

        print(f"\nWeek 10 → 13 change: {w10_total} → {w13_total} ({decline_pct:+.1f}%)")

        return {
            'quarter': quarter_id,
            'w10_total': w10_total,
            'w13_total': w13_total,
            'decline_pct': decline_pct,
            'w10_active': weeks_data[10]['by_status'].get('active', 0),
            'w13_active': weeks_data[13]['by_status'].get('active', 0)
        }

    return None


def check_snapshot_job_behavior(sb, quarter_id):
    """Check if snapshot job changed behavior around the drop."""
    print(f"\n{quarter_id} - Snapshot Job Behavior")
    print("="*70)

    # Check snapshot_source distribution by week
    print(f"\n{'Week':>6} {'Total':>7} | Snapshot Sources")
    print("-"*70)

    for week in range(8, 14):
        result = sb.table('deals_snapshot') \
            .select('snapshot_source') \
            .eq('fiscal_quarter', quarter_id) \
            .eq('week_of_quarter', week) \
            .execute()

        if not result.data:
            continue

        # Count by source
        source_counts = defaultdict(int)
        for row in result.data:
            source = row.get('snapshot_source', 'unknown')
            source_counts[source] += 1

        total = len(result.data)
        sources_str = ', '.join(f"{src}:{cnt}" for src, cnt in sorted(source_counts.items()))

        print(f"  {week:>4} {total:>7} | {sources_str}")


def main():
    sb = get_supabase()

    print("="*70)
    print("INVESTIGATING Q1 WEEK 11-13 SNAPSHOT DROP")
    print("="*70)
    print("\nQuestion: Is late-quarter decline normal (deals closing) or anomalous?")

    # Analyze all three quarters
    quarters = ['FY2026 Q3', 'FY2026 Q4', 'FY2027 Q1']
    patterns = []

    for quarter in quarters:
        pattern = analyze_quarter_end_pattern(sb, quarter)
        if pattern:
            patterns.append(pattern)

        # Check snapshot job behavior for Q1 specifically
        if quarter == 'FY2027 Q1':
            check_snapshot_job_behavior(sb, quarter)

    # Compare patterns
    print("\n" + "="*70)
    print("COMPARISON: Late-Quarter Patterns")
    print("="*70)
    print()

    print(f"{'Quarter':>12} {'Week 10':>10} {'Week 13':>10} {'Change':>10} {'Active W10':>11} {'Active W13':>11}")
    print("-"*75)

    for p in patterns:
        print(f"{p['quarter']:>12} {p['w10_total']:>10} {p['w13_total']:>10} {p['decline_pct']:>9.1f}% "
              f"{p['w10_active']:>11} {p['w13_active']:>11}")

    # Analysis
    print("\n" + "="*70)
    print("CONCLUSION")
    print("="*70)
    print()

    # Check if all quarters show decline
    declines = [p['decline_pct'] for p in patterns]
    all_decline = all(d < -10 for d in declines)

    if all_decline:
        print("✓ NORMAL PATTERN: All quarters show late-quarter decline")
        print(f"  Q3: {patterns[0]['decline_pct']:.1f}%")
        print(f"  Q4: {patterns[1]['decline_pct']:.1f}%")
        print(f"  Q1: {patterns[2]['decline_pct']:.1f}%")
        print()
        print("Interpretation:")
        print("  - Deals close (won/lost) toward quarter end, removing them from active snapshots")
        print("  - This is EXPECTED behavior, not an anomaly")
        print()
        print("Implication for Trigger 6:")
        print("  - Must compare week N against equivalent week N in prior quarters")
        print("  - NOT a flat trailing-4-week median (doesn't account for quarter phase)")
        print("  - Late-quarter weeks naturally have fewer rows than mid-quarter")
    else:
        q1_decline = patterns[2]['decline_pct']
        others = [patterns[0]['decline_pct'], patterns[1]['decline_pct']]

        if q1_decline < min(others) - 20:
            print("⚠️  ANOMALY: Q1 decline is significantly steeper than Q3/Q4")
            print(f"  Q1: {q1_decline:.1f}% vs Q3/Q4: {min(others):.1f}% to {max(others):.1f}%")
            print()
            print("Recommendation: Investigate Q1 snapshot job for errors around week 11")
        else:
            print("✓ VARIATION: Q1 shows similar late-quarter pattern to Q3/Q4")
            print("  Decline magnitude is within normal range")


if __name__ == '__main__':
    main()
