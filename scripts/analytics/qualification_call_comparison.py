#!/usr/bin/env python3
"""
Qualification Phase 2: MEDDICC call scores of Meeting Set deals that went on
to a qualified stage ("progressed") vs deals that did not ("stalled"), from
calls made before the move only.

EXPLORATORY. This is hypothesis-generating, never a finding. Every report
states two caveats: stalled deals are mostly lost, so a gap may be lead fit;
and a score records what a call uncovered, so a high score may mark a deal
that was already moving. "No reliable signal" is a fine and expected result.
The route to a confident answer is a live coaching test measured on the
crossing rate, not more analysis of this cohort.

Standalone and read-only, like qualification_crossing_walk.py: no handler,
no writes, nothing reaches Slack.

Definitions (Sales pipeline 'default', stages as in qualification_crossing_walk):
  milestones   ms_first  = first snapshot at Meeting Set;
               q_first   = first qualified snapshot after ms_first (the crossing);
               prev_d    = the snapshot just before q_first.
               A deal with a qualified row before ms_first is first seen past
               Meeting Set and is in neither cohort.
  progressed   q_first exists. Window [ms_first, min(prev_d, ms_first + 7)].
               Snapshots are weekly, so the crossing is known only to a week;
               a call inside that week may be the qualifying call itself, so
               the window stops at the previous snapshot (anti-leakage).
  stalled      never seen qualified, ms_first <= latest snapshot - 21 days
               (P75 of days to cross). Window [ms_first, ms_first + 7]: the
               same observation time as progressed.
  still open   View 2 keeps only stalled deals whose deal_status is active
               (stalled deals are mostly lost; see caveat 1).
  calls        call_scores rows with text_source 'transcript' (as
               assess_rep_coaching), call_date inside the window, both ends
               inclusive. A deal with no such call is in neither cohort.
  per deal     each component's mean over its window calls (nulls skipped).

Controls and validation:
  strata       segment x size band (0/unknown, <50k, >=50k of new + expansion
               ARR, else deal_value) x rep tenure at ms_first (<180 days,
               >=180 days, unknown; tenure = days since the owner's first
               deal create_date, a lower bound for owners whose first deal is
               the CRM import date).
  effect       within-stratum mean difference (progressed - stalled),
               weighted by n1*n0/(n1+n0); strata holding one cohort only
               contribute nothing. p from a permutation of labels within
               strata. Cohen's d and a pooled Mann-Whitney p for reference.
  holdout      sha256(deal_id) % 3 == 0 (a fixed third, set before looking).
  directional  train stratified p < 0.05 and |d| >= 0.3, and the holdout d
               has the same sign with |d| >= 0.2. Fixed in advance; not tuned.

    SUPABASE_URL=... SUPABASE_SERVICE_KEY=... \\
        python scripts/analytics/qualification_call_comparison.py
    python scripts/analytics/qualification_call_comparison.py --input data.json

--input takes the shape of tests/fixtures/qualification_call_comparison_*.json:
{"latest_snapshot", "snapshots": [[deal_id, snapshot_date, stage_id,
pipeline_id], ...], "deals": [{deal_id, deal_status, segment, new_arr,
expansion_arr, deal_value, owner_email}], "owners_first_deal": {email: date},
"calls": [[deal_id, call_id, call_date, <7 scores in COMPONENTS order>,
"comma,separated,evidence,keys"], ...]}. Calls may also be dicts, and may
carry "evidence" ({component: text}) for example quotes.
"""
import argparse
import hashlib
import json
import math
import random
import statistics
import sys
from collections import Counter, defaultdict
from datetime import date, timedelta
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO))
sys.path.insert(0, str(REPO / "scripts"))
sys.path.insert(0, str(Path(__file__).resolve().parent))

from api.incremental_arr import incremental_arr  # noqa: E402
from qualification_crossing_walk import MEETING_SET, PIPELINE, QUALIFIED_STAGES  # noqa: E402

COMPONENTS = ("pain", "metrics", "champion", "economic_buyer",
              "decision_criteria", "decision_process", "competition")
