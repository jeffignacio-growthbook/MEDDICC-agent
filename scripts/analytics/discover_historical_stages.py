"""
Discover every stage ID that appears in HubSpot dealstage property history.

Reconstruction refuses to classify a stage field_semantics does not know
(point_in_time.UnclassifiableStageError), so this must run and come back
clean BEFORE any backfill. Historical reconstruction reaches back to 2023;
the current deal export only proves that today's stage IDs resolve.

Previously this script read deals.stage — the CURRENT stage of each deal —
despite its docstring claiming otherwise. It could not see a retired stage
that appears only in history, which is exactly the case that matters.

Inputs:
  - property_history_cache.json   (required; build with hubspot_history.py --all)
  - deals.stage from Supabase     (optional; adds the current-stage cross-check)

Exit code is non-zero if any stage ID cannot be classified, so this can gate
a backfill in CI.

Usage:
    python scripts/analytics/discover_historical_stages.py
    python scripts/analytics/discover_historical_stages.py --cache-file path.json
"""
import argparse
import json
import os
import sys
import yaml
from collections import defaultdict
from pathlib import Path

REPO_ROOT = Path(__file__).parent.parent.parent
sys.path.insert(0, str(REPO_ROOT / 'scripts'))
sys.path.insert(0, str(REPO_ROOT / 'api'))

from field_semantics import (RETIRED_STAGES, STAGE_MAP, is_retired_stage,
                             stage_bucket, stage_label)


NULL_VALUE = '<null>'   # a cleared dealstage, not a stage id


def load_client_yaml_stage_ids():
    """Stage IDs configured in config/client.yaml pipelines."""
    config = yaml.safe_load((REPO_ROOT / 'config/client.yaml').read_text())
    ids = set()
    for pipeline in config['pipeline']['pipelines']:
        for stage in pipeline['stages']:
            ids.add(str(stage['id']))
    return ids


def load_field_semantics_stage_ids():
    """Stage IDs field_semantics can classify, including aliases."""
    ids = set()
    for stage_id, info in STAGE_MAP.items():
        ids.add(str(stage_id))
        for alias in info.get('aliases', []):
            ids.add(str(alias))
    return ids


def scan_history(cache_path):
    """
    Every distinct dealstage value in property history, with occurrence
    counts and the timestamp range it was seen over.
    """
    cache = json.loads(cache_path.read_text())
    seen = defaultdict(lambda: {'entries': 0, 'deals': set(),
                                'first': None, 'last': None})
    # Stage ids that are the LAST history entry for some deal. A lookup
    # returns the last entry at or before the date, so an id absent from this
    # set can never be returned for any date — it is unreachable.
    terminal_values = set()
    for deal_id, record in cache['deals'].items():
        hist = sorted((record.get('history') or []),
                      key=lambda e: e.get('timestamp') or '')
        if hist and hist[-1].get('value') is not None:
            terminal_values.add(str(hist[-1]['value']))
        for entry in record.get('history') or []:
            value = entry.get('value')
            ts = entry.get('timestamp')
            key = str(value) if value is not None else NULL_VALUE
            s = seen[key]
            s['entries'] += 1
            s['deals'].add(deal_id)
            if ts and (s['first'] is None or ts < s['first']):
                s['first'] = ts
            if ts and (s['last'] is None or ts > s['last']):
                s['last'] = ts
    return cache, seen, terminal_values


def get_current_stage_ids():
    """Current stage IDs from the deals table. None if no credentials."""
    url = os.environ.get('SUPABASE_URL')
    key = os.environ.get('SUPABASE_SERVICE_KEY')
    if not url or not key:
        return None
    from supabase import create_client
    from supabase_client import select_all
    client = create_client(url, key)
    rows = select_all(client, 'deals', columns='stage')
    return {str(r['stage']) for r in rows if r.get('stage')}


