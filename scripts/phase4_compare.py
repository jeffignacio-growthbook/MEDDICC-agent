#!/usr/bin/env python3
"""
Phase 4 comparison (PROGRESSIVE_SCORING_SPEC): progressive roll-up vs batch score,
side by side, for a handful of deals. REPORT BOTH — do not declare a winner.

Read-only. No scoring happens here: progressive scores come from call_scores
(backfilled in Phase 3), batch scores from the latest analyses row per deal
(run #39's pinned set). Needs SUPABASE_URL + SUPABASE_SERVICE_KEY only.

The roll-up is most-recent-non-null per component (call_scorer.roll_up over the
stored per-call deltas), with provenance (which call set each score). Bands are
the surfaced signal: red 0-3, yellow 4-6, green 7-10.

Judged on "reads better", not just "more stable": the table shows both scores,
both bands, and — for the named deals — the progressive evidence per component,
so a human can decide whether progressive matches what someone who knows the
deal would say. LiveSport's champion is the touchstone (batch gave 2/3/5 on
different nights; what does progressive say, and does it match "Tomas coordinates
procurement without advocating"?).

Env: PHASE4_NAMED (default 'livesport,skyscanner,ikea'), PHASE4_RANDOM (default 5).
"""
import os
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
for p in ("", "scripts", "api"):
    sys.path.insert(0, str(REPO / p) if p else str(REPO))
try:
    sys.stdout.reconfigure(line_buffering=True)
except Exception:
    pass

import call_scorer as cs  # noqa: E402

NAMED = [s.strip() for s in os.getenv("PHASE4_NAMED", "livesport,skyscanner,ikea").split(",") if s.strip()]
N_RANDOM = int(os.getenv("PHASE4_RANDOM", "5"))

_SCORE_COLS = [f"{k}_score" for k in cs.COMPONENT_KEYS]


def band(score):
    if score is None:
        return "—"
    if score <= 3:
        return "red"
    if score <= 6:
        return "yellow"
    return "green"


def _chunked(seq, n):
    for i in range(0, len(seq), n):
        yield seq[i:i + n]


def _load_call_scores(sb, deal_ids):
    """call_scores rows grouped by deal_id, oldest first."""
    from supabase_client import select_all
    from collections import defaultdict
    cols = "call_id,deal_id,call_date," + ",".join(_SCORE_COLS) + ",evidence"
    by_deal = defaultdict(list)
    for chunk in _chunked(list(deal_ids), 100):
        for r in select_all(sb, "call_scores", columns=cols,
                            filters=[("in_", "deal_id", chunk)]):
            by_deal[str(r["deal_id"])].append(r)
    for did in by_deal:
        by_deal[did].sort(key=lambda r: (r.get("call_date") or ""))
    return by_deal


def _row_to_components(row):
    import json
    ev = {}
    if row.get("evidence"):
        try:
            ev = json.loads(row["evidence"]) if isinstance(row["evidence"], str) else row["evidence"]
        except Exception:
            ev = {}
    return {k: {"score": row.get(f"{k}_score"), "evidence": ev.get(k)} for k in cs.COMPONENT_KEYS}


def _progressive(rows):
    """Roll up a deal's call_scores rows → {key:{score,evidence,call_id,call_date}}."""
    scored = [{"call_id": r["call_id"], "call_date": r.get("call_date"),
               "components": _row_to_components(r)} for r in rows]
    return cs.roll_up(scored)


def _latest_batch(sb, deal_id):
    """Latest analyses row (batch score of record) for a deal."""
    from supabase_client import select_all
    cols = "deal_id,analyzed_at,overall_score,status,passed," + ",".join(_SCORE_COLS)
    rows = select_all(sb, "analyses", columns=cols, filters=[("eq", "deal_id", str(deal_id))])
    if not rows:
        return None
    rows.sort(key=lambda r: (r.get("analyzed_at") or ""))
    return rows[-1]


def _resolve_named(sb, tokens):
    """Resolve company-name tokens to (deal_id, company_name) via the deals table."""
    from supabase_client import select_all
    out = []
    for tok in tokens:
        rows = select_all(sb, "deals", columns="deal_id,company_name,company_slug",
                          filters=[("ilike", "company_slug", f"%{tok}%")])
        if not rows:
            rows = select_all(sb, "deals", columns="deal_id,company_name,company_slug",
                              filters=[("ilike", "company_name", f"%{tok}%")])
        if rows:
            out.append((str(rows[0]["deal_id"]), rows[0].get("company_name") or tok))
        else:
            print(f"  (could not resolve named deal '{tok}')")
    return out