WINDOW_DAYS = 7
STALL_DAYS = 21
TENURE_DAYS = 180
SIZE_SPLIT = 50000
N_PERM = 2000
SEED = 20260924
TRAIN_P, TRAIN_D, HOLDOUT_D = 0.05, 0.3, 0.2
SNAP_KEYS = ("deal_id", "snapshot_date", "stage_id", "pipeline_id")
QUOTE_CHARS = 200


def _d(v):
    return date.fromisoformat(str(v)[:10]) if v else None


# ------------------------------------------------------------------ input

def load_input(data):
    """Normalise fixture/--input JSON (lists or dicts) to dicts."""
    snaps = [dict(zip(SNAP_KEYS, s)) if isinstance(s, list) else s for s in data["snapshots"]]
    calls = []
    for c in data["calls"]:
        if isinstance(c, list):
            row = {"deal_id": str(c[0]), "call_id": c[1], "call_date": c[2]}
            row.update(zip(COMPONENTS, c[3:3 + len(COMPONENTS)]))
            keys = c[3 + len(COMPONENTS)] if len(c) > 3 + len(COMPONENTS) else ""
            row["evidence_keys"] = [k for k in keys.split(",") if k] if isinstance(keys, str) else list(keys)
            c = row
        calls.append(c)
    latest = _d(data.get("latest_snapshot")) or max(_d(s["snapshot_date"]) for s in snaps)
    return {"latest": latest, "snapshots": snaps, "calls": calls, "deals": data.get("deals") or [],
            "owners_first_deal": data.get("owners_first_deal") or {}}


def compress_snapshots(snapshots):
    """Keep the first and last row of every stage run per deal: every
    milestone survives (tests prove it), a fraction of the rows."""
    by = defaultdict(list)
    for s in snapshots:
        by[str(s["deal_id"])].append(s)
    out = []
    for _, rs in sorted(by.items()):
        rs = sorted(rs, key=lambda s: str(s["snapshot_date"]))
        st = [s.get("stage_id") for s in rs]
        for k, s in enumerate(rs):
            if k == 0 or k == len(rs) - 1 or st[k] != st[k - 1] or st[k] != st[k + 1]:
                out.append(s)
    return out


# ------------------------------------------------------- milestones/cohorts

def deal_milestones(snapshots, qualified=QUALIFIED_STAGES):
    qualified = set(qualified)
    by = defaultdict(list)
    for s in snapshots:
        if str(s.get("pipeline_id")) == PIPELINE:
            by[str(s["deal_id"])].append(s)
    out = {}
    for deal_id, rs in by.items():
        rs.sort(key=lambda s: str(s["snapshot_date"]))
        stages = [str(s.get("stage_id") or "") for s in rs]
        if MEETING_SET not in stages:
            continue
        i_ms = stages.index(MEETING_SET)
        after = [j for j in range(i_ms + 1, len(stages)) if stages[j] in qualified]
        j = after[0] if after else None
        out[deal_id] = {
            "ms_first": _d(rs[i_ms]["snapshot_date"]),
            "q_first": _d(rs[j]["snapshot_date"]) if j is not None else None,
            "prev_d": _d(rs[j - 1]["snapshot_date"]) if j is not None else None,
            "qualified_before_ms": any(st in qualified for st in stages[:i_ms]),
        }
    return out


def build_cohorts(milestones, latest, statuses):
    """deal_id -> {cohort, start, end, still_open}; excluded deals absent."""
    out = {}
    for deal_id, m in milestones.items():
        if m["qualified_before_ms"]:
            continue
        start = m["ms_first"]
        cap = start + timedelta(days=WINDOW_DAYS)
        if m["q_first"]:
            out[deal_id] = {"cohort": "progressed", "start": start,
                            "end": min(m["prev_d"], cap), "still_open": False}
        elif start <= latest - timedelta(days=STALL_DAYS):
            out[deal_id] = {"cohort": "stalled", "start": start, "end": cap,
                            "still_open": str(statuses.get(deal_id) or "").lower() == "active"}
    return out


def window_calls(calls, cohorts):
    by = defaultdict(list)
    for c in calls:
        w = cohorts.get(str(c["deal_id"]))
        d = _d(c.get("call_date"))
        if w and d and w["start"] <= d <= w["end"]:
            by[str(c["deal_id"])].append(c)
    for v in by.values():
        v.sort(key=lambda c: (str(c["call_date"]), str(c["call_id"])))
    return dict(by)


