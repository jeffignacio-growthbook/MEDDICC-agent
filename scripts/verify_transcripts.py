#!/usr/bin/env python3
"""
Spot-check STORED transcripts + metrics (STORE_AND_BACKFILL_TRANSCRIPTS Phase 5).
Reads back a few call_transcripts rows and prints the transcript head + every
metric, so the computed talk time / questions / monologue can be eyeballed
against a real call before scaling to the Fireflies leg. Read-only.
"""
import json
import os
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
for p in ("", "scripts", "api"):
    sys.path.insert(0, str(REPO / p) if p else str(REPO))

# Known field-probe Apollo calls (Christian/Jay etc.) for a stable cross-check.
KNOWN_APOLLO = ["6a88afa8a3dc7a0017a4f2c9", "6a86203f10dffd000c59b075",
                "6a85debd41ac9b0018dbaac8"]
_COLS = ("call_id,source,transcript_quality,char_count,sentence_count,"
         "total_speech_seconds,longest_monologue_seconds,longest_monologue_speaker,"
         "talk_time_seconds,question_count,speakers,transcript,unavailable_reason")


def _show(r):
    print(f"\n  call {r.get('call_id')}  [{r.get('source')}/{r.get('transcript_quality')}]")
    if r.get("transcript_quality") == "unavailable":
        print(f"    unavailable_reason: {r.get('unavailable_reason')}")
        return
    print(f"    chars={r.get('char_count')} sentences={r.get('sentence_count')} "
          f"total_speech={r.get('total_speech_seconds')}s")
    print(f"    longest_monologue={r.get('longest_monologue_seconds')}s "
          f"by {r.get('longest_monologue_speaker')}")
    tt = r.get("talk_time_seconds") or {}
    qc = r.get("question_count") or {}
    sp = r.get("speakers") or {}
    # show per-speaker with display name, sorted by talk time desc
    print("    talk time / questions per speaker:")
    for key in sorted(tt, key=lambda k: -(tt.get(k) or 0)):
        name = sp.get(key, key)
        print(f"      {str(name)[:28]:28} talk={tt.get(key)}s  questions={qc.get(key, 0)}")
    head = (r.get("transcript") or "").splitlines()[:4]
    print("    transcript head:")
    for line in head:
        print(f"      | {line[:100]}")


def main():
    if not (os.getenv("SUPABASE_URL") and os.getenv("SUPABASE_SERVICE_KEY")):
        print("cannot verify — SUPABASE_* not set"); return 2
    from api.db import get_supabase
    from supabase_client import select_all
    sb = get_supabase()

    print("=" * 78)
    print("STORED TRANSCRIPT SPOT-CHECK")
    print("=" * 78)

    # Per-source × quality tally — the real state of the backfill, from the DB
    # (not logs). 'full' = has text (done); 'unavailable' = no row-text yet.
    from collections import Counter
    allrows = select_all(sb, "call_transcripts", columns="source,transcript_quality")
    tally = Counter((r.get("source"), r.get("transcript_quality")) for r in allrows)
    calls = Counter(c.get("source") for c in
                    select_all(sb, "calls", columns="source") if c.get("source"))
    print(f"total call_transcripts rows: {len(allrows)}")
    print(f"{'source':12} {'full':>7} {'unavail':>8} {'stored':>7} {'/calls':>8} {'coverage':>9}")
    for src in sorted({s for s, _ in tally}):
        full = tally.get((src, "full"), 0)
        un = sum(n for (s, q), n in tally.items() if s == src and q != "full")
        stored = full + un
        ncalls = calls.get(src, 0)
        cov = f"{100*full/ncalls:.0f}%" if ncalls else "—"
        print(f"{str(src):12} {full:>7} {un:>8} {stored:>7} {ncalls:>8} {cov:>9}")
    print("  (coverage = full-text rows ÷ calls of that source; unavailable rows "
          "re-attempt on the\n   next backfill pass — they are not 'done')")

    print("\n--- known Apollo calls (field-probe cross-check) ---")
    known = select_all(sb, "call_transcripts", columns=_COLS,
                       filters=[("in_", "call_id", KNOWN_APOLLO)])
    for r in known:
        _show(r)

    print("\n--- the 2 'unavailable' rows (CHECK-constraint path) ---")
    un = select_all(sb, "call_transcripts", columns=_COLS,
                    filters=[("eq", "transcript_quality", "unavailable")])
    print(f"  unavailable rows stored: {len(un)}")
    for r in un[:5]:
        _show(r)

    print("\n" + "=" * 78)
    print("Sanity: talk time should sum≈total_speech; a discovery call should show "
          "the rep\nasking more questions than the prospect; monologue seconds "
          "should be plausible.")
    print("=" * 78)


if __name__ == "__main__":
    sys.exit(main() or 0)
