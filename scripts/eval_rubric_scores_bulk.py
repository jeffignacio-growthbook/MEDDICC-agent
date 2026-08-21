#!/usr/bin/env python3
"""
Eval: query_rubric_scores_bulk company-resolution + crash guards.

Regression for the live failure ("Score the LiveSport deal on MEDDICC"):
  * KeyError('deal_ids') when a company was named but no prior deal-id set
    existed — which fell through to the dynamic loop and burned the query
    budget ("Hit query budget with partial data").
  * The three bulk handlers that still did params["deal_ids"] now guard it,
    matching the existing query_deal_stages_bulk fix.
"""
import sys
import types
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
for p in ("", "scripts", "api"):
    sys.path.insert(0, str(REPO / p) if p else str(REPO))

if "supabase" not in sys.modules:
    _f = types.ModuleType("supabase")
    _f.create_client = lambda *a, **k: None
    _f.Client = type("Client", (), {})
    sys.modules["supabase"] = _f


class MockSB:
    """Returns deals rows for the 'deals' table (company resolution) and
    analyses rows for 'analyses' (scores). Supports ilike / in_ / range."""
    def __init__(self, deals, analyses):
        self._deals, self._analyses = deals, analyses
        self._t = None

    def table(self, name):
        self._t = name
        return self

    def select(self, cols):
        return self

    def ilike(self, col, val):
        return self

    def in_(self, col, vals):
        return self

    def range(self, a, b):
        return self

    def execute(self):
        data = self._deals if self._t == "deals" else self._analyses
        return types.SimpleNamespace(data=data)


def run():
    import asyncio
    from api.handlers import (query_rubric_scores_bulk, query_deal_owners_bulk,
                              query_deal_values_bulk)
    print("=" * 72)
    print("QUERY_RUBRIC_SCORES_BULK — company resolution + crash guards")
    print("=" * 72)
    passed = failed = 0

    def check(name, cond):
        nonlocal passed, failed
        if cond:
            passed += 1; print(f"  ✓ {name}")
        else:
            failed += 1; print(f"  ❌ {name}")

    deals = [{"deal_id": "62160567676", "company_name": "LiveSport Media"}]
    analyses = [
        {"deal_id": "62160567676", "company_name": "LiveSport Media",
         "overall_score": 55, "decision_process_score": 4,
         "analyzed_at": "2026-08-06T00:00:00Z"},
        {"deal_id": "62160567676", "company_name": "LiveSport Media",
         "overall_score": 61, "decision_process_score": 6,
         "analyzed_at": "2026-08-19T00:00:00Z"},  # latest
    ]

    # 1. Company-named, no deal_ids → resolves, no crash, latest-per-deal.
    r = asyncio.run(query_rubric_scores_bulk(
        {"company": "LiveSport"}, MockSB(deals, analyses)))
    check("company resolves to a deal (no KeyError)",
          r.get("resolved_from_company") is True and r.get("deal_count") == 1)
    check("latest analysis per deal kept (1 not 2)",
          r.get("scored_count") == 1 and r["scores"][0]["overall_score"] == 61)

    # 2. deal_ids path still works.
    r2 = asyncio.run(query_rubric_scores_bulk(
        {"deal_ids": ["62160567676"]}, MockSB(deals, analyses)))
    check("deal_ids path returns scores", r2.get("scored_count") == 1)

    # 3. Neither deal_ids nor company → graceful error, no raise.
    r3 = asyncio.run(query_rubric_scores_bulk({}, MockSB([], [])))
    check("no ids/company → error, not crash",
          r3.get("scores") == [] and "error" in r3)

    # 4. owners / values guard missing deal_ids.
    ro = asyncio.run(query_deal_owners_bulk({}, MockSB([], [])))
    rv = asyncio.run(query_deal_values_bulk({}, MockSB([], [])))
    check("owners_bulk guards missing deal_ids",
          ro.get("owners") == [] and "error" in ro)
    check("values_bulk guards missing deal_ids",
          rv.get("values") == [] and "error" in rv and rv.get("total_arr") == 0)

    print("\n" + "=" * 72)
    print(f"RESULTS: {passed} passed, {failed} failed")
    print("=" * 72)
    return 0 if failed == 0 else 1


if __name__ == "__main__":
    sys.exit(run())