# ------------------------------------------------------------------ strata

def _segment(d):
    s = str(d.get("segment") or "").strip()
    return "unknown" if not s or s.lower() == "unknown" else s


def _size_band(d):
    amt = incremental_arr(d) or d.get("deal_value")   # null stays null: no 0-fill
    if not amt:
        return "0/unknown"
    return "<50k" if amt < SIZE_SPLIT else ">=50k"


def _tenure_band(d, owners, ms_first):
    first = _d(owners.get(d.get("owner_email") or ""))
    if not d.get("owner_email") or not first:
        return "unknown"
    return "<180d" if (ms_first - first).days < TENURE_DAYS else ">=180d"


# ------------------------------------------------------------------- stats

def holdout(deal_id):
    return int(hashlib.sha256(str(deal_id).encode()).hexdigest(), 16) % 3 == 0


def _phi(z):
    return 0.5 * (1 + math.erf(z / math.sqrt(2)))


def mann_whitney(a, b):
    """U for a, two-sided p (normal approximation, tie-corrected, continuity)."""
    n1, n2 = len(a), len(b)
    if not n1 or not n2:
        return None, None
    pooled = sorted((v, g) for g, xs in ((0, a), (1, b)) for v in xs)
    i = 0
    rank_sum_a, ties = 0.0, 0.0
    while i < len(pooled):
        j = i
        while j < len(pooled) and pooled[j][0] == pooled[i][0]:
            j += 1
        r = (i + j + 1) / 2
        t = j - i
        ties += t ** 3 - t
        rank_sum_a += r * sum(1 for k in range(i, j) if pooled[k][1] == 0)
        i = j
    u = rank_sum_a - n1 * (n1 + 1) / 2
    n = n1 + n2
    var = n1 * n2 / 12 * ((n + 1) - ties / (n * (n - 1))) if n > 1 else 0
    if var <= 0:
        return u, 1.0
    z = (abs(u - n1 * n2 / 2) - 0.5) / math.sqrt(var)
    return u, min(1.0, 2 * (1 - _phi(max(z, 0))))


def cohens_d(a, b):
    if len(a) < 2 or len(b) < 2:
        return None
    va, vb = statistics.variance(a), statistics.variance(b)
    sp = math.sqrt(((len(a) - 1) * va + (len(b) - 1) * vb) / (len(a) + len(b) - 2))
    return 0.0 if sp == 0 else (statistics.mean(a) - statistics.mean(b)) / sp


def _strat_stat(groups):
    num = den = 0.0
    for vals, labs in groups:
        g1 = [v for v, lab in zip(vals, labs) if lab]
        g0 = [v for v, lab in zip(vals, labs) if not lab]
        w = len(g1) * len(g0) / (len(g1) + len(g0))
        num += w * (statistics.mean(g1) - statistics.mean(g0))
        den += w
    return num / den


def stratified_permutation(values, labels, strata, n_perm=N_PERM, seed=SEED):
    """Within-stratum mean difference (label 1 - label 0) and its two-sided
    permutation p (labels shuffled within strata). Returns (stat, p,
    deals in strata holding both labels)."""
    by = defaultdict(lambda: ([], []))
    for v, lab, s in zip(values, labels, strata):
        by[s][0].append(v)
        by[s][1].append(lab)
    groups = [(v, lab) for v, lab in by.values() if 0 < sum(lab) < len(lab)]
    if not groups:
        return 0.0, 1.0, 0
    obs = _strat_stat(groups)
    rnd = random.Random(seed)
    hits = 0
    for _ in range(n_perm):
        perm = []
        for v, lab in groups:
            lab = lab[:]
            rnd.shuffle(lab)
            perm.append((v, lab))
        if abs(_strat_stat(perm)) >= abs(obs) - 1e-12:
            hits += 1
    return round(obs, 10), (hits + 1) / (n_perm + 1), sum(len(v) for v, _ in groups)


# ---------------------------------------------------------------- analysis

