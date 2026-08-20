"""
Condition 2 — close_date rule vs terminal-stage rule, BOTH arms point-in-time.

The earlier comparison (compare_inclusion_rules.py) stood current values in
for stage-as-of-D because this had no property history. That reproduces the
exact proxy bug the terminal-stage rule exists to eliminate, inside the test
meant to validate it, and a comparison with one point-in-time arm and one
proxy arm cannot attribute a disagreement to the rule versus the proxy.

Now that the cache carries closedate history as well as dealstage, both arms
are reconstructed:

  close_date rule    create_date <= D AND (close_date@D IS NULL OR >= D)
  terminal rule      create_date <= D AND stage@D is not won/lost

Scoping is config-driven and identical on both arms, evaluated at D from the
point-in-time stage — so a deal sitting in Meeting Set at D is excluded for
that week even if it has since moved on.

Expected result: the close-only set collapses to near zero. Under the proxy
it ran 16 -> 2 -> 1 across weeks 1-3, which is the signature of deals that
closed AFTER D reading as terminal AT D. Any close-only deal that survives
under true history is a genuine disagreement and is listed individually.

Usage:
    python scripts/analytics/compare_inclusion_rules_pit.py
    python scripts/analytics/compare_inclusion_rules_pit.py --deals-json deals.json
    python scripts/analytics/compare_inclusion_rules_pit.py --dates 2026-08-04,2026-08-11
"""
import argparse
import json
import os
import sys
import yaml
from datetime import date, datetime
from pathlib import Path

REPO_ROOT = Path(__file__).parent.parent.parent
sys.path.insert(0, str(REPO_ROOT / 'scripts'))
sys.path.insert(0, str(REPO_ROOT / 'scripts' / 'analytics'))
sys.path.insert(0, str(REPO_ROOT / 'api'))

from point_in_time import (UnclassifiableStageError, get_field_at_date,
                           get_stage_at_date, is_terminal_stage)

FISCAL_QUARTER = 'FY2027 Q3'
WEEKS = 3


def load_scoping():
    """Config-driven scoping, shared by both arms."""
    cfg = yaml.safe_load((REPO_ROOT / 'config/client.yaml').read_text())
    excluded_pipelines = {str(p['id']) for p in cfg['pipelines']['excluded']}
    default_qso = cfg['pipeline'].get('qualified_stage_order', 1)
    stages = {}
    for p in cfg['pipeline']['pipelines']:
        qso = p.get('qualified_stage_order', default_qso)
        for s in p['stages']:
            stages[str(s['id'])] = {
                'name': s['name'], 'order': s['order'],
                'excluded': bool(s.get('exclude_from_analysis')),
                'qualified_stage_order': qso,
            }
    return excluded_pipelines, stages


def parse_hubspot_date(raw):
    """
    Property-history values arrive as ISO strings or epoch-millis strings
    depending on the property. Tolerate both; return None on anything else.
    """
    if raw in (None, '', 'null'):
        return None
    s = str(raw).strip()
    if s.lstrip('-').isdigit():
        try:
            return datetime.utcfromtimestamp(int(s) / 1000).date()
        except (ValueError, OSError, OverflowError):
            return None
    try:
        return datetime.fromisoformat(s.replace('Z', '+00:00')).date()
    except ValueError:
        return None


def load_deals(deals_json):
    """create_date and pipeline per deal, from a file or from Supabase."""
    if deals_json:
        rows = json.loads(Path(deals_json).read_text())
    else:
        from supabase import create_client
        from supabase_client import select_all
        url, key = os.environ['SUPABASE_URL'], os.environ['SUPABASE_SERVICE_KEY']
        sb = create_client(url, key)
        rows = select_all(sb, 'deals',
                          columns='deal_id,create_date,pipeline_id,company_name')
    deals = {}
    for r in rows:
        cd = parse_hubspot_date(r.get('create_date'))
        if cd is None:
            continue
        deals[str(r['deal_id'])] = {
            'create': cd,
            'pipeline': str(r.get('pipeline_id') or 'default'),
            'name': r.get('company_name') or '',
        }
    return deals


