#!/usr/bin/env python3
"""
Qualification crossing walk: Sales-pipeline deals that moved from Meeting Set
into a qualified stage, and what became of them.

Standalone and read-only, like commit_cohort_walk.py: no handler, no writes,
nothing reaches Slack.

Scope: the Sales pipeline only (pipeline_id 'default'), from deals_snapshot.
The Renewal Pipeline (866608541) has qualified_stage_order 0 in
config/client.yaml, so every renewal stage is already "qualified" and no
Meeting Set -> qualified crossing is possible there; its rows are ignored.

Definitions:
  Meeting Set     stage_id '79653122' (order 0).
  qualified       stage_id in QUALIFIED_STAGES: the 'default' stages with
                  order >= qualified_stage_order, minus closedwon, closedlost
                  and Disqualified (68509551). Matched by stage_id, never by
                  stage_order: Review (decisionmakerboughtin) has order 8 but
                  sits mid-sequence. main() asserts the config yields the list.
  crossing        the deal is seen at Meeting Set before it is ever seen at a
                  qualified stage, and later appears at a qualified stage. The
                  crossing snapshot is the first qualified snapshot after the
                  first Meeting Set snapshot. A deal first seen at a qualified
                  stage is not a crossing even if a Meeting Set row follows.
  first seen past Meeting Set
                  a deal never seen at Meeting Set, the complement of the
                  Meeting Set population, so its crossing is not observable.
                  Broken down by its first known (non-null) stage: qualified,
                  other (a closed or renewal stage on this pipeline), or none.
  pinned          the deal's previous snapshot (the one just before the
                  crossing) is <= 7 days earlier, so the crossing week is
                  known. Otherwise AMBIGUOUS: counted, flagged, never dropped.
  outcome         the deal's current deals.deal_status (won / lost / active).

Figures, each with its N:
  1. win rate of crossers = won / (won + lost). Still-open crossers are
     counted and listed separately, never folded into the rate.
  2. Meeting Set -> qualified conversion = crossers / deals ever seen at
     Meeting Set. Non-crossers include deals still at Meeting Set, so this is
     "ever crossed so far", not a final conversion rate.
  3. never-at-Meeting-Set count (with its breakdown), pinned vs ambiguous, and the
     snapshot_source / backfill_confidence of the two snapshots around each
     crossing.
No per-quarter or per-segment split (too thin to read) and no speed-of-close
claim; days from crossing to close_date appear only in a CRM-hygiene note.

    SUPABASE_URL=... SUPABASE_SERVICE_KEY=... \\
        python scripts/analytics/qualification_crossing_walk.py
    python scripts/analytics/qualification_crossing_walk.py --input rows.json

--input takes {"snapshots": [[deal_id, snapshot_date, stage_id, pipeline_id,
snapshot_source, backfill_confidence], ...] (or dicts with those keys),
"deals": [{"deal_id", "deal_status", "close_date", "company_name"}, ...]}.
"""
import argparse
import json
import statistics
import sys
from collections import Counter, defaultdict
from datetime import date
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO))
sys.path.insert(0, str(REPO / "scripts"))

PIPELINE = "default"
MEETING_SET = "79653122"
QUALIFIED_STAGES = ("appointmentscheduled", "qualifiedtobuy", "presentationscheduled",
                    "24682892", "43449439", "decisionmakerboughtin")
NOT_QUALIFIED = {"closedwon", "closedlost", "68509551"}
PIN_DAYS = 7
SNAP_COLS = ("deal_id", "snapshot_date", "stage_id", "pipeline_id",
             "snapshot_source", "backfill_confidence")


def _d(v):
    return date.fromisoformat(str(v)[:10]) if v else None


def qualified_stages_from_config(cfg):
    """Stages of pipeline 'default' with order >= its qualified_stage_order,
    minus closed-won, closed-lost and Disqualified."""
    pipes = (cfg.get("pipeline") or cfg).get("pipelines") or []
    for p in pipes:
        if str(p.get("id")) == PIPELINE:
            q = p.get("qualified_stage_order", 1)
            return {str(s["id"]) for s in p.get("stages", [])
                    if s.get("order", -1) >= q and str(s["id"]) not in NOT_QUALIFIED}
    raise KeyError("pipeline 'default' not found in config")


def _src(s):
    return f"{s.get('snapshot_source') or 'null'}/{s.get('backfill_confidence') or 'null'}"