def _split_stats(rows, comp, n_perm):
    rows = [r for r in rows if r["scores"].get(comp) is not None]
    prog = [r["scores"][comp] for r in rows if r["label"]]
    stall = [r["scores"][comp] for r in rows if not r["label"]]
    stat, p, n_inf = stratified_permutation([r["scores"][comp] for r in rows],
                                            [r["label"] for r in rows],
                                            [r["stratum"] for r in rows], n_perm=n_perm)
    return {"n_prog": len(prog), "n_stall": len(stall),
            "mean_prog": statistics.mean(prog) if prog else None,
            "mean_stall": statistics.mean(stall) if stall else None,
            "d": cohens_d(prog, stall), "mw_p": mann_whitney(prog, stall)[1],
            "strat_diff": stat, "p": p, "n_informative": n_inf}


def _view(rows, n_perm):
    train = [r for r in rows if not r["holdout"]]
    test = [r for r in rows if r["holdout"]]
    comps, directional = {}, []
    for comp in COMPONENTS:
        tr, ho = _split_stats(train, comp, n_perm), _split_stats(test, comp, n_perm)
        ok = (tr["d"] is not None and ho["d"] is not None and tr["p"] < TRAIN_P
              and abs(tr["d"]) >= TRAIN_D and abs(ho["d"]) >= HOLDOUT_D
              and (tr["d"] > 0) == (ho["d"] > 0))
        ev = {}
        for lab, name in ((1, "progressed"), (0, "stalled")):
            calls = [c for r in rows if r["label"] == lab for c in r["calls"]]
            ev[name] = (sum(1 for c in calls if comp in (c.get("evidence_keys") or [])), len(calls))
        comps[comp] = {"train": tr, "holdout": ho, "directional": ok, "evidence": ev}
        if ok:
            directional.append(comp)
    return {"n_progressed": sum(1 for r in rows if r["label"]),
            "n_stalled": sum(1 for r in rows if not r["label"]),
            "n_holdout": len(test), "components": comps, "directional": directional,
            "rows": rows}


def analyse(data, n_perm=N_PERM):
    deals = {str(d["deal_id"]): d for d in data["deals"]}
    statuses = {k: d.get("deal_status") for k, d in deals.items()}
    ms = deal_milestones(data["snapshots"])
    cohorts = build_cohorts(ms, data["latest"], statuses)
    wc = window_calls(data["calls"], cohorts)
    rows = []
    for deal_id, calls in sorted(wc.items()):
        co = cohorts[deal_id]
        d = deals.get(deal_id, {})
        scores = {}
        for comp in COMPONENTS:
            v = [c[comp] for c in calls if c.get(comp) is not None]
            scores[comp] = statistics.mean(v) if v else None
        rows.append({"deal_id": deal_id, "label": 1 if co["cohort"] == "progressed" else 0,
                     "still_open": co["still_open"], "status": d.get("deal_status"),
                     "holdout": holdout(deal_id), "calls": calls, "scores": scores,
                     "stratum": (_segment(d), _size_band(d),
                                 _tenure_band(d, data["owners_first_deal"], co["start"]))})
    prog = [r for r in rows if r["label"]]
    stall = [r for r in rows if not r["label"]]
    return {
        "latest": data["latest"].isoformat(),
        "cohorts": {"progressed": len(prog), "progressed_calls": sum(len(r["calls"]) for r in prog),
                    "stalled": len(stall), "stalled_calls": sum(len(r["calls"]) for r in stall),
                    "stalled_still_open": sum(1 for r in stall if r["still_open"]),
                    "stalled_status": dict(Counter(str(r["status"]) for r in stall)),
                    "progressed_status": dict(Counter(str(r["status"]) for r in prog))},
        "views": {"all_stalled": _view(rows, n_perm),
                  "still_open_stalled": _view([r for r in rows if r["label"] or r["still_open"]], n_perm)},
    }


# ------------------------------------------------------------------ report

def _f(v, nd=2):
    return "  n/a" if v is None else f"{v:.{nd}f}"


def _mix(rows, idx):
    c = Counter(r["stratum"][idx] for r in rows)
    return ", ".join(f"{k} {v}" for k, v in sorted(c.items()))


