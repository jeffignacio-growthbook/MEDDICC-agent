#!/usr/bin/env python3
"""
Transcript-availability PROBE (STORE_AND_BACKFILL_TRANSCRIPTS, Phase 3, scoped).

Answers the one question that decides the whole task, for ~a dozen API calls
instead of committing to ~1000 blind: does transcript TEXT actually come back
per source, and is it retained for OLD calls or only recent ones?

The spec assumed transcripts were fetched and dropped. They are NOT for
Fireflies (788 of ~1000 calls) — the list query only pulls the AI summary, so
this probe uses a NEW per-id fetch (FirefliesClient.get_transcript_sentences).
Apollo's transcript text IS reachable via ApolloClient.get_conversation(id).

WRITES NOTHING. Reports, per source:
  - availability: of N sampled ids, how many returned usable text
  - RETENTION: availability split by age (oldest sampled vs newest sampled) —
    if old calls come back empty but recent ones don't, the backfill has a
    horizon and that changes what's worth doing
  - char-count sample (min / median / max) — sizes the storage decision
  - one pasted excerpt per source, so the assembled text can be eyeballed

Needs FIREFLIES_API_KEY, APOLLO_API_KEY, SUPABASE_URL, SUPABASE_SERVICE_KEY.
Env knobs: PROBE_PER_BUCKET (default 3 oldest + 3 newest per source).
"""
import os
import sys
import statistics
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
for p in ("", "scripts", "api"):
    sys.path.insert(0, str(REPO / p) if p else str(REPO))

PER_BUCKET = int(os.getenv("PROBE_PER_BUCKET", "3"))


def _sample_calls(sb, source):
    """Oldest PER_BUCKET and newest PER_BUCKET call ids for a source, so we can
    read the retention horizon. Returns [(call_id, call_date, bucket)]."""
    from supabase_client import select_all
    rows = select_all(sb, "calls", columns="call_id,call_date,source,company_name",
                      filters=[("eq", "source", source)])
    rows = [r for r in rows if r.get("call_id") and r.get("call_date")]
    rows.sort(key=lambda r: r["call_date"])
    if not rows:
        return []
    oldest = [(r["call_id"], r["call_date"], "oldest") for r in rows[:PER_BUCKET]]
    newest = [(r["call_id"], r["call_date"], "newest") for r in rows[-PER_BUCKET:]]
    # de-dup if the source has fewer than 2*PER_BUCKET calls
    seen, out = set(), []
    for cid, cd, b in oldest + newest:
        if cid not in seen:
            seen.add(cid); out.append((cid, cd, b))
    return out


def _probe_fireflies(sample):
    from fireflies_client import FirefliesClient
    client = FirefliesClient()
    results = []
    for cid, cd, bucket in sample:
        rec = {"call_id": cid, "call_date": cd, "bucket": bucket}
        try:
            sentences = client.get_transcript_sentences(cid)
            text = client.assemble_transcript(sentences)
            rec.update(text=text, chars=len(text), n_sentences=len(sentences),
                       ok=bool(text), error=None)
        except Exception as e:
            rec.update(text="", chars=0, n_sentences=0, ok=False,
                       error=f"{type(e).__name__}: {str(e)[:120]}")
        results.append(rec)
    return results


def _assemble_apollo(conversation):
    lines = []
    for entry in (conversation.get("transcript") or []):
        speaker = entry.get("participant_name") or entry.get("speaker") or "Unknown"
        text = (entry.get("spoken_sentence") or entry.get("text") or "").strip()
        if text:
            lines.append(f"[{speaker}]: {text}")
    return "\n".join(lines)


def _probe_apollo(sample):
    from apollo_client import ApolloClient
    client = ApolloClient()
    results = []
    for cid, cd, bucket in sample:
        rec = {"call_id": cid, "call_date": cd, "bucket": bucket}
        try:
            convo = client.get_conversation(cid)
            text = _assemble_apollo(convo)
            rec.update(text=text, chars=len(text),
                       n_sentences=len(convo.get("transcript") or []),
                       ok=bool(text), error=None)
        except Exception as e:
            rec.update(text="", chars=0, n_sentences=0, ok=False,
                       error=f"{type(e).__name__}: {str(e)[:120]}")
        results.append(rec)
    return results


def _report(source, results):
    print("\n" + "=" * 76)
    print(f"SOURCE: {source}   (sampled {len(results)} calls)")
    print("=" * 76)
    if not results:
        print("  no calls of this source in the substrate — nothing to probe")
        return
    for r in results:
        flag = "ok" if r["ok"] else "EMPTY"
        err = f"  err={r['error']}" if r.get("error") else ""
        print(f"  [{r['bucket']:>6}] {r['call_date']}  {r['call_id'][:24]:24} "
              f"{flag:5} chars={r['chars']:>7} sentences={r['n_sentences']:>4}{err}")

    ok = [r for r in results if r["ok"]]
    print(f"\n  availability: {len(ok)}/{len(results)} returned usable text")
    for bucket in ("oldest", "newest"):
        b = [r for r in results if r["bucket"] == bucket]
        bok = [r for r in b if r["ok"]]
        if b:
            span = f"{b[0]['call_date']}…{b[-1]['call_date']}"
            print(f"    {bucket:>6}: {len(bok)}/{len(b)} have text   ({span})")
    if ok:
        chars = sorted(r["chars"] for r in ok)
        print(f"  char-count: min={chars[0]}  median={int(statistics.median(chars))}  "
              f"max={chars[-1]}")
        # one excerpt
        sample = max(ok, key=lambda r: r["chars"])
        excerpt = sample["text"][:700]
        print(f"\n  --- excerpt ({source}, call {sample['call_id'][:20]}, "
              f"{sample['call_date']}, {sample['chars']} chars) ---")
        for line in excerpt.splitlines()[:12]:
            print(f"  | {line[:110]}")
        print("  --- end excerpt ---")


def main():
    missing = [k for k in ("SUPABASE_URL", "SUPABASE_SERVICE_KEY") if not os.getenv(k)]
    if missing:
        print(f"cannot probe — missing {missing}"); return 2
    from api.db import get_supabase
    sb = get_supabase()

    print("=" * 76)
    print("TRANSCRIPT AVAILABILITY PROBE — writes nothing")
    print(f"sampling {PER_BUCKET} oldest + {PER_BUCKET} newest per source")
    print("=" * 76)

    # Fireflies
    if os.getenv("FIREFLIES_API_KEY") or os.getenv("GROWTHBOOK_FIREFLIES_API_KEY"):
        _report("fireflies", _probe_fireflies(_sample_calls(sb, "fireflies")))
    else:
        print("\n[fireflies] FIREFLIES_API_KEY not set — skipped")

    # Apollo
    if os.getenv("APOLLO_API_KEY"):
        _report("apollo", _probe_apollo(_sample_calls(sb, "apollo")))
    else:
        print("\n[apollo] APOLLO_API_KEY not set — skipped")

    print("\n" + "=" * 76)
    print("READ THIS BEFORE ANY BACKFILL: if a source shows 0/N text, the "
          "backfill\ncan't store it — diagnose the fetch, don't write empties. "
          "If oldest=0 but\nnewest>0, there is a retention horizon.")
    print("=" * 76)


if __name__ == "__main__":
    sys.exit(main() or 0)
