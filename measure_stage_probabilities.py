#!/usr/bin/env python3
"""
Measure actual stage-to-won conversion rates from historical data.

Validates PROVISIONAL stage probabilities in config/client.yaml against
measured outcomes. Uses same scope filter as conversion rate work:
default pipeline only, renewals excluded.

Method:
- For each stage, find all deals that reached it (deals_snapshot)
- Check terminal outcome (deals.deal_status)
- Calculate: won / (won + lost)
- Report per-quarter and pooled
- Compare measured vs configured

If Technical Evaluation is configured at 0.40 but measures 0.15,
stage-weighted forecast has been overstating for months.
"""

import os
import sys
from pathlib import Path
from collections import defaultdict

REPO_ROOT = Path(__file__).parent
sys.path.insert(0, str(REPO_ROOT / 'scripts'))

def main():
    import psycopg2
    from utils import load_client_config

    db_url = os.getenv('SUPABASE_DB_URL')
    if not db_url:
        print("⚠️  SUPABASE_DB_URL not set")
        return

    # URL-encode password if needed
    if 'ShoheiOhtani145928!' in db_url:
        db_url = db_url.replace('ShoheiOhtani145928!', 'ShoheiOhtani145928%21')

    config = load_client_config()

    # Get renewal pipeline IDs (exclude from analysis)
    renewal_pipeline_ids = set(
        config.get('pipeline', {}).get('value_field', {}).get('renewal_pipeline_ids', [])
    )

    # Get scope filter (same as conversion rate work)
    from analytics.point_in_time import load_scope_config
    excl_pipelines, stage_cfg = load_scope_config(config)

    # Build stage map: id -> {name, configured_probability}
    stage_map = {}
    for pipeline in config.get('pipeline', {}).get('pipelines', []):
        if pipeline['id'] in renewal_pipeline_ids:
            continue  # Skip renewal pipeline stages

        for stage in pipeline.get('stages', []):
            stage_id = stage['id']
            stage_map[stage_id] = {
                'name': stage['name'],
                'configured_prob': stage.get('stage_probability', 0.0),
                'order': stage.get('order', 99)
            }

    conn = psycopg2.connect(db_url)
    cur = conn.cursor()

    # Get all terminal outcomes (won/lost) for default pipeline deals
    cur.execute("""
        SELECT deal_id, deal_status, close_date
        FROM deals
        WHERE pipeline_id NOT IN (%s)  -- Exclude renewal pipeline
          AND deal_status IN ('won', 'lost')
          AND close_date IS NOT NULL;
    """, (','.join(f"'{pid}'" for pid in renewal_pipeline_ids) if renewal_pipeline_ids else 'NULL',))

    outcomes = {}
    for deal_id, status, close_date in cur.fetchall():
        outcomes[deal_id] = {
            'status': status,
            'close_date': str(close_date) if close_date else None
        }

    print(f"✓ Loaded {len(outcomes)} terminal outcomes (won/lost)")
    print()

    # Get fiscal quarter function from config
    from utils import get_fiscal_quarter

    # For each stage, find all deals that reached it
    stage_conversions = defaultdict(lambda: {
        'by_quarter': defaultdict(lambda: {'won': 0, 'lost': 0}),
        'pooled': {'won': 0, 'lost': 0}
    })

    # Get stage progression from deals_snapshot
    cur.execute("""
        SELECT DISTINCT deal_id, stage_id, fiscal_quarter
        FROM deals_snapshot
        WHERE stage_id IS NOT NULL
        ORDER BY deal_id, fiscal_quarter;
    """)

    print("Processing stage progression history...")
    deals_seen = set()

    for deal_id, stage_id, fiscal_quarter in cur.fetchall():
        # Skip if not a tracked stage
        if stage_id not in stage_map:
            continue

        # Skip if no terminal outcome
        if deal_id not in outcomes:
            continue

        # Skip if already counted (only count first time deal reached each stage)
        key = (deal_id, stage_id)
        if key in deals_seen:
            continue
        deals_seen.add(key)

        outcome = outcomes[deal_id]
        status = outcome['status']

        # Increment counts
        if status == 'won':
            stage_conversions[stage_id]['pooled']['won'] += 1
            stage_conversions[stage_id]['by_quarter'][fiscal_quarter]['won'] += 1
        elif status == 'lost':
            stage_conversions[stage_id]['pooled']['lost'] += 1
            stage_conversions[stage_id]['by_quarter'][fiscal_quarter]['lost'] += 1

    cur.close()
    conn.close()

    # Report: Pooled (all-time)
    print("\n" + "="*90)
    print("POOLED (All-Time) Stage Conversion Rates")
    print("="*90)
    print(f"{'Stage':<30} {'Won':>6} {'Lost':>6} {'Total':>6} {'Measured':>10} {'Config':>10} {'Δ':>10}")
    print("-"*90)

    sorted_stages = sorted(stage_map.items(), key=lambda x: x[1]['order'])

    for stage_id, stage_info in sorted_stages:
        if stage_id not in stage_conversions:
            continue

        conv = stage_conversions[stage_id]['pooled']
        won = conv['won']
        lost = conv['lost']
        total = won + lost

        if total == 0:
            continue

        measured_rate = won / total
        configured_rate = stage_info['configured_prob']
        delta = measured_rate - configured_rate

        delta_str = f"{delta:+.3f}"
        if abs(delta) > 0.15:
            delta_str += " ⚠️"

        print(f"{stage_info['name']:<30} {won:>6} {lost:>6} {total:>6} "
              f"{measured_rate:>10.3f} {configured_rate:>10.3f} {delta_str:>10}")

    # Report: Per-Quarter variance
    print("\n" + "="*90)
    print("PER-QUARTER Variance (Measured Conversion Rates)")
    print("="*90)

    # Collect all quarters
    all_quarters = set()
    for stage_id in stage_conversions:
        all_quarters.update(stage_conversions[stage_id]['by_quarter'].keys())

    sorted_quarters = sorted(all_quarters, reverse=True)[:6]  # Last 6 quarters

    for stage_id, stage_info in sorted_stages:
        if stage_id not in stage_conversions:
            continue

        # Skip if stage has too few outcomes
        pooled_total = (stage_conversions[stage_id]['pooled']['won'] +
                       stage_conversions[stage_id]['pooled']['lost'])
        if pooled_total < 5:
            continue

        print(f"\n{stage_info['name']} (configured: {stage_info['configured_prob']:.2f})")
        print(f"{'Quarter':<15} {'Won':>6} {'Lost':>6} {'Rate':>8} {'vs Config':>10}")
        print("-"*50)

        rates = []
        for quarter in sorted_quarters:
            conv = stage_conversions[stage_id]['by_quarter'].get(quarter, {'won': 0, 'lost': 0})
            won = conv['won']
            lost = conv['lost']
            total = won + lost

            if total == 0:
                continue

            rate = won / total
            rates.append(rate)
            delta = rate - stage_info['configured_prob']

            print(f"{quarter:<15} {won:>6} {lost:>6} {rate:>8.3f} {delta:>+10.3f}")

        # Show variance
        if len(rates) > 1:
            import statistics
            mean_rate = statistics.mean(rates)
            stdev_rate = statistics.stdev(rates)
            min_rate = min(rates)
            max_rate = max(rates)

            print(f"\nVariance: μ={mean_rate:.3f} σ={stdev_rate:.3f} "
                  f"range=[{min_rate:.3f}, {max_rate:.3f}]")

    print("\n" + "="*90)
    print("KEY FINDINGS")
    print("="*90)

    # Flag large discrepancies
    findings = []
    for stage_id, stage_info in sorted_stages:
        if stage_id not in stage_conversions:
            continue

        conv = stage_conversions[stage_id]['pooled']
        won = conv['won']
        lost = conv['lost']
        total = won + lost

        if total < 5:
            continue

        measured_rate = won / total
        configured_rate = stage_info['configured_prob']
        delta = measured_rate - configured_rate

        if abs(delta) > 0.15:
            direction = "overstating" if delta < 0 else "understating"
            findings.append(
                f"• {stage_info['name']}: configured at {configured_rate:.2f}, "
                f"measures {measured_rate:.3f} ({delta:+.3f}) — "
                f"stage-weighted forecast {direction} by {abs(delta)*100:.0f}pp"
            )

    if findings:
        for finding in findings:
            print(finding)
    else:
        print("• No major discrepancies found (all within ±15pp)")

    print()
    print("="*90)
    print("RECOMMENDATION")
    print("="*90)
    print()
    print("If measured rates differ significantly from configured:")
    print("1. Update stage probabilities in config/client.yaml with measured values")
    print("2. Re-run compute_forecast.py to get corrected stage-weighted forecast")
    print("3. Document why PROVISIONAL guesses were off (e.g., optimistic templates)")
    print()
    print("If quarter-to-quarter variance is high (σ > 0.10):")
    print("4. Consider stage-specific factors (seasonality, segment mix, rep changes)")
    print("5. Use pooled rate but monitor quarterly trend for early warnings")
    print()

if __name__ == '__main__':
    main()
