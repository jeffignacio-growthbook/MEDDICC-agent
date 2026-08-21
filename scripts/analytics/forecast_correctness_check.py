#!/usr/bin/env python3
"""
Diagnostic for the analysis-correctness pass (forecast_analyses.py).

NOT a fix — it establishes the DATA MECHANISM the numerator fix must use, so
Phase 1 is implemented against reality rather than an assumption. Specifically
it answers, per complete quarter:

  * Does deals_snapshot even contain won rows? (Method 2 backfill writes only
    OPEN rows, so a snapshot-transition numerator may see zero wins there.)
  * Which candidate numerator reproduces the known-correct in-quarter closes
    (31 / 40 / 48)?
      A. buggy_current      — deal is won in its LAST in-quarter snapshot
      B. snapshot_transition — deal_status/stage transitions to won across
                               consecutive in-quarter weekly snapshots
      C. terminal_close      — deal is terminally won (deals table is_won) with
                               close_date inside the quarter window, among deals
                               that appear in the quarter's scoped snapshots
  * The scoped week-3 denominator, per pipeline.

Runs in CI (needs SUPABASE_URL / SUPABASE_SERVICE_KEY).
"""
import os
import sys
from collections import defaultdict
from datetime import date
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent.parent
for p in ("scripts", "scripts/analytics", "api", "."):
    sys.path.insert(0, str(REPO / p))


def _sb():
    from supabase import create_client
    return create_client(os.environ["SUPABASE_URL"],
                         os.environ["SUPABASE_SERVICE_KEY"])


def main():
    from supabase_client import select_all
    from utils import get_fiscal_quarter
    from field_semantics import is_won
    from analytics.point_in_time import (
        load_scope_config, is_deal_in_analytics_scope)

    sb = _sb()
    excl, stage_cfg = load_scope_config()

    def in_scope(stage_id, pipeline_id):
        if pipeline_id is not None and str(pipeline_id) in excl:
            return False
        if stage_id is None or not str(stage_id).strip():
            return False  # denominator scoping: unknown stage is not qualified
        return is_deal_in_analytics_scope(str(stage_id), pipeline_id, excl, stage_cfg)

    # Complete quarters (13 weeks)
    snaps = select_all(sb, "deals_snapshot",
                       columns="fiscal_quarter,week_of_quarter")
    weeks_by_q = defaultdict(set)
    for r in snaps:
        if r.get("fiscal_quarter") and r.get("week_of_quarter"):
            weeks_by_q[r["fiscal_quarter"]].add(r["week_of_quarter"])
    complete = sorted(q for q, w in weeks_by_q.items() if len(w) == 13)
    print(f"Complete quarters (13 weeks): {complete}\n")

    # Terminal outcomes from deals table (won stage + close_date).
    deals = select_all(sb, "deals", columns="deal_id,stage,close_date,pipeline_id")
    terminal = {}
    for d in deals:
        st = d.get("stage")
        won = False
        try:
            won = is_won(str(st)) if st else False
        except Exception:
            won = False
        terminal[str(d["deal_id"])] = {
            "won": won, "close_date": d.get("close_date"),
            "pipeline_id": d.get("pipeline_id")}

    for q in complete:
        qrows = select_all(
            sb, "deals_snapshot",
            columns="deal_id,snapshot_date,week_of_quarter,stage_id,"
                    "pipeline_id,deal_status,snapshot_source",
            filters=[("eq", "fiscal_quarter", q)])
        if not qrows:
            continue
        # quarter window from any in-quarter date
        any_d = date.fromisoformat(min(r["snapshot_date"] for r in qrows))
        q_start, q_end, _ = get_fiscal_quarter(any_d)

        # snapshot source mix
        src_ct = defaultdict(int)
        won_rows = 0
        for r in qrows:
            src_ct[r.get("snapshot_source")] += 1
            st = r.get("stage_id")
            if (r.get("deal_status") == "won") or (st and _safe_is_won(st)):
                won_rows += 1

        # week-3 scoped denominator (per pipeline)
        wk3 = [r for r in qrows if r.get("week_of_quarter") == 3]
        denom_ids = {r["deal_id"] for r in wk3
                     if in_scope(r.get("stage_id"), r.get("pipeline_id"))}
        denom_by_pipe = defaultdict(int)
        for r in wk3:
            if in_scope(r.get("stage_id"), r.get("pipeline_id")):
                denom_by_pipe[r.get("pipeline_id")] += 1

        # A. buggy_current: last in-quarter snapshot shows won
        by_deal = defaultdict(list)
        for r in qrows:
            by_deal[r["deal_id"]].append(r)
        num_buggy = 0
        for did, rs in by_deal.items():
            last = max(rs, key=lambda x: x["snapshot_date"])
            st = (last.get("stage_id") or "")
            if (last.get("deal_status") == "won") or _safe_is_won(st):
                num_buggy += 1

        # B. snapshot_transition: won transition across consecutive weeks
        num_transition = 0
        for did, rs in by_deal.items():
            rs_sorted = sorted(rs, key=lambda x: x["snapshot_date"])
            prev_won = False
            transitioned = False
            for r in rs_sorted:
                st = r.get("stage_id") or ""
                now_won = (r.get("deal_status") == "won") or _safe_is_won(st)
                if now_won and not prev_won:
                    transitioned = True
                prev_won = now_won
            if transitioned:
                num_transition += 1

        # C. terminal_close: appears in quarter's scoped snapshots AND is
        #    terminally won with close_date in the quarter window.
        appeared = set(by_deal)
        num_terminal = 0
        num_terminal_by_pipe = defaultdict(int)
        for did in appeared:
            t = terminal.get(str(did))
            if not t or not t["won"] or not t["close_date"]:
                continue
            cd = t["close_date"][:10]
            if q_start.isoformat() <= cd <= q_end.isoformat():
                num_terminal += 1
                num_terminal_by_pipe[t["pipeline_id"]] += 1

        print("=" * 78)
        print(f"{q}   window {q_start}..{q_end}   sources={dict(src_ct)}")
        print(f"  won rows present in deals_snapshot for quarter: {won_rows}")
        print(f"  week-3 scoped denominator: {len(denom_ids)}  "
              f"by_pipeline={dict(denom_by_pipe)}")
        print(f"  NUMERATOR candidates:")
        print(f"    A buggy_current (won in last in-qtr snapshot): {num_buggy}")
        print(f"    B snapshot_transition (won transition in-qtr): {num_transition}")
        print(f"    C terminal_close (deals.is_won & close in qtr): {num_terminal}"
              f"  by_pipeline={dict(num_terminal_by_pipe)}")
        print()

    print("Compare candidate C (and B) against known-correct 31 / 40 / 48.")


def _safe_is_won(stage_id):
    from field_semantics import is_won
    try:
        return is_won(str(stage_id))
    except Exception:
        return False


if __name__ == "__main__":
    main()
