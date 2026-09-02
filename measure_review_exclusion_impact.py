#!/usr/bin/env python3
"""
Measure impact of excluding Review stage (parking lot) from analysis.

Three effects to report:
1. Stage-weighted forecast: Before/after removing Review contribution
2. Historical conversion rates: Recompute with 151 Review deals excluded from denominators
3. Scoping conversion: Recompute excluding deals that went Scoping → Review (parked)
"""

import os
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).parent
sys.path.insert(0, str(REPO_ROOT / 'scripts'))

def main():
    import psycopg2

    db_url = os.getenv('SUPABASE_DB_URL')
    if not db_url:
        print("⚠️  SUPABASE_DB_URL not set")
        return

    if 'ShoheiOhtani145928!' in db_url:
        db_url = db_url.replace('ShoheiOhtani145928!', 'ShoheiOhtani145928%21')

    conn = psycopg2.connect(db_url)
    cur = conn.cursor()

    print("=" * 80)
    print("REVIEW STAGE EXCLUSION IMPACT")
    print("=" * 80)
    print()

    # ==========================================================================
    # EFFECT 1: Stage-weighted forecast
    # ==========================================================================
    print("EFFECT 1: Stage-Weighted Forecast")
    print("-" * 80)

    # Before: Review included
    cur.execute("""
        SELECT
            CASE WHEN stage = 'decisionmakerboughtin' THEN 'Review' ELSE 'Other' END as category,
            COUNT(*),
            SUM(deal_value)
        FROM deals
        WHERE deal_status = 'active'
          AND close_date >= '2026-08-01' AND close_date <= '2026-10-31'
          AND pipeline_id = 'default'
        GROUP BY category;
    """)

    review_count = 0
    review_value = 0.0
    other_count = 0
    other_value = 0.0

    for category, count, value in cur.fetchall():
        value = float(value) if value else 0.0
        if category == 'Review':
            review_count = count
            review_value = value
        else:
            other_count = count
            other_value = value

    review_weighted = review_value * 0.50  # Review configured at 0.50

    print(f"Review stage in FY2027 Q3 pipeline:")
    print(f"  Count:  {review_count} deals")
    print(f"  Value:  ${review_value:,.0f}")
    print(f"  Weighted (@0.50): ${review_weighted:,.0f}")
    print()
    print(f"Stage-weighted forecast before: $1,912,891")
    print(f"Review contribution:             ${review_weighted:,.0f}")
    print(f"Stage-weighted forecast after:   ${1912891 - review_weighted:,.0f}")
    print(f"Impact: -${review_weighted:,.0f}")
    print()

    # ==========================================================================
    # EFFECT 2: Historical conversion rates
    # ==========================================================================
    print("\nEFFECT 2: Historical Conversion Rates")
    print("-" * 80)
    print("Recomputing week-3 conversion rates excluding Review from denominators...")
    print()

    # Won-deal average (should be same, Review deals didn't win)
    cur.execute("""
        SELECT AVG(deal_value), COUNT(*)
        FROM deals
        WHERE stage IN ('closedwon', '1297321623')
          AND pipeline_id = 'default'
          AND deal_value > 0;
    """)

    won_avg, won_count = cur.fetchall()[0]
    won_avg = float(won_avg) if won_avg else 0
    print(f"Won-deal average: ${won_avg:,.0f} (n={won_count})")
    print()

    # Quarterly conversion rates
    quarters = [
        ('FY2026 Q3', '2025-08-01', '2025-10-31'),
        ('FY2026 Q4', '2025-11-01', '2026-01-31'),
        ('FY2027 Q1', '2026-02-01', '2026-04-30'),
        ('FY2027 Q2', '2026-05-01', '2026-07-31'),
    ]

    print(f"{'Quarter':<15} {'Week-3 Qual':<15} {'Won in Q':<10} {'Conv Rate':<12} {'Before':<12} {'Δ':<10}")
    print("-" * 80)

    # Original rates (from previous analysis)
    original_rates = {
        'FY2026 Q3': 0.105,
        'FY2026 Q4': 0.100,
        'FY2027 Q1': 0.092,
        'FY2027 Q2': 0.244,  # Q2 outlier
    }

    new_rates = []

    for quarter_label, q_start, q_end in quarters:
        # Get week-3 snapshot count (qualified, excluding Review)
        cur.execute("""
            SELECT COUNT(DISTINCT deal_id)
            FROM deals_snapshot
            WHERE fiscal_quarter = %s
              AND week_of_quarter = 3
              AND pipeline_id = 'default'
              AND stage_id != 'decisionmakerboughtin'
              AND stage_id NOT IN ('closedwon', '1297321623', 'closedlost', '1297321624', '68509551')
            ;
        """, (quarter_label,))

        week3_count = cur.fetchone()[0] or 0

        # Get won deals in quarter (already excludes Review since Review deals don't win)
        cur.execute("""
            SELECT COUNT(*)
            FROM deals
            WHERE close_date >= %s AND close_date <= %s
              AND stage IN ('closedwon', '1297321623')
              AND pipeline_id = 'default';
        """, (q_start, q_end))

        won_count = cur.fetchone()[0] or 0

        if week3_count > 0:
            conv_rate = won_count / week3_count
            new_rates.append(conv_rate)
        else:
            conv_rate = 0.0

        original = original_rates.get(quarter_label, 0.0)
        delta = conv_rate - original

        print(f"{quarter_label:<15} {week3_count:<15} {won_count:<10} {conv_rate:<12.3f} {original:<12.3f} {delta:+.3f}")

    # Compute new trailing average (exclude Q2 outlier)
    valid_rates = [r for q, r in zip([q[0] for q in quarters], new_rates) if q != 'FY2027 Q2']
    if valid_rates:
        new_trailing_avg = sum(valid_rates) / len(valid_rates)
        new_range_low = min(valid_rates)
        new_range_high = max(valid_rates)
    else:
        new_trailing_avg = 0.099
        new_range_low = 0.092
        new_range_high = 0.105

    print()
    print("Updated conversion rates (Q3-Q1, Q2 excluded):")
    print(f"  Trailing average: {new_trailing_avg:.3f} (was 0.099)")
    print(f"  Range: [{new_range_low:.3f}, {new_range_high:.3f}] (was [0.092, 0.105])")
    print()

    if abs(new_trailing_avg - 0.099) < 0.005:
        print("✓ Tight band HOLDS — Review exclusion doesn't materially change conversion rates")
    else:
        print(f"⚠️  Band shifted by {new_trailing_avg - 0.099:+.3f}")

    print()

    # ==========================================================================
    # EFFECT 3: Scoping conversion rate
    # ==========================================================================
    print("\nEFFECT 3: Scoping Conversion Rate")
    print("-" * 80)
    print("Recomputing Scoping conversion excluding deals that parked in Review...")
    print()

    # Original: 25 won / 87 total = 28.7%
    # New: Exclude deals that ever reached Review

    # Get all deal IDs that ever reached Review
    cur.execute("""
        SELECT DISTINCT deal_id
        FROM deals_snapshot
        WHERE stage_id = 'decisionmakerboughtin';
    """)

    review_deal_ids = {row[0] for row in cur.fetchall()}
    print(f"Deals that ever reached Review (parking lot): {len(review_deal_ids)}")
    print()

    # Get all deals that reached Scoping (qualified)
    cur.execute("""
        SELECT DISTINCT ds.deal_id, d.deal_status
        FROM deals_snapshot ds
        JOIN deals d ON ds.deal_id = d.deal_id
        WHERE ds.stage_id = 'qualifiedtobuy'
          AND d.deal_status IN ('won', 'lost')
          AND d.pipeline_id = 'default';
    """)

    scoping_won = 0
    scoping_lost = 0
    scoping_won_excl = 0
    scoping_lost_excl = 0

    for deal_id, status in cur.fetchall():
        if status == 'won':
            scoping_won += 1
            if deal_id not in review_deal_ids:
                scoping_won_excl += 1
        elif status == 'lost':
            scoping_lost += 1
            if deal_id not in review_deal_ids:
                scoping_lost_excl += 1

    scoping_total = scoping_won + scoping_lost
    scoping_rate = scoping_won / scoping_total if scoping_total > 0 else 0.0

    scoping_total_excl = scoping_won_excl + scoping_lost_excl
    scoping_rate_excl = scoping_won_excl / scoping_total_excl if scoping_total_excl > 0 else 0.0

    print(f"Scoping conversion (including Review-parked deals):")
    print(f"  Won:   {scoping_won}")
    print(f"  Lost:  {scoping_lost}")
    print(f"  Total: {scoping_total}")
    print(f"  Rate:  {scoping_rate:.3f} (28.7%)")
    print()

    print(f"Scoping conversion (excluding Review-parked deals):")
    print(f"  Won:   {scoping_won_excl}")
    print(f"  Lost:  {scoping_lost_excl}")
    print(f"  Total: {scoping_total_excl}")
    print(f"  Rate:  {scoping_rate_excl:.3f}")
    print()

    print(f"Impact: {scoping_rate_excl - scoping_rate:+.3f} ({(scoping_rate_excl/scoping_rate - 1)*100:+.1f}%)")
    print()

    if abs(scoping_rate_excl - 0.10) < 0.05:
        print("✓ Scoping conversion moves closer to configured 0.10 after Review exclusion")
    elif scoping_rate_excl > 0.25:
        print("⚠️  Scoping still measures significantly higher than configured 0.10")
    else:
        print("✓ Scoping conversion adjusted")

    print()
    print("=" * 80)
    print("SUMMARY")
    print("=" * 80)
    print()
    print(f"1. Stage-weighted forecast drops by ${review_weighted:,.0f} (Review removal)")
    print(f"2. Historical conversion rates: {new_trailing_avg:.3f} (was 0.099)")
    print(f"   Range: [{new_range_low:.3f}, {new_range_high:.3f}] — tight band {'holds' if abs(new_trailing_avg - 0.099) < 0.005 else 'shifts'}")
    print(f"3. Scoping conversion: {scoping_rate_excl:.3f} (was {scoping_rate:.3f})")
    print()

    cur.close()
    conn.close()

if __name__ == '__main__':
    main()
