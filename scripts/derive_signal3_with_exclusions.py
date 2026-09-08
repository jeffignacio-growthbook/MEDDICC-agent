#!/usr/bin/env python3
"""
Signal 3 Threshold Derivation with Bulk Event Exclusion and Truncation Handling

Applies TWO fixes before computing thresholds:
1. Exclude notes_last_updated changes in bulk cleanup months (from business_events_registry.yaml)
2. Handle truncation correctly - exclude only gaps spanning truncation boundary, not whole deal

Reports coverage and sample sizes AFTER fixes to determine if Signal 3 is viable.
"""
import os
import sys
import json
import statistics
from pathlib import Path
from datetime import datetime, timezone, timedelta
from collections import defaultdict
from dotenv import load_dotenv

env_path = Path(__file__).parent.parent / ".env"
load_dotenv(env_path)

sys.path.insert(0, str(Path(__file__).parent.parent / 'api'))
from db import get_supabase
from field_semantics import is_won, stage_bucket

# Bulk cleanup months from business_events_registry.yaml
BULK_CLEANUP_MONTHS = [
    "2023-08",
    "2024-11",
    "2026-01",
    "2026-02",
    "2026-03",
    "2026-04",
    "2026-05",
    "2026-06",
    "2026-07",
    "2026-08"
]

# Minimum sample size per cell (from Signal 2 config)
MIN_SAMPLE_PER_CELL = 5

# Truncation boundary: if earliest change is >30 days after creation, treat as truncated
TRUNCATION_THRESHOLD_DAYS = 30

def parse_date(date_str):
    if not date_str:
        return None
    try:
        dt = datetime.fromisoformat(date_str.replace('Z', '+00:00'))
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        return dt
    except:
        return None

def is_bulk_cleanup_month(timestamp):
    """Check if timestamp falls in a bulk cleanup month."""
    if not timestamp:
        return False
    date_str = timestamp.strftime('%Y-%m')
    return date_str in BULK_CLEANUP_MONTHS

def compute_activity_gaps_with_exclusions(deal, activity_history, dealstage_history):
    """
    Compute gaps between activities with:
    1. Bulk event exclusion - skip activities in cleanup months
    2. Truncation handling - skip gaps spanning truncation boundary

    Returns list of (gap_days, stage, is_valid) tuples
    """
    if not activity_history or not dealstage_history:
        return []

    create_date = parse_date(deal.get('create_date'))
    close_date = parse_date(deal.get('close_date'))

    if not create_date or not close_date:
        return []

    # Extract and sort activity timestamps (excluding bulk cleanup months)
    activities = []
    excluded_count = 0

    for change in activity_history:
        ts_str = change.get('timestamp')
        value_str = change.get('value')

        if ts_str:
            ts = parse_date(ts_str)
            if ts:
                # EXCLUSION 1: Skip activities in bulk cleanup months
                if is_bulk_cleanup_month(ts):
                    excluded_count += 1
                    continue

                # Parse activity date from value
                activity_date = parse_date(value_str) if value_str else ts
                if activity_date:
                    activities.append(activity_date)

    if len(activities) < 2:
        return []  # Need at least 2 activities to compute gaps

    activities = sorted(activities)

    # EXCLUSION 2: Detect truncation boundary
    earliest_activity = activities[0]
    days_after_creation = (earliest_activity - create_date).days

    truncation_boundary = None
    if days_after_creation > TRUNCATION_THRESHOLD_DAYS:
        # Truncated - earliest activity is NOT the true first activity
        truncation_boundary = earliest_activity

    # Build stage timeline from dealstage history
    stage_timeline = []
    for change in dealstage_history:
        ts_str = change.get('timestamp')
        stage_value = change.get('value')

        if ts_str and stage_value:
            ts = parse_date(ts_str)
            if ts:
                stage_timeline.append((ts, stage_value))

    stage_timeline = sorted(stage_timeline, key=lambda x: x[0])

    def get_stage_at_time(timestamp):
        """Get stage at given timestamp from stage timeline."""
        current_stage = None
        for stage_ts, stage_value in stage_timeline:
            if stage_ts <= timestamp:
                current_stage = stage_value
            else:
                break
        return current_stage

    # Compute gaps between consecutive activities
    gaps = []

    for i in range(len(activities) - 1):
        activity_1 = activities[i]
        activity_2 = activities[i + 1]

        gap_days = (activity_2 - activity_1).days

        # EXCLUSION 2: Skip gaps that span truncation boundary
        if truncation_boundary and activity_1 < truncation_boundary:
            continue  # First activity is before truncation boundary - gap is invalid

        # Get stage at midpoint of gap
        midpoint = activity_1 + (activity_2 - activity_1) / 2
        stage = get_stage_at_time(midpoint)

        if stage:
            gaps.append((gap_days, stage, True))

    # Add gap from last activity to close
    if activities:
        last_activity = activities[-1]

        # Only include if last activity is after truncation boundary
        if not truncation_boundary or last_activity >= truncation_boundary:
            final_gap = (close_date - last_activity).days
            final_stage = get_stage_at_time(last_activity)

            if final_stage and final_gap >= 0:
                gaps.append((final_gap, final_stage, True))

    return gaps

