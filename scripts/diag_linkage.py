#!/usr/bin/env python3
"""
Read-only diagnostic: WHY are 1,421 calls unlinked (deal_id NULL), and how much
active-deal coverage would re-resolving recover?

calls.deal_id is set only by scripts/enrichment/resolve_calls.py (a manual
run-once step: participant-domain match, else company_slug match, else NULL +
needs_review). It is NOT wired into the nightly or the calls ETL, so every new
call lands with deal_id NULL until the resolver is re-run. This quantifies the
upside of re-running it WITHOUT writing anything:

  - of the NULL-deal_id calls, how many carry a company_slug that matches a
    CURRENT active deal (→ would become scoreable), vs a non-active deal, vs no
    deal at all (internal meetings, generic titles).

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
    deals = idx.get("deals") if isinstance(idx.get("deals"), dict) else idx
    return {k: v for k, v in deals.items() if isinstance(v, dict) and v.get("deal_id")}


def _select(sb, table, base_cols, optional_cols, filters=None):
    """select_all, but drop optional columns the table may not have (the
    calls schema has grown over migrations; is_internal/call_intent are newer)."""
    from supabase_client import select_all
    cols = base_cols + optional_cols
    while True:
        try:
            return select_all(sb, table, columns=",".join(cols), filters=filters), \
                   [c for c in optional_cols if c in cols]
        except Exception as e:
            # Postgres names the missing column in the error; drop it and retry.
            dropped = None
            for c in list(optional_cols):
                if c in cols and c in str(e):
                    cols.remove(c); dropped = c; break
            if dropped is None:
                raise
            print(f"  (calls has no '{dropped}' column — skipping it)")


def main():
    from supabase_client import SupabaseWriter
    sb = SupabaseWriter().client

    active = _active_deals()
    active_slugs = {(v.get("company_slug") or "").lower() for v in active.values()
                    if v.get("company_slug")}
    print("=" * 74)
    print(f"CALL LINKAGE — why deal_id is NULL, and the active-coverage upside")
    print("=" * 74)
    print(f"active deals: {len(active)}  ({len(active_slugs)} distinct slugs)")

    # All deal slugs (active + historical) to tell "matches a non-active deal"
    # from "matches nothing".
    from supabase_client import select_all
    all_deals = select_all(sb, "deals", columns="deal_id,company_slug,deal_status")
    all_slugs = {(d.get("company_slug") or "").lower() for d in all_deals
                 if d.get("company_slug")}
    print(f"deals table: {len(all_deals)} rows, {len(all_slugs)} distinct slugs")

    rows, opt = _select(sb, "calls",
                        base_cols=["call_id", "company_slug", "deal_id"],
                        optional_cols=["is_internal", "call_intent", "needs_review"],
                        filters=[("is_", "deal_id", None)])
    print(f"\nNULL-deal_id calls: {len(rows)}")

    has_internal = "is_internal" in opt
    buckets = Counter()
    intents = Counter()
    for r in rows:
        slug = (r.get("company_slug") or "").lower()
        if has_internal and r.get("is_internal"):
            buckets["internal (correctly unlinked)"] += 1
        elif slug and slug in active_slugs:
            buckets["→ matches an ACTIVE deal (recoverable coverage)"] += 1
        elif slug and slug in all_slugs:
            buckets["matches a non-active deal (won't help nightly)"] += 1
        else:
            buckets["no deal-slug match (internal/generic title)"] += 1
        if "call_intent" in opt:
            intents[r.get("call_intent") or "(unset)"] += 1

    print("\nBreakdown of the NULL-deal_id calls:")
    for label, n in buckets.most_common():
        print(f"  {n:5d}  {label}")

    if intents:
        print("\ncall_intent on NULL-deal_id calls (resolver also sets this):")
        for label, n in intents.most_common():
            print(f"  {n:5d}  {label}")

    recover_calls = buckets["→ matches an ACTIVE deal (recoverable coverage)"]
    recover_deals = _deals_touched(rows, active_slugs)
    print("\n" + "=" * 74)
    print(f"UPSIDE of re-running resolve_calls.py (--only-unresolved):")
    print(f"  {recover_calls} NULL calls carry an active-deal slug, spanning "
          f"{recover_deals} distinct active deals")
    print(f"  → those {recover_deals} deals could gain calls they currently lack, "
          f"lifting coverage above the 96/{len(active)} measured now.")
    print("=" * 74)
    if not has_internal:
        print("NOTE: calls has no is_internal column, so internal meetings can't be "
              "separated here;\n'no deal-slug match' includes them.")
    return 0


def _deals_touched(rows, active_slugs):
    """Distinct active-deal slugs among the NULL calls (a call count overstates
    coverage gain — many calls share a deal). This is the real added-deal upper
    bound; the mapping slug→deal_id is 1:1 within active_slugs by construction."""
    seen = set()
    for r in rows:
        slug = (r.get("company_slug") or "").lower()
        if slug in active_slugs:
            seen.add(slug)
    return len(seen)


if __name__ == "__main__":
    sys.exit(main())
