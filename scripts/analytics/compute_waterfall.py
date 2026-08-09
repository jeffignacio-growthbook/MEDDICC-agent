#!/usr/bin/env python3
"""
Computes week-over-week pipeline waterfall from deals_snapshot.
Uses the two most recent snapshot dates (not "exactly 7 days
prior" — uses nearest prior to survive missed crons).
Writes to waterfall_weekly table.

Usage: python scripts/analytics/compute_waterfall.py
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
    from utils import load_client_config

    sb = create_client(SUPABASE_URL, SUPABASE_KEY)

    # Find the two most recent distinct snapshot dates
    dates_result = sb.table('deals_snapshot')\
        .select('snapshot_date')\
        .order('snapshot_date', desc=True)\
        .limit(200)\
        .execute()

    distinct_dates = sorted(set(
        r['snapshot_date'] for r in (dates_result.data or [])
    ), reverse=True)

    if len(distinct_dates) < 2:
        print("Insufficient snapshot history — need at least 2 "
              "snapshot dates. Skipping waterfall computation.")
        return

    new_date = distinct_dates[0]
    prev_date = distinct_dates[1]
    print(f"Comparing {new_date} vs {prev_date}")

    # Load both snapshots
    def load_snapshot(snap_date: str) -> dict:
        result = sb.table('deals_snapshot')\
            .select('*')\
            .eq('snapshot_date', snap_date)\
            .execute()
        return {r['deal_id']: r for r in (result.data or [])}

    new_snap = load_snapshot(new_date)
    prev_snap = load_snapshot(prev_date)

    config = load_client_config()

    # Diff into waterfall categories per pipeline
    from collections import defaultdict
    pipeline_waterfalls = defaultdict(lambda: {
        'new_pipeline_value': 0.0,
        'moved_forward_value': 0.0,
        'moved_backward_value': 0.0,
        'won_value': 0.0,
        'lost_value': 0.0,
        'net_change': 0.0,
        'deals_created_count': 0,
        'deals_qualified_count': 0,
        'details': [],
    })

    all_deal_ids = set(new_snap) | set(prev_snap)

    for deal_id in all_deal_ids:
        n = new_snap.get(deal_id)
        p = prev_snap.get(deal_id)
        pipeline_id = (n or p).get('pipeline_id', 'default')
        wf = pipeline_waterfalls[pipeline_id]
        value = float((n or p).get('deal_value') or 0)

        if n and not p:
            # New deal entered pipeline this week
            wf['new_pipeline_value'] += value
            wf['deals_created_count'] += 1
            wf['details'].append({
                'deal_id': deal_id,
                'change_type': 'new',
                'value': value,
            })
        elif p and not n:
            # Deal disappeared — shouldn't happen often
            wf['details'].append({
                'deal_id': deal_id,
                'change_type': 'removed',
                'value': value,
            })
        else:
            n_order = n.get('stage_order', 0) or 0
            p_order = p.get('stage_order', 0) or 0
            n_status = n.get('deal_status', 'active')
            p_status = p.get('deal_status', 'active')

            if n_status == 'won' and p_status != 'won':
                wf['won_value'] += value
                wf['details'].append({
                    'deal_id': deal_id,
                    'change_type': 'won', 'value': value,
                })
            elif n_status == 'lost' and p_status != 'lost':
                wf['lost_value'] += value
                wf['details'].append({
                    'deal_id': deal_id,
                    'change_type': 'lost', 'value': value,
                })
            elif n_order > p_order:
                wf['moved_forward_value'] += value
                wf['details'].append({
                    'deal_id': deal_id,
                    'change_type': 'moved_forward',
                    'from_order': p_order,
                    'to_order': n_order,
                    'value': value,
                })
            elif n_order < p_order:
                wf['moved_backward_value'] += value
                wf['details'].append({
                    'deal_id': deal_id,
                    'change_type': 'moved_backward',
                    'from_order': p_order,
                    'to_order': n_order,
                    'value': value,
                })

    for pipeline_id, wf in pipeline_waterfalls.items():
        wf['net_change'] = (
            wf['new_pipeline_value']
            + wf['moved_forward_value']
            - wf['moved_backward_value']
            - wf['won_value']
            - wf['lost_value']
        )
        row = {
            'week_ending': new_date,
            'pipeline_id': pipeline_id,
            'new_pipeline_value': wf['new_pipeline_value'],
            'moved_forward_value': wf['moved_forward_value'],
            'moved_backward_value': wf['moved_backward_value'],
            'won_value': wf['won_value'],
            'lost_value': wf['lost_value'],
            'net_change': wf['net_change'],
            'deals_created_count': wf['deals_created_count'],
            'deals_qualified_count': wf['deals_qualified_count'],
            'details': json.dumps(wf['details']),
            'computed_source': 'prospective',
        }
        sb.table('waterfall_weekly').upsert(
            row, on_conflict='week_ending,pipeline_id'
        ).execute()
        print(f"✓ Waterfall {new_date} / {pipeline_id}: "
              f"won={wf['won_value']:.0f}, "
              f"lost={wf['lost_value']:.0f}, "
              f"new={wf['new_pipeline_value']:.0f}, "
              f"net={wf['net_change']:.0f}")


if __name__ == '__main__':
    main()