def walk(snapshots, deals, qualified=QUALIFIED_STAGES, pin_days=PIN_DAYS):
    """Find the crossings. Pure: rows in, result dict out."""
    qualified = set(qualified)
    by_deal = defaultdict(list)
    for s in snapshots:
        if str(s.get("pipeline_id")) != PIPELINE:
            continue
        by_deal[str(s["deal_id"])].append(s)
    deals_by_id = {str(d["deal_id"]): d for d in deals}

    ever_ms, crossings, stuck_non_crossers = [], [], []
    never_ms = Counter()           # first known stage of deals never at Meeting Set
    first_qual_later_ms = []       # first seen qualified, Meeting Set row later: not crossings
    for deal_id, snaps in sorted(by_deal.items()):
        snaps.sort(key=lambda s: str(s["snapshot_date"]))
        stages = [str(s.get("stage_id") or "") for s in snaps]
        if MEETING_SET not in stages:
            known = [st for st in stages if st]
            never_ms["no_stage" if not known else
                     "qualified" if known[0] in qualified else "other"] += 1
            continue
        if stages[0] in qualified:
            first_qual_later_ms.append(deal_id)
        ever_ms.append(deal_id)
        i_ms = stages.index(MEETING_SET)
        q_idx = [i for i, st in enumerate(stages) if st in qualified]
        if not q_idx or q_idx[0] < i_ms:
            # never crossed, or qualified before Meeting Set (first seen past it)
            if not q_idx:
                stuck_non_crossers.append(deal_id)
            continue
        j = q_idx[0]
        cur, prev = snaps[j], snaps[j - 1]
        gap = (_d(cur["snapshot_date"]) - _d(prev["snapshot_date"])).days
        d = deals_by_id.get(deal_id)
        status = str((d or {}).get("deal_status") or "").lower()
        outcome = status if status in ("won", "lost") else ("active" if d else "missing")
        close = _d((d or {}).get("close_date"))
        crossings.append({
            "deal_id": deal_id, "company_name": (d or {}).get("company_name"),
            "crossing_date": str(cur["snapshot_date"])[:10],
            "crossing_stage": stages[j],
            "prev_date": str(prev["snapshot_date"])[:10], "prev_stage": stages[j - 1],
            "gap_days": gap, "pinned": gap <= pin_days,
            "sources": f"{_src(prev)} -> {_src(cur)}",
            "outcome": outcome,
            "close_date": close.isoformat() if close else None,
            "days_to_close": (close - _d(cur["snapshot_date"])).days if close else None,
        })
    return {"crossings": crossings,
            "summary": summarise(crossings, ever_ms, never_ms, len(by_deal),
                                 stuck_non_crossers, first_qual_later_ms)}


def summarise(crossings, ever_ms, never_ms, deals_seen, never_qualified=(),
              first_qual_later_ms=()):
    won = [c for c in crossings if c["outcome"] == "won"]
    lost = [c for c in crossings if c["outcome"] == "lost"]
    still = [c for c in crossings if c["outcome"] not in ("won", "lost")]

    def _med(xs):
        v = [c["days_to_close"] for c in xs if c["days_to_close"] is not None]
        return {"median": statistics.median(v) if v else None, "n": len(v)}

    return {
        "deals_seen": deals_seen,
        "ever_meeting_set": len(ever_ms),
        "never_meeting_set": sum(never_ms.values()),
        "never_ms_first_known": {k: never_ms.get(k, 0) for k in ("qualified", "other", "no_stage")},
        "first_seen_qualified_later_ms": len(first_qual_later_ms),
        "never_qualified_after_meeting_set": len(never_qualified),
        "crossers": len(crossings),
        "pinned": sum(1 for c in crossings if c["pinned"]),
        "ambiguous": sum(1 for c in crossings if not c["pinned"]),
        "won": len(won), "lost": len(lost), "resolved": len(won) + len(lost),
        "open": len(still),
        "open_deals": sorted(still, key=lambda c: c["crossing_date"]),
        "missing": sum(1 for c in still if c["outcome"] == "missing"),
        "conversion": {"crossers": len(crossings), "of": len(ever_ms)},
        "sources": dict(Counter(c["sources"] for c in crossings).most_common()),
        "days_to_close": {"won": _med(won), "lost": _med(lost)},
    }


def _pct(a, b):
    return f"{a / b:.0%}" if b else "n/a"


