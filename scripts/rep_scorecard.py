#!/usr/bin/env python3
"""
Per-rep scorecard for the quarter-health loss-concentration rep table: two
computed, factual lines per rep, so a bare "14 of 14 qualified deals lost"
reads next to how those losses looked and how the rep's win pace compares to
their own history. No narrative frame — the reader draws the conclusion.

  1. loss_depth: of this rep's qualified losses this quarter, how many never
     passed Discovery (deepest qualifying stage reached, on or before close,
     was Discovery itself), and how many were ever tagged COMMIT or Most
     Likely at any snapshot up to close. Both from the same fields the
     qualified loss rate already uses (deals_snapshot stage_id and
     forecast_category history). "Never passed Discovery" = a loss that got
     into the funnel but no further than the first qualified stage.

  2. pace: this rep's wins-to-date this quarter (count and incremental ARR
     closed by the same point of the quarter bookings_seasonality measures
     the team at) against the same point in their last up to PRIOR_QUARTERS
     quarters that had any Sales win. A rep well below their own prior pace
     (Christian: 0 this quarter vs 2-4 by this point in each of the last
     three) shows without anyone calling it good or bad.

Qualified / Discovery-or-later comes from loss_concentration, unchanged, so
the boundary is defined once. Sales pipeline only, incremental ARR only.

Read-only. Two fetches (this quarter's losses + their snapshots; Sales wins
over the trailing window).
"""
import sys
from collections import defaultdict
from datetime import date, timedelta
from pathlib import Path
from typing import Any, Dict, List, Optional

REPO_ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(REPO_ROOT / "scripts"))
sys.path.insert(0, str(REPO_ROOT / "api"))

PRIOR_QUARTERS = 3
_COMMIT_ML = ("COMMIT", "MOST_LIKELY")


def _money(x: float) -> str:
    return f"${x:,.0f}"


def loss_depth_line(qual: int, never_past: int, ever_cm: int) -> str:
    if qual == 0:
        return "no qualified losses this quarter"
    cm = ("none ever tagged COMMIT or Most Likely" if ever_cm == 0
          else f"{ever_cm} ever tagged COMMIT or Most Likely")
    return f"{never_past} of {qual} qualified losses never passed Discovery; {cm}"


def pace_line(days_elapsed: int, cur_wins: int, cur_arr: float, priors: List[dict]) -> str:
    cur = f"{cur_wins} win{'' if cur_wins == 1 else 's'} / {_money(cur_arr)} this quarter"
    if not priors:
        return f"day-{days_elapsed} pace: {cur}; no prior-quarter win pace to compare"
    w = [p["wins"] for p in priors]
    a = [p["arr"] for p in priors]
    labels = ", ".join(p["label"] for p in priors)
    if len(priors) == 1:
        vs = f"{w[0]} win{'' if w[0] == 1 else 's'} / {_money(a[0])}"
    else:
        wr = f"{min(w)}" if min(w) == max(w) else f"{min(w)}-{max(w)}"
        ar = _money(min(a)) if min(a) == max(a) else f"{_money(min(a))}-{_money(max(a))}"
        vs = f"{wr} wins / {ar}"
    return (f"day-{days_elapsed} pace: {cur}, vs {vs} at this point in the prior "
            f"{len(priors)} quarter{'' if len(priors) == 1 else 's'} ({labels})")


def _prior_windows(as_of: date):
    """Current quarter (start, end, label, days_elapsed, fraction) and the
    trailing PRIOR_QUARTERS windows before it, newest first."""
    from utils import get_fiscal_quarter
    cur_start, cur_end, cur_label = get_fiscal_quarter(as_of)
    cur_len = (cur_end - cur_start).days + 1
    days_elapsed = min(max((as_of - cur_start).days + 1, 0), cur_len)
    fraction = days_elapsed / cur_len
    priors = []
    cursor = cur_start
    for _ in range(PRIOR_QUARTERS):
        s, e, lab = get_fiscal_quarter(cursor - timedelta(days=1))
        priors.append((s, e, lab))
        cursor = s
    return (cur_start, cur_end, cur_label, days_elapsed, fraction), priors


