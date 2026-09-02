#!/usr/bin/env python3
"""
Measure Review exclusion impact using proper scope filter from point_in_time.py
"""

import os
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).parent
sys.path.insert(0, str(REPO_ROOT / 'scripts'))

def main():
    from supabase import create_client
    from utils import load_client_config, get_fiscal_quarter
    from supabase_client import select_all
    from analytics.point_in_time import load_scope_config, is_deal_in_analytics_scope

    SUPABASE_URL = os.getenv('SUPABASE_URL')
    SUPABASE_KEY = os.getenv('SUPABASE_SERVICE_KEY')

    if not SUPABASE_URL or not SUPABASE_KEY:
        print("⚠️  SUPABASE_URL or SUPABASE_SERVICE_KEY not set")
        return

    sb = create_client(SUPABASE_URL, SUPABASE_KEY)
    config = load_client_config()

    # Load scope filter BEFORE Review exclusion
    excl_pipelines_old, stage_cfg_old = load_scope_config(config)

    # Reload config with Review now excluded
    config = load_client_config()  # Fresh reload picks up exclude_from_analysis: true
    excl_pipelines_new, stage_cfg_new = load_scope_config(config)

    renewal_pipeline_ids = set(config.get('pipeline', {}).get('value_field', {}).get('renewal_pipeline_ids', []))

    print("=" * 80)
    print("REVIEW EXCLUSION IMPACT (Using Proper Scope Filter)")
    print("=" * 80)
    print()

    # ==========================================================================
    # EFFECT 1: Stage-weighted forecast
    # ==========================================================================
    print("EFFECT 1: Stage-Weighted Forecast")
    print("-" * 80)

    deals = select_all(sb, 'deals',
        columns='deal_id,pipeline_id,stage,deal_value,deal_status,close_date')

    # FY2027 Q3 pipeline (Aug 1 - Oct 31, 2026)
    from datetime import date
    q3_deals_before = []
    q3_deals_after = []
    review_value = 0.0

    for d in deals:
        if d.get('deal_status') != 'active':
            continue
        if d.get('pipeline_id') in renewal_pipeline_ids:
            continue

        close_date_str = d.get('close_date')
        if not close_date_str:
            continue

        try:
            close_dt = date.fromisoformat(str(close_date_str)[:10])
        except:
            continue

        _, _, fq_label = get_fiscal_quarter(close_dt, config)
        if fq_label != 'FY2027 Q3':
            continue

        stage_id = d.get('stage')
        pipeline_id = d.get('pipeline_id', 'default')

        # Check if qualified BEFORE Review exclusion
        if is_deal_in_analytics_scope(stage_id, pipeline_id, excl_pipelines_old, stage_cfg_old):
            q3_deals_before.append(d)

        # Check if qualified AFTER Review exclusion
        if is_deal_in_analytics_scope(stage_id, pipeline_id, excl_pipelines_new, stage_cfg_new):
            q3_deals_after.append(d)
        elif stage_id == 'decisionmakerboughtin':
            # This is a Review deal that got excluded
            review_value += float(d.get('deal_value') or 0)

    review_weighted = review_value * 0.50
    before_count = len(q3_deals_before)
    after_count = len(q3_deals_after)

    print(f"FY2027 Q3 qualified pipeline:")
    print(f"  Before Review exclusion: {before_count} deals")
    print(f"  After Review exclusion:  {after_count} deals")
    print(f"  Review deals excluded:   {before_count - after_count} deals, ${review_value:,.0f}")
    print()
    print(f"Review contribution to stage-weighted (@0.50): ${review_weighted:,.0f}")
    print(f"Impact on stage-weighted forecast: -${review_weighted:,.0f}")
    print()

    # ==========================================================================
    # EFFECT 2: Historical conversion rates
    # ==========================================================================
    print("\nEFFECT 2: Historical Conversion Rates")
    print("-" * 80)

    # Get won-deal average
    won_deals = [d for d in deals
                 if d.get('stage') in ['closedwon', '1297321623']
                 and d.get('pipeline_id') not in renewal_pipeline_ids
                 and d.get('deal_value') and float(d['deal_value']) > 0]

    if won_deals:
        won_avg = sum(float(d['deal_value']) for d in won_deals) / len(won_deals)
    else:
        won_avg = 0

    print(f"Won-deal average: ${won_avg:,.0f} (n={len(won_deals)})")
    print()

    # Recompute conversion rates for each quarter
    quarters_to_check = [
        ('FY2026 Q3', '2025-08-01', '2025-10-31'),
        ('FY2026 Q4', '2025-11-01', '2026-01-31'),
        ('FY2027 Q1', '2026-02-01', '2026-04-30'),
        ('FY2027 Q2', '2026-05-01', '2026-07-31'),
    ]

    print(f"{'Quarter':<15} {'Before':<12} {'After':<12} {'Won':<8} {'Rate Before':<13} {'Rate After':<13} {'Δ':<10}")
    print("-" * 90)

    rates_before = []
    rates_after = []

    for fq_label, q_start, q_end in quarters_to_check:
        # Get week-3 snapshot
        week3_rows = select_all(sb, 'deals_snapshot',
            columns='deal_id,stage_id,pipeline_id',
            filters=[('eq', 'fiscal_quarter', fq_label),
                     ('eq', 'week_of_quarter', 3)])

        # Count qualified BEFORE Review exclusion
        week3_before = [r for r in week3_rows
                        if r.get('pipeline_id') not in renewal_pipeline_ids
                        and is_deal_in_analytics_scope(
                            r.get('stage_id'),
                            r.get('pipeline_id'),
                            excl_pipelines_old,
                            stage_cfg_old)]

        # Count qualified AFTER Review exclusion
        week3_after = [r for r in week3_rows
                       if r.get('pipeline_id') not in renewal_pipeline_ids
                       and is_deal_in_analytics_scope(
                           r.get('stage_id'),
                           r.get('pipeline_id'),
                           excl_pipelines_new,
                           stage_cfg_new)]

        # Count won deals in quarter
        won_in_q = len([d for d in won_deals
                        if d.get('close_date')
                        and q_start <= str(d['close_date'])[:10] <= q_end])

        count_before = len(week3_before)
        count_after = len(week3_after)
        rate_before = won_in_q / count_before if count_before > 0 else 0.0
        rate_after = won_in_q / count_after if count_after > 0 else 0.0

        if fq_label != 'FY2027 Q2':  # Exclude Q2 outlier from averages
            rates_before.append(rate_before)
            rates_after.append(rate_after)

        delta = rate_after - rate_before

        print(f"{fq_label:<15} {count_before:<12} {count_after:<12} {won_in_q:<8} {rate_before:<13.3f} {rate_after:<13.3f} {delta:+.3f}")

    avg_before = sum(rates_before) / len(rates_before) if rates_before else 0.0
    avg_after = sum(rates_after) / len(rates_after) if rates_after else 0.0

    print()
    print(f"Trailing 3Q average (Q2 excluded):")
    print(f"  Before Review exclusion: {avg_before:.3f}")
    print(f"  After Review exclusion:  {avg_after:.3f}")
    print(f"  Change: {avg_after - avg_before:+.3f}")
    print()

    if abs(avg_after - avg_before) < 0.01:
        print("✓ Tight band HOLDS — Review exclusion has minimal impact")
    else:
        print(f"⚠️  Band shifted by {avg_after - avg_before:+.3f}")

    print()
    print("=" * 80)
    print("SUMMARY")
    print("=" * 80)
    print(f"1. Stage-weighted forecast: -${review_weighted:,.0f}")
    print(f"2. Historical conversion: {avg_before:.3f} → {avg_after:.3f} ({avg_after - avg_before:+.3f})")
    print(f"3. Week-3 qualified counts drop by ~{100 * (1 - after_count/before_count if before_count > 0 else 0):.0f}% (Review parking lot removed)")

if __name__ == '__main__':
    main()
