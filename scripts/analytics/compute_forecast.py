#!/usr/bin/env python3
"""
Computes stage-weighted, category-weighted, and historical
conversion forecasts for open pipeline, grouped by fiscal
quarter. Reads current deals table state (not snapshots —
forecast is a point-in-time view, not a diff).

Historical conversion method applies measured week-3 conversion
rates (9.2% low, 13.5% mid, 24.4% high) to qualified pipeline.
Stores full range per metrics.yaml caveat.

Usage: python scripts/analytics/compute_forecast.py
"""

import os
import json
from datetime import date
from pathlib import Path

REPO_ROOT = Path(__file__).parent.parent.parent


def main():
    SUPABASE_URL = os.getenv('SUPABASE_URL')
    SUPABASE_KEY = os.getenv('SUPABASE_SERVICE_KEY')
    if not SUPABASE_URL or not SUPABASE_KEY:
        print("⚠️  SUPABASE_URL or SUPABASE_SERVICE_KEY not set")
        return

    from supabase import create_client
    import sys
    sys.path.insert(0, str(REPO_ROOT / 'scripts'))
    from utils import load_client_config, get_fiscal_quarter
    from supabase_client import select_all

    sb = create_client(SUPABASE_URL, SUPABASE_KEY)
    config = load_client_config()

    # Get historical conversion rates from registry
    # Verified 2026-09-01, Q2 excluded (grid coverage issue)
    # See config/metrics.yaml for full provenance
    conversion_rates = {
        'trailing_avg': 0.099,  # Q3-Q1 average (Q2 excluded)
        'range_low': 0.092,     # Q1 FY2027 (conservative)
        'range_high': 0.105,    # Q3 FY2026 (aggressive)
    }

    category_weights = (config.get('forecast', {})
                        .get('category_weights', {}))
    if not category_weights:
        print("⚠️  No forecast.category_weights configured — "
              "category-weighted forecast will be all zeros. "
              "Add config/client.yaml forecast block to enable.")

    # Build stage_id -> probability map, per pipeline
    prob_map = {}  # (pipeline_id, stage_id) -> probability
    for p in config.get('pipeline', {}).get('pipelines', []):
        for s in p.get('stages', []):
            prob_map[(p['id'], s['id'])] = s.get(
                'stage_probability', 0.0)

    # Get renewal pipeline IDs for incremental-only forecast logic
    renewal_pipeline_ids = set(
        config.get('pipeline', {}).get('value_field', {}).get('renewal_pipeline_ids', [])
    )

    # Load scope filter for historical conversion qualified check
    from analytics.point_in_time import (
        load_scope_config, is_deal_in_analytics_scope)
    excl_pipelines, stage_cfg = load_scope_config(config)

    def _qualified_in_own_pipeline(stage_id, pipeline_id):
        """Check if deal is qualified (shared scope rule, per-pipeline)."""
        if stage_id is None or not str(stage_id).strip():
            return False
        return is_deal_in_analytics_scope(
            str(stage_id), pipeline_id, set(), stage_cfg)

    deals = select_all(
        sb, 'deals',
        columns=('deal_id, pipeline_id, stage, deal_value, '
                 'new_arr, expansion_arr, '
                 'close_date, deal_status, forecast_category')
    )

    open_deals = [d for d in deals
                  if d.get('deal_status') == 'active'
                  and d.get('close_date')]

    today = date.today()

    # Group by (pipeline_id, fiscal_quarter)
    from collections import defaultdict
    groups = defaultdict(lambda: {
        'open_value': 0.0, 'open_count': 0,
        'stage_weighted': 0.0, 'category_weighted': 0.0,
        'historical_conversion_low': 0.0,
        'historical_conversion_mid': 0.0,
        'historical_conversion_high': 0.0,
        'category_breakdown': defaultdict(
            lambda: {'count': 0, 'value': 0.0, 'weighted': 0.0}),
        'uncategorized_value': 0.0,
        'unknown_incremental_count': 0,  # Track renewals with no incremental data
    })

    for d in open_deals:
        try:
            close_dt = date.fromisoformat(str(d['close_date'])[:10])
        except (ValueError, TypeError):
            continue

        _, _, fq_label = get_fiscal_quarter(close_dt, config)
        pipeline_id = d.get('pipeline_id', 'default')
        key = (pipeline_id, fq_label)
        g = groups[key]

        # Forecast basis is Incremental ARR, never renewal base
        if pipeline_id in renewal_pipeline_ids:
            # For renewals: only new_arr + expansion_arr (no renewal_revenue)
            new_arr = d.get('new_arr')
            expansion_arr = d.get('expansion_arr')

            # If both are null, incremental is unknown (not zero) — exclude
            if new_arr is None and expansion_arr is None:
                g['unknown_incremental_count'] += 1
                continue  # Skip this deal

            # Coalesce each component to 0 if the other exists
            forecast_value = float(new_arr or 0) + float(expansion_arr or 0)
        else:
            # For default pipeline: deal_value equals incremental
            forecast_value = float(d.get('deal_value') or 0)

        g['open_value'] += forecast_value
        g['open_count'] += 1

        # Stage-weighted
        stage_id = d.get('stage')
        prob = prob_map.get((pipeline_id, stage_id), 0.0)
        g['stage_weighted'] += forecast_value * prob

        # Category-weighted
        cat = d.get('forecast_category')

        # NULL treated same as OMIT (0.0 weight) - not a data quality issue
        # Only genuinely unrecognized non-null values are data quality issues
        if cat is None:
            # NULL = not yet categorized by rep, treat as OMIT (0.0)
            weight = category_weights.get('OMIT', 0.0)
            cat_label = 'NULL'
        elif cat in category_weights:
            # Recognized category
            weight = category_weights[cat]
            cat_label = cat
        else:
            # Unrecognized non-null value (typo, new picklist value, etc.)
            weight = 0.0
            cat_label = cat
            g['uncategorized_value'] += forecast_value

        weighted_value = forecast_value * weight
        g['category_weighted'] += weighted_value
        cb = g['category_breakdown'][cat_label]
        cb['count'] += 1
        cb['value'] += forecast_value
        cb['weighted'] += weighted_value

    # Get won-deal average size for Kellogg method
    # (won deals are 40% smaller than pipeline average — bias correction)
    won_stages = ['closedwon', '1297321623']  # from field_semantics.yaml
    all_won_deals = [
        d for d in deals
        if d.get('stage') in won_stages
        and d.get('pipeline_id') not in renewal_pipeline_ids
        and d.get('deal_value')
        and d['deal_value'] > 0
    ]

    if all_won_deals:
        won_deal_avg = sum(d['deal_value'] for d in all_won_deals) / len(all_won_deals)
        print(f"\n✓ Won-deal average: ${won_deal_avg:,.0f} (n={len(all_won_deals)})")
    else:
        # Fallback to open pipeline average if no won deals exist yet
        won_deal_avg = None
        print(f"\n⚠️  No won deals found — will use week-3 pipeline avg as fallback")

    # Compute historical conversion from week-3 snapshots (Kellogg method)
    # For each quarter, get week-3 snapshot count and apply conversion rates
    print("\n" + "="*70)
    print("Computing historical conversion from week-3 snapshots")
    print("="*70)

    for (pipeline_id, fq_label), g in groups.items():
        # Only for default pipeline — renewal has different motion
        if pipeline_id in renewal_pipeline_ids:
            g['historical_conversion_low'] = 0.0
            g['historical_conversion_mid'] = 0.0
            g['historical_conversion_high'] = 0.0
            continue

        # Get week-3 snapshot for this quarter
        week3_rows = select_all(
            sb, 'deals_snapshot',
            columns='deal_id,stage_id,pipeline_id,deal_value',
            filters=[('eq', 'fiscal_quarter', fq_label),
                     ('eq', 'week_of_quarter', 3)])

        if not week3_rows:
            # No week-3 snapshot yet — use current pipeline as fallback
            # (happens for current quarter before week 3)
            print(f"  ⚠️  {fq_label}: No week-3 snapshot, using current pipeline")
            week3_count = g['open_count']
            # Use won-deal average if available, else current pipeline avg
            avg_deal_size = (won_deal_avg if won_deal_avg is not None
                           else (g['open_value'] / g['open_count']
                                 if g['open_count'] > 0 else 0))
        else:
            # Filter to qualified deals in this pipeline
            week3_qualified = [
                r for r in week3_rows
                if r.get('pipeline_id') == pipeline_id
                and _qualified_in_own_pipeline(r.get('stage_id'), pipeline_id)
            ]

            week3_count = len(week3_qualified)

            # Use won-deal average (corrects -39.6% bias from using pipeline avg)
            if won_deal_avg is not None:
                avg_deal_size = won_deal_avg
                print(f"  ✓ {fq_label}: week-3 count={week3_count}, "
                      f"using won-deal avg=${avg_deal_size:,.0f} (bias-corrected)")
            else:
                # Fallback: week-3 pipeline average
                week3_value = sum(r.get('deal_value') or 0 for r in week3_qualified)
                avg_deal_size = (week3_value / week3_count
                               if week3_count > 0 else 0)
                print(f"  ⚠️  {fq_label}: week-3 count={week3_count}, "
                      f"using week-3 avg=${avg_deal_size:,.0f} (no won-deal data)")

        # Kellogg method: expected_wins = week3_count × conversion_rate
        # forecast = expected_wins × won_deal_avg (not pipeline avg — corrects 40% bias)
        g['historical_conversion_low'] = (week3_count * conversion_rates['range_low']
                                         * avg_deal_size)
        g['historical_conversion_mid'] = (week3_count * conversion_rates['trailing_avg']
                                         * avg_deal_size)
        g['historical_conversion_high'] = (week3_count * conversion_rates['range_high']
                                          * avg_deal_size)

    today_iso = today.isoformat()
    written = 0
    for (pipeline_id, fq_label), g in groups.items():
        # Data quality warning: uncategorized > 25% of open pipeline
        uncategorized_pct = (g['uncategorized_value'] / g['open_value'] * 100
                            if g['open_value'] > 0 else 0)

        row = {
            'week_ending': today_iso,
            'pipeline_id': pipeline_id,
            'fiscal_quarter': fq_label,
            'open_pipeline_value': g['open_value'],
            'open_deal_count': g['open_count'],
            'stage_weighted_forecast': g['stage_weighted'],
            'category_weighted_forecast': g['category_weighted'],
            'historical_conversion_low': g['historical_conversion_low'],
            'historical_conversion_mid': g['historical_conversion_mid'],
            'historical_conversion_high': g['historical_conversion_high'],
            'category_breakdown': json.dumps(dict(g['category_breakdown'])),
            'uncategorized_value': g['uncategorized_value'],
        }
        sb.table('forecast_weekly').upsert(
            row, on_conflict='week_ending,pipeline_id,fiscal_quarter'
        ).execute()
        written += 1

        # Show historical conversion range for default pipeline only
        hist_conv_display = ""
        if pipeline_id not in renewal_pipeline_ids:
            hist_conv_display = (f"hist-conv=${g['historical_conversion_mid']:,.0f} "
                               f"[${g['historical_conversion_low']:,.0f}-${g['historical_conversion_high']:,.0f}]  ")

        print(f"✓ {fq_label} / {pipeline_id}: "
              f"open=${g['open_value']:,.0f}  "
              f"stage-wtd=${g['stage_weighted']:,.0f}  "
              f"cat-wtd=${g['category_weighted']:,.0f}  "
              f"{hist_conv_display}"
              f"uncategorized=${g['uncategorized_value']:,.0f}")

        if uncategorized_pct > 25:
            print(f"  ⚠️  DATA QUALITY: {uncategorized_pct:.1f}% of pipeline "
                  f"has NULL or unrecognized forecast_category")

        if g['unknown_incremental_count'] > 0:
            print(f"  ⚠️  {g['unknown_incremental_count']} renewal deals excluded "
                  f"(both new_arr and expansion_arr NULL — incremental unknown, not zero)")

    print(f"\n✓ Wrote {written} forecast rows for {today_iso}")


if __name__ == '__main__':
    main()
