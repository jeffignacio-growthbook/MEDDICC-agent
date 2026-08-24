#!/usr/bin/env python3
"""
Phase 1 acceptance harness (PROGRESSIVE_SCORING_SPEC).

Score Livesport's calls one at a time, accumulate the roll-up after each, and
print the cumulative table — then diff it against the hand-scored target in the
spec. This is the gate: if the per-call scorer does not roughly reproduce the
hand-scored progression, stop and fix the prompt before wiring anything.

Read-only against Supabase + the model; writes nothing to the DB. Needs
ANTHROPIC_API_KEY + SUPABASE_URL + SUPABASE_SERVICE_KEY. Sonnet (generator role),
temperature 0. Env: PHASE1_DEAL_ID (default Livesport 62160567676),
PHASE1_SLUG (default 'livesport' — linkage fallback).
"""
import os
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
for p in ("", "scripts", "api"):
    sys.path.insert(0, str(REPO / p) if p else str(REPO))
try:
    sys.stdout.reconfigure(line_buffering=True)  # CI block-buffers; flush per line
except Exception:
    pass

import call_scorer as cs  # noqa: E402

DEAL_ID = os.getenv("PHASE1_DEAL_ID", "62160567676")
SLUG = os.getenv("PHASE1_SLUG", "livesport")
COMPANY = "Livesport"

# Hand-scored target from the spec (the acceptance reference).
HAND = {
    "dates": ["Jul 15 Demo", "Jul 16 Technical", "Jul 30 Commercials", "Aug 5 Pricing"],
    "final": {"metrics": 8, "economic_buyer": 6, "decision_criteria": 8,
              "decision_process": 8, "pain": 9, "champion": 6, "competition": 8},
    "per_call_total": [33, 36, 50, 53],
}


def _load_calls(sb):
    """Livesport's calls with text. Prefer the linked deal_id; fall back to
    company_slug because calls.deal_id is only set by the manual resolver."""
    from supabase_client import select_all
    cols = "call_id,call_date,summary,title,source,company_slug"
    calls = select_all(sb, "calls", columns=cols, filters=[("eq", "deal_id", str(DEAL_ID))])
    linkage = "deal_id"
    if not calls:
        calls = select_all(sb, "calls", columns=cols, filters=[("ilike", "company_slug", f"%{SLUG}%")])
        linkage = f"company_slug~{SLUG}"
    calls = [c for c in calls if (c.get("call_date") or "")]
    calls.sort(key=lambda c: c["call_date"])
    ids = [c["call_id"] for c in calls]
    tx = {}
    if ids:
        for r in select_all(sb, "call_transcripts",
                            columns="call_id,transcript,transcript_quality,char_count",
                            filters=[("in_", "call_id", ids)]):
            tx[r["call_id"]] = r
    return calls, tx, linkage


def _text_for(call, tx):
    """Prefer a usable transcript; fall back to the call summary. Returns
    (text, source, chars) or (None, None, 0) when neither is scoreable."""
    t = tx.get(call["call_id"])
    if t and (t.get("transcript") or "").strip() and t.get("transcript_quality") in ("full", "partial"):
        txt = t["transcript"].strip()
        return txt, "transcript", len(txt)
    summ = (call.get("summary") or "").strip()
    if summ:
        return summ, "summary", len(summ)
    return None, None, 0


def _fmt(v):
    return "  ·" if v is None else f"{v:>3}"


