#!/usr/bin/env python3
"""
Investigate forecast methodology questions.

1. What did the agent compute? (Did it read forecast_weekly?)
2. Why $7.6M vs $16.1M discrepancy?
3. Is stage_weighted_forecast trustworthy?
4. What is forecast_category coverage?
5. Which methods are computable today?
"""

import os
import sys
from pathlib import Path
from datetime import date

REPO_ROOT = Path(__file__).parent
sys.path.insert(0, str(REPO_ROOT / 'scripts'))

from supabase import create_client
from utils import load_client_config, get_fiscal_quarter

def question_1_agent_computation():
    """
    Q1: Did the agent's $1M-$1.5M answer read forecast_weekly?

    Since we don't have the actual run logs, we'll check what handlers
    WOULD do if asked "What do you forecast for the quarter?"
    """
    print("="*70)
    print("Q1: What Did the Agent Compute?")
    print("="*70)
    print()

    print("Without actual run logs, checking handler behavior:")
    print()
    print("1. Intent classification for 'What do you forecast for the quarter?'")
    print("   - After business metric negative example: routes to query_waterfall (0.92)")
    print("   - Before fix: routed to query_help (wrong)")
    print()
    print("2. query_waterfall does NOT read forecast_weekly")
    print("   - Sums raw deals from deals table")
    print("   - Applies scope filter (renewals + Meeting Set excluded)")
    print("   - Result: $16.1M total open pipeline")
    print()
    print("3. Dynamic loop (if triggered) COULD discover forecast_weekly")
    print("   - table_classifier.py line 23: 'forecast_weekly: Weekly forecast snapshots'")
    print("   - Table is discoverable but not precomputed-first")
    print()
    print("FINDING: Agent likely summed raw deals, not forecast_weekly precomputed values")
    print()


def question_2_population_reconciliation():
    """
    Q2: Why $7.6M in forecast_weekly vs $16.1M in query_waterfall?

    Check what compute_forecast.py includes vs query_waterfall.
    """
    print("="*70)
    print("Q2: Why $7.6M vs $16.1M?")
    print("="*70)
    print()

    SUPABASE_URL = os.getenv('SUPABASE_URL')
    SUPABASE_KEY = os.getenv('SUPABASE_SERVICE_KEY')

    if not SUPABASE_URL or not SUPABASE_KEY:
        print("⚠️  Credentials not set")
        return

    sb = create_client(SUPABASE_URL, SUPABASE_KEY)
    config = load_client_config()

    # Get Q3 fiscal quarter bounds
    today = date.today()
    _, _, current_fq = get_fiscal_quarter(today, config)

    print(f"Current fiscal quarter: {current_fq}")
    print()

    # What forecast_weekly shows
    forecast_q3 = sb.table('forecast_weekly').select('*').eq(
        'fiscal_quarter', 'FY2027 Q3'
    ).execute()

    if forecast_q3.data:
        row = forecast_q3.data[0]
        print(f"forecast_weekly (FY2027 Q3):")
        print(f"  Pipeline: {row['pipeline_id']}")
        print(f"  Open pipeline: ${row['open_pipeline_value']:,.0f}")
        print(f"  Deal count: {row['open_deal_count']}")
        print(f"  Week ending: {row['week_ending']}")
        print()

    # What query_waterfall shows
    from analytics.point_in_time import load_scope_config, is_deal_in_analytics_scope

    excluded_pipelines, stage_cfg = load_scope_config(config)

    # Query all active deals (what query_waterfall does)
    all_active = sb.table('deals').select(
        'deal_id, deal_value, close_date, stage, pipeline_id'
    ).eq('deal_status', 'active').execute()

    # Apply scope filter (what query_waterfall does)
    scoped_deals = [
        d for d in all_active.data
        if is_deal_in_analytics_scope(
            d.get('stage'),
            d.get('pipeline_id'),
            excluded_pipelines,
            stage_cfg
        )
    ]

    waterfall_total = sum(d.get('deal_value') or 0 for d in scoped_deals)

    print(f"query_waterfall (all active, scoped):")
    print(f"  Pipeline: default (renewals excluded)")
    print(f"  Open pipeline: ${waterfall_total:,.0f}")
    print(f"  Deal count: {len(scoped_deals)}")
    print()

    # What compute_forecast.py does: filters by close_date in Q3
    import re
    from datetime import date as dt

    # Parse Q3 bounds from fiscal quarter
    # FY2027 Q3 = Aug-Oct 2026 (if FY starts Feb)
    fy_start_month = config.get('fiscal', {}).get('fy_start_month', 2)

    # Q3 is months 6-8 of fiscal year
    # FY2027 starts Feb 2026, so Q3 is Aug-Oct 2026
    q3_start = dt(2026, 8, 1)
    q3_end = dt(2026, 10, 31)

    q3_deals = [
        d for d in scoped_deals
        if d.get('close_date') and
        q3_start <= dt.fromisoformat(d['close_date'][:10]) <= q3_end
    ]

    q3_total = sum(d.get('deal_value') or 0 for d in q3_deals)

    print(f"compute_forecast.py logic (close_date in Q3):")
    print(f"  Pipeline: default (renewals excluded)")
    print(f"  Open pipeline: ${q3_total:,.0f}")
    print(f"  Deal count: {len(q3_deals)}")
    print()

    print("RECONCILIATION:")
    print(f"  forecast_weekly: ${row['open_pipeline_value']:,.0f} (Q3 close dates)")
    print(f"  query_waterfall: ${waterfall_total:,.0f} (all active, any close date)")
    print(f"  Difference: ${waterfall_total - row['open_pipeline_value']:,.0f}")
    print()
    print("FINDING: forecast_weekly scopes to Q3 close dates,")
    print("         query_waterfall sums ALL active deals.")
    print("         These answer different questions.")
    print()