def main():
    parser = argparse.ArgumentParser(
        description='Discover stage IDs in HubSpot dealstage property history')
    parser.add_argument('--cache-file', default='property_history_cache.json',
                        help='Path to property history cache')
    args = parser.parse_args()

    print("=" * 74)
    print("HISTORICAL STAGE ID DISCOVERY")
    print("=" * 74)

    cache_path = Path(args.cache_file)
    if not cache_path.exists():
        print(f"\n✗ Property history cache not found: {cache_path}")
        print("  Build it first:  python scripts/analytics/hubspot_history.py --all")
        print("  Cannot verify historical stage coverage without it.")
        return 2

    configured = load_client_yaml_stage_ids()
    classifiable = load_field_semantics_stage_ids()
    cache, seen, terminal_values = scan_history(cache_path)

    print(f"\nHistory cache: {len(cache['deals'])} deals, "
          f"{sum(v['entries'] for v in seen.values())} dealstage entries")
    print(f"config/client.yaml:          {len(configured)} stage IDs")
    print(f"config/field_semantics.yaml: {len(classifiable)} stage IDs (incl. aliases)")

    print(f"\n{'stage_id':<22} {'bucket':<12} {'entries':>8} {'deals':>6} "
          f"{'first seen':<12} {'in cfg':<7} {'classifiable'}")
    print("-" * 96)
    unclassifiable, not_in_client_yaml, null_valued = [], [], None
    retired_found = []
    for stage_id in sorted(seen, key=lambda k: -seen[k]['entries']):
        s = seen[stage_id]
        # A null history value is not a stage to map — the property was
        # cleared. Reported separately; mapping it would be nonsense.
        if stage_id == NULL_VALUE:
            null_valued = s
            continue
        bucket = stage_bucket(stage_id)
        ok = stage_id in classifiable and bucket != 'unknown'
        in_cfg = stage_id in configured
        if not ok:
            if is_retired_stage(stage_id):
                retired_found.append((stage_id, s))
            else:
                unclassifiable.append((stage_id, s))
        if not in_cfg:
            not_in_client_yaml.append(stage_id)
        print(f"{stage_id:<22} {bucket:<12} {s['entries']:>8} {len(s['deals']):>6} "
              f"{(s['first'] or '')[:10]:<12} {'yes' if in_cfg else 'NO':<7} "
              f"{'yes' if ok else ('retired' if is_retired_stage(stage_id) else 'NO')}")

    current = get_current_stage_ids()
    if current is None:
        print("\n(No Supabase credentials — skipped the current-stage cross-check.)")
    else:
        history_only = set(seen) - current - {'<null>'}
        print(f"\nCurrent deals.stage values: {len(current)}")
        print(f"Appear ONLY in history, never as a current stage: "
              f"{len(history_only)}")
        for stage_id in sorted(history_only):
            print(f"  {stage_id}  ({stage_label(stage_id)})")
        for stage_id in sorted(current - set(seen)):
            print(f"  ⚠ current stage absent from history: {stage_id}")

    print("\n" + "=" * 74)
    print("SUMMARY")
    print("=" * 74)
    print(f"Distinct stage IDs in history: "
          f"{len(seen) - (1 if null_valued else 0)}")
    print(f"Not in config/client.yaml:     {len(not_in_client_yaml)}")
    print(f"UNCLASSIFIABLE:                {len(unclassifiable)}")

    if null_valued:
        print(f"\n⚠ {null_valued['entries']} history entries across "
              f"{len(null_valued['deals'])} deals have a NULL dealstage.")
        print("  Not a mapping gap — the property was cleared. But note that")
        print("  get_stage_at_date cannot currently distinguish 'last entry at or")
        print("  before D had a null value' from 'no entry at or before D': both")
        print("  return (None, 'pre_history'). Worth resolving before these rows")
        print("  are labelled.")

    reachable_retired = []
    if retired_found:
        print(f"\n  {len(retired_found)} acknowledged retired stage ID(s) "
              f"(config/field_semantics.yaml retired_stages):")
        for stage_id, s in retired_found:
            meta = RETIRED_STAGES.get(stage_id, {})
            reach = stage_id in terminal_values
            if reach:
                reachable_retired.append(stage_id)
            print(f"    {stage_id}  last seen {(s['last'] or '?')[:10]}  "
                  f"(recorded {meta.get('last_seen', '?')})  "
                  f"{'REACHABLE — see below' if reach else 'unreachable'}")
        print("    Deliberately unclassified. Reconstruction still raises on")
        print("    them; they are listed so this gate can tell them apart from")
        print("    a genuinely new unknown stage.")

    if reachable_retired:
        print(f"\n✗ BACKFILL BLOCKED — retired stage ID(s) {reachable_retired} "
              f"are a deal's FINAL history entry.")
        print("  The unreachability assumption that justified leaving them")
        print("  unclassified no longer holds: a point-in-time lookup returns")
        print("  the last entry at or before the date, so these CAN now be")
        print("  returned and reconstruction will raise. Assign a real bucket.")
        return 1

    if not unclassifiable:
        print("\n✓ Every stage ID in history classifies, or is acknowledged")
        print("  retired and provably unreachable. Reconstruction can proceed.")
        return 0

    print("\n✗ BACKFILL BLOCKED — these stage IDs cannot be classified.")
    print("  Reconstruction raises on them rather than reading them as open.")
    print("  Add each to config/field_semantics.yaml, then re-run")
    print("  scripts/generate_field_semantics.py:\n")
    for stage_id, s in unclassifiable:
        print(f'  "{stage_id}":')
        print(f'    label: "TODO"        # {s["entries"]} entries across '
              f'{len(s["deals"])} deals')
        print(f'    bucket: "TODO"       # discovery|scoping|proposal|'
              f'closed_won|closed_lost')
        print(f'    transition: null     # seen {(s["first"] or "?")[:10]} '
              f'to {(s["last"] or "?")[:10]}')
        print()
    print("  Quote every numeric key — yaml parses a bare number as an int,")
    print("  but HubSpot sends stage ids as strings, so the lookup would miss.")
    return 1


if __name__ == '__main__':
    sys.exit(main())