def _quotes(view, comp):
    """Up to two short evidence quotes per cohort, highest-scored progressed
    and lowest-scored stalled, when the input carried evidence text."""
    out = []
    for lab, name, rev in ((1, "progressed", True), (0, "stalled", False)):
        calls = [c for r in view["rows"] if r["label"] == lab for c in r["calls"]
                 if (c.get("evidence") or {}).get(comp) and c.get(comp) is not None]
        calls.sort(key=lambda c: c[comp], reverse=rev)
        for c in calls[:2]:
            q = " ".join(str(c["evidence"][comp]).split())
            q = q if len(q) <= QUOTE_CHARS else q[:QUOTE_CHARS - 3] + "..."
            out.append(f"     {name:<10} score {c[comp]}  {c['call_date']}  \"{q}\"")
    return out


def _view_block(title, v, n_perm):
    out = [title, f"   {v['n_progressed']} progressed vs {v['n_stalled']} stalled deals "
                  f"({v['n_holdout']} of them in the held-out third).",
           "   component          train N p/s  mean p  mean s  within-strata diff  d      strata p"
           "   holdout N p/s  d      evidence present p / s"]
    for comp in COMPONENTS:
        c = v["components"][comp]
        tr, ho = c["train"], c["holdout"]
        ep, es = c["evidence"]["progressed"], c["evidence"]["stalled"]
        out.append(f"   {comp:<18} {tr['n_prog']:>4}/{tr['n_stall']:<4}   {_f(tr['mean_prog'])}  "
                   f"{_f(tr['mean_stall'])}  {_f(tr['strat_diff']):>7} (N {tr['n_informative']:>3})  "
                   f"{_f(tr['d']):>5}  {_f(tr['p'], 3):>6}     {ho['n_prog']:>4}/{ho['n_stall']:<4}     "
                   f"{_f(ho['d']):>5}  {ep[0]}/{ep[1]} calls / {es[0]}/{es[1]} calls"
                   + ("   DIRECTIONAL" if c["directional"] else ""))
    if not v["directional"]:
        out.append("   No reliable signal found in this view: no component met the fixed rule on "
                   "the training deals and held its direction on the held-out third.")
    else:
        for comp in v["directional"]:
            tr, ho = v["components"][comp]["train"], v["components"][comp]["holdout"]
            hi = "higher" if tr["d"] > 0 else "lower"
            out.append(f"   Directional, not confirmed: progressed deals' pre-move calls scored {hi} on "
                       f"{comp} (train d {_f(tr['d'])}, strata p {_f(tr['p'], 3)}; held-out d "
                       f"{_f(ho['d'])}). A pattern to test, not an explanation.")
            q = _quotes(v, comp)
            out.append("   Example evidence (truncated):" if q else
                       "   Example evidence: none in this input (the live query carries it).")
            out.extend(q)
    return out