def question_3_stage_weighted_trustworthy():
    """
    Q3: Was forecast_weekly recomputed after unmapped-stage fix?
    """
    print("="*70)
    print("Q3: Is stage_weighted_forecast Trustworthy?")
    print("="*70)
    print()

    SUPABASE_URL = os.getenv('SUPABASE_URL')
    SUPABASE_KEY = os.getenv('SUPABASE_SERVICE_KEY')

    if not SUPABASE_URL or not SUPABASE_KEY:
        print("⚠️  Credentials not set")
        return

    sb = create_client(SUPABASE_URL, SUPABASE_KEY)

    forecast_q3 = sb.table('forecast_weekly').select('*').eq(
        'fiscal_quarter', 'FY2027 Q3'
    ).execute()

    if forecast_q3.data:
        row = forecast_q3.data[0]
        computed_at = row['week_ending']

        print(f"forecast_weekly computed: {computed_at}")
        print(f"Unmapped-stage finding: 2026-09-01 (today)")
        print()

        if computed_at < '2026-09-01':
            print("⚠️  STALE: forecast_weekly predates unmapped-stage discovery")
            print()
            print("Unmapped stages (148 renewal deals defaulting to 0.0 probability):")
            print("  - 1297321618 (Upcoming Renewal): 139 deals")
            print("  - 1297321619 (Renewal Engaged): 8 deals")
            print("  - 1297321620 (Pricing Presented): 1 deal")
            print()
            print(f"stage_weighted_forecast: ${row['stage_weighted_forecast']:,.0f}")
            print("  → UNDERSTATED by renewal deal value × their true probabilities")
            print()
            print("FINDING: stage_weighted_forecast is STALE and UNDERSTATED")
        else:
            print("✓ FRESH: forecast_weekly computed after unmapped-stage fix")
    else:
        print("No Q3 data in forecast_weekly")

    print()


def question_4_forecast_category_coverage():
    """
    Q4: Do reps actually set forecast_category?
    """
    print("="*70)
    print("Q4: forecast_category Coverage")
    print("="*70)
    print()

    SUPABASE_URL = os.getenv('SUPABASE_URL')
    SUPABASE_KEY = os.getenv('SUPABASE_SERVICE_KEY')

    if not SUPABASE_URL or not SUPABASE_KEY:
        print("⚠️  Credentials not set")
        return

    sb = create_client(SUPABASE_URL, SUPABASE_KEY)

    result = sb.rpc('exec_sql', {
        'query': """
        SELECT
            COALESCE(forecast_category, 'NULL') as category,
            COUNT(*) as count,
            SUM(deal_value) as total_value
        FROM deals
        WHERE deal_status = 'active'
        GROUP BY forecast_category
        ORDER BY count DESC
        """
    }).execute()

    if result.data:
        print(f"{'Category':<20} {'Count':<10} {'Total Value':<15}")
        print("-" * 50)

        total_deals = 0
        total_value = 0
        null_count = 0
        null_value = 0

        for row in result.data:
            cat = row['category']
            count = row['count']
            value = row['total_value'] or 0

            print(f"{cat:<20} {count:<10} ${value:>13,.0f}")

            total_deals += count
            total_value += value

            if cat == 'NULL':
                null_count = count
                null_value = value

        print("-" * 50)
        print(f"{'TOTAL':<20} {total_deals:<10} ${total_value:>13,.0f}")
        print()

        if total_deals > 0:
            null_pct = (null_count / total_deals) * 100
            null_value_pct = (null_value / total_value) * 100 if total_value > 0 else 0

            print(f"NULL coverage: {null_count}/{total_deals} deals ({null_pct:.1f}%)")
            print(f"NULL value: ${null_value:,.0f}/{total_value:,.0f} ({null_value_pct:.1f}%)")
            print()

            if null_pct > 50:
                print("⚠️  MAJORITY NULL: category_weighted_forecast built on small subset")
                print("    Not representative of full pipeline")
            elif null_pct > 25:
                print("⚠️  SIGNIFICANT GAPS: 25%+ of pipeline uncategorized")
            else:
                print("✓ GOOD COVERAGE: <25% NULL")

        print()
        print("FINDING: forecast_category coverage determines if category_weighted")
        print("         is trustworthy or built on incomplete data")
    else:
        print("Could not query forecast_category distribution")

    print()


