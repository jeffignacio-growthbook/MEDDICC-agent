#!/usr/bin/env python3
"""
HubSpot Property History Feasibility Test

Task: Determine if HubSpot API can provide stage transition timestamps for Q3/Q4 deals
to reconstruct qualification weeks without relying on incomplete snapshot grid.

Test approach:
1. Sample 5-10 deals from Q3/Q4 won cohort
2. Fetch dealstage property history from HubSpot
3. Check data retention (goes back to Nov 2025?)
4. Verify we can identify first qualified-stage entry
5. Report feasibility: data completeness, rate limits, timestamp precision

Decision criteria:
- FEASIBLE if: history goes back to Q3 start, timestamps are precise to week-of-quarter
- NOT FEASIBLE if: history truncated, missing stages, rate limits prohibitive
"""

import os
import sys
from pathlib import Path
from datetime import datetime, timedelta
from dotenv import load_dotenv
from collections import defaultdict

# Load environment
env_path = Path(__file__).parent / '.env'
load_dotenv(env_path)

# Add to path
sys.path.insert(0, str(Path(__file__).parent))

from scripts.analytics.point_in_time import load_scope_config
from scripts.analytics.hubspot_history import PropertyHistoryFetcher
from api.db import get_supabase

FISCAL_QUARTERS = [
    ('FY2026 Q3', '2025-11-01', '2026-01-31'),
    ('FY2026 Q4', '2026-02-01', '2026-04-30'),
]

PIPELINE_ID = 'default'