def report(result, n_perm=N_PERM):
    co = result["cohorts"]
    lost = co["stalled_status"].get("lost", 0)
    v1, v2 = result["views"]["all_stalled"], result["views"]["still_open_stalled"]
    out = [
        "Qualification Phase 2: MEDDICC scores on pre-move calls, Meeting Set deals that progressed",
        f"vs deals that stalled. Read-only. Latest snapshot {result['latest']}.",
        "",
        "EXPLORATORY: hypothesis-generating only. Nothing below shows that any MEDDICC component",
        "moves a deal to a qualified stage; at most it points at something worth testing. 'No",
        "reliable signal' is a fine and expected outcome at these sample sizes.",
        f"  Caveat 1: {lost} of the {co['stalled']} stalled deals are lost. A gap may reflect lead fit",
        "  (the deal was never a real opportunity) rather than anything done on the call. View 2",
        "  (still-open stalled deals only) narrows this but does not remove it.",
        "  Caveat 2: a score records what the call uncovered. A high score may mark a deal that was",
        "  already moving, not a rep behaviour that moved it.",
        "",
        f"Cohorts: {co['progressed']} progressed ({co['progressed_calls']} calls), {co['stalled']} stalled "
        f"({co['stalled_calls']} calls), of which {co['stalled_still_open']} still open.",
        f"  Progressed status today: {co['progressed_status']}; stalled: {co['stalled_status']}.",
        f"  Calls: transcript-scored, from the first Meeting Set snapshot to {WINDOW_DAYS} days after it,",
        "  and for progressed deals no later than the snapshot before the crossing. Stalled: never",
        f"  qualified, at least {STALL_DAYS} days since first Meeting Set.",
        "  Controls: segment x size band x rep tenure strata; the effect is the within-stratum",
        "  difference, strata holding one cohort only add nothing (N beside it = deals compared).",
        f"  Rule (fixed in advance): train strata p < {TRAIN_P} and |d| >= {TRAIN_D}, held-out third",
        f"  same sign with |d| >= {HOLDOUT_D}. {len(COMPONENTS)} components x 2 views: at p < 0.05 about",
        "  one pass in twenty is expected by chance alone; the held-out third is the check.",
        f"  Segment mix: {_mix(v1['rows'], 0)}.",
        f"  Size mix:    {_mix(v1['rows'], 1)}.",
        f"  Tenure mix:  {_mix(v1['rows'], 2)} (tenure is a lower bound for owners whose first",
        "  deal is the CRM import date).",
        "",
    ]
    out += _view_block("View 1: progressed vs all stalled", v1, n_perm) + [""]
    out += _view_block("View 2: progressed vs still-open stalled only", v2, n_perm) + [""]
    cands = sorted(set(v1["directional"]) | set(v2["directional"]))
    out.append("Next step (the real path to a confident answer):")
    if cands:
        out += [f"  Pick one candidate ({', '.join(cands)}) and turn it into one concrete coaching change,",
                "  e.g. a specific question reps ask on every first Meeting Set call. Roll it out, then",
                "  track the Meeting Set -> qualified crossing rate week by week against the weeks before.",
                "  That live test answers the question far sooner than waiting on this cohort to grow."]
    else:
        out += ["  No component stands out as a candidate. If a coaching change is tried anyway, the way",
                "  to a confident answer is the same: one concrete change, rolled out, with the Meeting",
                "  Set -> qualified crossing rate tracked week by week against the weeks before. That is",
                "  faster than waiting on this cohort to grow."]
    return "\n".join(out)


# ------------------------------------------------------------------- fetch

def _fetch():
    import os
    from supabase import create_client
    from supabase_client import select_all
    sb = create_client(os.environ["SUPABASE_URL"], os.environ["SUPABASE_SERVICE_KEY"])
    snaps = select_all(sb, "deals_snapshot", columns=",".join(SNAP_KEYS),
                       filters=[("eq", "pipeline_id", PIPELINE)])
    ms_ids = sorted({str(s["deal_id"]) for s in snaps if str(s.get("stage_id")) == MEETING_SET})
    cols = "deal_id,call_id,call_date,evidence," + ",".join(f"{c}_score" for c in COMPONENTS)
    calls, deals = [], []
    for i in range(0, len(ms_ids), 100):
        chunk = ms_ids[i:i + 100]
        for r in select_all(sb, "call_scores", columns=cols,
                            filters=[("eq", "text_source", "transcript"), ("in_", "deal_id", chunk)]):
            ev = r.get("evidence")
            if isinstance(ev, str):
                try:
                    ev = json.loads(ev)
                except ValueError:
                    ev = {}
            ev = ev if isinstance(ev, dict) else {}
            row = {"deal_id": str(r["deal_id"]), "call_id": r["call_id"], "call_date": r["call_date"],
                   "evidence": ev, "evidence_keys": [k for k, v in ev.items() if str(v or "").strip()]}
            row.update({c: r.get(f"{c}_score") for c in COMPONENTS})
            calls.append(row)
        deals += sb.table("deals").select(
            "deal_id,deal_status,segment,new_arr,expansion_arr,deal_value,owner_email").in_(
            "deal_id", chunk).execute().data or []
    owners = sorted({d["owner_email"] for d in deals if d.get("owner_email")})
    first = {}
    for o in owners:
        r = sb.table("deals").select("create_date").eq("owner_email", o).order(
            "create_date").limit(1).execute().data or []
        if r and r[0].get("create_date"):
            first[o] = str(r[0]["create_date"])[:10]
    return {"snapshots": snaps, "calls": calls, "deals": deals, "owners_first_deal": first}


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--input", help="data as JSON instead of querying Supabase")
    args = ap.parse_args()
    raw = json.loads(Path(args.input).read_text()) if args.input else _fetch()
    print(report(analyse(load_input(raw))))


if __name__ == "__main__":
    main()