def main():
    if not os.getenv("ANTHROPIC_API_KEY"):
        print("ANTHROPIC_API_KEY not set — cannot score"); return 2
    try:
        from api.db import get_supabase
        sb = get_supabase()
    except Exception:
        from supabase_client import SupabaseWriter
        sb = SupabaseWriter().client
    from llm_client import LLMClient
    client = LLMClient.from_config("generator")

    calls, tx, linkage = _load_calls(sb)
    print("=" * 78)
    print(f"PHASE 1 — per-call cumulative scoring: {COMPANY} (deal {DEAL_ID})")
    print(f"scorer={cs.SCORER_VERSION}  model={getattr(client, 'model', 'generator')}  "
          f"linkage={linkage}  calls_found={len(calls)}")
    print("=" * 78)
    if not calls:
        print("No calls found for Livesport — cannot run Phase 1."); return 2

    scored = []          # running list for roll_up
    columns = []         # (label, text_source, chars, per_component this-call scores)
    tok_in = tok_out = 0
    for i, call in enumerate(calls, 1):
        text, source, chars = _text_for(call, tx)
        label = f"{call['call_date']}"
        if text is None:
            print(f"[{i}/{len(calls)}] {label}: no transcript or summary — skipped")
            continue
        result = cs.score_call(text, {"company": COMPANY}, client=client)
        tok_in += result["input_tokens"]; tok_out += result["output_tokens"]
        scored.append({"call_id": call["call_id"], "call_date": call["call_date"],
                       "components": result["components"]})
        this = {k: result["components"][k]["score"] for k in cs.COMPONENT_KEYS}
        columns.append((label, source, chars, this))
        rolled = cs.roll_up(scored)
        adv = ",".join(result.get("advanced", [])) or "(none)"
        print(f"[{i}/{len(calls)}] {label}  source={source} ({chars} chars)  "
              f"advanced={adv}  "
              f"this-call total={sum(v for v in this.values() if v is not None)}  "
              f"cumulative/70={cs.rollup_total(rolled)}")

    # Cumulative table: components x calls, each cell = this-call score (· = null).
    print("\n" + "-" * 78)
    print("PER-CALL SCORES (· = null, call said nothing about the component)")
    hdr = "component".ljust(20) + "".join(f"{c[0][:14]:>15}" for c in columns)
    print(hdr)
    for label, key in cs.COMPONENTS:
        row = key.ljust(20) + "".join(f"{_fmt(c[3][key]):>15}" for c in columns)
        print(row)
    tot = "TOTAL /70".ljust(20) + "".join(
        f"{sum(v for v in c[3].values() if v is not None):>15}" for c in columns)
    print(tot)

    # Roll-up (most-recent-non-null) vs the hand-scored final.
    rolled = cs.roll_up(scored)
    print("\n" + "-" * 78)
    print(f"{'component':20}{'rolled':>8}{'hand':>8}{'Δ':>6}   provenance (call the score came from)")
    worst = 0
    for label, key in cs.COMPONENTS:
        got = rolled[key]["score"]
        want = HAND["final"].get(key)
        delta = None if (got is None or want is None) else got - want
        if delta is not None:
            worst = max(worst, abs(delta))
        prov = rolled[key]["call_date"] or "—"
        gs = "·" if got is None else str(got)
        ws = "·" if want is None else str(want)
        ds = "·" if delta is None else f"{delta:+d}"
        print(f"{key:20}{gs:>8}{ws:>8}{ds:>6}   {prov}")
    got_total = cs.rollup_total(rolled)
    print(f"{'TOTAL /70':20}{got_total:>8}{sum(HAND['final'].values()):>8}"
          f"{got_total - sum(HAND['final'].values()):+6d}")

    print(f"\ntokens: {tok_in} in / {tok_out} out")
    print("\n" + "=" * 78)
    print("READING")
    print("=" * 78)
    print(f"largest per-component gap vs hand-scored: ±{worst}")
    if any(c[1] == "summary" for c in columns):
        print("NOTE: at least one call was scored from its SUMMARY, not a full transcript "
              "(transcripts not backfilled for this deal yet). The hand-scored target may "
              "assume transcripts — treat the diff as directional, not exact.")
    if len(columns) != len(HAND["dates"]):
        print(f"NOTE: scored {len(columns)} call(s); the hand-scored table has "
              f"{len(HAND['dates'])}. Some Livesport calls are not in the DB (or unlinked). "
              "Per-call totals are not directly comparable position-by-position.")
    if worst <= 2:
        print("VERDICT: roughly reproduces the hand-scored progression (all components within ±2).")
    else:
        print("VERDICT: does NOT roughly reproduce — at least one component is >2 off. "
              "Per the spec, fix the prompt before going further.")
    print("=" * 78)
    return 0


if __name__ == "__main__":
    sys.exit(main())
