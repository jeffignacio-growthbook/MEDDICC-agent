#!/usr/bin/env python3
"""
Read-only diagnostic: how many active deals actually have calls in Supabase?

The nightly scores a deal only if get_calls_for_company() returns rows from the
`calls` table (keyed by deal_id). After an ETL refresh the active deal set can
rotate to deals with no linked calls — in which case a crash-free nightly still
writes zero analyses. This answers "how many of the N active deals would the
nightly find calls for" WITHOUT scoring anything (no LLM, no writes).

Needs SUPABASE_URL + SUPABASE_SERVICE_KEY. Never writes.
"""
import json
import sys
from collections import Counter
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
for p in ("", "scripts", "api"):
    sys.path.insert(0, str(REPO / p) if p else str(REPO))


def _active_deals():
    idx = json.load(open(REPO / "memory" / "deals" / "index.json"))
    return {k: v for k, v in idx.items() if isinstance(v, dict) and v.get("deal_id")}


def main():
    from supabase_client import SupabaseWriter, select_all
    sb = SupabaseWriter().client

    deals = _active_deals()
    print("=" * 72)
    print(f"CALL COVERAGE — {len(deals)} active deals in index")
    print("=" * 72)

    # One pass over calls: deal_id -> count, and how many carry a null deal_id.
    per_deal = Counter()
    null_deal_id = 0
    rows = select_all(sb, "calls", columns="call_id,deal_id,source")
    total_rows = len(rows)
    for r in rows:
        did = r.get("deal_id")
        if did in (None, "", "None"):
            null_deal_id += 1
        else:
            per_deal[str(did)] += 1

    with_calls = [d for d in deals if per_deal.get(str(d), 0) > 0]
    without = [d for d in deals if per_deal.get(str(d), 0) == 0]

    print(f"\ncalls table: {total_rows} rows total, "
          f"{len(per_deal)} distinct deal_ids, {null_deal_id} rows with null deal_id")
    print(f"\nActive deals WITH ≥1 call:  {len(with_calls)} / {len(deals)}")
    print(f"Active deals WITH NO calls: {len(without)} / {len(deals)}")

    # A deal scored yesterday would be re-scored tonight only if it has calls;
    # show the coverage leaders so we can eyeball that they are real deals.
    top = sorted(((per_deal[str(d)], deals[d].get("company_name"), d)
                  for d in with_calls), reverse=True)[:15]
    print("\nTop active deals by call count (would score):")
    for n, name, did in top:
        print(f"  {n:4d} calls  {did}  {name}")

    if without:
        print(f"\nFirst 15 active deals with NO calls (would skip):")
        for d in without[:15]:
            print(f"        0 calls  {d}  {deals[d].get('company_name')}")

    print("\n" + "=" * 72)
    print(f"VERDICT: a clean nightly would find calls for {len(with_calls)} "
          f"of {len(deals)} active deals ({100*len(with_calls)//max(1,len(deals))}%).")
    print("=" * 72)
    return 0


if __name__ == "__main__":
    sys.exit(main())
