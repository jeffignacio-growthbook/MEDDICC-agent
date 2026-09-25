#!/usr/bin/env python3
"""
Commit cohort walk: what happened to the deals a quarter's forecast called COMMIT.

Standalone and read-only, like the MEDDICC significance test: no handler, no
writes, nothing reaches Slack. It exists to answer, for one closed quarter,
whether committed deals were real opportunities whose timing was misjudged, or
deals that were never going to close.

Cohort (point-in-time, from deals_snapshot):
  --cohort ever      tagged COMMIT in any weekly snapshot of the quarter (default)
  --anchor-week N    tagged COMMIT in week N's snapshot
Both are printed by default, with the week each deal was first tagged, because
a deal tagged COMMIT in the week it signed flatters the in-quarter hit rate.

Every deal lands in exactly one of four buckets:
  WON_IN_QUARTER   won, and the win happened on or before quarter end
  WON_LATER        won, but after the quarter it was committed for
  STILL_OPEN       not won or lost yet
  LOST             lost (split into in-quarter / later in the detail)

When did it close? The date the deal ENTERED its terminal stage, from
property_history (dealstage), when that history exists. Otherwise the deal's
close_date. close_date alone is not trusted blindly: a lost deal can carry a
close_date from before the quarter it was committed in (live: PhonePe, lost
2026-07-20 per stage history, close_date 2026-04-01).

Coverage check. The complete quarters are backfilled: deals_snapshot holds only
OPEN rows, so a deal leaving the snapshots is the only trace of it closing.
For each deal the walk compares its terminal date with the week it left the
snapshots. A deal is AMBIGUOUS when the evidence can't place its outcome on one
side of quarter end:
  - it is missing from `deals` (deleted, or never synced);
  - it is won/lost with no stage history and no close_date;
  - it has no stage history, and its close_date and its snapshot exit fall on
    different sides of quarter end.
Softer flags (reported, bucket unaffected): close_date disagreeing with stage
history, snapshot gaps mid-quarter, and a close_date-only outcome that the
snapshots can't confirm because the deal was still open in the last snapshot.

Two framings, each with its own dollar total, each with N stated:
  in-quarter hit rate   WON_IN_QUARTER / N
  eventual win rate     (WON_IN_QUARTER + WON_LATER) / (won + lost), with the
                        still-open count stated beside it, never folded in
Dollars are deal_value, the snapshot basis for quarters before 2026-09-11:
committed value from the deal's last COMMIT snapshot, won value from `deals`.
New business and the Renewal Pipeline are also shown separately.

    SUPABASE_URL=... SUPABASE_SERVICE_KEY=... \\
        python scripts/analytics/commit_cohort_walk.py --quarter "FY2027 Q2"
    python scripts/analytics/commit_cohort_walk.py --quarter "FY2027 Q2" --input rows.json

--input takes {"snapshots": [[deal_id, snapshot_date, week, forecast_category,
deal_value, close_date, pipeline_id, stage_id, deal_status], ...],
"snapshot_dates": [...], "deals": [{...}], "stage_history": [[deal_id,
changed_at, new_value], ...], "deleted": [deal_id, ...] | null}.
"""
import argparse
import json
import sys
from collections import defaultdict
from datetime import date
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO))
sys.path.insert(0, str(REPO / "scripts"))

from api.field_semantics import is_won, is_lost  # noqa: E402

BUCKETS = ("WON_IN_QUARTER", "WON_LATER", "STILL_OPEN", "LOST")
SNAP_COLS = ("deal_id", "snapshot_date", "week_of_quarter", "forecast_category",
             "deal_value", "close_date", "pipeline_id", "stage_id", "deal_status")


def _d(v):
    return date.fromisoformat(str(v)[:10]) if v else None


def _terminal(stage):
    try:
        return "won" if is_won(str(stage)) else "lost" if is_lost(str(stage)) else None
    except Exception:
        return None


def _entered_terminal(history, outcome):
    """Date the deal last entered a stage of its terminal bucket, or None."""
    entered = None
    for changed_at, stage in sorted(history):
        if _terminal(stage) == outcome:
            if entered is None:
                entered = _d(changed_at)
        else:
            entered = None           # left it again (reopened): only the last entry counts
    return entered


