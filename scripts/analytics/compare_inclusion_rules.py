#!/usr/bin/env python3
"""
Phase 2a measurement — close_date rule vs terminal-stage rule.

The Method 2 spec says the shared inclusion rule "must match Method 1's
exactly" and then states a rule Method 1 does not implement:

  Method 1 (snapshot_deals.py:9-11)
      create_date <= D AND (close_date IS NULL OR close_date >= D)
  Spec text / point_in_time.is_deal_open_at_date
      create_date <= D AND deal had not reached a terminal stage as of D

This script measures the disagreement on the FY2027 Q3 weeks so the choice
is made from deal-level evidence rather than from the spec text.

SCOPING is applied identically to both arms, so only the open-test varies.
Driven from config/client.yaml, not hardcoded:
  - pipelines.excluded            -> Renewal pipeline (866608541)
  - exclude_from_analysis: true   -> Meeting Set (79653122), Disqualified (68509551)
  - order < qualified_stage_order -> Meeting Set

CAVEAT: this container has no Supabase or HubSpot credentials, so there is
no property history and no access to Method 1's written rows. Values are
current-as-of the committed 2026-08-13 export, used as a proxy for
stage-as-of-D and close_date-as-of-D. The proxy is directional, and the
direction is measurable:

  - The terminal-only set is ROBUST to the proxy. Those deals sit in open
    stages today and their close dates are long past, so both rules' inputs
    are stable across the proxy window.
  - The close-only set is DOMINATED by proxy error. It collapses 16 -> 2 -> 1
    as D approaches and passes the export date, because a deal that closed
    between D and the export date reads as terminal at D when it was in fact
    open. With real stage-as-of-D history those deals move into "both".

Usage:
    python scripts/analytics/compare_inclusion_rules.py
"""
import ast
import csv
import collections
import sys
import yaml
from datetime import date, datetime
from pathlib import Path

REPO_ROOT = Path(__file__).parent.parent.parent
sys.path.insert(0, str(REPO_ROOT / 'api'))
sys.path.insert(0, str(REPO_ROOT / 'scripts'))

from field_semantics import is_won, is_lost

EXPORT = REPO_ROOT / 'deals_export_20260813_115841.csv'
EXPORT_AS_OF = date(2026, 8, 13)
# FY2027 Q3 = 2026-08-01 .. 2026-10-31; weeks are 7-day blocks from quarter start.
WEEKS = [(1, date(2026, 8, 4)), (2, date(2026, 8, 11)), (3, date(2026, 8, 18))]


def load_config():
    cfg = yaml.safe_load((REPO_ROOT / 'config/client.yaml').read_text())
    excluded_pipelines = {str(p['id']) for p in cfg['pipelines']['excluded']}
    default_qso = cfg['pipeline'].get('qualified_stage_order', 1)
    stages = {}
    for p in cfg['pipeline']['pipelines']:
        qso = p.get('qualified_stage_order', default_qso)
        for s in p['stages']:
            stages[str(s['id'])] = {
                'name': s['name'],
                'order': s['order'],
                'pipeline': str(p['id']),
                'excluded': bool(s.get('exclude_from_analysis')),
                'qualified_stage_order': qso,
            }
    return excluded_pipelines, stages


def load_deals():
    csv.field_size_limit(10 ** 7)
    deals = []
    with open(EXPORT) as f:
        for row in csv.DictReader(f):
            props = ast.literal_eval(row['properties'])

            def as_date(key):
                val = props.get(key)
                if not val:
                    return None
                return datetime.fromisoformat(val.replace('Z', '+00:00')).date()

            deals.append({
                'id': str(props.get('hs_object_id') or row['id']),
                'name': props.get('dealname') or '',
                'create': as_date('createdate'),
                'close': as_date('closedate'),
                'stage': str(props.get('dealstage')),
                'pipeline': str(props.get('pipeline')),
            })
    return deals


