#!/usr/bin/env python3
"""
Phase 2a diagnostic — locate the "~291-row population cap" in the prior
Method 2 backfill.

VERDICT: there is no cap. Not a hardcoded limit, not a pagination failure.
It is a filter in backfill_snapshots.build_snapshot(), which returns None
(counted as 'snapshots_skipped') whenever get_stage_at_date() finds no
dealstage history entry at or before the snapshot date. The population of
each snapshot date is therefore "deals whose HubSpot dealstage history
reaches back that far", not "deals genuinely open on that date".

"~291" is not a ceiling. It is the mean rows-per-date: 315 across the
FY2026 Q4 + FY2027 Q1 block, 250 across all 39 dates. Per-date counts run
14 to 514.

Runs entirely off two files committed to the repo, so the finding survives
a fresh clone with no Supabase or HubSpot credentials:
  - data/backups/deals_snapshot_purge_20260819_221600.json  (prior output)
  - deals_export_20260813_115841.csv                        (HubSpot export)

Usage:
    python scripts/analytics/diagnose_population_cap.py
"""
import ast
import csv
import collections
import json
import statistics
import sys
from datetime import date, datetime
from pathlib import Path

REPO_ROOT = Path(__file__).parent.parent.parent
BACKUP = REPO_ROOT / 'data/backups/deals_snapshot_purge_20260819_221600.json'
EXPORT = REPO_ROOT / 'deals_export_20260813_115841.csv'

TERMINAL_STAGES = {'closedwon', 'closedlost'}
SEGMENT_B_START = '2026-05-05'   # FY2027 Q2 week 1 — a separate, sparser run


def load_deals():
    """Deal attributes from the committed HubSpot export."""
    csv.field_size_limit(10 ** 7)
    deals = {}
    with open(EXPORT) as f:
        for row in csv.DictReader(f):
            props = ast.literal_eval(row['properties'])

            def as_date(key):
                val = props.get(key)
                if not val:
                    return None
                return datetime.fromisoformat(val.replace('Z', '+00:00')).date()

            deal_id = str(props.get('hs_object_id') or row['id'])
            deals[deal_id] = {
                'create': as_date('createdate'),
                'close': as_date('closedate'),
                'stage': props.get('dealstage'),
                'pipeline': props.get('pipeline'),
            }
    return deals


def load_prior_output():
    """Snapshot rows the purge removed — the prior backfill's actual output."""
    rows = json.loads(BACKUP.read_text())
    by_date = collections.defaultdict(set)
    by_deal = collections.defaultdict(set)
    for r in rows:
        by_date[r['snapshot_date']].add(str(r['deal_id']))
        by_deal[str(r['deal_id'])].add(r['snapshot_date'])
    return rows, by_date, by_deal