def walk(snapshots, snapshot_dates, deals, stage_history, deleted, q_start, q_end,
         renewal_pipelines=(), anchor_week=None):
    """Classify the quarter's COMMIT cohort. Pure: rows in, result dict out.

    snapshots: dicts with SNAP_COLS keys, already limited to the quarter.
    anchor_week None = ever tagged COMMIT in the quarter.
    """
    snap_dates = sorted(_d(s) for s in snapshot_dates)
    by_deal = defaultdict(list)
    for s in snapshots:
        by_deal[str(s["deal_id"])].append(s)
    deals_by_id = {str(d["deal_id"]): d for d in deals}
    hist = defaultdict(list)
    for deal_id, changed_at, stage in stage_history or []:
        hist[str(deal_id)].append((changed_at, stage))
    deleted = {str(x) for x in (deleted or [])}

    rows = []
    for deal_id, snaps in sorted(by_deal.items()):
        snaps.sort(key=lambda s: str(s["snapshot_date"]))
        commits = [s for s in snaps if str(s.get("forecast_category") or "").upper() == "COMMIT"]
        if anchor_week is None:
            if not commits:
                continue
        elif not any(s["week_of_quarter"] == anchor_week for s in commits):
            continue
        last_commit = commits[-1]
        present = sorted({_d(s["snapshot_date"]) for s in snaps})
        first_i, last_i = snap_dates.index(present[0]), snap_dates.index(present[-1])
        gap_weeks = [i + 1 for i in range(first_i, last_i + 1) if snap_dates[i] not in present]
        exit_after = present[-1]                                   # last snapshot it was open in
        exit_by = snap_dates[last_i + 1] if last_i + 1 < len(snap_dates) else None

        d = deals_by_id.get(deal_id)
        r = {"deal_id": deal_id, "company_name": (d or {}).get("company_name"),
             "pipeline_id": str((d or {}).get("pipeline_id") or last_commit.get("pipeline_id")),
             "first_commit_week": commits[0]["week_of_quarter"],
             "commit_weeks": [s["week_of_quarter"] for s in commits],
             "committed_value": _value(last_commit.get("deal_value")),
             "committed_close_date": str(last_commit.get("close_date") or "")[:10] or None,
             "commit_weeks_close_outside": [
                 s["week_of_quarter"] for s in commits
                 if _d(s.get("close_date")) and not q_start <= _d(s.get("close_date")) <= q_end],
             "won_value": 0.0, "flags": [], "ambiguous": None,
             "snapshot_gap_weeks": gap_weeks,
             "last_open_snapshot": exit_after.isoformat(),
             "left_snapshots_by": exit_by.isoformat() if exit_by else None}
        if gap_weeks:
            r["flags"].append(f"no snapshot row in week(s) {gap_weeks} while in the quarter")
        rows.append(r)

        if d is None:
            r["bucket"] = None
            r["ambiguous"] = ("deleted in HubSpot (deleted_deals)" if deal_id in deleted
                              else "not in deals")
            continue
        outcome = _terminal(d.get("stage"))
        close = _d(d.get("close_date"))
        if outcome is None:
            r["bucket"], r["outcome_date"], r["outcome_date_source"] = "STILL_OPEN", None, None
            if exit_by is not None:
                r["flags"].append(f"still open, but not in snapshots after {exit_after} "
                                  "(left the quarter's scope)")
            continue

        entered = _entered_terminal(hist.get(deal_id, []), outcome)
        when, source = (entered, "stage_history") if entered else (close, "close_date")
        r["outcome_date"], r["outcome_date_source"] = when.isoformat() if when else None, source
        if when is None:
            r["bucket"] = None
            r["ambiguous"] = f"{outcome}, but no stage history and no close_date"
            continue
        in_q = when <= q_end
        side = lambda x: "before" if x < q_start else "in" if x <= q_end else "after"
        if entered and close and side(close) != side(entered):
            r["flags"].append(f"close_date {close} ({side(close)} the quarter) disagrees with "
                              f"stage history ({outcome} {entered}, {side(entered)} it); "
                              "stage history used")
        elif entered and close and close != entered and abs((close - entered).days) > 7:
            r["flags"].append(f"close_date {close} vs stage history {entered} (same side of quarter end)")
        if when < q_start:
            r["flags"].append(f"{outcome} {when}, before the quarter it was committed in")
        if not entered:
            # close_date only: can the snapshot exit confirm which side of quarter end?
            if exit_by is None:
                if in_q:
                    r["flags"].append("close_date only; still open in the last snapshot, "
                                      "so the snapshots can't confirm it")
            elif (exit_by <= q_end) != in_q and (exit_after < q_end) != in_q:
                r["ambiguous"] = (f"close_date {close} and snapshot exit "
                                  f"({exit_after}..{exit_by}) are on different sides of "
                                  f"quarter end, no stage history")
                r["bucket"] = None
                continue
        if outcome == "won":
            r["bucket"] = "WON_IN_QUARTER" if in_q else "WON_LATER"
            r["won_value"] = _value(d.get("deal_value"))
        else:
            r["bucket"] = "LOST"
            r["lost_timing"] = "in_quarter" if in_q else "later"
    return {"rows": rows, "summary": summarise(rows, renewal_pipelines)}