def assess_rep_scorecard(sb, as_of: Optional[date] = None) -> Dict[str, Any]:
    from field_semantics import is_incremental_pipeline  # noqa: F401 (kept parallel to others)
    from incremental_arr import incremental_arr
    from loss_concentration import (SALES_PIPELINE, discovery_or_later_stages,
                                    disqualified_stage_ids)
    from supabase_client import select_all
    from utils import get_pipeline_config

    if as_of is None:
        from sdr_utils import today_in_reporting_tz
        as_of = today_in_reporting_tz()

    (cur_start, cur_end, cur_label, days_elapsed, fraction), priors = _prior_windows(as_of)
    cfg = get_pipeline_config()
    qualifying = list(discovery_or_later_stages(cfg))
    discovery = qualifying[0] if qualifying else None
    qualifying_set = set(qualifying)
    disqualified = disqualified_stage_ids(cfg)

    # --- line 1: this quarter's qualified losses, depth + ever-COMMIT/ML ------
    losses = select_all(sb, "deals", columns="deal_id,owner_email,close_date,stage",
                        filters=[("eq", "pipeline_id", SALES_PIPELINE),
                                 ("eq", "deal_status", "lost"),
                                 ("gte", "close_date", cur_start.isoformat()),
                                 ("lte", "close_date", cur_end.isoformat())])
    losses = [d for d in losses if str(d.get("stage")) not in disqualified]
    close_by = {str(d["deal_id"]): str(d.get("close_date"))[:10] for d in losses}
    owner_by = {str(d["deal_id"]): d.get("owner_email") for d in losses}

    snaps: Dict[str, list] = defaultdict(list)
    ids = sorted(close_by)
    for i in range(0, len(ids), 100):
        for s in select_all(sb, "deals_snapshot",
                            columns="deal_id,snapshot_date,stage_id,forecast_category",
                            filters=[("in_", "deal_id", ids[i:i + 100])]):
            snaps[str(s["deal_id"])].append(s)

    depth = defaultdict(lambda: {"qual": 0, "never_past": 0, "ever_cm": 0})
    for did, close in close_by.items():
        rows = [s for s in snaps.get(did, []) if str(s.get("snapshot_date"))[:10] <= close]
        seen = [str(s.get("stage_id")) for s in rows]
        if not any(st in qualifying_set for st in seen):
            continue  # never qualified -> not a qualified loss
        d = depth[owner_by[did]]
        d["qual"] += 1
        if not any(st in qualifying_set and st != discovery for st in seen):
            d["never_past"] += 1
        if any(s.get("forecast_category") in _COMMIT_ML for s in rows):
            d["ever_cm"] += 1

    # --- line 2: win pace, this quarter vs the same point in prior quarters ---
    win_from = priors[-1][0].isoformat() if priors else cur_start.isoformat()
    wins = select_all(sb, "deals", columns="deal_id,owner_email,close_date,new_arr,expansion_arr",
                     filters=[("eq", "pipeline_id", SALES_PIPELINE),
                              ("eq", "deal_status", "won"),
                              ("gte", "close_date", win_from),
                              ("lte", "close_date", cur_end.isoformat())])
    by_owner_wins = defaultdict(list)
    for w in wins:
        by_owner_wins[w.get("owner_email")].append((str(w.get("close_date"))[:10], incremental_arr(w)))

    def to_point(rows, start: date, end: date):
        cutoff = max(round(fraction * ((end - start).days + 1)), 1)
        n = arr = 0
        for cd, a in rows:
            days = (date.fromisoformat(cd) - start).days
            if 0 <= days < cutoff:
                n += 1
                arr += a
        return n, arr

    owners = set(depth) | set(by_owner_wins) | {d.get("owner_email") for d in losses}
    owners.discard(None)
    by_owner = {}
    for owner in owners:
        d = depth.get(owner, {"qual": 0, "never_past": 0, "ever_cm": 0})
        rows = by_owner_wins.get(owner, [])
        cur_n, cur_arr = to_point(rows, cur_start, cur_end)
        prior_list = []
        for s, e, lab in priors:
            if any(s.isoformat() <= cd <= e.isoformat() for cd, _ in rows):  # a win that quarter
                n, arr = to_point(rows, s, e)
                prior_list.append({"label": lab, "wins": n, "arr": arr})
        by_owner[owner] = {
            "qualified_losses": d["qual"], "never_past_discovery": d["never_past"],
            "ever_commit_ml": d["ever_cm"], "loss_depth": loss_depth_line(**{
                "qual": d["qual"], "never_past": d["never_past"], "ever_cm": d["ever_cm"]}),
            "current_wins": cur_n, "current_won_arr": cur_arr, "prior_pace": prior_list,
            "pace": pace_line(days_elapsed, cur_n, cur_arr, prior_list),
        }

    return {
        "status": "ok", "fiscal_quarter": cur_label, "days_elapsed": days_elapsed,
        "by_owner": by_owner,
        "note": ("Per rep, two backward-looking reads next to the loss row: loss_depth (how many "
                 "qualified losses never passed Discovery, and how many were ever COMMIT/Most Likely) "
                 "and pace (wins and incremental ARR closed by this point of the quarter vs the same "
                 f"point in the last {PRIOR_QUARTERS} quarters with a Sales win). Facts, not a verdict."),
    }