def main():
    sb = get_supabase()

    print("=" * 80)
    print("SIGNAL 3 DERIVATION: With Bulk Event Exclusion & Truncation Handling")
    print("=" * 80)
    print()

    print("Loading validation results from full population fetch...")
    results_file = Path(__file__).parent.parent / "notes_last_updated_validation_results.json"

    if not results_file.exists():
        print("❌ Validation results not found. Run validate_notes_last_updated_full.py first.")
        sys.exit(1)

    with open(results_file) as f:
        validation_data = json.load(f)

    print(f"Loaded validation data: {validation_data['coverage_stats']['total_deals']} deals")
    print()

    # We need to re-fetch the actual property history data
    # The validation script didn't save the full history, just stats
    print("Re-fetching property history for closed deals...")
    print("(This is necessary because validation only saved stats, not full history)")
    print()

    all_deals = sb.table('deals').select(
        'deal_id,company_name,stage,deal_status,segment,create_date,close_date'
    ).execute().data

    closed_deals = []
    for deal in all_deals:
        if is_won(deal.get('stage')):
            deal['outcome'] = 'won'
            closed_deals.append(deal)
        elif deal.get('deal_status') == 'lost':
            deal['outcome'] = 'lost'
            closed_deals.append(deal)

    print(f"Total closed deals: {len(closed_deals)}")
    print()

    # Load property history cache if available
    cache_file = Path(__file__).parent.parent / 'scripts' / 'analytics' / 'property_history_cache.json'

    if cache_file.exists():
        print(f"Loading property history from cache: {cache_file}")
        with open(cache_file) as f:
            cache = json.load(f)

        deals_cache = cache.get('deals', {})
        print(f"Loaded cache with {len(deals_cache)} deals")
    else:
        print("⚠️  No property history cache found")
        print("   Run: python scripts/analytics/hubspot_history.py --all")
        print("   Then re-run this script")
        sys.exit(1)

    print()

    # ========================================================================
    # COMPUTE GAPS WITH EXCLUSIONS
    # ========================================================================
    print("=" * 80)
    print("COMPUTING ACTIVITY GAPS (with bulk event exclusion & truncation handling)")
    print("=" * 80)
    print()

    gaps_by_cell = defaultdict(lambda: {'won': [], 'lost': []})

    stats = {
        'deals_processed': 0,
        'deals_with_both_histories': 0,
        'deals_with_truncation': 0,
        'gaps_excluded_truncation': 0,
        'activities_excluded_bulk': 0,
        'valid_gaps_computed': 0
    }

    for deal in closed_deals:
        deal_id = str(deal['deal_id'])

        # Get property history from cache
        cached_deal = deals_cache.get(deal_id)
        if not cached_deal:
            continue

        stats['deals_processed'] += 1

        # Get histories
        nlu_history = cached_deal.get('notes_last_updated_history', [])
        dealstage_history = cached_deal.get('history', [])  # 'history' is dealstage

        if not nlu_history or not dealstage_history:
            continue

        stats['deals_with_both_histories'] += 1

        # Compute gaps with exclusions
        gaps = compute_activity_gaps_with_exclusions(
            deal, nlu_history, dealstage_history
        )

        if not gaps:
            continue

        segment = deal.get('segment') or 'Unknown'
        outcome = deal['outcome']

        for gap_days, stage, is_valid in gaps:
            if not is_valid:
                stats['gaps_excluded_truncation'] += 1
                continue

            # Get stage bucket
            bucket = stage_bucket(stage)

            # Skip terminal stages
            if bucket in ['closed_won', 'closed_lost', 'unknown']:
                continue

            # Add to cell
            cell_key = (bucket, segment)
            gaps_by_cell[cell_key][outcome].append(gap_days)
            stats['valid_gaps_computed'] += 1

        if (stats['deals_processed'] % 100) == 0:
            print(f"  Processed {stats['deals_processed']} deals...")

    print()
    print("PROCESSING STATS:")
    print(f"  Deals processed: {stats['deals_processed']}")
    print(f"  Deals with both histories: {stats['deals_with_both_histories']}")
    print(f"  Valid gaps computed: {stats['valid_gaps_computed']}")
    print()

    # ========================================================================
    # SAMPLE SIZE ANALYSIS
    # ========================================================================
    print("=" * 80)
    print("SAMPLE SIZE ANALYSIS (after exclusions)")
    print("=" * 80)
    print()

    print(f"{'Stage':<20} {'Segment':<15} {'Won Gaps':<10} {'Lost Gaps':<10} {'Status':<20}")
    print("-" * 80)

    cells_with_sufficient_sample = 0
    cells_with_insufficient_sample = 0

    for (bucket, segment), data in sorted(gaps_by_cell.items()):
        won_count = len(data['won'])
        lost_count = len(data['lost'])

        if won_count >= MIN_SAMPLE_PER_CELL and lost_count >= MIN_SAMPLE_PER_CELL:
            status = "✅ Sufficient"
            cells_with_sufficient_sample += 1
        elif won_count > 0 and lost_count > 0:
            status = "⚠️  Small sample"
            cells_with_insufficient_sample += 1
        else:
            status = "❌ Insufficient"
            cells_with_insufficient_sample += 1

        print(f"{bucket:<20} {segment:<15} {won_count:<10} {lost_count:<10} {status:<20}")

    print()

    total_cells = len(gaps_by_cell)

    print(f"Total stage x segment cells: {total_cells}")
    print(f"Cells with sufficient sample (>=5 won and >=5 lost): {cells_with_sufficient_sample}")
    print(f"Cells with insufficient sample: {cells_with_insufficient_sample}")
    print()

    if total_cells > 0:
        sufficient_pct = 100 * cells_with_sufficient_sample / total_cells
        print(f"Coverage: {sufficient_pct:.1f}% of cells have sufficient sample")

    print()

    # ========================================================================
    # DERIVE THRESHOLDS (if sufficient sample)
    # ========================================================================
    if cells_with_sufficient_sample > 0:
        print("=" * 80)
        print("DERIVED THRESHOLDS (Won vs Lost Separation)")
        print("=" * 80)
        print()

        thresholds = {}

        print(f"{'Stage':<20} {'Segment':<15} {'Won Med':<10} {'Lost P25':<10} {'Threshold':<10} {'Method':<20}")
        print("-" * 110)

        for (bucket, segment), data in sorted(gaps_by_cell.items()):
            won_gaps = data['won']
            lost_gaps = data['lost']

            if len(won_gaps) < MIN_SAMPLE_PER_CELL or len(lost_gaps) < MIN_SAMPLE_PER_CELL:
                continue

            # Compute distributions
            won_median = statistics.median(won_gaps)
            lost_sorted = sorted(lost_gaps)
            lost_p25 = statistics.quantiles(lost_sorted, n=4)[0] if len(lost_sorted) >= 4 else lost_sorted[0]
            lost_median = statistics.median(lost_gaps)

            # Derive threshold at separation point
            if won_median < lost_p25:
                threshold = round((won_median + lost_p25) / 2)
                method = "Midpoint won-lost"
            else:
                threshold = round(lost_p25)
                method = "Lost P25 (overlap)"

            thresholds[(bucket, segment)] = {
                'threshold_days': threshold,
                'won_median': round(won_median, 1),
                'lost_p25': round(lost_p25, 1),
                'lost_median': round(lost_median, 1),
                'won_sample': len(won_gaps),
                'lost_sample': len(lost_gaps),
                'method': method,
                'status': 'derived'
            }

            print(f"{bucket:<20} {segment:<15} {won_median:<10.1f} {lost_p25:<10.1f} {threshold:<10} {method:<20}")

        print()
        print(f"Total thresholds derived: {len(thresholds)}")
    else:
        print("=" * 80)
        print("NO THRESHOLDS DERIVED - Insufficient sample sizes")
        print("=" * 80)
        thresholds = {}

    print()

    # ========================================================================
    # FALLBACK STRATEGY (Stage-only, no segment)
    # ========================================================================
    print("=" * 80)
    print("FALLBACK STRATEGY (Stage-Only, No Segment)")
    print("=" * 80)
    print()

    # Group by stage only
    gaps_by_stage = defaultdict(lambda: {'won': [], 'lost': []})

    for (bucket, segment), data in gaps_by_cell.items():
        gaps_by_stage[bucket]['won'].extend(data['won'])
        gaps_by_stage[bucket]['lost'].extend(data['lost'])

    print(f"{'Stage':<20} {'Won Gaps':<10} {'Lost Gaps':<10} {'Won Med':<10} {'Lost P25':<10} {'Threshold':<10} {'Method':<20}")
    print("-" * 110)

    fallback_thresholds = {}

    for bucket, data in sorted(gaps_by_stage.items()):
        won_gaps = data['won']
        lost_gaps = data['lost']

        if len(won_gaps) < MIN_SAMPLE_PER_CELL or len(lost_gaps) < MIN_SAMPLE_PER_CELL:
            print(f"{bucket:<20} {len(won_gaps):<10} {len(lost_gaps):<10} {'N/A':<10} {'N/A':<10} {'N/A':<10} {'Insufficient':<20}")
            continue

        won_median = statistics.median(won_gaps)
        lost_sorted = sorted(lost_gaps)
        lost_p25 = statistics.quantiles(lost_sorted, n=4)[0] if len(lost_sorted) >= 4 else lost_sorted[0]

        if won_median < lost_p25:
            threshold = round((won_median + lost_p25) / 2)
            method = "Midpoint won-lost"
        else:
            threshold = round(lost_p25)
            method = "Lost P25 (overlap)"

        fallback_thresholds[bucket] = {
            'threshold_days': threshold,
            'won_median': round(won_median, 1),
            'lost_p25': round(lost_p25, 1),
            'won_sample': len(won_gaps),
            'lost_sample': len(lost_gaps),
            'method': method,
            'status': 'fallback_stage_only'
        }

        print(f"{bucket:<20} {len(won_gaps):<10} {len(lost_gaps):<10} {won_median:<10.1f} {lost_p25:<10.1f} {threshold:<10} {method:<20}")

    print()
    print(f"Fallback thresholds derived: {len(fallback_thresholds)}")
    print()

    # ========================================================================
    # FINAL RECOMMENDATION
    # ========================================================================
    print("=" * 80)
    print("FINAL ASSESSMENT")
    print("=" * 80)
    print()

    if cells_with_sufficient_sample >= (total_cells * 0.5):
        print("✅ SIGNAL 3 VIABLE:")
        print(f"   {cells_with_sufficient_sample}/{total_cells} cells have sufficient sample")
        print(f"   {len(thresholds)} segment-specific thresholds derived")
        print(f"   {len(fallback_thresholds)} stage-only fallbacks available")
        print()
        print("PROCEED with Signal 3 implementation using:")
        print("  1. Bulk event exclusion (10 cleanup months filtered)")
        print("  2. Truncation-aware gap computation")
        print("  3. Segment-specific thresholds where available")
        print("  4. Stage-only fallback otherwise")

        recommendation = "proceed"
    else:
        print("❌ SIGNAL 3 NOT VIABLE:")
        print(f"   Only {cells_with_sufficient_sample}/{total_cells} cells have sufficient sample")
        print(f"   ({100*cells_with_sufficient_sample/total_cells:.1f}% coverage)")
        print()
        print("DEFER Signal 3 until:")
        print("  1. More data accumulates (future deals without truncation)")
        print("  2. Alternative methodology developed (global threshold)")

        recommendation = "defer"

    print()

    # Save results
    output = {
        'recommendation': recommendation,
        'segment_specific': thresholds,
        'stage_only_fallback': fallback_thresholds,
        'coverage': {
            'total_cells': total_cells,
            'cells_with_sufficient_sample': cells_with_sufficient_sample,
            'cells_with_insufficient_sample': cells_with_insufficient_sample,
            'sufficient_pct': 100 * cells_with_sufficient_sample / total_cells if total_cells > 0 else 0
        },
        'exclusions_applied': {
            'bulk_cleanup_months': BULK_CLEANUP_MONTHS,
            'truncation_threshold_days': TRUNCATION_THRESHOLD_DAYS
        },
        'stats': stats
    }

    output_file = Path(__file__).parent.parent / 'signal3_derived_thresholds_with_exclusions.json'
    with open(output_file, 'w') as f:
        json.dump(output, f, indent=2)

    print(f"Results saved to: {output_file}")

if __name__ == '__main__':
    main()