def _value(v):
    """deal_value as a float, or None when unknown. A snapshot row with no
    value history reconstructs to None (Phase 2b); 0-filling it would put a
    fabricated $0 into a dollar total (eval_reconstruction's ratchet). An
    unknown value is left out of every dollar sum and counted instead."""
    return None if v is None else float(v)


def _sum(rows, key):
    return round(sum(r[key] for r in rows if r[key] is not None), 2)


def summarise(rows, renewal_pipelines=()):
    renewal = {str(p) for p in renewal_pipelines}

    def _one(rs):
        n = len(rs)
        b = {k: [r for r in rs if r["bucket"] == k] for k in BUCKETS}
        amb = [r for r in rs if r["bucket"] is None]
        cv = lambda xs: _sum(xs, "committed_value")
        wv = lambda xs: _sum(xs, "won_value")
        won = b["WON_IN_QUARTER"] + b["WON_LATER"]
        resolved = won + b["LOST"]
        return {
            "n": n, "ambiguous": len(amb), "committed_value": cv(rs),
            "value_unknown": {"committed": sum(1 for r in rs if r["committed_value"] is None),
                              "won": sum(1 for r in rs if r["won_value"] is None)},
            "buckets": {k: {"n": len(v), "committed_value": cv(v), "won_value": wv(v)}
                        for k, v in b.items()},
            "lost_in_quarter": sum(1 for r in b["LOST"] if r.get("lost_timing") == "in_quarter"),
            "in_quarter_hit": {"won": len(b["WON_IN_QUARTER"]), "of": n,
                               "won_value": wv(b["WON_IN_QUARTER"]),
                               "committed_value_won": cv(b["WON_IN_QUARTER"]),
                               "committed_value_all": cv(rs)},
            "eventual_win": {"won": len(won), "of_resolved": len(resolved),
                             "still_open": len(b["STILL_OPEN"]),
                             "won_value": wv(won), "committed_value_won": cv(won),
                             "committed_value_resolved": cv(resolved),
                             "committed_value_open": cv(b["STILL_OPEN"])},
        }
    return {"all": _one(rows),
            "new_business": _one([r for r in rows if r["pipeline_id"] not in renewal]),
            "renewal": _one([r for r in rows if r["pipeline_id"] in renewal])}


def headlines(rows, last_week, late_weeks=3):
    """The three findings to lead with, computed, not written per quarter:
    lost outright; COMMIT tags against a close date outside the quarter
    (the biggest-dollar such deal first); wins first tagged COMMIT only in
    the last `late_weeks` weeks."""
    n = len(rows)
    lost = [r for r in rows if r["bucket"] == "LOST"]
    outside = sorted((r for r in rows if r["commit_weeks_close_outside"]),
                     key=lambda r: -(r["committed_value"] or 0))
    wins = [r for r in rows if r["bucket"] == "WON_IN_QUARTER"]
    late_from = last_week - late_weeks + 1
    late = [r for r in wins if r["first_commit_week"] >= late_from]
    return {"n": n, "lost": len(lost), "lost_value": _sum(lost, "committed_value"),
            "lost_value_unknown": sum(1 for r in lost if r["committed_value"] is None),
            "close_outside": [{"deal_id": r["deal_id"], "company_name": r["company_name"],
                               "weeks": r["commit_weeks_close_outside"],
                               "committed_value": r["committed_value"], "bucket": r["bucket"]}
                              for r in outside],
            "wins": len(wins), "late_wins": len(late), "late_from_week": late_from,
            "last_week": last_week}


