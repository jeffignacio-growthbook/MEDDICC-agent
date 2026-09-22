#!/usr/bin/env python3
"""
One-off, READ-ONLY audit: the post-8/21 call transcript gap.

Question: for calls dated after 2026-08-21, is call_transcripts.transcript
missing while the calls row (metadata) is present, and is it Apollo-only?

Distinguishes the two ways a transcript can be "missing" — never conflated:
  - ABSENT: calls row exists, NO call_transcripts row at all (a LEFT JOIN
            reads this as NULL transcript)
  - NULL:   a call_transcripts row exists with transcript IS NULL
            (transcript_quality='unavailable' + a reason)
  - TEXT:   a call_transcripts row with transcript text

Breaks out by source x call_date window, by source x ingest date
(calls.created_at), and per call_date day after the cutoff. Optionally
spot-checks a few ABSENT Apollo calls against the live Apollo API
(GET /conversations/{id}, read-only) to confirm the text exists at the
source, i.e. the gap is ours, not Apollo's.

No writes anywhere.
"""
import os
import sys
from collections import Counter, defaultdict
from datetime import date
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
for p in ("", "scripts", "api"):
    sys.path.insert(0, str(REPO / p) if p else str(REPO))

from supabase import create_client  # noqa: E402
from supabase_client import select_all  # noqa: E402

CUTOFF = date(2026, 8, 21)
SPOT_CHECK_N = int(os.getenv("SPOT_CHECK_N", "5"))


def _d(v):
    try:
        return date.fromisoformat(str(v)[:10])
    except Exception:
        return None


def _pct(a, b):
    return f"{(100.0 * a / b):.1f}%" if b else "n/a"


def _row(label, c):
    total = c["TEXT"] + c["NULL"] + c["ABSENT"]
    miss = c["NULL"] + c["ABSENT"]
    print(f"  {label:34} total={total:5}  text={c['TEXT']:5}  "
          f"null_row={c['NULL']:4}  absent={c['ABSENT']:5}  "
          f"missing={miss:5} ({_pct(miss, total)})")