def main():
    for path in (BACKUP, EXPORT):
        if not path.exists():
            print(f"✗ missing required input: {path}")
            return 1

    deals = load_deals()
    rows, by_date, by_deal = load_prior_output()
    dates = sorted(by_date)
    seg_a = [d for d in dates if d < SEGMENT_B_START]
    seg_b = [d for d in dates if d >= SEGMENT_B_START]

    print("=" * 78)
    print("PHASE 2a — WHERE DID THE ~291-ROW POPULATION CAP COME FROM?")
    print("=" * 78)
    print(f"\nPrior output: {len(rows)} rows, {len(dates)} weekly dates, "
          f"{len(by_deal)} distinct deals")
    print(f"HubSpot export: {len(deals)} deals")

    # ---- Finding 1: "291" is a mean, not a ceiling -------------------------
    print("\n" + "-" * 78)
    print("FINDING 1 — '291' is the mean rows-per-date, not a ceiling")
    print("-" * 78)
    counts = [len(by_date[d]) for d in dates]
    print(f"  rows/date: min {min(counts)}  max {max(counts)}  "
          f"mean {statistics.mean(counts):.0f}  median {statistics.median(counts):.0f}")
    print(f"  mean over FY2026 Q4 + FY2027 Q1 ({len(seg_a)} dates): "
          f"{statistics.mean(len(by_date[d]) for d in seg_a):.0f}")
    print(f"  mean over FY2027 Q2 ({len(seg_b)} dates):             "
          f"{statistics.mean(len(by_date[d]) for d in seg_b):.0f}")
    print("  A hardcoded limit would produce a flat ceiling. This is a ramp.")

    # ---- Finding 2: deals enter the grid long after they were created -----
    print("\n" + "-" * 78)
    print("FINDING 2 — deals enter the grid long after creation (the filter)")
    print("-" * 78)
    lags = []
    for deal_id, seen in by_deal.items():
        created = deals[deal_id]['create']
        lags.append((date.fromisoformat(min(seen)) - created).days)
    lags.sort()
    print(f"  first_snapshot_date - create_date, in days:")
    print(f"    min {min(lags)}  p25 {lags[len(lags)//4]}  "
          f"median {statistics.median(lags):.0f}  "
          f"p75 {lags[3*len(lags)//4]}  max {max(lags)}")
    print(f"  appear within 7 days of creation: {sum(1 for v in lags if v <= 7)} "
          f"of {len(lags)}")
    print(f"  appear BEFORE their create_date:  {sum(1 for v in lags if v < 0)}")
    print("  create_date <= D was honored. Deals are dropped from dates their")
    print("  dealstage history does not reach back to — the 'pre_history' case,")
    print("  which build_snapshot() drops instead of writing a null-stage row.")

    # ---- Finding 3: no open/closed filter was applied at all --------------
    print("\n" + "-" * 78)
    print("FINDING 3 — no open/closed filter ran: closed deals were retained")
    print("-" * 78)
    print(f"  {'date':<12} {'rows':>6} {'terminal today':>15} {'created after D':>16}")
    for ds in dates[:4] + ['...'] + dates[-3:]:
        if ds == '...':
            print(f"  {'...':<12}")
            continue
        D = date.fromisoformat(ds)
        seen = by_date[ds]
        term = sum(1 for x in seen if (deals[x]['stage'] or '') in TERMINAL_STAGES)
        after = sum(1 for x in seen if deals[x]['create'] and deals[x]['create'] > D)
        print(f"  {ds:<12} {len(seen):>6} {term:>15} {after:>16}")
    print("  The prior run undercaptured AND overcaptured at the same time:")
    print("  it dropped pre-history deals, and kept deals that had already closed.")

    # ---- Finding 4: coverage band reproduces ------------------------------
    print("\n" + "-" * 78)
    print("FINDING 4 — reproduces the reported 16-27% coverage")
    print("-" * 78)
    ratios = []
    for ds in seg_a:
        D = date.fromisoformat(ds)
        created = sum(1 for d in deals.values() if d['create'] and d['create'] <= D)
        ratios.append(len(by_date[ds]) / created * 100)
    print(f"  rows / deals created by D, FY2026 Q4 + FY2027 Q1:")
    print(f"    min {min(ratios):.1f}%  max {max(ratios):.1f}%  "
          f"mean {statistics.mean(ratios):.1f}%")

    # ---- Finding 5: two producers ----------------------------------------
    print("\n" + "-" * 78)
    print("FINDING 5 — FY2027 Q2 came from a separate, much sparser run")
    print("-" * 78)
    last_seen = collections.Counter(max(seen) for seen in by_deal.values())
    print(f"  deals whose last appearance is {seg_a[-1]} (end of FY2027 Q1): "
          f"{last_seen[seg_a[-1]]}")
    print(f"  deals whose last appearance is {seg_b[-1]} (end of FY2027 Q2): "
          f"{last_seen[seg_b[-1]]}")
    print(f"  rows/date drops {len(by_date[seg_a[-1]])} -> {len(by_date[seg_b[0]])} "
          f"across the Q1/Q2 boundary.")
    print("  The backup did not preserve snapshot_source, so the two runs cannot")
    print("  be attributed to specific scripts from this data alone.")

    # ---- Assertions ------------------------------------------------------
    print("\n" + "=" * 78)
    print("ASSERTIONS")
    print("=" * 78)
    failures = []

    if max(counts) <= 300:
        failures.append("expected per-date counts to exceed any ~291 ceiling")
    else:
        print(f"  ✓ per-date max {max(counts)} exceeds the supposed ~291 cap")

    if statistics.median(lags) < 30:
        failures.append("expected a large create-to-first-appearance lag")
    else:
        print(f"  ✓ median create-to-first-appearance lag is "
              f"{statistics.median(lags):.0f} days, not ~0")

    early_terminal = sum(1 for x in by_date[dates[0]]
                         if (deals[x]['stage'] or '') in TERMINAL_STAGES)
    if early_terminal == 0:
        failures.append("expected closed deals to be present (no open filter)")
    else:
        print(f"  ✓ {early_terminal} of {len(by_date[dates[0]])} rows on "
              f"{dates[0]} are deals closed today")

    if not (16 <= statistics.mean(ratios) <= 30):
        failures.append("coverage band did not reproduce in 16-30%")
    else:
        print(f"  ✓ coverage reproduces at {statistics.mean(ratios):.1f}% "
              f"(reported: 16-27%)")

    print()
    if failures:
        for f in failures:
            print(f"  ✗ {f}")
        return 1
    print("  ALL ASSERTIONS PASSED")
    print("\nFIX FOR PHASE 2a: drive the snapshot population from the deals")
    print("table via the shared inclusion rule, and use property history only")
    print("to supply point-in-time values. A deal with no history at date D")
    print("must yield a row with a null stage and confidence 'pre_history',")
    print("never no row at all.")
    return 0


if __name__ == '__main__':
    sys.exit(main())
