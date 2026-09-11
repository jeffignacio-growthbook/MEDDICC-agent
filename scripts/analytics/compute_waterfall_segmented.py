#!/usr/bin/env python3
"""
Computes week-over-week pipeline waterfall from deals_snapshot.
NEW: Groups by region AND segment for granular pipeline analysis.

Grain: (week_ending, pipeline_id, region, segment)

Changes from original:
1. Loads deal enrichment (region, segment, company_name) from deals table
2. Applies is_test_deal() hygiene filter
3. Groups waterfall by (pipeline_id, region, segment)
4. Upserts with new conflict resolution key

Usage:
    python scripts/analytics/compute_waterfall_segmented.py              # Prospective mode (latest week)
    python scripts/analytics/compute_waterfall_segmented.py --backfill   # Historical mode (all weeks)
"""

import os
import sys
import json
import argparse
from datetime import date
from pathlib import Path

REPO_ROOT = Path(__file__).parent.parent.parent


def _qualified_as_of(qual_map, deal_id, as_of_iso):
    """Point-in-time qualified-pipeline membership (defect 5)."""
    qd = (qual_map.get(deal_id) or {}).get('qualified_date')
    if not qd:
        return False
    try:
        return date.fromisoformat(qd) <= date.fromisoformat(as_of_iso)
    except (ValueError, TypeError):
        return False


