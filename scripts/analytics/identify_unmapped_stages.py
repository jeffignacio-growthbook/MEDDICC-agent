"""
Identify stage IDs that appear in property history but cannot be classified.

discover_historical_stages.py reports WHICH ids are unmapped and blocks the
backfill. This says WHAT they are, so a correct bucket can be assigned rather
than guessed. Two independent sources:

  1. HubSpot's pipelines API, including archived pipelines and stages. A stage
     deleted from a pipeline often still resolves here.
  2. Transition evidence from the cache: for every deal that passed through
     the unknown stage, the stage immediately before and after it, and where
     the deal ended up. A stage whose successors are all Closed Won behaves
     like a late stage; one whose predecessors are all Meeting Set is early.

Source 2 works with no API access, so the inference still runs if HubSpot
cannot resolve the id.

Usage:
    python scripts/analytics/identify_unmapped_stages.py
    python scripts/analytics/identify_unmapped_stages.py --stage-ids 24682891,43746397
"""
import argparse
import json
import os
import sys
from collections import Counter, defaultdict
from pathlib import Path

REPO_ROOT = Path(__file__).parent.parent.parent
sys.path.insert(0, str(REPO_ROOT / 'scripts'))
sys.path.insert(0, str(REPO_ROOT / 'api'))

from field_semantics import stage_bucket, stage_label


def hubspot_stage_labels():
    """
    {stage_id: (pipeline_label, stage_label, display_order, archived)} from
    the pipelines API, active and archived. Empty dict without an API key.
    """
    api_key = os.environ.get('HUBSPOT_API_KEY')
    if not api_key:
        return {}
    try:
        from hubspot_deals import HubSpotDealsClient
    except ImportError:
        return {}

    client = HubSpotDealsClient(api_key)
    found = {}
    for archived in (False, True):
        try:
            resp = client._get('/crm/v3/pipelines/deals',
                               {'archived': str(archived).lower()})
        except Exception as e:
            print(f"  ⚠ pipelines API (archived={archived}) failed: {e}")
            continue
        for pipeline in resp.get('results', []):
            for stage in pipeline.get('stages', []):
                found[str(stage.get('id'))] = (
                    pipeline.get('label', '?'),
                    stage.get('label', '?'),
                    stage.get('displayOrder'),
                    archived or bool(stage.get('archived')),
                )
    return found


def transition_evidence(cache, stage_ids):
    """For each target stage: what came before, after, and how deals ended."""
    ev = {s: {'before': Counter(), 'after': Counter(), 'final': Counter(),
              'deals': [], 'pipelines': Counter()} for s in stage_ids}

    for deal_id, record in cache['deals'].items():
        hist = sorted((record.get('history') or []),
                      key=lambda e: e.get('timestamp') or '')
        values = [str(e.get('value')) for e in hist]
        for i, val in enumerate(values):
            if val not in ev:
                continue
            e = ev[val]
            e['before'][values[i - 1] if i > 0 else '<none: first entry>'] += 1
            e['after'][values[i + 1] if i + 1 < len(values)
                       else '<none: still there>'] += 1
            e['final'][values[-1]] += 1
            if len(e['deals']) < 6:
                e['deals'].append((deal_id, hist[i].get('timestamp', '')[:10],
                                   ' -> '.join(values)))
    return ev


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--cache-file', default='property_history_cache.json')
    parser.add_argument('--stage-ids', default=None,
                        help='Comma-separated. Default: every unclassifiable '
                             'id found in the cache.')
    args = parser.parse_args()

    cache_path = Path(args.cache_file)
    if not cache_path.exists():
        print(f"✗ cache not found: {cache_path}")
        return 2
    cache = json.loads(cache_path.read_text())

    if args.stage_ids:
        targets = [s.strip() for s in args.stage_ids.split(',') if s.strip()]
    else:
        seen = {str(e.get('value')) for r in cache['deals'].values()
                for e in (r.get('history') or []) if e.get('value') is not None}
        targets = sorted(s for s in seen if stage_bucket(s) == 'unknown')

    print("=" * 78)
    print("IDENTIFY UNMAPPED STAGE IDS")
    print("=" * 78)
    if not targets:
        print("\n✓ No unclassifiable stage ids in the cache. Nothing to identify.")
        return 0
    print(f"\nTargets: {', '.join(targets)}")

    print("\n--- Source 1: HubSpot pipelines API (active + archived) ---")
    labels = hubspot_stage_labels()
    if not labels:
        print("  (no HUBSPOT_API_KEY, or the API call failed — skipped)")
    else:
        print(f"  {len(labels)} stage ids resolved from the API")
        for s in targets:
            if s in labels:
                pl, sl, order, arch = labels[s]
                print(f"  ✓ {s}: \"{sl}\"  pipeline=\"{pl}\"  "
                      f"displayOrder={order}  archived={arch}")
            else:
                print(f"  ✗ {s}: not present in any pipeline, active or archived "
                      f"(hard-deleted)")

    print("\n--- Source 2: transition evidence from history ---")
    ev = transition_evidence(cache, targets)
    for s in targets:
        e = ev[s]
        print(f"\n  === {s} ===")
        print(f"    immediately BEFORE it:")
        for v, n in e['before'].most_common(6):
            print(f"      {n:>4}x  {v}  ({stage_label(v)})")
        print(f"    immediately AFTER it:")
        for v, n in e['after'].most_common(6):
            print(f"      {n:>4}x  {v}  ({stage_label(v)})")
        print(f"    deal's FINAL stage:")
        for v, n in e['final'].most_common(6):
            print(f"      {n:>4}x  {v}  ({stage_label(v)})")
        print(f"    example paths:")
        for deal_id, ts, path in e['deals']:
            print(f"      {deal_id} @ {ts}: {path[:150]}")

    print("\n" + "=" * 78)
    print("PROPOSED field_semantics.yaml ENTRIES — REVIEW BEFORE COMMITTING")
    print("=" * 78)
    print("Buckets are inferred, not authoritative. A wrong bucket is worse")
    print("than an unmapped stage, because it stops erroring and starts lying.")
    print()
    for s in targets:
        api = labels.get(s)
        label = api[1] if api else 'UNKNOWN — set from HubSpot UI or deal history'
        print(f'  "{s}":')
        print(f'    label: "{label}"')
        print(f'    bucket: "TODO"      # discovery|scoping|proposal|closed_won|closed_lost')
        print(f'    transition: null')
        print()
    return 0


if __name__ == '__main__':
    sys.exit(main())