def main():
    sb = create_client(os.environ["SUPABASE_URL"], os.environ["SUPABASE_SERVICE_KEY"])

    calls = select_all(sb, "calls",
                       columns="call_id,source,call_date,created_at,call_intent,is_internal,deal_id,title")
    trs = select_all(sb, "call_transcripts",
                     columns="call_id,source,transcript_quality,unavailable_reason,char_count,fetched_at")
    tmap = {r["call_id"]: r for r in trs}
    print(f"calls rows: {len(calls)}   call_transcripts rows: {len(trs)}")
    call_ids = {c["call_id"] for c in calls}
    orphan = [r for r in trs if r["call_id"] not in call_ids]
    print(f"call_transcripts rows with no calls row: {len(orphan)}")

    def state(cid):
        t = tmap.get(cid)
        if t is None:
            return "ABSENT"
        return "TEXT" if t.get("transcript_quality") != "unavailable" else "NULL"

    # ── 1. source x call_date window ────────────────────────────────────
    print("\n" + "=" * 100)
    print(f"1. BY SOURCE x CALL_DATE WINDOW (cutoff: call_date > {CUTOFF})")
    print("=" * 100)
    by = defaultdict(Counter)
    by_prospect = defaultdict(Counter)
    for c in calls:
        cd = _d(c.get("call_date"))
        win = "no_date" if cd is None else ("after" if cd > CUTOFF else "on_or_before")
        src = (c.get("source") or "?").lower()
        s = state(c["call_id"])
        by[(src, win)][s] += 1
        if (c.get("call_intent") or "") != "skip" and not c.get("is_internal"):
            by_prospect[(src, win)][s] += 1
    for k in sorted(by):
        _row(f"{k[0]} / {k[1]}", by[k])
    print("\n  -- same, excluding call_intent='skip' and is_internal (what coaching reads) --")
    for k in sorted(by_prospect):
        _row(f"{k[0]} / {k[1]}", by_prospect[k])

    # ── 2. source x ingest date (calls.created_at) ──────────────────────
    print("\n" + "=" * 100)
    print("2. BY SOURCE x INGEST DATE (calls.created_at, UTC day) — calls with call_date > cutoff")
    print("=" * 100)
    ing = defaultdict(Counter)
    for c in calls:
        cd = _d(c.get("call_date"))
        if cd is None or cd <= CUTOFF:
            continue
        ing[((c.get("source") or "?").lower(), str(c.get("created_at") or "")[:10])][state(c["call_id"])] += 1
    for k in sorted(ing, key=lambda k: (k[1], k[0])):
        _row(f"ingested {k[1]} {k[0]}", ing[k])

    # ── 3. per call_date day after cutoff ───────────────────────────────
    print("\n" + "=" * 100)
    print("3. PER CALL_DATE DAY (call_date > cutoff), apollo vs fireflies")
    print("=" * 100)
    day = defaultdict(Counter)
    for c in calls:
        cd = _d(c.get("call_date"))
        if cd is None or cd <= CUTOFF:
            continue
        day[(str(cd), (c.get("source") or "?").lower())][state(c["call_id"])] += 1
    for k in sorted(day):
        _row(f"{k[0]} {k[1]}", day[k])

    # ── 4. reasons on NULL rows after cutoff ────────────────────────────
    print("\n" + "=" * 100)
    print("4. unavailable_reason on NULL rows (call_date > cutoff)")
    print("=" * 100)
    reasons = Counter()
    fetched = Counter()
    for c in calls:
        cd = _d(c.get("call_date"))
        t = tmap.get(c["call_id"])
        if cd is None or cd <= CUTOFF or t is None:
            continue
        fetched[((c.get("source") or "?").lower(), str(t.get("fetched_at") or "")[:10])] += 1
        if t.get("transcript_quality") == "unavailable":
            reasons[((c.get("source") or "?").lower(), (t.get("unavailable_reason") or "")[:90])] += 1
    for (src, r), n in reasons.most_common(15):
        print(f"  {src:10} x{n:4}  {r}")
    print("\n  call_transcripts.fetched_at day for post-cutoff calls that DO have a row:")
    for k in sorted(fetched, key=lambda k: (k[1], k[0])):
        print(f"    {k[1]} {k[0]:10} {fetched[k]}")

    # ── 5. live spot-check of ABSENT Apollo calls ───────────────────────
    absent_apollo = [c for c in calls
                     if (c.get("source") or "").lower() == "apollo"
                     and (_d(c.get("call_date")) or date.min) > CUTOFF
                     and state(c["call_id"]) == "ABSENT"]
    absent_apollo.sort(key=lambda c: str(c.get("call_date")), reverse=True)
    print("\n" + "=" * 100)
    print(f"5. LIVE SPOT-CHECK: {min(SPOT_CHECK_N, len(absent_apollo))} of "
          f"{len(absent_apollo)} ABSENT post-cutoff Apollo calls (GET /conversations/{{id}})")
    print("=" * 100)
    if os.getenv("APOLLO_API_KEY") and SPOT_CHECK_N > 0:
        from transcript_store import fetch_utterances, assemble_text
        clients = {}
        for c in absent_apollo[:SPOT_CHECK_N]:
            utts, err, _ = fetch_utterances("apollo", c["call_id"], clients, retries=2)
            text = assemble_text(utts)
            print(f"  {c['call_id']}  {c.get('call_date')}  {str(c.get('title'))[:40]:40}  "
                  f"fragments={len(utts):4}  chars={len(text):6}  err={err}")
    else:
        print("  skipped (no APOLLO_API_KEY or SPOT_CHECK_N=0)")

    # ── 6. calls-row completeness (cause A open item) ───────────────────
    # On nights the etl_calls.py calls upsert failed, the only writers of
    # these rows were the participant steps, which never set
    # formatted_summary / duration_minutes / company_slug. Measure it.
    print("\n" + "=" * 100)
    print("6. CALLS-ROW COMPLETENESS (call_date > cutoff): formatted_summary / duration / company_slug")
    print("=" * 100)
    rich = select_all(sb, "calls",
                      columns="call_id,source,call_date,formatted_summary,duration_minutes,company_slug",
                      filters=[("gt", "call_date", str(CUTOFF))])
    comp = defaultdict(Counter)
    for r in rich:
        src = (r.get("source") or "?").lower()
        tstate = "transcript_missing" if state(r["call_id"]) != "TEXT" else "transcript_ok"
        k = (src, tstate)
        comp[k]["rows"] += 1
        if not (r.get("formatted_summary") or "").strip():
            comp[k]["no_summary"] += 1
        if r.get("duration_minutes") in (None, 0, "0"):
            comp[k]["no_duration"] += 1
        if not (r.get("company_slug") or "").strip():
            comp[k]["no_company_slug"] += 1
        if (not (r.get("formatted_summary") or "").strip()
                and r.get("duration_minutes") in (None, 0, "0")):
            comp[k]["no_summary_and_no_duration"] += 1
    for k in sorted(comp):
        c = comp[k]
        print(f"  {k[0]:10} {k[1]:19} rows={c['rows']:4}  no_summary={c['no_summary']:4}  "
              f"no_duration={c['no_duration']:4}  no_company_slug={c['no_company_slug']:4}  "
              f"both_missing={c['no_summary_and_no_duration']:4}")

    print("\nDONE")


if __name__ == "__main__":
    main()