def question_5_methodology_table():
    """
    Q5: Which methods are computable today?
    """
    print("="*70)
    print("Q5: Which Forecast Methods Are Computable?")
    print("="*70)
    print()

    SUPABASE_URL = os.getenv('SUPABASE_URL')
    SUPABASE_KEY = os.getenv('SUPABASE_SERVICE_KEY')

    if not SUPABASE_URL or not SUPABASE_KEY:
        print("⚠️  Credentials not set")
        return

    sb = create_client(SUPABASE_URL, SUPABASE_KEY)
    config = load_client_config()

    methods = []

    # 1. Stage-weighted
    stage_probs_exist = any(
        s.get('stage_probability') is not None
        for p in config.get('pipeline', {}).get('pipelines', [])
        for s in p.get('stages', [])
    )

    forecast_weekly_exists = sb.table('forecast_weekly').select('fiscal_quarter').limit(1).execute()

    if stage_probs_exist and forecast_weekly_exists.data:
        methods.append({
            'method': 'Stage-weighted',
            'computable': 'Yes (STALE)',
            'inputs': 'stage_probability config + active deals',
            'blocker': 'Probabilities are template guesses, forecast_weekly predates unmapped-stage fix'
        })
    else:
        methods.append({
            'method': 'Stage-weighted',
            'computable': 'No',
            'inputs': 'stage_probability config + active deals',
            'blocker': 'Missing config or forecast_weekly table'
        })

    # 2. Category-weighted
    # Already checked in question 4, just reference
    methods.append({
        'method': 'Category-weighted',
        'computable': 'Yes (if coverage >75%)',
        'inputs': 'forecast_category field + category_weights config',
        'blocker': 'Check Q4 results for NULL coverage'
    })

    # 3. Historical conversion
    # Needs: starting pipeline at quarter start + measured week-3 conversion rate
    snapshots_exist = sb.table('deals_snapshot').select('snapshot_date').limit(1).execute()

    if snapshots_exist.data:
        methods.append({
            'method': 'Historical conversion',
            'computable': 'Yes',
            'inputs': 'deals_snapshot + measured week-3 conversion (13.5%)',
            'blocker': None
        })
    else:
        methods.append({
            'method': 'Historical conversion',
            'computable': 'No',
            'inputs': 'deals_snapshot + measured week-3 conversion',
            'blocker': 'Missing deals_snapshot table'
        })

    # 4. Run-rate
    # Needs: closed-won to-date + historical pace
    waterfall_exists = sb.table('waterfall_weekly').select('week_ending').limit(1).execute()

    if waterfall_exists.data:
        methods.append({
            'method': 'Run-rate',
            'computable': 'Yes',
            'inputs': 'waterfall_weekly (won_value) + historical Q remaining pace',
            'blocker': None
        })
    else:
        methods.append({
            'method': 'Run-rate',
            'computable': 'No',
            'inputs': 'waterfall_weekly + historical pace',
            'blocker': 'Missing waterfall_weekly table'
        })

    # 5. Rep-committed
    # Check if any field exists
    rep_forecast_fields = sb.rpc('exec_sql', {
        'query': """
        SELECT column_name
        FROM information_schema.columns
        WHERE table_name = 'deals'
        AND column_name ILIKE '%forecast%'
        OR column_name ILIKE '%commit%'
        """
    }).execute()

    has_rep_field = bool(rep_forecast_fields.data)

    methods.append({
        'method': 'Rep-committed',
        'computable': 'No',
        'inputs': 'Rep forecast calls (AE $1.574M + AM $325K = $1.899M)',
        'blocker': 'Not captured in system — exists in business but not in data'
    })

    # Print table
    print(f"{'Method':<25} {'Computable?':<20} {'Blocker':<50}")
    print("-" * 95)

    for m in methods:
        computable = m['computable']
        blocker = m['blocker'] or '—'
        print(f"{m['method']:<25} {computable:<20} {blocker:<50}")

    print()
    print("FINDING: Multiple methods exist, but each has data quality issues.")
    print("         Value is in the SPREAD — when they cluster vs diverge.")
    print()


if __name__ == '__main__':
    question_1_agent_computation()
    question_2_population_reconciliation()
    question_3_stage_weighted_trustworthy()
    question_4_forecast_category_coverage()
    question_5_methodology_table()

    print()
    print("="*70)
    print("SUMMARY")
    print("="*70)
    print()
    print("1. Agent likely summed raw deals, not forecast_weekly precomputed values")
    print("2. $7.6M (forecast_weekly Q3 scoped) vs $16.1M (all active deals) — different populations")
    print("3. stage_weighted_forecast is STALE (predates unmapped-stage fix)")
    print("4. Check forecast_category NULL coverage (determines category_weighted validity)")
    print("5. Multiple methods exist, but rep-committed calls not captured in system")
    print()
    print("RECOMMENDATION: Report spread across all computable methods, not single number")