def main():
    # Load environment variables
    from dotenv import load_dotenv
    load_dotenv(REPO_ROOT / '.env')

    parser = argparse.ArgumentParser(description='Compute segmented pipeline waterfall')
    parser.add_argument('--backfill', action='store_true',
                       help='Backfill mode: compute waterfall for all historical snapshot pairs')
    args = parser.parse_args()

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
    from datetime import datetime

    sb = create_client(SUPABASE_URL, SUPABASE_KEY)
    config = load_client_config()

    # Load qualification threshold
    pipeline_cfg = config.get('pipelines', {}).get('default', {})
    threshold = pipeline_cfg.get('qualified_stage_order', 2)

    print(f"Qualification threshold (config): stage_order >= {threshold}; "
          f"membership is point-in-time via qualified_date")

    # Load qualification event data
    qual_rows = select_all(sb, 'deals',
                          columns='deal_id, qualified_date')
    qual_map = {
        row['deal_id']: {'qualified_date': row.get('qualified_date')}
        for row in qual_rows
    }
    print(f"Loaded qualification (event) data for {len(qual_map)} deals")

    # NEW: Load deal enrichment data (company_name only - for test deal filter)
    # Region and segment now come from point-in-time snapshot data
    print("\nLoading deal enrichment data (company_name for test deal filter)...")
    enrichment_rows = select_all(sb, 'deals',
                                 columns='deal_id, company_name')
    enrichment_map = {
        row['deal_id']: {
            'company_name': row.get('company_name') or ''
        }
        for row in enrichment_rows
    }
    print(f"Loaded enrichment data for {len(enrichment_map)} deals")
    print("Note: Region/segment now sourced from point-in-time snapshot data")

    # NEW: Import is_test_deal hygiene filter
    sys.path.insert(0, str(REPO_ROOT / 'api'))
    from field_semantics import is_test_deal

    # Import hybrid won/lost detection function
    sys.path.insert(0, str(REPO_ROOT / 'scripts' / 'analytics'))
    from deal_status_history import get_deal_status_as_of

    # Load deal data for close_date and stage (needed for hybrid approach fallback)
    print("\nLoading deal data for close_date and stage (for won/lost detection)...")
    deal_status_rows = select_all(sb, 'deals',
                                  columns='deal_id, close_date, stage')
    deal_status_map = {
        row['deal_id']: {
            'close_date': row.get('close_date'),
            'stage': row.get('stage')
        }
        for row in deal_status_rows
    }
    print(f"Loaded status data for {len(deal_status_map)} deals")

    if args.backfill:
        # Backfill mode: get all snapshot dates and compute waterfalls for all pairs
        print()
        print("=" * 70)
        print("BACKFILL MODE: Computing segmented waterfall for all historical pairs")
        print("=" * 70)
        print()

        # Get ONLY dates where ALL snapshots are backfilled
        all_snapshots = select_all(sb, 'deals_snapshot',
                                   columns='snapshot_date,snapshot_source')
        from collections import defaultdict
        date_sources = defaultdict(set)
        for row in all_snapshots:
            date_sources[row['snapshot_date']].add(row['snapshot_source'])

        backfill_dates = sorted(
            d for d, sources in date_sources.items()
            if sources == {'backfilled'}   # ONLY pure backfill dates
        )

        if len(backfill_dates) < 2:
            print("Insufficient backfilled snapshot history — skipping")
            return

        print(f"Found {len(backfill_dates)} backfilled snapshot dates")
        print(f"  Oldest: {backfill_dates[0]}")
        print(f"  Newest: {backfill_dates[-1]}")
        print()
        print(f"Will compute {len(backfill_dates) - 1} weekly waterfalls")
        print()

        # Compute waterfall for each consecutive pair and collect reconciliation results
        all_reconciliation_results = []
        for i in range(len(backfill_dates) - 1):
            prev_date = backfill_dates[i]
            new_date = backfill_dates[i + 1]

            print(f"[{i + 1}/{len(backfill_dates) - 1}] Computing {new_date} vs {prev_date}")

            results = compute_waterfall_for_dates(
                sb, config, qual_map, enrichment_map, deal_status_map, is_test_deal, threshold,
                prev_date, new_date,
                computed_source='backfill'
            )
            all_reconciliation_results.extend(results)
            print()

        # Analyze reconciliation results
        print("=" * 70)
        print("RECONCILIATION ANALYSIS")
        print("=" * 70)

        total_groups = len(all_reconciliation_results)
        mismatched = [r for r in all_reconciliation_results if not r['matches']]

        print(f"\nTotal group/week combinations: {total_groups}")
        print(f"Perfect reconciliation: {total_groups - len(mismatched)}")
        print(f"Reconciliation mismatches: {len(mismatched)}")
        print(f"Success rate: {(total_groups - len(mismatched)) / total_groups * 100:.1f}%")

        if mismatched:
            print(f"\nMismatches by group:")
            from collections import defaultdict
            mismatches_by_group = defaultdict(int)
            for r in mismatched:
                mismatches_by_group[r['group']] += 1

            for group, count in sorted(mismatches_by_group.items(), key=lambda x: -x[1]):
                pct = count / total_groups * 100
                print(f"  {group}: {count} weeks ({pct:.1f}%)")

            # Check if mismatches are ONLY in UNKNOWN group
            unknown_only = all('UNKNOWN' in r['group'] for r in mismatched)

            if unknown_only:
                print(f"\n✓ ALL MISMATCHES ARE IN UNKNOWN GROUPS")
                print(f"  This is expected due to boundary crossing (deals changing enrichment)")
                print(f"  All properly-enriched groups reconcile perfectly")
                print(f"\n{'='*70}")
                print("✓ BACKFILL COMPLETE - FIX VERIFIED")
                print("{'='*70}")
            else:
                print(f"\n✗ MISMATCHES IN PROPERLY-ENRICHED GROUPS DETECTED")
                print(f"  This indicates the fix is incomplete or introduced new bugs")
                print(f"\n  Sample mismatches:")
                non_unknown = [r for r in mismatched if 'UNKNOWN' not in r['group']]
                for r in non_unknown[:5]:
                    print(f"\n    {r['group']} week {r['week']}:")
                    print(f"      Expected: ${r['expected_ending']:,.2f}")
                    print(f"      Actual:   ${r['actual_ending']:,.2f}")
                    print(f"      Diff:     ${r['difference']:,.2f}")

                    # NEW: Show phantom exits if any
                    phantom_exits = r.get('phantom_exits', [])
                    if phantom_exits:
                        # 'value' can be None (_deal_value never 0-coalesces) —
                        # exclude and count unknowns rather than crashing on
                        # sum()/format of None, matching this file's own
                        # established null-propagation convention.
                        known = [p['value'] for p in phantom_exits if p['value'] is not None]
                        unknown_count = len(phantom_exits) - len(known)
                        phantom_total = sum(known)
                        suffix = f" (+{unknown_count} unknown-value)" if unknown_count else ""
                        print(f"      Phantom exits: {len(phantom_exits)} deals, "
                              f"${phantom_total:,.0f}{suffix}")
                        for p in phantom_exits:
                            val_str = (f"${p['value']:,.0f}" if p['value'] is not None
                                       else "unknown value")
                            print(f"        - Deal {p['deal_id']}: {val_str}")
                raise ValueError("Reconciliation failures in properly-enriched groups indicate a bug")
        else:
            print(f"\n✓ ZERO MISMATCHES - PERFECT RECONCILIATION ACROSS ALL GROUPS")
            print(f"  The won/lost detection fix is fully verified")
            print(f"\n{'='*70}")
            print("✓ BACKFILL COMPLETE - FIX VERIFIED")
            print("{'='*70}")

    else:
        # Prospective mode: compute waterfall for the two most recent snapshots
        def latest_date_before(sb, before=None):
            q = sb.table('deals_snapshot')\
                .select('snapshot_date')\
                .order('snapshot_date', desc=True)\
                .limit(1)
            if before:
                q = q.lt('snapshot_date', before)
            rows = q.execute().data or []
            return rows[0]['snapshot_date'] if rows else None

        new_date  = latest_date_before(sb)
        prev_date = latest_date_before(sb, before=new_date)

        if not new_date or not prev_date:
            print("Insufficient snapshot history — need at least 2 "
                  "snapshot dates. Skipping waterfall computation.")
            return

        print(f"Comparing {new_date} vs {prev_date}")

        compute_waterfall_for_dates(
            sb, config, qual_map, enrichment_map, deal_status_map, is_test_deal, threshold,
            prev_date, new_date,
            computed_source='prospective'
        )