def headline_text(h):
    unk = h.get("lost_value_unknown") or 0
    out = [f"1. Lost outright: {h['lost']} of {h['n']} committed deals "
           f"({_money(h['lost_value'])} committed"
           + (f"; {unk} with no value, not in that total" if unk else "") + ")."]
    co = h["close_outside"]
    if co:
        top = co[0]
        out.append(f"2. COMMIT against a close date outside the quarter: {len(co)} of {h['n']} deals. "
                   f"Largest: {top['company_name']} ({_money(top['committed_value'])}), "
                   f"{len(top['weeks'])} COMMIT week(s) {top['weeks']}, now {top['bucket'] or 'AMBIGUOUS'}.")
        for r in co[1:]:
            out.append(f"   also {r['company_name']} ({_money(r['committed_value'])}): week(s) {r['weeks']}, "
                       f"now {r['bucket'] or 'AMBIGUOUS'}")
    else:
        out.append(f"2. COMMIT against a close date outside the quarter: 0 of {h['n']} deals.")
    out.append(f"3. Late tags: {h['late_wins']} of {h['wins']} in-quarter wins were first tagged COMMIT "
               f"in weeks {h['late_from_week']}-{h['last_week']}, the last three weeks; they add to the "
               "hit rate without showing early judgment.")
    return "\n".join(out)


def _pct(a, b):
    return f"{a / b:.0%}" if b else "n/a"


def _money(v):
    return "unknown" if v is None else f"${v:,.0f}"


def report(title, s):
    """Plain-text report. N is stated on every rate; no bare percentages."""
    n = s["n"]
    b = s["buckets"]
    out = [f"{title}: N = {n} deals, {_money(s['committed_value'])} committed (deal_value)"]
    if n == 0:
        return "\n".join(out + ["  (no deals)"])
    for k in BUCKETS:
        extra = ""
        if k == "LOST":
            extra = f" ({s['lost_in_quarter']} in quarter, {b[k]['n'] - s['lost_in_quarter']} later)"
        won = f", {_money(b[k]['won_value'])} won" if k.startswith("WON") else ""
        out.append(f"  {k:<15} {b[k]['n']:>3} of {n}  {_money(b[k]['committed_value']):>12} committed{won}{extra}")
    if s["ambiguous"]:
        out.append(f"  AMBIGUOUS       {s['ambiguous']:>3} of {n}  (excluded from both rates below; see detail)")
    unk = s.get("value_unknown") or {}
    if unk.get("committed") or unk.get("won"):
        out.append(f"  Value unknown: {unk.get('committed', 0)} committed value and {unk.get('won', 0)} won "
                   "value unknown (no deal_value); left out of every dollar figure, deal counts unchanged")
    h, e = s["in_quarter_hit"], s["eventual_win"]
    out.append(f"  In-quarter hit rate: {h['won']} of {n} deals ({_pct(h['won'], n)}) won by quarter end; "
               f"{_money(h['committed_value_won'])} of {_money(h['committed_value_all'])} committed "
               f"({_pct(h['committed_value_won'], h['committed_value_all'])}), {_money(h['won_value'])} won")
    out.append(f"  Eventual win rate:   {e['won']} of {e['of_resolved']} resolved deals "
               f"({_pct(e['won'], e['of_resolved'])}) won, {e['still_open']} still open "
               f"({_money(e['committed_value_open'])} committed) not counted; "
               f"{_money(e['committed_value_won'])} of {_money(e['committed_value_resolved'])} resolved "
               f"committed ({_pct(e['committed_value_won'], e['committed_value_resolved'])}), "
               f"{_money(e['won_value'])} won")
    if n < 30:
        out.append(f"  Small sample: N = {n}. One deal moves the hit rate by {1 / n:.0%}.")
    return "\n".join(out)


def detail(rows):
    out = ["deal_id      company                    pipe      first  committed    bucket          closed      source"]
    for r in sorted(rows, key=lambda r: (str(r["bucket"]), r["first_commit_week"])):
        out.append(f"{r['deal_id']:<12} {str(r['company_name'])[:26]:<26} "
                   f"{'renewal' if r['pipeline_id'] == '866608541' else r['pipeline_id']:<9} "
                   f"wk{r['first_commit_week']:<4} {_money(r['committed_value']):>10}  "
                   f"{str(r['bucket'] or 'AMBIGUOUS'):<15} {str(r.get('outcome_date') or ''):<11} "
                   f"{r.get('outcome_date_source') or ''}")
        for f in r["flags"] + ([f"AMBIGUOUS: {r['ambiguous']}"] if r["ambiguous"] else []):
            out.append(f"             - {f}")
    return "\n".join(out)


