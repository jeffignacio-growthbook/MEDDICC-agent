"""
Which quarters have enough prospective coverage to cross-validate Method 2?

Phase 3b wants weeks captured by Method 1 to check Method 2 against. FY2027 Q3
turned out to have ONE prospective date, not the three the plan assumed, so
this surveys every quarter before Phase 3b commits to a baseline.

Reports per fiscal quarter and snapshot_source: distinct dates, rows, deals.
Supabase only — no HubSpot fetch, so it runs in seconds.

Usage:
    python scripts/analytics/survey_snapshot_coverage.py
"""
import os
import sys
from collections import defaultdict
from pathlib import Path

REPO_ROOT = Path(__file__).parent.parent.parent
sys.path.insert(0, str(REPO_ROOT / 'scripts'))

MIN_WEEKS_FOR_CROSS_VALIDATION = 3


def main():
    url = os.environ.get('SUPABASE_URL')
    key = os.environ.get('SUPABASE_SERVICE_KEY')
    if not url or not key:
        print("✗ SUPABASE_URL / SUPABASE_SERVICE_KEY not set")
        return 2

    from supabase import create_client
    from supabase_client import select_all

    sb = create_client(url, key)
    rows = select_all(sb, 'deals_snapshot',
                      columns='deal_id,snapshot_date,fiscal_quarter,'
                              'snapshot_source,week_of_quarter')

    print("=" * 88)
    print("SNAPSHOT COVERAGE SURVEY — what can Phase 3b cross-validate against?")
    print("=" * 88)
    print(f"\ndeals_snapshot: {len(rows)} rows")

    by_qs = defaultdict(lambda: {'dates': set(), 'rows': 0, 'deals': set(),
                                 'weeks': set()})
    for r in rows:
        key_ = (r.get('fiscal_quarter'), r.get('snapshot_source'))
        e = by_qs[key_]
        e['dates'].add(r.get('snapshot_date'))
        e['rows'] += 1
        e['deals'].add(str(r.get('deal_id')))
        if r.get('week_of_quarter') is not None:
            e['weeks'].add(r['week_of_quarter'])

    print(f"\n{'fiscal_quarter':<16} {'source':<26} {'dates':>6} {'weeks':>6} "
          f"{'rows':>7} {'deals':>7}")
    print("-" * 88)
    for (fq, src) in sorted(by_qs, key=lambda k: (str(k[0]), str(k[1]))):
        e = by_qs[(fq, src)]
        print(f"{str(fq):<16} {str(src):<26} {len(e['dates']):>6} "
              f"{len(e['weeks']):>6} {e['rows']:>7} {len(e['deals']):>7}")

    prospective = {fq: e for (fq, src), e in by_qs.items()
                   if src == 'prospective'}
    print("\n" + "=" * 88)
    print("PROSPECTIVE COVERAGE — Method 1's own writes, the only cross-check "
          "baseline available")
    print("=" * 88)
    if not prospective:
        print("  none. Phase 3b has no Method 1 baseline at all.")
        return 1

    usable = []
    for fq in sorted(prospective, key=str):
        e = prospective[fq]
        n = len(e['dates'])
        verdict = ("usable" if n >= MIN_WEEKS_FOR_CROSS_VALIDATION
                   else f"only {n} week(s)")
        if n >= MIN_WEEKS_FOR_CROSS_VALIDATION:
            usable.append(fq)
        print(f"  {str(fq):<16} {n:>2} date(s)  {verdict}")
        for d in sorted(e['dates']):
            print(f"      {d}")

    print()
    if usable:
        print(f"✓ Quarter(s) with ≥{MIN_WEEKS_FOR_CROSS_VALIDATION} prospective "
              f"dates: {usable}")
        print("  Prefer these for Phase 3b cross-validation.")
    else:
        best = max(prospective, key=lambda fq: len(prospective[fq]['dates']))
        print(f"⚠ No quarter has ≥{MIN_WEEKS_FOR_CROSS_VALIDATION} prospective "
              f"dates. Best is {best} with "
              f"{len(prospective[best]['dates'])}.")
        print("  Method 1 cannot backfill earlier weeks — only Method 2 can")
        print("  produce them, and Method 2 is the thing under test. So Phase 3b")
        print("  runs at the coverage that exists and states the limitation")
        print("  rather than manufacturing a baseline.")
    return 0


if __name__ == '__main__':
    sys.exit(main())