def report(result):
    """Plain-text report. N is stated on every rate; no bare percentages."""
    s = result["summary"]
    n = s["crossers"]
    out = [f"Sales pipeline (pipeline_id '{PIPELINE}'): {s['deals_seen']} deals in deals_snapshot.", ""]
    out.append(f"1. Outcome of crossers: N = {n} crossings. Resolved N = {s['resolved']}: "
               f"{s['won']} won, {s['lost']} lost.")
    out.append(f"   Win rate: {s['won']} won of {s['resolved']} resolved "
               f"({_pct(s['won'], s['resolved'])}).")
    out.append(f"   {s['open']} still open (listed below), not in the rate"
               + (f"; {s['missing']} of them missing from deals" if s["missing"] else "") + ".")
    c = s["conversion"]
    out.append("")
    out.append(f"2. Meeting Set -> qualified: {c['crossers']} of {c['of']} deals ever seen at Meeting Set "
               f"({_pct(c['crossers'], c['of'])}) have crossed. The non-crossers include deals still "
               "at Meeting Set, so this is \"ever crossed so far\", not a final conversion rate.")
    out.append("")
    out.append("3. Coverage:")
    nk = s["never_ms_first_known"]
    out.append(f"   Never seen at Meeting Set: {s['never_meeting_set']} of {s['deals_seen']} deals "
               "(crossing not observable, not counted). First known "
               f"stage: {nk['qualified']} qualified, {nk['other']} other (closed or renewal stage), "
               f"{nk['no_stage']} no stage recorded.")
    if s["first_seen_qualified_later_ms"]:
        out.append(f"   {s['first_seen_qualified_later_ms']} deal(s) first seen at a qualified stage later "
                   "show a Meeting Set row; they are in the Meeting Set denominator but not crossings.")
    out.append(f"   Crossing week: {s['pinned']} pinned (previous snapshot <= {PIN_DAYS} days earlier), "
               f"{s['ambiguous']} ambiguous (longer gap; still counted above), of {n} crossings.")
    out.append(f"   Snapshot source/confidence, previous -> crossing snapshot (of {n}):")
    for k, v in s["sources"].items():
        out.append(f"     {v:>4}  {k}")
    dtc = s["days_to_close"]
    if dtc["won"]["n"] or dtc["lost"]["n"]:
        out.append("")
        out.append("Note on CRM hygiene (not a property of the metric): median days from crossing to "
                   f"close_date are similar for won ({dtc['won']['median']}, N = {dtc['won']['n']}) and "
                   f"lost ({dtc['lost']['median']}, N = {dtc['lost']['n']}). close_date on lost deals is "
                   "not reliable (FY2027 Q2's COMMIT walk found PhonePe lost inside the quarter with a "
                   "close_date before it), so treat these durations as approximate; no speed-of-close "
                   "claim is made.")
    return "\n".join(out)


def detail(result):
    s = result["summary"]
    out = [f"Still-open crossers ({s['open']}), not in the win rate:",
           "  deal_id      company                     crossed     stage                  status"]
    for c in s["open_deals"]:
        out.append(f"  {c['deal_id']:<12} {str(c['company_name'])[:26]:<26}  {c['crossing_date']}  "
                   f"{c['crossing_stage']:<22} {c['outcome']}")
    amb = [c for c in result["crossings"] if not c["pinned"]]
    out.append("")
    out.append(f"Ambiguous crossings ({len(amb)}), counted in every figure above:")
    for c in amb:
        out.append(f"  {c['deal_id']:<12} {str(c['company_name'])[:26]:<26}  prev {c['prev_date']} "
                   f"({c['prev_stage']}) -> {c['crossing_date']} ({c['crossing_stage']}), "
                   f"{c['gap_days']} days, {c['outcome']}")
    return "\n".join(out)


def _fetch():
    import os
    from supabase import create_client
    from supabase_client import select_all
    sb = create_client(os.environ["SUPABASE_URL"], os.environ["SUPABASE_SERVICE_KEY"])
    snaps = select_all(sb, "deals_snapshot", columns=",".join(SNAP_COLS),
                       filters=[("eq", "pipeline_id", PIPELINE)])
    ids = sorted({str(s["deal_id"]) for s in snaps})
    deals = []
    for i in range(0, len(ids), 100):
        deals += sb.table("deals").select("deal_id,deal_status,close_date,company_name").in_(
            "deal_id", ids[i:i + 100]).execute().data or []
    return {"snapshots": snaps, "deals": deals}


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--input", help="rows as JSON instead of querying Supabase")
    ap.add_argument("--json", action="store_true", help="print the full result as JSON too")
    args = ap.parse_args()

    import yaml
    cfg = yaml.safe_load((REPO / "config" / "client.yaml").read_text())
    from_cfg = qualified_stages_from_config(cfg)
    assert from_cfg == set(QUALIFIED_STAGES), (sorted(from_cfg), QUALIFIED_STAGES)

    data = json.loads(Path(args.input).read_text()) if args.input else _fetch()
    snaps = [dict(zip(SNAP_COLS, s)) if isinstance(s, list) else s for s in data["snapshots"]]
    result = walk(snaps, data["deals"])
    print("Qualification crossing walk (Meeting Set -> qualified), read-only.\n")
    print(report(result) + "\n")
    print(detail(result))
    if args.json:
        print("\nJSON " + json.dumps(result, default=str))


if __name__ == "__main__":
    main()