def method1_dates_and_rows():
    """Method 1's actual written snapshot dates and deal sets for the quarter."""
    from supabase import create_client
    from supabase_client import select_all
    url, key = os.environ['SUPABASE_URL'], os.environ['SUPABASE_SERVICE_KEY']
    sb = create_client(url, key)
    rows = select_all(sb, 'deals_snapshot', columns='deal_id,snapshot_date',
                      filters=[('eq', 'fiscal_quarter', FISCAL_QUARTER),
                               ('eq', 'snapshot_source', 'prospective')])
    by_date = {}
    for r in rows:
        by_date.setdefault(r['snapshot_date'], set()).add(str(r['deal_id']))
    return by_date


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--cache-file', default='property_history_cache.json')
    parser.add_argument('--deals-json', default=None,
                        help='Deal rows from a file instead of Supabase '
                             '(offline testing).')
    parser.add_argument('--dates', default=None,
                        help='Comma-separated snapshot dates. Default: the '
                             'dates Method 1 actually wrote for the quarter.')
    args = parser.parse_args()

    cache_path = Path(args.cache_file)
    if not cache_path.exists():
        print(f"✗ cache not found: {cache_path}")
        return 2
    cache = json.loads(cache_path.read_text())
    stage_history = cache['deals']
    close_history = {d: {'history': r.get('closedate_history') or []}
                     for d, r in cache['deals'].items()}

    have_closedate = sum(1 for r in cache['deals'].values()
                         if r.get('closedate_history'))
    if have_closedate == 0:
        print("✗ The cache has no closedate history. Both arms cannot be")
        print("  reconstructed point-in-time. Re-run hubspot_history.py with")
        print("  the current TRACKED_PROPERTIES.")
        return 2

    excluded_pipelines, stage_cfg = load_scoping()
    deals = load_deals(args.deals_json)

    method1 = {}
    if args.dates:
        dates = [d.strip() for d in args.dates.split(',') if d.strip()]
    else:
        method1 = method1_dates_and_rows()
        dates = sorted(method1)[:WEEKS]

    print("=" * 100)
    print(f"CONDITION 2 — BOTH ARMS POINT-IN-TIME, {FISCAL_QUARTER} WEEKS 1-{WEEKS}")
    print("=" * 100)
    print(f"\nCache: {len(stage_history)} deals, "
          f"{have_closedate} with closedate history")
    print(f"Deals: {len(deals)} with a create_date")
    if not dates:
        print(f"\n✗ No {FISCAL_QUARTER} prospective snapshot dates found.")
        return 2
    print(f"Dates: {', '.join(dates)}"
          + ("  (from Method 1's written rows)" if method1 else "  (supplied)"))

    def pit(deal_id, D):
        """Point-in-time stage and close_date, plus their confidence."""
        stage, s_conf, _ = get_stage_at_date(stage_history, deal_id, D)
        raw_close, c_conf = get_field_at_date(close_history, deal_id, D)
        return stage, s_conf, parse_hubspot_date(raw_close), c_conf

    summary = []
    for ds in dates:
        D = date.fromisoformat(ds)
        Ddt = datetime.combine(D, datetime.min.time())

        by_close, by_term, unresolvable, raised = set(), set(), [], []
        detail = {}
        for deal_id, d in deals.items():
            if d['create'] > D:
                continue
            if d['pipeline'] in excluded_pipelines:
                continue

            stage, s_conf, close_at_d, c_conf = pit(deal_id, Ddt)

            # Scope on the point-in-time stage, not today's.
            if stage is None:
                unresolvable.append((deal_id, s_conf))
                continue
            cfg = stage_cfg.get(stage)
            if cfg is None or cfg['excluded'] \
                    or cfg['order'] < cfg['qualified_stage_order']:
                continue

            detail[deal_id] = (stage, cfg['name'], close_at_d, s_conf, c_conf)

            if close_at_d is None or close_at_d >= D:
                by_close.add(deal_id)
            try:
                if not is_terminal_stage(stage):
                    by_term.add(deal_id)
            except UnclassifiableStageError as e:
                raised.append((deal_id, stage, str(e)[:80]))

        close_only = by_close - by_term
        term_only = by_term - by_close
        summary.append((ds, len(by_close), len(by_term),
                        len(by_close & by_term), len(close_only),
                        len(term_only), len(unresolvable), len(raised)))

        print("\n" + "=" * 100)
        print(f"WEEK {dates.index(ds) + 1} — {ds}")
        print("=" * 100)
        print(f"  close_date rule: {len(by_close)}   terminal rule: {len(by_term)}"
              f"   both: {len(by_close & by_term)}"
              f"   close-only: {len(close_only)}   term-only: {len(term_only)}")
        if unresolvable:
            confs = {}
            for _, c in unresolvable:
                confs[c] = confs.get(c, 0) + 1
            print(f"  no point-in-time stage, so not scopable: "
                  f"{len(unresolvable)} ({confs})")
        if raised:
            print(f"  ✗ {len(raised)} deal(s) raised on an unclassifiable stage:")
            for deal_id, stage, msg in raised[:5]:
                print(f"      {deal_id} stage={stage}")

        if method1 and ds in method1:
            m1 = method1[ds]
            print(f"  Method 1 actually wrote {len(m1)} rows; "
                  f"close_date arm agrees on {len(by_close & m1)}, "
                  f"terminal arm on {len(by_term & m1)}")

        for label, ids in (("CLOSE-ONLY — genuine disagreement if non-empty",
                            close_only),
                           ("TERM-ONLY — recovered past-due open deals",
                            term_only)):
            print(f"\n  {label}: {len(ids)}")
            if ids:
                print(f"    {'deal_id':<13} {'stage@D':<24} {'close@D':<12} "
                      f"{'days past D':>11} {'stage conf':<11} {'close conf':<11} name")
            for i in sorted(ids, key=lambda x: detail[x][2] or date(1970, 1, 1)):
                stage, name, close_at_d, s_conf, c_conf = detail[i]
                past = (D - close_at_d).days if close_at_d else None
                print(f"    {i:<13} {name:<24} {str(close_at_d):<12} "
                      f"{str(past):>11} {s_conf:<11} {c_conf:<11} "
                      f"{deals[i]['name'][:26]}")

    print("\n" + "=" * 100)
    print("SUMMARY — both arms point-in-time")
    print("=" * 100)
    print(f"{'date':<12} {'close':>7} {'term':>6} {'both':>6} {'close-only':>11} "
          f"{'term-only':>10} {'no stage':>9} {'raised':>7}")
    for row in summary:
        print(f"{row[0]:<12} {row[1]:>7} {row[2]:>6} {row[3]:>6} {row[4]:>11} "
              f"{row[5]:>10} {row[6]:>9} {row[7]:>7}")

    total_close_only = sum(r[4] for r in summary)
    total_raised = sum(r[7] for r in summary)
    print()
    if total_raised:
        print(f"✗ {total_raised} deal-week(s) raised on an unclassifiable stage. "
              f"Resolve before switching.")
        return 1
    if total_close_only == 0:
        print("✓ close-only is empty on every week. The 16 -> 2 -> 1 pattern under")
        print("  the proxy was entirely artifact: deals that closed after D read")
        print("  as terminal at D. The two rules disagree in one direction only —")
        print("  the terminal rule recovers genuinely-open past-due deals.")
    else:
        print(f"⚠ {total_close_only} close-only deal-week(s) survive under true")
        print("  history. These are genuine disagreements, listed per week above.")
        print("  Review each before switching the shared rule.")
    return 0


if __name__ == '__main__':
    sys.exit(main())