def _fetch(quarter):
    import os
    from supabase import create_client
    from supabase_client import select_all
    sb = create_client(os.environ["SUPABASE_URL"], os.environ["SUPABASE_SERVICE_KEY"])
    snaps = select_all(sb, "deals_snapshot", columns=",".join(SNAP_COLS),
                       filters=[("eq", "fiscal_quarter", quarter)])
    ids = sorted({str(s["deal_id"]) for s in snaps
                  if str(s.get("forecast_category") or "").upper() == "COMMIT"})
    snaps = [s for s in snaps if str(s["deal_id"]) in set(ids)]
    dates = sorted({str(s["snapshot_date"]) for s in select_all(
        sb, "deals_snapshot", columns="snapshot_date", filters=[("eq", "fiscal_quarter", quarter)])})
    deals, hist, deleted = [], [], []
    for i in range(0, len(ids), 100):
        chunk = ids[i:i + 100]
        deals += sb.table("deals").select(
            "deal_id,company_name,stage,deal_status,close_date,pipeline_id,deal_value").in_(
            "deal_id", chunk).execute().data or []
        hist += [[h["deal_id"], h["changed_at"], h["new_value"]] for h in sb.table(
            "property_history").select("deal_id,changed_at,new_value").eq(
            "property_name", "dealstage").in_("deal_id", chunk).execute().data or []]
        deleted += [x["deal_id"] for x in sb.table("deleted_deals").select("deal_id").in_(
            "deal_id", chunk).execute().data or []]
    return {"snapshots": snaps, "snapshot_dates": dates, "deals": deals,
            "stage_history": hist, "deleted": deleted}


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--quarter", required=True, help='e.g. "FY2027 Q2"')
    ap.add_argument("--input", help="rows as JSON instead of querying Supabase")
    ap.add_argument("--anchor-week", type=int, action="append",
                    help="also report the cohort COMMIT at this week (repeatable; default 3)")
    ap.add_argument("--json", action="store_true", help="print the full result as JSON too")
    args = ap.parse_args()

    import yaml
    from utils import get_fiscal_quarter
    data = json.loads(Path(args.input).read_text()) if args.input else _fetch(args.quarter)
    snaps = [dict(zip(SNAP_COLS, s)) if isinstance(s, list) else s for s in data["snapshots"]]
    q_start, q_end, label = get_fiscal_quarter(_d(sorted(data["snapshot_dates"])[0]))
    assert label == args.quarter, (label, args.quarter)
    cfg = yaml.safe_load((REPO / "config" / "client.yaml").read_text())
    renewal = []
    def _find(o):
        if isinstance(o, dict):
            for k, v in o.items():
                if k == "renewal_pipeline_ids":
                    renewal.extend(v)
                _find(v)
        elif isinstance(o, list):
            for v in o:
                _find(v)
    _find(cfg)

    print(f"Commit cohort walk, {label} ({q_start} to {q_end}), read-only. "
          f"{len(data['snapshot_dates'])} weekly snapshots.\n")
    ever = walk(snaps, data["snapshot_dates"], data["deals"], data["stage_history"],
                data.get("deleted"), q_start, q_end, renewal)
    last_week = max(s["week_of_quarter"] for s in snaps)
    print("Lead with:\n" + headline_text(headlines(ever["rows"], last_week)) + "\n")
    for key, title in (("all", "Ever COMMIT in the quarter"), ("new_business", "  of which new business"),
                       ("renewal", "  of which Renewal Pipeline")):
        print(report(title, ever["summary"][key]) + "\n")

    for w in args.anchor_week or [3]:
        a = walk(snaps, data["snapshot_dates"], data["deals"], data["stage_history"],
                 data.get("deleted"), q_start, q_end, renewal, anchor_week=w)
        print(report(f"COMMIT at week {w}", a["summary"]["all"]) + "\n")

    print("By first COMMIT week (ever-COMMIT cohort):")
    by_week = defaultdict(lambda: defaultdict(int))
    for r in ever["rows"]:
        by_week[r["first_commit_week"]][r["bucket"] or "AMBIGUOUS"] += 1
    print("  week   N  " + "  ".join(f"{k:<14}" for k in BUCKETS))
    for w in sorted(by_week):
        n = sum(by_week[w].values())
        print(f"  {w:>4}  {n:>2}  " + "  ".join(f"{by_week[w][k]:<14}" for k in BUCKETS))
    print("\nCoverage / ambiguity, per deal:")
    print(detail(ever["rows"]))
    if args.json:
        print("\nJSON " + json.dumps(ever, default=str))


if __name__ == "__main__":
    main()