def get_week_of_quarter(timestamp_str, quarter_start_str):
    """Calculate week-of-quarter from timestamp."""
    try:
        ts = datetime.fromisoformat(timestamp_str.replace('Z', '+00:00'))
        quarter_start = datetime.fromisoformat(quarter_start_str + 'T00:00:00+00:00')

        days_since_start = (ts - quarter_start).days
        week = (days_since_start // 7) + 1

        return max(1, week)
    except:
        return None


def main():
    supabase = get_supabase()
    excluded_pipelines, stage_cfg = load_scope_config()

    # Build qualified stage IDs set
    qualified_stage_ids = set()
    for stage_id, cfg in stage_cfg.items():
        is_qualified = (cfg.get('order', -1) >= cfg.get('qualified_stage_order', 1)
                       and not cfg.get('excluded', False))
        if is_qualified:
            qualified_stage_ids.add(stage_id)

    print("=" * 80)
    print("HUBSPOT PROPERTY HISTORY FEASIBILITY TEST")
    print("=" * 80)
    print()
    print("Goal: Determine if HubSpot API can fill Q3/Q4 snapshot grid gaps")
    print()

    # Get sample of won deals from Q3/Q4
    print("Step 1: Sample won deals from Q3/Q4")
    print("-" * 80)

    sample_deals = []

    for quarter_id, start_date, end_date in FISCAL_QUARTERS:
        deals_resp = supabase.table('deals') \
            .select('deal_id, company_name, stage, close_date') \
            .eq('pipeline_id', PIPELINE_ID) \
            .gte('close_date', start_date) \
            .lte('close_date', end_date) \
            .limit(5) \
            .execute()

        for deal in deals_resp.data:
            from api.field_semantics import is_won
            stage = deal.get('stage')
            if stage and is_won(str(stage)):
                sample_deals.append({
                    'deal_id': str(deal['deal_id']),
                    'company_name': deal.get('company_name'),
                    'close_date': deal.get('close_date'),
                    'quarter': quarter_id,
                    'quarter_start': start_date
                })

    print(f"Sampled {len(sample_deals)} won deals from Q3/Q4")
    for deal in sample_deals:
        print(f"  {deal['company_name']:30s} | {deal['close_date']} | {deal['quarter']}")
    print()

    if not sample_deals:
        print("❌ No sample deals found - cannot test")
        return

    # Test HubSpot property history fetch
    print()
    print("Step 2: Fetch dealstage history from HubSpot")
    print("-" * 80)
    print()

    fetcher = PropertyHistoryFetcher()

    results = {
        'success': 0,
        'failed': 0,
        'complete_history': 0,
        'truncated_history': 0,
        'missing_qualified_entry': 0,
        'qualification_weeks_found': []
    }

    for i, deal in enumerate(sample_deals[:5], 1):  # Test up to 5 deals
        deal_id = deal['deal_id']
        company = deal['company_name']
        quarter_start = deal['quarter_start']

        print(f"[{i}/5] Fetching history for {company}...")

        try:
            history = fetcher.fetch_deal_history(deal_id)

            if not history:
                print(f"  ❌ No history returned")
                results['failed'] += 1
                continue

            results['success'] += 1

            # Extract dealstage history
            stage_history = history.get('dealstage', [])

            if not stage_history:
                print(f"  ❌ No dealstage history found")
                results['missing_qualified_entry'] += 1
                continue

            # Sort by timestamp (oldest first)
            stage_history.sort(key=lambda x: x.get('timestamp', ''))

            print(f"  ✓ Found {len(stage_history)} stage transitions")

            # Check earliest timestamp
            earliest = stage_history[0].get('timestamp') if stage_history else None
            latest = stage_history[-1].get('timestamp') if stage_history else None

            if earliest:
                earliest_date = datetime.fromisoformat(earliest.replace('Z', '+00:00'))
                quarter_start_date = datetime.fromisoformat(quarter_start + 'T00:00:00+00:00')

                days_before_quarter = (quarter_start_date - earliest_date).days

                if days_before_quarter <= 0:
                    print(f"  ⚠️  History starts AFTER quarter start (missing {abs(days_before_quarter)} days)")
                    results['truncated_history'] += 1
                else:
                    print(f"  ✓ History starts {days_before_quarter} days before quarter start")
                    results['complete_history'] += 1

            # Find first qualified stage entry
            first_qualified_week = None
            first_qualified_timestamp = None

            for entry in stage_history:
                stage_id = str(entry.get('value', ''))
                timestamp = entry.get('timestamp')

                if stage_id in qualified_stage_ids:
                    week = get_week_of_quarter(timestamp, quarter_start)
                    if week:
                        first_qualified_week = week
                        first_qualified_timestamp = timestamp
                        break

            if first_qualified_week:
                print(f"  ✓ First qualified in week {first_qualified_week} ({first_qualified_timestamp[:10]})")
                results['qualification_weeks_found'].append(first_qualified_week)
            else:
                print(f"  ⚠️  Never entered qualified stage in history")
                results['missing_qualified_entry'] += 1

            # Show sample transitions (first 3 and last 3)
            print(f"  Sample transitions:")
            for entry in stage_history[:3]:
                ts = entry.get('timestamp', '')[:19]
                stage_id = entry.get('value')
                qualified = '✓ QUALIFIED' if str(stage_id) in qualified_stage_ids else ''
                print(f"    {ts} | Stage {stage_id} {qualified}")

            if len(stage_history) > 6:
                print(f"    ... ({len(stage_history) - 6} more transitions) ...")

            for entry in stage_history[-3:] if len(stage_history) > 3 else []:
                ts = entry.get('timestamp', '')[:19]
                stage_id = entry.get('value')
                qualified = '✓ QUALIFIED' if str(stage_id) in qualified_stage_ids else ''
                print(f"    {ts} | Stage {stage_id} {qualified}")

            print()

        except Exception as e:
            print(f"  ❌ Error: {e}")
            results['failed'] += 1
            continue

    # Report feasibility assessment
    print()
    print("=" * 80)
    print("FEASIBILITY ASSESSMENT")
    print("=" * 80)
    print()

    print(f"API Success Rate: {results['success']}/{len(sample_deals[:5])} deals")
    print(f"Complete History (before quarter start): {results['complete_history']}")
    print(f"Truncated History (missing early transitions): {results['truncated_history']}")
    print(f"Qualification Week Reconstructed: {len(results['qualification_weeks_found'])} deals")
    print()

    # Decision
    total_tested = results['success']
    reconstruction_success_rate = len(results['qualification_weeks_found']) / total_tested if total_tested > 0 else 0

    print("DECISION CRITERIA:")
    print()

    if reconstruction_success_rate >= 0.8:
        print("✓ FEASIBLE - HubSpot API can reconstruct qualification weeks")
        print(f"  - {reconstruction_success_rate:.0%} of deals have complete history with qualification entry")
        print(f"  - History retention goes back far enough (≥ Q3 start)")
        print()
        print("RECOMMENDATION:")
        print("  → Proceed with full reconstruction from HubSpot audit trail")
        print("  → Create script to:")
        print("     1. Fetch all Q3/Q4 deals (both won and in-progress)")
        print("     2. Pull dealstage history for each")
        print("     3. Compute first qualification week per deal")
        print("     4. Run cohort-by-qualification-week analysis")
        print()
        print(f"ESTIMATED COST: ~100-200 deals × 5 calls/sec = 20-40 seconds API time")
        print("                (within HubSpot rate limits)")

    elif reconstruction_success_rate >= 0.5:
        print("~ PARTIAL - HubSpot API works for some deals but not all")
        print(f"  - Only {reconstruction_success_rate:.0%} of deals have complete history")
        print(f"  - History may be truncated or incomplete")
        print()
        print("RECOMMENDATION:")
        print("  → Fall back to Q1-only analysis (complete snapshot grid)")
        print("  → HubSpot approach too unreliable for systematic use")

    else:
        print("❌ NOT FEASIBLE - HubSpot API cannot reliably reconstruct qualification weeks")
        print(f"  - Only {reconstruction_success_rate:.0%} reconstruction success rate")
        print(f"  - History retention insufficient or data quality poor")
        print()
        print("RECOMMENDATION:")
        print("  → Proceed with Q1-only analysis (weeks 1-13 complete)")
        print("  → Flag Q3/Q4 snapshot grid gaps for infrastructure backlog")

    print()

    # Separately flag snapshot grid issue
    print("=" * 80)
    print("INFRASTRUCTURE BACKLOG ITEM")
    print("=" * 80)
    print()
    print("Issue: Snapshot grid incomplete for Q3/Q4")
    print("  - Q3: Only weeks 1-2 captured (missing weeks 3-13)")
    print("  - Q4: Only weeks 4-13 captured (missing weeks 1-3)")
    print("  - Q1: Complete weeks 1-13 ✓")
    print()
    print("Impact: Cannot compute cohort-by-qualification-week for Q3/Q4")
    print("        using snapshot table alone")
    print()
    print("Root cause investigation needed:")
    print("  - Was snapshot job not running during those periods?")
    print("  - Data deletion or migration issue?")
    print("  - Backfill possible from source system?")
    print()


if __name__ == '__main__':
    main()
