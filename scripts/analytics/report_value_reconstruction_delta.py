"""
Phase 2b — what changes when deal_value stops being proxied from today.

The prior backfill stamped today's deal_value on every historical week. That
made arr_change 0 by construction: a deal cannot change its own value
retroactively when every week carries the same number. This measures the
correction, per date, before any of it reaches an analysis:

  proxy  deals.deal_value as it stands today (what the old code wrote)
  pit    utils.compute_deal_value on point-in-time component history

Reports totals, how many deals move, the largest movers, and how many are
UNKNOWN at that date -- deals whose value history does not reach back, which
now write None instead of a fabricated 0.0.

Scoped to the analytics population, since that is what the conversion
analyses read.

Usage:
    python scripts/analytics/report_value_reconstruction_delta.py
    python scripts/analytics/report_value_reconstruction_delta.py --dates 2026-05-05,2026-08-19
"""
import argparse
import json
import os
import sys
from datetime import date, datetime
from pathlib import Path

REPO_ROOT = Path(__file__).parent.parent.parent
sys.path.insert(0, str(REPO_ROOT / 'scripts'))
sys.path.insert(0, str(REPO_ROOT / 'scripts' / 'analytics'))
sys.path.insert(0, str(REPO_ROOT / 'api'))

import yaml
from hubspot_history import HISTORY_KEYS
from point_in_time import (UnclassifiableStageError, get_field_at_date,
                           get_stage_at_date, is_deal_in_analytics_scope,
                           is_terminal_stage, load_scope_config)
from utils import compute_deal_value, get_value_properties

# One date per elapsed quarter in the reconstruction window, plus the week
# Method 1 captured, so the drift is visible across the whole span rather
# than only at the recent end where proxy and truth nearly agree.
DEFAULT_DATES = ['2025-11-04', '2026-01-27', '2026-04-28', '2026-07-28',
                 '2026-08-19']


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--cache-file', default='property_history_cache.json')
    parser.add_argument('--dates', default=None)
    args = parser.parse_args()

    cache_path = Path(args.cache_file)
    if not cache_path.exists():
        print(f"✗ cache not found: {cache_path}")
        return 2
    cache = json.loads(cache_path.read_text())

    config = yaml.safe_load((REPO_ROOT / 'config/client.yaml').read_text())
    value_props = get_value_properties(config)
    field_history = {
        prop: {d: {'history': r.get(HISTORY_KEYS[prop]) or []}
               for d, r in cache['deals'].items()}
        for prop in value_props
    }
    stage_history = cache['deals']

    from supabase import create_client
    from supabase_client import select_all
    sb = create_client(os.environ['SUPABASE_URL'],
                       os.environ['SUPABASE_SERVICE_KEY'])
    deals = {str(d['deal_id']): d for d in select_all(
        sb, 'deals',
        columns='deal_id,create_date,pipeline_id,deal_value,company_name')}

    excluded_pipelines, stage_cfg = load_scope_config(config)
    dates = ([d.strip() for d in args.dates.split(',')]
             if args.dates else DEFAULT_DATES)

    print("=" * 96)
    print("PHASE 2b — deal_value: PROXY (today's value) vs POINT-IN-TIME")
    print("=" * 96)
    print(f"\nCache: {len(stage_history)} deals   deals table: {len(deals)}")
    print(f"Value rule components: {', '.join(value_props)}")

    summary = []
    for ds in dates:
        D = date.fromisoformat(ds)
        Ddt = datetime.combine(D, datetime.min.time())

        proxy_total = pit_total = 0.0
        n_scope = n_moved = n_unknown = n_same = 0
        movers = []

        for deal_id, d in deals.items():
            cd = d.get('create_date')
            if not cd:
                continue
            if datetime.fromisoformat(cd).date() > D:
                continue

            stage, _, _ = get_stage_at_date(stage_history, deal_id, Ddt)
            if stage is None:
                continue
            try:
                if is_terminal_stage(stage):
                    continue
            except UnclassifiableStageError:
                continue
            if not is_deal_in_analytics_scope(stage, d.get('pipeline_id'),
                                             excluded_pipelines, stage_cfg):
                continue

            n_scope += 1
            proxy = float(d.get('deal_value') or 0.0)

            pit_props, confs = {}, []
            for prop in value_props:
                v, c = get_field_at_date(field_history[prop], deal_id, Ddt)
                pit_props[prop] = v
                confs.append(c)

            if 'exact' not in confs:
                n_unknown += 1
                proxy_total += proxy
                movers.append((proxy, None, d.get('company_name') or deal_id))
                continue

            pit = compute_deal_value(pit_props, config, d.get('pipeline_id'))
            proxy_total += proxy
            pit_total += pit
            if abs(pit - proxy) > 0.01:
                n_moved += 1
                movers.append((proxy, pit, d.get('company_name') or deal_id))
            else:
                n_same += 1

        drift = ((pit_total - proxy_total) / proxy_total * 100
                 if proxy_total else 0.0)
        summary.append((ds, n_scope, proxy_total, pit_total, drift,
                        n_moved, n_same, n_unknown))

        print("\n" + "=" * 96)
        print(f"{ds}   in-scope open deals: {n_scope}")
        print("=" * 96)
        print(f"  proxy total   ${proxy_total:>14,.0f}")
        print(f"  pit total     ${pit_total:>14,.0f}   ({drift:+.1f}%)")
        print(f"  moved: {n_moved}   unchanged: {n_same}   "
              f"unknown at this date (now null, was proxied): {n_unknown}")

        known = [m for m in movers if m[1] is not None]
        known.sort(key=lambda m: -abs(m[1] - m[0]))
        if known:
            print(f"\n  largest movers:")
            print(f"    {'proxy':>12} {'point-in-time':>14} {'delta':>13}  name")
            for proxy, pit, name in known[:10]:
                print(f"    {proxy:>12,.0f} {pit:>14,.0f} "
                      f"{pit - proxy:>+13,.0f}  {str(name)[:34]}")
        unknown = [m for m in movers if m[1] is None]
        if unknown:
            print(f"\n  unknown at this date ({len(unknown)}), "
                  f"proxy would have claimed:")
            for proxy, _, name in sorted(unknown, key=lambda m: -m[0])[:8]:
                print(f"    {proxy:>12,.0f}  ->  null    {str(name)[:34]}")

    print("\n" + "=" * 96)
    print("SUMMARY")
    print("=" * 96)
    print(f"{'date':<12} {'deals':>6} {'proxy $':>14} {'pit $':>14} "
          f"{'drift':>8} {'moved':>6} {'same':>6} {'unknown':>8}")
    for ds, n, pxy, pit, drift, moved, same, unk in summary:
        print(f"{ds:<12} {n:>6} {pxy:>14,.0f} {pit:>14,.0f} "
              f"{drift:>7.1f}% {moved:>6} {same:>6} {unk:>8}")

    print("\nProxy totals are identical per deal across dates by construction —")
    print("that is the defect. Any drift below is real value movement the")
    print("proxy erased, and 'unknown' rows are dates where the proxy asserted")
    print("a number the history does not support.")
    return 0


if __name__ == '__main__':
    sys.exit(main())