def main():
    if not EXPORT.exists():
        print(f"✗ missing required input: {EXPORT}")
        return 1

    excluded_pipelines, stages = load_config()
    deals = load_deals()

    def in_scope(d):
        if d['pipeline'] in excluded_pipelines:
            return False
        s = stages.get(d['stage'])
        if s is None or s['excluded']:
            return False
        return s['order'] >= s['qualified_stage_order']

    def created_by(d, D):
        return d['create'] is not None and d['create'] <= D

    def open_by_close_date(d, D):
        return d['close'] is None or d['close'] >= D

    def open_by_terminal_stage(d, D):
        return not (is_won(d['stage']) or is_lost(d['stage']))

    print("=" * 96)
    print("PHASE 2a — CLOSE_DATE RULE vs TERMINAL-STAGE RULE, FY2027 Q3")
    print("=" * 96)
    print(f"\nValues current as of the committed export ({EXPORT_AS_OF}); "
          f"no property history in this container.")

    dropped = collections.Counter()
    for d in deals:
        if d['pipeline'] in excluded_pipelines:
            dropped['renewal pipeline (pipelines.excluded)'] += 1
        elif stages.get(d['stage']) is None:
            dropped['stage not in client.yaml'] += 1
        elif stages[d['stage']]['excluded']:
            dropped[f"exclude_from_analysis: {stages[d['stage']]['name']}"] += 1
        elif stages[d['stage']]['order'] < stages[d['stage']]['qualified_stage_order']:
            dropped['below qualified_stage_order'] += 1
    scoped = [d for d in deals if in_scope(d)]
    print(f"\nScoping: {len(deals)} deals -> {len(scoped)} in scope")
    for reason, n in dropped.most_common():
        print(f"  excluded  {n:>4}  {reason}")

    print("\n" + "-" * 96)
    print(f"{'week':<5} {'date':<12} {'close_date':>11} {'terminal':>9} {'both':>6} "
          f"{'close only':>11} {'term only':>10} {'delta':>8}")
    print("-" * 96)
    detail = {}
    for week, D in WEEKS:
        base = [d for d in scoped if created_by(d, D)]
        by_close = {d['id'] for d in base if open_by_close_date(d, D)}
        by_term = {d['id'] for d in base if open_by_terminal_stage(d, D)}
        detail[week] = (D, by_close, by_term)
        delta = (len(by_term) - len(by_close)) / len(by_close) * 100
        print(f"{week:<5} {D.isoformat():<12} {len(by_close):>11} {len(by_term):>9} "
              f"{len(by_close & by_term):>6} {len(by_close - by_term):>11} "
              f"{len(by_term - by_close):>10} {delta:>7.1f}%")

    by_id = {d['id']: d for d in deals}
    for week in sorted(detail):
        D, by_close, by_term = detail[week]
        print("\n" + "=" * 96)
        print(f"WEEK {week} ({D}) — deal-by-deal")
        print("=" * 96)
        for label, ids in (
            ("TERMINAL-RULE ONLY — genuinely open, close_date rule excludes", by_term - by_close),
            ("CLOSE_DATE-RULE ONLY — terminal rule excludes", by_close - by_term),
        ):
            print(f"\n  {label}: {len(ids)}")
            if ids:
                print(f"    {'deal_id':<13} {'stage':<22} {'close_date':<12} "
                      f"{'days past D':>11}  name")
            for i in sorted(ids, key=lambda x: by_id[x]['close'] or date(1970, 1, 1)):
                d = by_id[i]
                past = (D - d['close']).days if d['close'] else None
                print(f"    {i:<13} {stages[d['stage']]['name']:<22} "
                      f"{str(d['close']):<12} {str(past):>11}  {d['name'][:34]}")

    # ---- Assertions -----------------------------------------------------
    print("\n" + "=" * 96)
    print("ASSERTIONS")
    print("=" * 96)
    failures = []

    _, w2_close, w2_term = detail[2]
    _, w3_close, w3_term = detail[3]

    # The terminal rule should select MORE deals: it recovers past-due open deals.
    if not (len(w2_term) > len(w2_close) and len(w3_term) > len(w3_close)):
        failures.append("expected the terminal rule to select more deals")
    else:
        print(f"  ✓ terminal rule recovers deals the close_date rule drops "
              f"(+{len(w2_term)-len(w2_close)} wk2, +{len(w3_term)-len(w3_close)} wk3)")

    # Every terminal-only deal must be in a non-terminal stage with a PAST close date.
    bad = [i for i in (w3_term - w3_close)
           if is_won(by_id[i]['stage']) or is_lost(by_id[i]['stage'])
           or by_id[i]['close'] is None or by_id[i]['close'] >= WEEKS[2][1]]
    if bad:
        failures.append(f"terminal-only set contains unexpected deals: {bad}")
    else:
        print(f"  ✓ all {len(w3_term - w3_close)} terminal-only deals are open-stage "
              f"deals with past-due close dates")

    # Proxy-error signature: close-only shrinks as D approaches the export date.
    close_only = [len(detail[w][1] - detail[w][2]) for w in (1, 2, 3)]
    if not (close_only[0] > close_only[1] >= close_only[2]):
        failures.append(f"expected close-only to shrink toward the export date, got {close_only}")
    else:
        print(f"  ✓ close-only collapses {close_only[0]} -> {close_only[1]} -> "
              f"{close_only[2]} toward the export date (proxy error, not real disagreement)")

    print()
    if failures:
        for f in failures:
            print(f"  ✗ {f}")
        return 1
    print("  ALL ASSERTIONS PASSED")
    return 0


if __name__ == '__main__':
    sys.exit(main())