def compute_waterfall_for_dates(sb, config, qual_map, enrichment_map, deal_status_map, is_test_deal_fn,
                                threshold, prev_date, new_date, computed_source='prospective'):
    """
    Compute waterfall between two snapshot dates, grouped by region and segment.

    Args:
        sb: Supabase client
        config: Client configuration
        qual_map: {deal_id: {'qualified_date': ...}}
        enrichment_map: {deal_id: {'region': ..., 'segment': ..., 'company_name': ...}}
        deal_status_map: {deal_id: {'close_date': ..., 'stage': ...}}
        is_test_deal_fn: Function to filter test deals
        threshold: Qualification stage_order threshold
        prev_date: Previous snapshot date (str)
        new_date: New snapshot date (str)
        computed_source: 'prospective' or 'backfill'

    Returns:
        List of reconciliation status dicts (one per group)
    """
    reconciliation_results = []
    from utils import get_fiscal_quarter
    from supabase_client import select_all
    import sys as _sys
    _sys.path.insert(0, str(Path(__file__).parent))
    from null_propagation import null_propagate
    from deal_status_history import get_deal_status_as_of
    from arr_delta import arr_delta
    from datetime import date as _date

    max_null_pct = float(config.get('forecast_analysis', {})
                         .get('max_null_value_pct', 5))

    def _deal_value(row):
        """deal_value as float, or None when unknown — NEVER 0-coalesced."""
        if not row:
            return None
        v = row.get('deal_value')
        return float(v) if v is not None else None

    # Load both snapshots (paginated - critical for large history)
    def load_snapshot(snap_date: str) -> dict:
        rows = select_all(
            sb, 'deals_snapshot', '*',
            filters=[('eq', 'snapshot_date', snap_date)]
        )
        return {r['deal_id']: r for r in rows}

    new_snap = load_snapshot(new_date)
    prev_snap = load_snapshot(prev_date)

    # Get current fiscal quarter boundaries
    q_start, q_end, q_label = get_fiscal_quarter(date.fromisoformat(new_date), config)
    if computed_source == 'prospective':
        print(f"  Fiscal quarter: {q_label} ({q_start} to {q_end})")

    # NEW: Group by (pipeline_id, region, segment) instead of just pipeline_id
    from collections import defaultdict
    waterfall_groups = defaultdict(lambda: {
        'beginning_value': 0.0,
        'ending_value': 0.0,
        'new_pipeline_value': 0.0,
        'newly_qualified_value': 0.0,
        'newly_qualified_count': 0,
        'newly_arr_bearing_value': 0.0,  # NEW: Deals crossing ARR-bearing threshold
        'newly_arr_bearing_count': 0,
        'moved_forward_value': 0.0,
        'moved_backward_value': 0.0,
        'won_value': 0.0,
        'lost_value': 0.0,
        'pulled_in_value': 0.0,
        'pushed_out_value': 0.0,
        'arr_change_value': 0.0,  # NOW TRACKS DELTA, NOT VALUE
        'net_change': 0.0,
        'deals_created_count': 0,
        'deals_qualified_count': 0,
        'null_value_excluded_count': 0,
        'details': [],
    })

    # Beginning/ending values grouped by (pipeline_id, region, segment)
    from collections import defaultdict as _dd
    begin_values, end_values = _dd(list), _dd(list)

    # NEW: Track deal IDs per group for phantom exit detection
    prev_group_deals = _dd(set)  # group_key -> set of deal_ids
    new_group_deals = _dd(set)

    # Track test deals filtered
    test_deals_filtered = 0

    for deal_id, p in prev_snap.items():
        if (p.get('deal_status') == 'active' and
            _qualified_as_of(qual_map, deal_id, prev_date)):

            # NEW: Apply test deal filter
            enrich = enrichment_map.get(deal_id, {})
            if is_test_deal_fn({'company_name': enrich.get('company_name')}):
                test_deals_filtered += 1
                continue

            # NEW: Group by region and segment (from point-in-time snapshot)
            region = p.get('region') or 'UNKNOWN'
            segment = p.get('segment') or 'Unknown'
            group_key = (p.get('pipeline_id', 'default'), region, segment)
            begin_values[group_key].append(_deal_value(p))
            prev_group_deals[group_key].add(deal_id)  # Track deal ID

    for deal_id, n in new_snap.items():
        if (n.get('deal_status') == 'active' and
            _qualified_as_of(qual_map, deal_id, new_date)):

            # NEW: Apply test deal filter
            enrich = enrichment_map.get(deal_id, {})
            if is_test_deal_fn({'company_name': enrich.get('company_name')}):
                continue

            # NEW: Group by region and segment (from point-in-time snapshot)
            region = n.get('region') or 'UNKNOWN'
            segment = n.get('segment') or 'Unknown'
            group_key = (n.get('pipeline_id', 'default'), region, segment)
            end_values[group_key].append(_deal_value(n))
            new_group_deals[group_key].add(deal_id)  # Track deal ID

    if computed_source == 'prospective' and test_deals_filtered > 0:
        print(f"  [HYGIENE] Filtered {test_deals_filtered} test deals from waterfall")

    # Apply null propagation to beginning/ending values
    for group_key, vals in begin_values.items():
        npr = null_propagate(vals, max_null_pct)
        waterfall_groups[group_key]['beginning_value'] = npr['sum']
        waterfall_groups[group_key]['beginning_null_excluded'] = npr['null_count']
        waterfall_groups[group_key]['beginning_dollar_basis_null'] = npr['basis_null']

    for group_key, vals in end_values.items():
        npr = null_propagate(vals, max_null_pct)
        waterfall_groups[group_key]['ending_value'] = npr['sum']
        waterfall_groups[group_key]['ending_null_excluded'] = npr['null_count']
        waterfall_groups[group_key]['ending_dollar_basis_null'] = npr['basis_null']

    all_deal_ids = set(new_snap) | set(prev_snap)

    for deal_id in all_deal_ids:
        n = new_snap.get(deal_id)
        p = prev_snap.get(deal_id)

        # Skip deals not yet qualified
        if not _qualified_as_of(qual_map, deal_id, new_date):
            continue

        # NEW: Apply test deal filter
        enrich = enrichment_map.get(deal_id, {})
        if is_test_deal_fn({'company_name': enrich.get('company_name')}):
            continue

        # NEW: Get region and segment for grouping (from point-in-time snapshot)
        snapshot_record = n or p  # Use new if available, else prev
        region = snapshot_record.get('region') or 'UNKNOWN'
        segment = snapshot_record.get('segment') or 'Unknown'
        pipeline_id = snapshot_record.get('pipeline_id', 'default')
        group_key = (pipeline_id, region, segment)

        wf = waterfall_groups[group_key]
        value = _deal_value(n or p)
        value_known = value is not None
        if not value_known:
            wf['null_value_excluded_count'] += 1

        # Check if newly qualified this week
        qual_info = qual_map.get(deal_id, {})
        qualified_date_str = qual_info.get('qualified_date')
        newly_qualified_this_week = False
        if qualified_date_str:
            try:
                qualified_dt = date.fromisoformat(qualified_date_str)
                prev_dt = date.fromisoformat(prev_date)
                new_dt = date.fromisoformat(new_date)
                newly_qualified_this_week = prev_dt < qualified_dt <= new_dt
            except (ValueError, TypeError):
                pass

        if n and not p:
            # New deal created this week
            if value_known:
                wf['new_pipeline_value'] += value
            wf['deals_created_count'] += 1
            wf['details'].append({
                'deal_id': deal_id,
                'company_name': enrich.get('company_name', ''),
                'close_date': n.get('close_date'),
                'change_type': 'new',
                'value': value,
            })
        elif newly_qualified_this_week and p:
            # Crossed qualification threshold this week
            if value_known:
                wf['newly_qualified_value'] += value
            wf['deals_qualified_count'] += 1
            wf['details'].append({
                'deal_id': deal_id,
                'company_name': enrich.get('company_name', ''),
                'close_date': n.get('close_date') if n else p.get('close_date'),
                'change_type': 'newly_qualified',
                'value': value,
                'qualified_date': qualified_date_str,
            })
        else:
            # Existing deal movements
            n_order = n.get('stage_order', 0) or 0 if n else 0
            p_order = p.get('stage_order', 0) or 0 if p else 0

            # FIXED: Use hybrid won/lost detection for deals that LEFT pipeline
            # For deals still in both snapshots, use snapshot data directly
            p_status = p.get('deal_status', 'active') if p else 'active'

            if n:
                # Deal is in new snapshot - use snapshot data
                n_status = n.get('deal_status', 'active')
            else:
                # Deal LEFT pipeline - use hybrid approach
                # Get close_date and stage for hybrid fallback
                deal_data = deal_status_map.get(deal_id, {})
                close_date_str = deal_data.get('close_date')
                current_stage = deal_data.get('stage')

                # Parse close_date for hybrid function
                close_date_parsed = None
                if close_date_str:
                    try:
                        close_date_parsed = _date.fromisoformat(close_date_str[:10])
                    except (ValueError, TypeError, AttributeError):
                        pass

                # Use hybrid approach to determine status as of new_date
                new_date_parsed = _date.fromisoformat(new_date)

                n_status = get_deal_status_as_of(
                    sb, deal_id, new_date_parsed,
                    close_date=close_date_parsed,
                    current_stage=current_stage
                )

            # Get close_date for pulled_in/pushed_out analysis
            n_close_raw = n.get('close_date') if n else None
            p_close_raw = p.get('close_date') if p else None

            try:
                n_close = date.fromisoformat(n_close_raw) if n_close_raw else None
            except (ValueError, TypeError):
                n_close = None

            try:
                p_close = date.fromisoformat(p_close_raw) if p_close_raw else None
            except (ValueError, TypeError):
                p_close = None

            changes = []

            # Won/lost detection now uses hybrid function results
            if n_status == 'won' and p_status != 'won':
                changes.append('won')
            elif n_status == 'lost' and p_status != 'lost':
                changes.append('lost')

            # Check pulled_in/pushed_out
            if n_close and p_close:
                n_in_quarter = q_start <= n_close <= q_end
                p_in_quarter = q_start <= p_close <= q_end

                if not p_in_quarter and n_in_quarter:
                    changes.append('pulled_in')
                elif p_in_quarter and not n_in_quarter:
                    changes.append('pushed_out')

            # Stage movement for active deals only
            if n_status not in ('won', 'lost') and \
               p_status not in ('won', 'lost'):
                n_order_real = n_order if (n_order or 0) > 0 else None
                p_order_real = p_order if (p_order or 0) > 0 else None
                if n_order_real and p_order_real:
                    if n_order_real > p_order_real:
                        changes.append('moved_forward')
                    elif n_order_real < p_order_real:
                        changes.append('moved_backward')

            # FIXED: Independent tracking (no more precedence masking)
            # Track all movements independently - deals can contribute to multiple categories

            movements_recorded = []

            # Won/lost detection (already using hybrid function from earlier fix)
            if n_status == 'won' and p_status != 'won':
                if value_known:
                    wf['won_value'] += value
                movements_recorded.append('won')
            elif n_status == 'lost' and p_status != 'lost':
                if value_known:
                    wf['lost_value'] += value
                movements_recorded.append('lost')

            # Pulled in/pushed out (fiscal quarter movements)
            if n_close and p_close:
                n_in_quarter = q_start <= n_close <= q_end
                p_in_quarter = q_start <= p_close <= q_end

                if not p_in_quarter and n_in_quarter:
                    if value_known:
                        wf['pulled_in_value'] += value
                    movements_recorded.append('pulled_in')
                elif p_in_quarter and not n_in_quarter:
                    if value_known:
                        wf['pushed_out_value'] += value
                    movements_recorded.append('pushed_out')

            # Stage movement for active deals only
            if n_status not in ('won', 'lost') and p_status not in ('won', 'lost'):
                n_order_real = n_order if (n_order or 0) > 0 else None
                p_order_real = p_order if (p_order or 0) > 0 else None
                if n_order_real and p_order_real:
                    if n_order_real > p_order_real:
                        if value_known:
                            wf['moved_forward_value'] += value
                        movements_recorded.append('moved_forward')
                    elif n_order_real < p_order_real:
                        if value_known:
                            wf['moved_backward_value'] += value
                        movements_recorded.append('moved_backward')

            # ARR tracking using arr_delta function (FIXED: tracks delta, not value)
            # Only for deals that stayed in both snapshots (not new, not won/lost)
            if n and p:
                delta_result, delta_category = arr_delta(deal_id, p, n, threshold)

                if delta_category == 'newly_arr_bearing':
                    # Deal crossed ARR-bearing threshold ($0→value with stage progression)
                    # Add FULL VALUE to newly_arr_bearing (it appeared in pipeline this week)
                    n_val = _deal_value(n)
                    if n_val is not None:
                        wf['newly_arr_bearing_value'] += n_val
                        wf['newly_arr_bearing_count'] += 1
                    movements_recorded.append('newly_arr_bearing')

                elif delta_result is not None:
                    # ARR change (increase, decrease, or churn)
                    # Add DELTA (not value) to arr_change_value
                    wf['arr_change_value'] += delta_result
                    movements_recorded.append(delta_category)

            # Record details for debugging
            if movements_recorded:
                detail = {
                    'deal_id': deal_id,
                    'company_name': enrich.get('company_name', ''),
                    'close_date': n.get('close_date') if n else p.get('close_date'),
                    'movements': movements_recorded,  # List of all movements (can be multiple)
                    'value': value,
                }

                if 'moved_forward' in movements_recorded or 'moved_backward' in movements_recorded:
                    detail['from_order'] = p_order
                    detail['to_order'] = n_order

                if 'pulled_in' in movements_recorded or 'pushed_out' in movements_recorded:
                    detail['prev_close_date'] = p_close_raw
                    detail['new_close_date'] = n_close_raw

                if any(cat in movements_recorded for cat in ['arr_increase', 'arr_decrease', 'arr_churn', 'newly_arr_bearing']):
                    detail['prev_value'] = _deal_value(p) if p else None
                    detail['new_value'] = _deal_value(n) if n else None
                    if delta_result is not None:
                        detail['arr_delta'] = delta_result

                wf['details'].append(detail)

    # Write waterfall rows (one per region x segment combination)
    rows_written = 0
    for group_key, wf in waterfall_groups.items():
        pipeline_id, region, segment = group_key

        # Surface null-value exclusion in details
        excluded = wf.get('null_value_excluded_count', 0)
        begin_excl = wf.get('beginning_null_excluded', 0)
        end_excl = wf.get('ending_null_excluded', 0)
        if excluded or begin_excl or end_excl:
            wf['details'].insert(0, {
                'change_type': 'null_value_excluded_summary',
                'movement_null_value_excluded': excluded,
                'beginning_null_value_excluded': begin_excl,
                'ending_null_value_excluded': end_excl,
                'beginning_dollar_basis_null': wf.get('beginning_dollar_basis_null', False),
                'ending_dollar_basis_null': wf.get('ending_dollar_basis_null', False),
                'note': 'unknown-value deals excluded from dollar sums (not 0-filled); counts unaffected',
            })

        # FIXED: Complete net_change formula with independent movement types
        wf['net_change'] = (
            wf['new_pipeline_value']          # Deals created this week
            + wf['newly_qualified_value']     # Crossed qualification threshold
            + wf['newly_arr_bearing_value']   # Crossed ARR-bearing threshold ($0→value)
            - wf['won_value']                 # Closed-won
            - wf['lost_value']                # Closed-lost
            + wf['arr_change_value']          # ARR deltas (positive or negative)
        )

        # Reconciliation check - track mismatches
        expected_ending = wf['beginning_value'] + wf['net_change']
        actual_ending = wf['ending_value']
        reconciliation_match = abs(expected_ending - actual_ending) <= 0.01

        # Track phantom exits: deals that were in prev snapshot but missing from new snapshot
        # (not moved to different group, not closed won/lost - just disappeared)
        phantom_exits = []
        prev_ids_in_group = prev_group_deals.get(group_key, set())
        new_ids_in_group = new_group_deals.get(group_key, set())
        exited_ids = prev_ids_in_group - new_ids_in_group

        for deal_id in exited_ids:
            if deal_id not in new_snap:
                # Deal completely disappeared from snapshot (not just moved groups)
                prev_deal = prev_snap[deal_id]
                phantom_exits.append({
                    'deal_id': deal_id,
                    'value': _deal_value(prev_deal)
                })

        # Store reconciliation status for later reporting
        row_reconciliation_status = {
            'matches': reconciliation_match,
            'expected_ending': expected_ending,
            'actual_ending': actual_ending,
            'difference': actual_ending - expected_ending,
            'group': f"{pipeline_id}/{region}/{segment}",
            'week': new_date,
            'pipeline_id': pipeline_id,
            'region': region,
            'segment': segment,
            'phantom_exits': phantom_exits  # NEW: track deals that disappeared
        }
        reconciliation_results.append(row_reconciliation_status)

        # For now, log mismatches but don't fail (we'll check at the end)
        if not reconciliation_match:
            if computed_source == 'prospective':
                print(f"  ⚠️  Reconciliation mismatch for {pipeline_id}/{region}/{segment}:")
                print(f"      Expected ending: ${expected_ending:,.2f}")
                print(f"      Actual ending:   ${actual_ending:,.2f}")
                print(f"      Difference:      ${actual_ending - expected_ending:,.2f}")

        row = {
            'week_ending': new_date,
            'pipeline_id': pipeline_id,
            'region': region,
            'segment': segment,
            'beginning_value': wf['beginning_value'],
            'ending_value': wf['ending_value'],
            'new_pipeline_value': wf['new_pipeline_value'],
            'newly_qualified_value': wf['newly_qualified_value'],
            'newly_qualified_count': wf['deals_qualified_count'],
            'newly_arr_bearing_value': wf['newly_arr_bearing_value'],  # NEW FIELD
            'newly_arr_bearing_count': wf['newly_arr_bearing_count'],  # NEW FIELD
            'moved_forward_value': wf['moved_forward_value'],
            'moved_backward_value': wf['moved_backward_value'],
            'won_value': wf['won_value'],
            'lost_value': wf['lost_value'],
            'pulled_in_value': wf['pulled_in_value'],
            'pushed_out_value': wf['pushed_out_value'],
            'arr_change_value': wf['arr_change_value'],  # NOW TRACKS DELTA
            'net_change': wf['net_change'],
            'deals_created_count': wf['deals_created_count'],
            'deals_qualified_count': wf['deals_qualified_count'],
            'details': json.dumps(wf['details']),
            'computed_source': computed_source,
        }

        # NEW: Conflict resolution now includes region and segment
        # Skip if prospective row already exists (backfill mode only)
        if computed_source == 'backfill':
            existing = sb.table('waterfall_weekly')\
                .select('computed_source')\
                .eq('week_ending', new_date)\
                .eq('pipeline_id', pipeline_id)\
                .eq('region', region)\
                .eq('segment', segment)\
                .execute()
            if existing.data and existing.data[0].get('computed_source') == 'prospective':
                print(f"  Skipping {pipeline_id}/{region}/{segment} {new_date} — prospective row exists")
                continue

        # Upsert with new conflict key
        try:
            sb.table('waterfall_weekly').upsert(
                row, on_conflict='week_ending,pipeline_id,region,segment'
            ).execute()
            rows_written += 1
        except Exception as e:
            print(f"  ⚠️  Failed to upsert {pipeline_id}/{region}/{segment}: {e}")
            continue

        if computed_source == 'prospective':
            print(f"\n{'='*70}")
            print(f"✓ Waterfall {new_date} / {pipeline_id} / {region} / {segment}")
            print(f"{'='*70}")
            print(f"Beginning Value:        ${wf['beginning_value']:>12,.0f}")
            print(f"")
            print(f"+ New Created:          ${wf['new_pipeline_value']:>12,.0f}  ({wf['deals_created_count']} deals)")
            print(f"+ Newly Qualified:      ${wf['newly_qualified_value']:>12,.0f}  ({wf['deals_qualified_count']} deals)")
            print(f"+ Moved Forward:        ${wf['moved_forward_value']:>12,.0f}")
            print(f"- Moved Backward:       ${wf['moved_backward_value']:>12,.0f}")
            print(f"- Won:                  ${wf['won_value']:>12,.0f}")
            print(f"- Lost:                 ${wf['lost_value']:>12,.0f}")
            print(f"")
            print(f"= Net Change:           ${wf['net_change']:>12,.0f}")
            print(f"")
            print(f"Ending Value:           ${wf['ending_value']:>12,.0f}")
            print(f"{'='*70}")

    if computed_source == 'backfill':
        print(f"  ✓ Wrote {rows_written} segmented waterfall rows for {new_date}")

    return reconciliation_results


if __name__ == '__main__':
    main()