def _pick_random(sb, exclude, n):
    """n deals (excluding `exclude`) with the most call_scores rows — richest
    progressions, deterministic (no RNG)."""
    from supabase_client import select_all
    from collections import Counter
    rows = select_all(sb, "call_scores", columns="deal_id")
    cnt = Counter(str(r["deal_id"]) for r in rows if r.get("deal_id"))
    names = {str(d["deal_id"]): d.get("company_name") for d in
             select_all(sb, "deals", columns="deal_id,company_name")}
    ranked = [did for did, _ in cnt.most_common() if did not in exclude]
    return [(did, names.get(did) or did) for did in ranked[:n]]


def _print_deal(company, deal_id, prog, batch, rows, show_evidence):
    ncalls = len(rows)
    print("\n" + "=" * 78)
    print(f"{company}  (deal {deal_id})  — {ncalls} scored calls")
    print("=" * 78)
    print(f"{'component':20}{'progressive':>16}{'batch':>14}   note")
    p_tot = b_tot = 0
    for label, key in cs.COMPONENTS:
        ps = prog[key]["score"]
        bs = batch.get(f"{key}_score") if batch else None
        p_tot += ps or 0
        b_tot += bs or 0
        pcell = f"{('·' if ps is None else ps)}/{band(ps)}"
        bcell = f"{('·' if bs is None else bs)}/{band(bs)}"
        note = ""
        if ps is not None and bs is not None:
            if band(ps) != band(bs):
                note = f"BAND DIFF ({band(bs)}→{band(ps)})"
            elif ps != bs:
                note = f"Δ{ps - bs:+d}"
        print(f"{label:20}{pcell:>16}{bcell:>14}   {note}")
    b_overall = batch.get("overall_score") if batch else None
    print(f"{'TOTAL /70':20}{p_tot:>16}{(b_overall if b_overall is not None else b_tot):>14}")
    if batch:
        print(f"  batch status={batch.get('status')} passed={batch.get('passed')}")
    if show_evidence:
        print("  progressive evidence (per component, and the call it came from):")
        for label, key in cs.COMPONENTS:
            c = prog[key]
            if c["score"] is not None:
                ev = (c.get("evidence") or "").replace("\n", " ")
                if len(ev) > 160:
                    ev = ev[:160] + "…"
                print(f"    {label} = {c['score']} [{c.get('call_date')}]: {ev}")


def main():
    try:
        from api.db import get_supabase
        sb = get_supabase()
    except Exception:
        from supabase_client import SupabaseWriter
        sb = SupabaseWriter().client

    named = _resolve_named(sb, NAMED)
    exclude = {did for did, _ in named}
    rnd = _pick_random(sb, exclude, N_RANDOM)
    targets = named + rnd
    named_ids = {did for did, _ in named}

    print("=" * 78)
    print("PHASE 4 — progressive roll-up vs batch score (report both, do not decide)")
    print(f"named={[c for _, c in named]}  random(most-calls)={[c for _, c in rnd]}")
    print("bands: red 0-3 / yellow 4-6 / green 7-10")
    print("=" * 78)

    all_ids = [did for did, _ in targets]
    cs_by_deal = _load_call_scores(sb, all_ids)

    band_diffs = 0
    comps_compared = 0
    for did, company in targets:
        rows = cs_by_deal.get(did, [])
        if not rows:
            print(f"\n{company} ({did}): no call_scores rows — skipped")
            continue
        prog = _progressive(rows)
        batch = _latest_batch(sb, did)
        _print_deal(company, did, prog, batch, rows, show_evidence=(did in named_ids))
        if batch:
            for key in cs.COMPONENT_KEYS:
                ps, bs = prog[key]["score"], batch.get(f"{key}_score")
                if ps is not None and bs is not None:
                    comps_compared += 1
                    if band(ps) != band(bs):
                        band_diffs += 1

    print("\n" + "=" * 78)
    print("SUMMARY")
    print("=" * 78)
    if comps_compared:
        print(f"components with both scores: {comps_compared}; band differs on "
              f"{band_diffs} ({band_diffs/comps_compared*100:.0f}%)")
    print("This is a side-by-side for review, not a verdict. Judge whether the\n"
          "progressive read matches what someone who knows the deal would say —\n"
          "LiveSport champion is the touchstone.")
    print("=" * 78)
    return 0


if __name__ == "__main__":
    main()
